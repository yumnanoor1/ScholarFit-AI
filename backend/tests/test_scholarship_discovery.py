import io
import ipaddress
import json
import os
import socket
import ssl
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import dns.exception
import dns.resolver
import httpx
from groq import Groq
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import ScholarshipDiscoverySettings, scholarship_discovery_settings
from app.database import Base, create_application_schema
from app.models.opportunity import Scholarship, ScholarshipAuditLog
from app.models.scholarship_discovery import ScholarshipDiscoveryReviewItem, ScholarshipDiscoveryRun
from app.models.scholarship_discovery_publication import (
    ScholarshipDiscoveryPublication,
    ScholarshipDiscoveryPublicationEvent,
    ScholarshipDiscoveryPublicationSource,
    ScholarshipDiscoveryPublicationVersion,
)
from app.models.scholarship_knowledge import (
    ScholarshipChunkEmbedding,
    ScholarshipDocumentChunk,
    ScholarshipDocumentVersion,
    ScholarshipSourceDocument,
)
from app.models.user import User
from app.schemas.admin import AdminDiscoveryReviewItem
from app.routers.admin_scholarships import _discovery_run_history
from app.services import rag_service
from app.services.gemini_provider import gemini_request_payload_size_bytes
from app.services.groq_provider import (
    GroqProviderError,
    _groq_request_body,
    generate_json_completion,
    groq_request_payload_size_bytes,
)
from app.services.scholarship_discovery import _register_evidence, run_discovery
from app.services.scholarship_discovery_budget import (
    ControlledManualSourceConfigurationError,
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
    controlled_manual_sources,
)
from app.services.scholarship_discovery_extraction import (
    EXTRACTION_SYSTEM_INSTRUCTION,
    ExtractedScholarship,
    GeminiScholarshipExtractor,
    InvalidEvidenceURL,
    OutOfScopeScholarship,
    ScholarshipExtractionError,
    _groq_client,
    _strict_extraction_schema,
    _validate_candidate,
)
from app.services.scholarship_discovery_review import apply_review_action
from app.services.scholarship_discovery_publications import (
    _publication_source,
    record_publication_source_failure,
    record_publication_source_success,
    transition_publication,
)
from app.services.scholarship_discovery_scheduler import (
    DiscoveryLockLost,
    calculate_next_run,
)
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
    resolve_trusted_source_url,
)
from app.services.scholarship_discovery_sources import (
    EUROPEAN_COUNTRIES,
    SOURCES,
    SOURCES_BY_ID,
    TRANS_EUROPEAN_HOST_CITIES,
    DiscoverySource,
)


def _settings(**changes):
    values = {
        "enabled": True,
        "request_timeout_seconds": 2,
        "max_response_bytes": 2048,
        "max_extracted_chars": 2000,
        "max_pages_per_source": 5,
        "max_retries": 0,
        "request_delay_seconds": 0,
        "user_agent": "FitScholarTest/1.0",
        "model": "test-model",
    }
    values.update(changes)
    return ScholarshipDiscoverySettings(**values)


def _address_info(ip_address, port=443):
    ip = ipaddress.ip_address(ip_address)
    if ip.version == 6:
        return socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (str(ip), port, 0, 0)
    return socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (str(ip), port)


def _http_response(status=200, body=b"ok", headers=b"Content-Type: text/html\r\n"):
    reason = {
        200: b"OK",
        302: b"Found",
        404: b"Not Found",
        500: b"Internal Server Error",
        503: b"Service Unavailable",
    }[status]
    return (
        b"HTTP/1.1 " + str(status).encode("ascii") + b" " + reason + b"\r\n"
        + headers
        + b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
        + b"Connection: close\r\n\r\n"
        + body
    )


class _FakeSocket:
    def __init__(self, response_bytes):
        self.response = io.BytesIO(response_bytes)
        self.sent = bytearray()
        self.closed = False
        self.peer = None

    def makefile(self, mode, buffering=None):
        return self.response

    def sendall(self, data):
        self.sent.extend(data)

    def getpeername(self):
        if self.peer is None:
            raise OSError("peer is unavailable")
        return self.peer

    def close(self):
        self.closed = True


def _pinned_connector(*sockets):
    remaining = list(sockets)

    def connect(family, socket_type, protocol, sockaddr, timeout):
        sock = remaining.pop(0)
        sock.peer = sockaddr
        return sock

    return MagicMock(side_effect=connect)


class _ProviderFailure(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__("sanitized provider failure")


class _FakeDNSResolver:
    def __init__(self, answers=None, *, sequences=None, errors=None):
        self.answers = answers or {}
        self.sequences = sequences or {}
        self.errors = errors or {}
        self.sequence_indexes = {}
        self.calls = []

    def __call__(self, host, record_type, *, lifetime, search):
        record_name = dns.rdatatype.to_text(record_type)
        self.calls.append((host, record_name, lifetime, search))
        key = (host, record_name)
        if key in self.errors:
            raise self.errors[key]
        sequence_key = key if key in self.sequences else record_name
        if sequence_key in self.sequences:
            index = self.sequence_indexes.get(key, 0)
            self.sequence_indexes[key] = index + 1
            values = self.sequences[sequence_key][index]
        else:
            values = self.answers.get(record_name, [])
        if isinstance(values, BaseException):
            raise values
        addresses = []
        for value in values:
            if isinstance(value, tuple):
                value = value[4][0]
            addresses.append(SimpleNamespace(address=value))
        if not addresses:
            raise dns.resolver.NoAnswer()
        return addresses


class _RecordingSSLContext:
    check_hostname = True
    verify_mode = ssl.CERT_REQUIRED

    def __init__(self):
        self.server_hostname = None

    def wrap_socket(self, sock, server_hostname):
        self.server_hostname = server_hostname
        return sock


def _source(
    discovery_only=False,
    source_classification="government_authority",
    trust_basis="Test source authority",
    trust_reviewed=True,
    trusted_external_domains=(),
    trusted_external_domains_reviewed=False,
    trusted_external_domain_trust_basis=None,
):
    return DiscoverySource(
        "test-finland",
        "Finnish Official Scholarships",
        "official.example",
        "government_scholarship_programme",
        "Finland",
        "https://official.example/scholarships",
        source_classification=source_classification,
        trust_basis=trust_basis,
        trust_reviewed=trust_reviewed,
        country="Finland",
        discovery_only=discovery_only,
        trusted_external_domains=trusted_external_domains,
        trusted_external_domains_reviewed=trusted_external_domains_reviewed,
        trusted_external_domain_trust_basis=trusted_external_domain_trust_basis,
    )


def _page(text="Official scholarship details.", url=None, content_hash="a" * 64, links=()):
    return FetchedPage(
        url=url or _source().source_url,
        content_type="text/html",
        text=text,
        links=links,
        content_hash=content_hash,
    )


def _candidate(source=None, page=None, **changes):
    source = source or _source()
    page = page or _page()
    values = {
        "name": "Finland Master's Award",
        "country": "Finland",
        "degree_level": "Master",
        "eligible_degree_levels": ["Master"],
        "official_info_url": page.url,
        "source_name": source.name,
    }
    values.update(changes)
    return ExtractedScholarship(values=values, evidence={"name": "Finland Master's Award"})


def _raw_extraction_candidate(**changes):
    host_location = changes.pop("host_location", "study in Finland")
    host_city = changes.pop("host_city", "")
    values = {
        "name": "Finland Master's Award",
        "country": "Finland",
        "degree_level": "Master",
        "eligible_degree_levels": ["Master"],
    }
    values.update(changes)
    raw = {
        "values": values,
        "evidence": {
            "name": "Finland Master's Award",
            "country": values["country"],
            "degree_level": "Master",
            "eligible_degree_levels": "Master's applicants",
            "host_location": host_location,
        },
        "masters_only": True,
        "masters_evidence": "Master's applicants",
        "scholarship_offer_evidence": "scholarship is available",
    }
    if "host_institution" in values:
        raw["evidence"]["host_institution"] = values["host_institution"]
    if host_city:
        raw["host_city"] = host_city
        raw["evidence"]["host_city"] = host_city
    return raw


class DiscoverySourceRegistryTests(unittest.TestCase):
    APPROVED_CRAWL_ENABLED_SOURCE_IDS = {
        "daad-helmut-schmidt",
        "daad-epos",
        "nl-scholarship",
        "leiden-excellence",
        "maastricht-nl-high-potential",
        "radboud-scholarship",
        "kth-scholarship",
        "lund-university-scholarships",
        "chalmers-scholarships",
        "eiffel-scholarship",
        "sciences-po-emile-boutmy",
        "chevening-pakistan",
        "commonwealth-masters",
        "commonwealth-shared",
        "turkiye-burslari",
    }
    DISABLED_NEW_SOURCE_IDS = {
        "polimi-merit-scholarships",
        "amsterdam-excellence",
        "gates-cambridge",
        "deutschlandstipendium",
        "tudelft-justus-louise-van-effen",
        "great-scholarships-pakistan",
        "british-council-women-in-stem",
    }
    NEW_SOURCE_URLS = {
        "daad-helmut-schmidt": "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50026397",
        "daad-epos": "https://www.daad.de/en/information-services-for-higher-education-institutions/further-information-on-daad-programmes/epos/",
        "deutschlandstipendium": "https://www.deutschlandstipendium.de/deutschlandstipendium/de/services/english/the-deutschlandstipendium-best-of-both-worlds-for-students.html",
        "polimi-merit-scholarships": "https://www.polimi.it/en/international-prospective-students/laurea-magistrale-programmes-equivalent-to-master-of-science/scholarships/merit-based-scholarships",
        "nl-scholarship": "https://www.studyinnl.org/finances/nl-scholarship",
        "amsterdam-excellence": "https://www.uva.nl/shared-content/programmas/en/masters/communication-science-corporate-communication/tuition-fee/amsterdam-merit-scholarship.html",
        "leiden-excellence": "https://www.staff.universiteitleiden.nl/scholarships/sea/leiden-university-excellence-scholarship-lexs",
        "tudelft-justus-louise-van-effen": "https://www.tudelft.nl/en/education/study-programme-orientation/practical-matters/scholarships",
        "maastricht-nl-high-potential": "https://www.maastrichtuniversity.nl/studeren/toelating-inschrijving/financing-your-studies/scholarships/maastricht-university-nl-high",
        "radboud-scholarship": "https://www.ru.nl/en/education/scholarships/radboud-scholarship-programme",
        "kth-scholarship": "https://www.kth.se/en/2.985/admissions/scholarships/kth-scholarship-1.72827",
        "lund-university-scholarships": "https://lunduniversity.lu.se/admissions/bachelors-and-masters-studies/scholarships-and-awards",
        "chalmers-scholarships": "https://www.chalmers.se/en/education/application-and-admission/scholarships-for-fee-paying-students/",
        "eiffel-scholarship": "https://www.campusfrance.org/en/eiffel-scholarship-program-of-excellence",
        "sciences-po-emile-boutmy": "https://www.sciencespo.fr/students/en/fees-funding/bursaries-financial-aid/emile-boutmy-scholarship/",
        "chevening-pakistan": "https://www.chevening.org/scholarship/pakistan/",
        "commonwealth-masters": "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-masters-scholarships/",
        "commonwealth-shared": "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-shared-scholarships/",
        "great-scholarships-pakistan": "https://study-uk.britishcouncil.org/scholarships-funding/great-scholarships/pakistan",
        "british-council-women-in-stem": "https://www.britishcouncil.org/study-work-abroad/in-uk/scholarship-women-stem",
        "gates-cambridge": "https://www.gatescambridge.org/programme/the-scholarship/",
        "turkiye-burslari": "https://www.turkiyeburslari.gov.tr/",
    }
    def test_curated_sources_use_supplied_urls_without_changing_existing_ids(self):
        self.assertTrue(set(self.NEW_SOURCE_URLS).issubset(SOURCES_BY_ID))
        for source_id, source_url in self.NEW_SOURCE_URLS.items():
            with self.subTest(source_id=source_id):
                self.assertEqual(
                    sum(source.source_id == source_id for source in SOURCES),
                    1,
                )
                self.assertEqual(SOURCES_BY_ID[source_id].source_url, source_url)

        self.assertTrue({
            "erasmus-mundus",
            "daad",
            "stipendium-hungaricum",
            "swedish-institute",
            "government-of-ireland",
            "study-in-italy",
            "nawa-poland",
        }.issubset(SOURCES_BY_ID))
        self.assertEqual(
            SOURCES_BY_ID["nawa-poland"].source_url,
            "https://www.nawa.gov.pl/en/students/foreign-students/the-banach-scholarship-programme/about-the-programme",
        )
        self.assertFalse(SOURCES_BY_ID["nawa-poland"].discovery_only)
        self.assertEqual(
            SOURCES_BY_ID["stipendium-hungaricum"].source_url,
            "https://stipendiumhungaricum.hu/about/",
        )
        self.assertEqual(
            SOURCES_BY_ID["swedish-institute"].source_url,
            "https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/",
        )
        self.assertTrue(SOURCES_BY_ID["erasmus-mundus"].discovery_only)

    def test_new_source_trust_review_is_separate_from_crawl_activation(self):
        self.assertEqual(len(self.NEW_SOURCE_URLS), 22)
        self.assertEqual(len({source.source_id for source in SOURCES}), len(SOURCES))
        new_source_ids = set(self.NEW_SOURCE_URLS)
        self.assertEqual(
            self.APPROVED_CRAWL_ENABLED_SOURCE_IDS | self.DISABLED_NEW_SOURCE_IDS,
            new_source_ids,
        )
        self.assertFalse(
            self.APPROVED_CRAWL_ENABLED_SOURCE_IDS & self.DISABLED_NEW_SOURCE_IDS
        )
        enabled_new_source_ids = {
            source.source_id
            for source in SOURCES
            if source.source_id in new_source_ids and source.crawl_enabled
        }
        self.assertEqual(
            enabled_new_source_ids,
            self.APPROVED_CRAWL_ENABLED_SOURCE_IDS,
        )
        for source_id in self.NEW_SOURCE_URLS:
            source = SOURCES_BY_ID[source_id]
            self.assertEqual(
                source.crawl_enabled,
                source_id in self.APPROVED_CRAWL_ENABLED_SOURCE_IDS,
            )
            self.assertEqual(source.trusted_external_domains, ())
            self.assertTrue(source.trust_reviewed)
            self.assertTrue(source.trust_basis)
        self.assertEqual(
            SOURCES_BY_ID["amsterdam-excellence"].name,
            "Amsterdam Merit Scholarship (AMS)",
        )

        normalized_urls = [
            resolve_trusted_source_url(source.source_url, source.source_url, source)
            for source in SOURCES
        ]
        self.assertTrue(all(normalized_urls))
        self.assertEqual(len(set(normalized_urls)), len(normalized_urls))

    def test_generic_portal_urls_are_not_registered_as_scholarship_listings(self):
        registered_urls = {source.source_url for source in SOURCES}
        self.assertNotIn("https://www.daad.de/en/", registered_urls)
        self.assertNotIn("https://www.mur.gov.it/", registered_urls)
        self.assertNotIn("https://cscuk.fcdo.gov.uk/", registered_urls)


class GeographyAndExtractionTests(unittest.TestCase):
    def _validate_geographic_candidate(
        self,
        country,
        host_location,
        *,
        host_city="",
        host_institution="",
    ):
        page_text = (
            "Finland Master's Award scholarship is available to Master's applicants. "
            f"{host_location}"
        )
        page = _page(page_text)
        raw = _raw_extraction_candidate(
            country=country,
            host_location=host_location,
            host_city=host_city,
            host_institution=host_institution,
        )
        return _validate_candidate(raw, page, _source())

    def test_europe_is_an_explicit_country_configuration(self):
        self.assertEqual(EUROPEAN_COUNTRIES["Czech Republic"], "Czechia")
        self.assertEqual(TRANS_EUROPEAN_HOST_CITIES["Turkey"], {"edirne", "tekirdag", "kirklareli"})
        self.assertNotIn("Cyprus", EUROPEAN_COUNTRIES)
        self.assertTrue(any(source.category == "official_university_scholarship" for source in SOURCES))
        self.assertTrue(any(source.discovery_only for source in SOURCES))
        self.assertIn("official_provider", {source.source_classification for source in SOURCES})
        self.assertIn("government_authority", {source.source_classification for source in SOURCES})
        self.assertIn("trusted_listing", {source.source_classification for source in SOURCES})
        listing = _source(
            source_classification="trusted_listing",
            trust_basis="Manually reviewed scholarship-listing policy",
        )
        self.assertTrue(listing.trust_reviewed)
        with self.assertRaisesRegex(ValueError, "trust basis"):
            _source(
                source_classification="trusted_listing",
                trust_basis=None,
                trust_reviewed=True,
            )

    def test_candidate_requires_exact_quotes_and_master_specific_offer(self):
        source = _source()
        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants to study at the University of Helsinki in Helsinki, Finland.",
            content_hash="b" * 64,
        )
        raw = {
            "values": {
                "name": "Finland Master's Award",
                "country": "Finland",
                "degree_level": "Master's",
                "eligible_degree_levels": ["Master"],
                "host_institution": "University of Helsinki",
            },
            "evidence": {
                "name": "Finland Master's Award",
                "country": "Finland",
                "degree_level": "Master's",
                "eligible_degree_levels": "Master's applicants",
                "host_location": "study at the University of Helsinki in Helsinki, Finland",
                "host_city": "Helsinki",
                "host_institution": "University of Helsinki",
            },
            "host_city": "Helsinki",
            "masters_only": True,
            "masters_evidence": "Master's applicants",
            "scholarship_offer_evidence": "scholarship is available",
        }
        result = _validate_candidate(raw, page, source)
        self.assertEqual(result.values["country"], "Finland")
        self.assertEqual(result.values["official_info_url"], page.url)
        self.assertEqual(result.values["source_name"], source.name)
        self.assertNotIn("verification_status", result.values)
        self.assertNotIn("application_deadline_date", result.values)
        self.assertNotIn("funding_level", result.values)

    def test_missing_identity_and_malformed_fields_are_rejected(self):
        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants. "
            "Study in Finland."
        )
        invalid_candidates = []
        missing_name = _raw_extraction_candidate()
        missing_name["values"]["name"] = "   "
        invalid_candidates.append(missing_name)
        malformed_field = _raw_extraction_candidate(funding_level="full-scholarship")
        invalid_candidates.append(malformed_field)

        for raw in invalid_candidates:
            with self.subTest(candidate=raw["values"]):
                client = MagicMock()
                client.models.generate_content.return_value = SimpleNamespace(
                    text=json.dumps({"scholarships": [raw]}),
                )
                extractor = GeminiScholarshipExtractor(_settings(), client=client)

                self.assertEqual(extractor.extract(page, _source()), [])
                self.assertEqual(extractor.last_rejected_count, 1)
                self.assertEqual(extractor.last_rejection_reasons, ["invalid_candidate"])

    def test_irrelevant_page_evidence_cannot_produce_a_candidate(self):
        page = _page("University admissions, campus news, and student services.")
        raw = _raw_extraction_candidate()
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps({"scholarships": [raw]}),
        )
        extractor = GeminiScholarshipExtractor(_settings(), client=client)

        self.assertEqual(extractor.extract(page, _source()), [])
        self.assertEqual(extractor.last_rejected_count, 1)

    def test_explicit_european_host_evidence_accepts_international_applicants(self):
        result = self._validate_geographic_candidate(
            "Finland",
            "Master's study takes place at the University of Helsinki in Finland. "
            "Applicants from India and Nigeria may apply.",
        )
        self.assertEqual(result.values["country"], "Finland")
        labelled = self._validate_geographic_candidate("Finland", "Host country: Finland.")
        self.assertEqual(labelled.values["country"], "Finland")

    def test_applicant_country_references_are_held_for_review(self):
        references = (
            "Applicants of Finnish nationality may apply.",
            "The University offers the award to applicants residing in Finland.",
            "Citizens of Finland are eligible for the award.",
            "Finland is mentioned on the scholarship page.",
        )
        for quote in references:
            with self.subTest(quote=quote):
                candidate = self._validate_geographic_candidate("Finland", quote)
                self.assertTrue(candidate.requires_review)

    def test_multiple_host_countries_are_held_for_review(self):
        quotes = (
            "Study in France and Germany.",
            "The programme is offered in France or Germany.",
            "Studies take place across France and Germany.",
        )
        for quote in quotes:
            with self.subTest(quote=quote):
                candidate = self._validate_geographic_candidate("France", quote)
                self.assertTrue(candidate.requires_review)

    def test_international_applicants_from_pakistan_do_not_change_host_country(self):
        result = self._validate_geographic_candidate(
            "Finland",
            "The programme is open to applicants from Pakistan and other countries, "
            "with studies conducted in Finland.",
        )
        self.assertEqual(result.values["country"], "Finland")

    def test_invalid_country_values_reject_only_the_candidate(self):
        page = _page(
            "Finland Master's Award scholarship is available to Master's applicants. "
            "Study in Finland."
        )
        missing_country = _raw_extraction_candidate()
        del missing_country["values"]["country"]
        non_string_country = _raw_extraction_candidate()
        non_string_country["values"]["country"] = 17
        valid_candidate = _raw_extraction_candidate()
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=__import__("json").dumps({
                "scholarships": [missing_country, non_string_country, valid_candidate],
            }),
        )
        extractor = GeminiScholarshipExtractor(_settings(), client=client)

        candidates = extractor.extract(page, _source())

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].missing_required_fields, ("country",))
        self.assertTrue(candidates[0].requires_review)
        self.assertNotIn("country", candidates[0].values)
        self.assertEqual(candidates[0].values["official_info_url"], page.url)
        self.assertEqual(candidates[1].values["country"], "Finland")
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertEqual(
            extractor.last_rejection_reasons,
            ["ScholarshipExtractionError"],
        )
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")

    def test_conflicting_non_european_host_evidence_is_held_for_review(self):
        candidate = self._validate_geographic_candidate(
            "Finland",
            "Study at the University of Toronto in Canada; applicants from Finland may apply.",
        )
        self.assertTrue(candidate.requires_review)
        self.assertIn("conflicting_host_location_evidence", candidate.review_reasons)

    def test_transcontinental_host_requires_a_verified_european_city(self):
        accepted = self._validate_geographic_candidate(
            "Turkey",
            "Master's study takes place at Trakya University in Edirne, Turkey.",
            host_city="Edirne",
            host_institution="Trakya University",
        )
        self.assertEqual(accepted.values["country"], "Turkey")

        with self.assertRaises(OutOfScopeScholarship):
            self._validate_geographic_candidate(
                "Turkey",
                "Master's study takes place at Istanbul University in Istanbul, Turkey.",
                host_city="Istanbul",
                host_institution="Istanbul University",
            )

    def test_conflicting_host_country_evidence_is_rejected(self):
        candidate = self._validate_geographic_candidate(
            "Finland",
            "Study in Finland. The programme is hosted in Sweden.",
        )
        self.assertTrue(candidate.requires_review)
        self.assertIn("conflicting_host_location_evidence", candidate.review_reasons)

    def test_candidate_rejects_non_masters_and_unsupported_country(self):
        source = _source()
        page = _page("The Finland Master's Award scholarship is available to Master's applicants to study in Finland.")
        raw = {
            "values": {
                "name": "Finland Master's Award",
                "country": "Finland",
                "degree_level": "Master",
                "eligible_degree_levels": ["Master", "PhD"],
            },
            "evidence": {
                "host_location": "study in Finland",
            },
            "masters_only": True,
            "masters_evidence": "Master's applicants",
            "scholarship_offer_evidence": "scholarship is available",
        }
        with self.assertRaises(OutOfScopeScholarship):
            _validate_candidate(raw, page, source)

        raw["values"]["eligible_degree_levels"] = ["Master"]
        raw["values"]["country"] = "Atlantis"
        with self.assertRaises(OutOfScopeScholarship):
            _validate_candidate(raw, page, source)

    def test_extraction_accepts_registered_evidence_urls_and_resolves_relative_links(self):
        source = _source()
        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants to study in Finland.",
            url="https://official.example/scholarships/current",
            links=(
                ("/apply#application", "Apply"),
                ("https://www.official.example/docs", "Documents"),
                ("https://portal.europe.official.example/online", "Portal"),
                ("../extra", "Additional information"),
            ),
        )
        raw = _raw_extraction_candidate(
            official_application_url="/apply",
            additional_source_urls=[
                "https://www.official.example/docs",
                "https://portal.europe.official.example/online",
                "../extra",
            ],
        )

        result = _validate_candidate(raw, page, source)

        self.assertEqual(result.values["official_application_url"], "https://official.example/apply")
        self.assertEqual(
            result.values["additional_source_urls"],
            [
                "https://www.official.example/docs",
                "https://portal.europe.official.example/online",
                "https://official.example/extra",
            ],
        )

    def test_trusted_external_links_are_explicit_and_sensitive_urls_are_sanitized(self):
        source = _source(
            trusted_external_domains=("apply.example.org",),
            trusted_external_domains_reviewed=True,
            trusted_external_domain_trust_basis="Synthetic test-only reviewed portal",
        )
        text = (
            "The Finland Master's Award scholarship is available to Master's applicants "
            "to study in Finland. See https://official.example/guide?token=page-secret&lang=en."
        )
        trusted_url = (
            "https://apply.example.org/apply?campaign=summer&access_token=link-secret#form"
        )
        page = _page(
            text,
            url="https://official.example/scholarships?session=page-secret&lang=en#top",
            links=(
                ("/apply?campaign=summer&api_key=link-secret#form", "Official application"),
                ("/more?campaign=summer&token=link-secret#info", "Additional information"),
                (trusted_url, "University application portal"),
                ("https://unconfigured.example/apply?campaign=summer", "Scholarship application"),
                ("https://apply.example.org.attacker.com/apply", "Official application"),
                ("https://user:pass@apply.example.org/apply", "Official application"),
            ),
        )
        extractor = GeminiScholarshipExtractor(_settings(), client=MagicMock())
        payload = json.loads(
            extractor._prompt(page, source).split("Source page data (JSON):\n", 1)[1]
        )

        self.assertIn("https://official.example/apply?campaign=summer", payload["linked_urls"])
        self.assertIn("https://apply.example.org/apply?campaign=summer", payload["linked_urls"])
        self.assertNotIn("unconfigured.example", str(payload["linked_urls"]))
        self.assertNotIn("attacker.com", str(payload["linked_urls"]))
        self.assertNotIn("user:pass", str(payload["linked_urls"]))
        self.assertEqual(
            payload["source_url"],
            "https://official.example/scholarships?lang=en",
        )
        self.assertIn(
            "https://official.example/guide?lang=en",
            payload["official_page_text"],
        )
        self.assertNotIn("page-secret", str(payload))
        self.assertNotIn("link-secret", str(payload))

        result = _validate_candidate(
            _raw_extraction_candidate(
                official_application_url=trusted_url,
                additional_source_urls=[
                    "https://official.example/more?campaign=summer&token=link-secret#more",
                ],
            ),
            page,
            source,
        )
        self.assertEqual(
            result.values["official_application_url"],
            "https://apply.example.org/apply?campaign=summer",
        )
        self.assertEqual(
            result.values["additional_source_urls"],
            ["https://official.example/more?campaign=summer"],
        )
        self.assertEqual(
            result.values["official_info_url"],
            "https://official.example/scholarships?lang=en",
        )

    def test_external_allowlist_requires_reviewed_relationship(self):
        self.assertTrue(all(not source.trusted_external_domains for source in SOURCES))

        with self.assertRaisesRegex(ValueError, "explicit reviewed trust basis"):
            _source(trusted_external_domains=("apply.example.org",))

        with self.assertRaisesRegex(ValueError, "host names"):
            _source(
                trusted_external_domains=("https://apply.example.org/path",),
                trusted_external_domains_reviewed=True,
                trusted_external_domain_trust_basis="Synthetic test-only review",
            )

    def test_extraction_rejects_external_and_deceptive_evidence_urls_with_safe_reason(self):
        source = _source()
        invalid_urls = (
            "https://attacker.com/scholarships/apply",
            "https://official.example.attacker.com/scholarships/apply",
            "https://user:pass@official.example/scholarships/apply",
        )
        for field in ("official_application_url", "additional_source_urls"):
            for invalid_url in invalid_urls:
                page = _page(
                    "The Finland Master's Award scholarship is available to Master's applicants to study in Finland.",
                    links=((invalid_url, "Apply"),),
                )
                url_value = invalid_url if field == "official_application_url" else [invalid_url]
                raw = _raw_extraction_candidate(**{field: url_value})
                with self.subTest(field=field, url=invalid_url):
                    with self.assertRaises(InvalidEvidenceURL):
                        _validate_candidate(raw, page, source)

        invalid_url = invalid_urls[0]
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=__import__("json").dumps({"scholarships": [_raw_extraction_candidate(official_application_url=invalid_url)]}),
        )
        extractor = GeminiScholarshipExtractor(_settings(), client=client)
        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants to study in Finland.",
            links=((invalid_url, "Apply"),),
        )
        with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
            self.assertEqual(extractor.extract(page, source), [])
        self.assertEqual(extractor.last_rejection_reasons, ["invalid_evidence_url"])
        self.assertIn("invalid_evidence_url", logs.output[0])
        self.assertNotIn(invalid_url, logs.output[0])

    def test_gemini_extraction_output_is_validated(self):
        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants to study in Finland.",
            content_hash="c" * 64,
        )
        raw = {
            "scholarships": [{
                "values": {
                    "name": "Finland Master's Award",
                    "country": "Finland",
                    "degree_level": "Master's",
                    "eligible_degree_levels": ["Master"],
                },
                "evidence": {
                    "name": "Finland Master's Award",
                    "country": "Finland",
                    "degree_level": "Master's",
                    "eligible_degree_levels": "Master's applicants",
                    "host_location": "study in Finland",
                },
                "masters_only": True,
                "masters_evidence": "Master's applicants",
                "scholarship_offer_evidence": "scholarship is available",
            }],
        }
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=__import__("json").dumps(raw),
        )
        extractor = GeminiScholarshipExtractor(_settings(), client=client)
        candidates = extractor.extract(page, _source())
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].values["name"], "Finland Master's Award")
        self.assertEqual(client.models.generate_content.call_args.kwargs["model"], "test-model")

    def test_gemini_success_does_not_call_groq(self):
        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants. Study in Finland.",
        )
        gemini = MagicMock()
        gemini.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps({"scholarships": [_raw_extraction_candidate()]}),
        )
        groq = MagicMock()
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=True),
            client=gemini,
            groq_client=groq,
        )

        candidates = extractor.extract(page, _source())

        self.assertEqual(len(candidates), 1)
        groq.chat.completions.create.assert_not_called()

    def test_extraction_prompt_bounds_and_prioritizes_deduplicated_official_links(self):
        long_url = "/scholarship/" + ("x" * 150)
        news_links = tuple(
            (f"/news/{index}", "News")
            for index in range(500)
        )
        page = _page(
            "Eligibility: Master's students. Funding: €20,000. Deadline: 30 June.",
            links=news_links + (
                ("/scholarships/apply", "Official scholarship application"),
                ("https://official.example/scholarships/apply#form", "Apply"),
                (long_url, "Scholarship application"),
                ("https://unregistered.example/scholarship/apply", "Official application"),
                ("https://user:password@official.example/scholarships/apply", "Apply"),
            ),
        )
        extractor = GeminiScholarshipExtractor(
            _settings(
                max_linked_urls=2,
                max_linked_url_chars=100,
                max_linked_urls_bytes=512,
            ),
            client=MagicMock(),
        )

        prompt = extractor._prompt(page, _source())
        payload = json.loads(prompt.split("Source page data (JSON):\n", 1)[1])

        self.assertLessEqual(len(payload["linked_urls"]), 2)
        self.assertLessEqual(
            sum(len(url.encode("utf-8")) for url in payload["linked_urls"]),
            512,
        )
        self.assertIn("https://official.example/scholarships/apply", payload["linked_urls"])
        self.assertEqual(
            payload["linked_urls"].count("https://official.example/scholarships/apply"),
            1,
        )
        self.assertNotIn("x" * 150, prompt)
        self.assertNotIn("unregistered.example", prompt)
        self.assertNotIn("user:password", prompt)
        self.assertTrue(payload["linked_urls_limited"])

    def test_prompt_enforces_total_linked_url_byte_limit(self):
        page = _page(
            links=(
                ("/scholarships/award-one", "Scholarship award one"),
                ("/scholarships/award-two", "Scholarship award two"),
            ),
        )
        extractor = GeminiScholarshipExtractor(
            _settings(
                max_linked_urls=10,
                max_linked_url_chars=100,
                max_linked_urls_bytes=50,
            ),
            client=MagicMock(),
        )

        payload = json.loads(
            extractor._prompt(page, _source()).split("Source page data (JSON):\n", 1)[1]
        )

        self.assertLessEqual(
            sum(len(url.encode("utf-8")) for url in payload["linked_urls"]),
            50,
        )
        self.assertTrue(payload["linked_urls_limited"])

    def test_budget_reduction_drops_low_priority_links_and_duplicate_lines_first(self):
        source = _source()
        evidence = "\n".join((
            "Eligibility: Master's students with a 3.5 GPA.",
            "Funding: €24,000 stipend.",
            "Deadline: 30 June 2027.",
            "Applicants from Finland and international applicants may apply.",
            "General notice: apply early.",
            "General notice: apply early.",
        ))
        page = _page(
            evidence,
            links=(
                ("/news/latest", "News"),
                ("/news/archive", "News archive"),
                ("/scholarships/apply", "Official scholarship application"),
            ),
        )
        prompt_builder = GeminiScholarshipExtractor(_settings())
        deduplicated_evidence = prompt_builder._remove_redundant_text_lines(evidence)
        application_url = "https://official.example/scholarships/apply"
        reduced_prompt = prompt_builder._prompt(
            page,
            source,
            linked_urls=[application_url],
            linked_urls_limited=True,
            page_text=deduplicated_evidence,
            repeated_text_lines_removed=True,
        )
        limit = gemini_request_payload_size_bytes(
            reduced_prompt,
            {
                "system_instruction": EXTRACTION_SYSTEM_INSTRUCTION,
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        )
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps({"scholarships": []}),
        )
        extractor = GeminiScholarshipExtractor(
            _settings(max_provider_request_bytes=limit),
            client=client,
        )

        self.assertEqual(extractor.extract(page, source), [])

        submitted_prompt = client.models.generate_content.call_args.kwargs["contents"]
        payload = json.loads(submitted_prompt.split("Source page data (JSON):\n", 1)[1])
        self.assertEqual(payload["linked_urls"], [application_url])
        self.assertTrue(payload["linked_urls_limited"])
        self.assertTrue(payload["repeated_text_lines_removed"])
        self.assertEqual(payload["official_page_text"], deduplicated_evidence)
        self.assertEqual(payload["official_page_text"].count("General notice: apply early."), 1)
        for detail in ("3.5 GPA", "€24,000", "30 June 2027", "Finland"):
            self.assertIn(detail, payload["official_page_text"])

    def test_gemini_request_budget_preserves_complete_unicode_scholarship_evidence(self):
        evidence = (
            "Eligibility: Master's students with a 3.5 GPA. "
            "Funding: €24,000 stipend. Deadline: 30 June. "
            "Academic requirement: submit official transcripts."
        )
        page = _page(evidence)
        settings = _settings(max_provider_request_bytes=512_000)
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps({"scholarships": []}),
        )
        extractor = GeminiScholarshipExtractor(settings, client=client)
        prompt = extractor._prompt(page, _source())
        config = {
            "system_instruction": EXTRACTION_SYSTEM_INSTRUCTION,
            "temperature": 0.1,
            "response_mime_type": "application/json",
        }
        request_size = gemini_request_payload_size_bytes(prompt, config)

        self.assertLessEqual(request_size, settings.max_provider_request_bytes)
        self.assertEqual(extractor.extract(page, _source()), [])
        submitted_prompt = client.models.generate_content.call_args.kwargs["contents"]
        payload = json.loads(submitted_prompt.split("Source page data (JSON):\n", 1)[1])
        self.assertEqual(payload["official_page_text"], evidence)
        for detail in ("3.5 GPA", "€24,000", "30 June", "official transcripts"):
            self.assertIn(detail, payload["official_page_text"])

        too_small_client = MagicMock()
        too_small = GeminiScholarshipExtractor(
            _settings(max_provider_request_bytes=request_size - 1),
            client=too_small_client,
        )
        with self.assertLogs(
            "app.services.scholarship_discovery_extraction",
            level="WARNING",
        ) as logs:
            with self.assertRaises(ScholarshipExtractionError) as raised:
                too_small.extract(page, _source())
        self.assertEqual(raised.exception.category, "payload_too_large")
        self.assertEqual(too_small.last_outcome_status, "request_rejected")
        too_small_client.models.generate_content.assert_not_called()
        self.assertTrue(any("request rejected" in line for line in logs.output))
        self.assertFalse(any("provider=gemini" in line for line in logs.output))

    def test_groq_final_payload_budget_includes_json_and_strict_schema_modes(self):
        request_sizes = {}
        for model in ("test-groq-model", "openai/gpt-oss-20b"):
            with self.subTest(model=model):
                gemini = MagicMock()
                gemini.models.generate_content.side_effect = _ProviderFailure(429)
                groq = MagicMock()
                groq.chat.completions.create.return_value = SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(
                        content=json.dumps({"scholarships": []}),
                    ))],
                )
                settings = _settings(
                    groq_fallback_enabled=True,
                    groq_model=model,
                    max_provider_request_bytes=512_000,
                )
                extractor = GeminiScholarshipExtractor(
                    settings,
                    client=gemini,
                    groq_client=groq,
                )

                self.assertEqual(extractor.extract(_page(), _source()), [])
                request = groq.chat.completions.create.call_args.kwargs
                size = groq_request_payload_size_bytes(
                    request["model"],
                    request["messages"][0]["content"],
                    request["messages"][1]["content"],
                    request["response_format"],
                )
                request_sizes[model] = size
                self.assertLessEqual(size, settings.max_provider_request_bytes)

        self.assertGreater(request_sizes["openai/gpt-oss-20b"], request_sizes["test-groq-model"])

    def test_groq_request_budget_covers_offline_sdk_body_in_both_modes(self):
        system_instruction = EXTRACTION_SYSTEM_INSTRUCTION
        contents = "Eligibility: Master's students; funding €24,000."
        cases = (
            ("test-groq-model", None, {"type": "json_object"}),
            (
                "openai/gpt-oss-20b",
                {"type": "object", "properties": {"scholarships": {"type": "array"}}},
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "scholarship_extraction",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {"scholarships": {"type": "array"}},
                        },
                    },
                },
            ),
        )
        for model, schema, response_format in cases:
            with self.subTest(model=model):
                requests = []

                def capture(request):
                    requests.append(request)
                    return httpx.Response(
                        413,
                        json={"error": {"message": "offline payload rejection"}},
                        request=request,
                    )

                http_client = httpx.Client(
                    transport=httpx.MockTransport(capture),
                    trust_env=False,
                )
                client = Groq(
                    api_key="offline-test-key",
                    http_client=http_client,
                    max_retries=0,
                )
                request_size = groq_request_payload_size_bytes(
                    model,
                    system_instruction,
                    contents,
                    response_format,
                )
                expected_body = _groq_request_body(
                    model,
                    system_instruction,
                    contents,
                    response_format,
                )
                try:
                    with self.assertRaises(GroqProviderError) as raised:
                        generate_json_completion(
                            client,
                            model=model,
                            system_instruction=system_instruction,
                            contents=contents,
                            strict_schema=schema,
                            max_request_bytes=request_size,
                        )

                    self.assertEqual(raised.exception.category, "payload_too_large")
                    self.assertEqual(raised.exception.http_status, 413)
                    self.assertEqual(len(requests), 1)
                    self.assertEqual(json.loads(requests[0].content), expected_body)
                    # The SDK uses compact JSON serialization; assert semantic body equality
                    # and that its final wire body remains below the estimator's upper bound.
                    self.assertLessEqual(len(requests[0].content), request_size)
                finally:
                    http_client.close()

    def test_groq_strict_schema_budget_fails_before_request(self):
        page = _page()
        source = _source()
        strict_model = "openai/gpt-oss-20b"
        prompt_builder = GeminiScholarshipExtractor(_settings())
        prompt = prompt_builder._prompt(page, source, strict_output=True)
        schema = _strict_extraction_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "scholarship_extraction",
                "strict": True,
                "schema": schema,
            },
        }
        groq_size = groq_request_payload_size_bytes(
            strict_model,
            EXTRACTION_SYSTEM_INSTRUCTION,
            prompt,
            response_format,
        )
        gemini_size = gemini_request_payload_size_bytes(
            prompt_builder._prompt(page, source),
            {
                "system_instruction": EXTRACTION_SYSTEM_INSTRUCTION,
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        )
        self.assertGreater(groq_size, gemini_size)

        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        extractor = GeminiScholarshipExtractor(
            _settings(
                groq_model=strict_model,
                groq_fallback_enabled=True,
                max_provider_request_bytes=gemini_size,
            ),
            client=gemini,
            groq_client=groq,
        )

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, source)

        self.assertEqual(raised.exception.category, "payload_too_large")
        self.assertIsNone(raised.exception.http_status)
        gemini.models.generate_content.assert_called_once()
        groq.chat.completions.create.assert_not_called()

    def test_groq_413_is_classified_and_not_retried(self):
        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        groq.chat.completions.create.side_effect = _ProviderFailure(413)
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=True),
            client=gemini,
            groq_client=groq,
        )

        with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
            with self.assertRaises(ScholarshipExtractionError) as raised:
                extractor.extract(_page(), _source())

        self.assertEqual(raised.exception.category, "payload_too_large")
        self.assertEqual(raised.exception.http_status, 413)
        self.assertEqual(extractor.last_outcome_status, "provider_error")
        self.assertEqual(groq.chat.completions.create.call_count, 1)
        self.assertTrue(any("provider=groq category=payload_too_large" in line for line in logs.output))
        self.assertTrue(any("http_status=413" in line for line in logs.output))

    def test_gemini_quota_error_falls_back_to_groq_and_uses_shared_validation(self):
        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants. Study in Finland.",
        )
        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        groq.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"scholarships": [_raw_extraction_candidate()]}),
            ))],
        )
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=True, groq_model="test-groq-model"),
            client=gemini,
            groq_client=groq,
        )

        with self.assertLogs("app.services.scholarship_discovery_extraction", level="INFO") as logs:
            candidates = extractor.extract(page, _source())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(groq.chat.completions.create.call_args.kwargs["model"], "test-groq-model")
        self.assertEqual(
            gemini.models.generate_content.call_args.kwargs["contents"],
            groq.chat.completions.create.call_args.kwargs["messages"][1]["content"],
        )
        self.assertEqual(
            groq.chat.completions.create.call_args.kwargs["response_format"],
            {"type": "json_object"},
        )
        self.assertTrue(any("provider=gemini category=quota_error" in line for line in logs.output))
        self.assertTrue(any("provider=groq category=fallback_selected" in line for line in logs.output))
        self.assertTrue(any("provider=groq category=request_started" in line for line in logs.output))
        self.assertTrue(any("provider=groq category=fallback_success" in line for line in logs.output))
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")
        self.assertTrue(any("source_id=test-finland" in line for line in logs.output))
        self.assertNotIn(page.text, "\n".join(logs.output))
        self.assertNotIn("test-api-key", "\n".join(logs.output))

    def test_valid_empty_response_has_a_distinct_outcome(self):
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps({"scholarships": []}),
        )
        extractor = GeminiScholarshipExtractor(_settings(), client=client)

        self.assertEqual(extractor.extract(_page(), _source()), [])
        self.assertEqual(extractor.last_outcome_status, "valid_empty")
        self.assertEqual(extractor.last_rejected_count, 0)
        client.models.generate_content.assert_called_once()

    def test_insufficient_page_content_is_reported_before_provider_call(self):
        client = MagicMock()
        page = replace(_page(""), insufficient_content=True)
        extractor = GeminiScholarshipExtractor(_settings(), client=client)

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())

        self.assertEqual(raised.exception.category, "insufficient_page_content")
        self.assertEqual(extractor.last_outcome_status, "insufficient_page_content")
        client.models.generate_content.assert_not_called()

    def test_supported_groq_model_uses_strict_schema_with_protected_fields_excluded(self):
        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        groq.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"scholarships": [_raw_extraction_candidate()]}),
            ))],
        )
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=True, groq_model="openai/gpt-oss-20b"),
            client=gemini,
            groq_client=groq,
        )

        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants. Study in Finland.",
        )
        self.assertEqual(len(extractor.extract(page, _source())), 1)

        response_format = groq.chat.completions.create.call_args.kwargs["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        schema = response_format["json_schema"]["schema"]
        self.assertEqual(schema["required"], ["scholarships"])
        self.assertFalse(schema["additionalProperties"])
        values_schema = schema["properties"]["scholarships"]["items"]["properties"]["values"]
        self.assertFalse(values_schema["additionalProperties"])
        self.assertEqual(set(values_schema["required"]), set(values_schema["properties"]))
        self.assertNotIn("verification_status", values_schema["properties"])

    def test_groq_quota_error_is_classified_and_returned(self):
        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        groq.chat.completions.create.side_effect = _ProviderFailure(429)
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=True),
            client=gemini,
            groq_client=groq,
        )

        with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
            with self.assertRaises(ScholarshipExtractionError) as raised:
                extractor.extract(_page(), _source())

        self.assertEqual(raised.exception.category, "quota_error")
        self.assertEqual(raised.exception.http_status, 429)
        self.assertEqual(extractor.last_outcome_status, "provider_error")
        self.assertTrue(any("category=fallback_failed" in line for line in logs.output))
        self.assertTrue(any("category=all_providers_exhausted" in line for line in logs.output))

    def test_groq_authentication_error_is_not_retried_or_disclosed(self):
        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        groq.chat.completions.create.side_effect = _ProviderFailure(401)
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=True),
            client=gemini,
            groq_client=groq,
        )

        with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
            with self.assertRaises(ScholarshipExtractionError) as raised:
                extractor.extract(_page(), _source())

        self.assertEqual(raised.exception.category, "authentication_error")
        self.assertEqual(raised.exception.http_status, 401)
        self.assertEqual(groq.chat.completions.create.call_count, 1)
        self.assertNotIn("sanitized provider failure", "\n".join(logs.output))
        self.assertTrue(any("category=fallback_failed" in line for line in logs.output))
        self.assertTrue(any("category=all_providers_exhausted" in line for line in logs.output))

    def test_gemini_authentication_and_malformed_request_do_not_fall_back(self):
        for status, category in (
            (400, "provider_error"),
            (401, "authentication_error"),
            (403, "permission_error"),
        ):
            with self.subTest(status=status):
                gemini = MagicMock()
                gemini.models.generate_content.side_effect = _ProviderFailure(status)
                groq = MagicMock()
                extractor = GeminiScholarshipExtractor(
                    _settings(groq_fallback_enabled=True),
                    client=gemini,
                    groq_client=groq,
                )

                with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
                    with self.assertRaises(ScholarshipExtractionError) as raised:
                        extractor.extract(_page(), _source())

                self.assertEqual(raised.exception.category, category)
                self.assertEqual(extractor.last_outcome_status, "provider_error")
                groq.chat.completions.create.assert_not_called()
                self.assertTrue(any("reason=not_eligible" in line for line in logs.output))

    def test_fallback_disabled_preserves_gemini_quota_error(self):
        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=False),
            client=gemini,
            groq_client=groq,
        )

        with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
            with self.assertRaises(ScholarshipExtractionError) as raised:
                extractor.extract(_page(), _source())

        self.assertEqual(raised.exception.category, "quota_error")
        self.assertEqual(raised.exception.http_status, 429)
        self.assertTrue(any("reason=disabled" in line for line in logs.output))
        groq.chat.completions.create.assert_not_called()

    def test_groq_malformed_json_is_rejected_without_relaxing_validation(self):
        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        groq.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
        )
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=True),
            client=gemini,
            groq_client=groq,
        )

        with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
            with self.assertRaises(ScholarshipExtractionError) as raised:
                extractor.extract(_page(), _source())

        self.assertEqual(raised.exception.category, "malformed_response")
        self.assertEqual(extractor.last_outcome_status, "malformed_response")
        self.assertTrue(any("category=fallback_failed" in line for line in logs.output))
        self.assertTrue(any("category=all_providers_exhausted" in line for line in logs.output))

        groq.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({
                    "scholarships": [
                        _raw_extraction_candidate(verification_status="verified"),
                    ],
                }),
            ))],
        )
        self.assertEqual(extractor.extract(_page(), _source()), [])
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertEqual(extractor.last_rejection_reasons, ["ScholarshipExtractionError"])
        self.assertEqual(extractor.last_outcome_status, "candidates_rejected")

    def test_both_providers_failing_returns_only_sanitized_groq_error(self):
        gemini = MagicMock()
        gemini.models.generate_content.side_effect = _ProviderFailure(429)
        groq = MagicMock()
        groq.chat.completions.create.side_effect = _ProviderFailure(500)
        extractor = GeminiScholarshipExtractor(
            _settings(groq_fallback_enabled=True),
            client=gemini,
            groq_client=groq,
        )

        with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
            with self.assertRaises(ScholarshipExtractionError) as raised:
                extractor.extract(_page(), _source())

        self.assertEqual(raised.exception.category, "provider_error")
        self.assertEqual(raised.exception.http_status, 500)
        self.assertNotIn("official_page_text", "\n".join(logs.output))
        self.assertTrue(any("provider=groq category=provider_error" in line for line in logs.output))

    def test_groq_configuration_and_api_key_are_loaded_without_exposing_them(self):
        with patch.dict(
            os.environ,
            {
                "GROQ_MODEL": "configured-test-model",
                "GROQ_FALLBACK_ENABLED": "true",
                "SCHOLARSHIP_DISCOVERY_MAX_LINKED_URLS": "25",
                "SCHOLARSHIP_DISCOVERY_MAX_LINKED_URL_CHARS": "1024",
                "SCHOLARSHIP_DISCOVERY_MAX_LINKED_URL_BYTES": "8192",
                "SCHOLARSHIP_DISCOVERY_MAX_PROVIDER_REQUEST_BYTES": "262144",
            },
            clear=True,
        ):
            settings = scholarship_discovery_settings()
        self.assertEqual(settings.groq_model, "configured-test-model")
        self.assertTrue(settings.groq_fallback_enabled)
        self.assertEqual(settings.max_linked_urls, 25)
        self.assertEqual(settings.max_linked_url_chars, 1024)
        self.assertEqual(settings.max_linked_urls_bytes, 8192)
        self.assertEqual(settings.max_provider_request_bytes, 262144)

        client = MagicMock()
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=True):
            with patch("app.services.scholarship_discovery_extraction._groq_client_instance", None):
                with patch("app.services.scholarship_discovery_extraction.create_groq_client") as create_client:
                    create_client.return_value = client
                    self.assertIs(_groq_client(), client)
                    create_client.assert_called_once_with("test-key")

    def test_extraction_rejects_verification_fields_and_bad_json(self):
        page = _page("Evidence")
        source = _source()
        protected = {
            "scholarships": [{
                "values": {"name": "Award", "country": "Finland", "verification_status": "verified"},
                "evidence": {},
                "masters_only": True,
                "masters_evidence": "Master's",
                "scholarship_offer_evidence": "scholarship award",
            }],
        }
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=__import__("json").dumps(protected),
        )
        extractor = GeminiScholarshipExtractor(_settings(), client=client)
        candidates = extractor.extract(page, source)
        self.assertEqual(candidates, [])
        self.assertEqual(extractor.last_rejected_count, 1)

        client.models.generate_content.return_value = SimpleNamespace(text="not-json")
        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(page, source)


class SafeFetchingTests(unittest.TestCase):
    def test_validate_url_accepts_registered_domain_and_subdomains_only(self):
        fetcher = OfficialSourceFetcher(_settings())
        accepted = (
            "https://official.example/scholarships",
            "https://official.example./scholarships",
            "https://www.official.example/scholarships",
            "https://portal.europe.official.example/scholarships",
        )
        rejected = (
            "https://official.example.attacker.com/scholarships",
            "https://bad..official.example/scholarships",
            "https://official.example../scholarships",
            "https://other.example/scholarships",
        )

        for url in accepted:
            with self.subTest(url=url):
                self.assertEqual(fetcher._validate_url(_source(), url).scheme, "https")
        for url in rejected:
            with self.subTest(url=url):
                with self.assertRaises(DiscoveryFetchError):
                    fetcher._validate_url(_source(), url)

    def test_fetcher_rejects_unregistered_and_non_public_hosts(self):
        fetcher = OfficialSourceFetcher(_settings())
        with self.assertRaises(DiscoveryFetchError):
            fetcher._validate_url(_source(), "https://other.example/scholarship")

        private_fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("192.168.1.10")]}),
            connector=MagicMock(),
        )
        with self.assertRaisesRegex(DiscoveryFetchError, "public addresses"):
            private_fetcher._request(_source(), _source().source_url)

    def test_crawl_raises_when_root_page_fails(self):
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(fetcher, "fetch", side_effect=DiscoveryFetchError("root fetch failed")):
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher.crawl(_source())
        self.assertEqual(raised.exception.stage, "root_fetch")
        self.assertEqual(raised.exception.page_stage, "root_fetch")

    def test_http_status_diagnostics_preserve_status_and_retry_counts(self):
        source = _source()
        transient_sleeper = Mock()
        fetcher = OfficialSourceFetcher(_settings(max_retries=1), sleep=transient_sleeper)
        with patch.object(fetcher, "_request", return_value=(503, Message(), b"")) as request:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher._fetch_bytes(source, source.source_url)

        self.assertEqual(request.call_count, 2)
        self.assertEqual(raised.exception.category, "http_status")
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.attempt_count, 2)
        self.assertEqual(raised.exception.attempt_limit, 2)
        transient_sleeper.assert_called_once_with(1)

        non_transient_sleeper = Mock()
        non_transient_fetcher = OfficialSourceFetcher(
            _settings(max_retries=1),
            sleep=non_transient_sleeper,
        )
        with patch.object(
            non_transient_fetcher,
            "_request",
            return_value=(403, Message(), b""),
        ) as request:
            with self.assertRaises(DiscoveryFetchError) as raised:
                non_transient_fetcher._fetch_bytes(source, source.source_url)

        self.assertEqual(request.call_count, 1)
        self.assertEqual(raised.exception.category, "http_status")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.attempt_count, 1)
        self.assertEqual(raised.exception.attempt_limit, 2)
        non_transient_sleeper.assert_not_called()

    def test_timeout_and_connection_failures_are_sanitized_and_categorized(self):
        source = _source()
        cases = (
            (TimeoutError("sensitive timeout detail"), "timeout", "TimeoutError"),
            (ConnectionError("sensitive connection detail"), "connection_error", "ConnectionError"),
        )
        for error, category, cause_type in cases:
            with self.subTest(category=category):
                fetcher = OfficialSourceFetcher(_settings(max_retries=0))
                with patch.object(fetcher, "_request", side_effect=error):
                    with self.assertRaises(DiscoveryFetchError) as raised:
                        fetcher._fetch_bytes(source, source.source_url)

                self.assertEqual(raised.exception.category, category)
                self.assertEqual(raised.exception.immediate_cause_type, cause_type)
                self.assertEqual(raised.exception.attempt_count, 1)
                self.assertEqual(raised.exception.attempt_limit, 1)
                self.assertNotIn("sensitive", str(raised.exception))

    def test_unsupported_content_type_has_content_validation_category(self):
        source = _source()
        headers = Message()
        headers["Content-Type"] = "application/octet-stream"
        fetcher = OfficialSourceFetcher(_settings(max_retries=0))
        with patch.object(fetcher, "_request", return_value=(200, headers, b"")):
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher._fetch_bytes(source, source.source_url)

        self.assertEqual(raised.exception.category, "content_validation_failed")
        self.assertEqual(raised.exception.status_code, 200)
        self.assertEqual(raised.exception.attempt_count, 1)
        self.assertEqual(raised.exception.attempt_limit, 1)

    def test_redirect_without_location_preserves_status_and_attempt_metadata(self):
        source = _source()
        fetcher = OfficialSourceFetcher(_settings(max_retries=1), sleep=Mock())
        with patch.object(fetcher, "_request", return_value=(302, Message(), b"")) as request:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher._fetch_bytes(source, source.source_url)

        self.assertEqual(request.call_count, 1)
        self.assertEqual(raised.exception.category, "content_validation_failed")
        self.assertEqual(raised.exception.status_code, 302)
        self.assertEqual(raised.exception.attempt_count, 1)
        self.assertEqual(raised.exception.attempt_limit, 2)

    def test_https_redirect_downgrade_is_rejected_before_second_request(self):
        source = _source()
        headers = Message()
        headers["Location"] = "http://official.example/next"
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(
            fetcher,
            "_request",
            return_value=(302, headers, b""),
        ) as request:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher._fetch_bytes(source, source.source_url)

        self.assertEqual(request.call_count, 1)
        self.assertEqual(raised.exception.category, "https_downgrade_rejected")
        self.assertIn("HTTPS redirect to HTTP", str(raised.exception))

    def test_https_redirect_to_https_is_preserved(self):
        source = _source()
        redirect_headers = Message()
        redirect_headers["Location"] = "https://official.example/next"
        response_headers = Message()
        response_headers["Content-Type"] = "text/html"
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(
            fetcher,
            "_request",
            side_effect=[
                (302, redirect_headers, b""),
                (200, response_headers, b"official page"),
            ],
        ) as request:
            final_url, _headers, body = fetcher._fetch_bytes(
                source,
                source.source_url,
            )

        self.assertEqual(request.call_count, 2)
        self.assertEqual(final_url, "https://official.example/next")
        self.assertEqual(body, b"official page")

    def test_http_transport_is_not_invoked_when_cancellation_wins(self):
        budget = DiscoveryRunBudget(
            duration_seconds=60,
            start_deadline_timer=False,
        )
        connector = MagicMock()
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34")]}),
            connector=connector,
            run_budget=budget,
        )
        begin_attempt = budget.begin_http_attempt

        def cancel_after_registration(callback):
            token, remaining = begin_attempt(callback)
            budget._expire()
            return token, remaining

        try:
            with patch.object(
                budget,
                "begin_http_attempt",
                side_effect=cancel_after_registration,
            ):
                with self.assertRaises(DiscoveryRunLimitExceeded):
                    fetcher._request(_source(), _source().source_url)

            connector.assert_not_called()
            self.assertEqual(budget.snapshot()["http_attempts"], 0)
            self.assertEqual(budget._cancellations, {})
            self.assertEqual(budget._operation_gates, {})
        finally:
            budget.close()

    def test_manual_import_fetcher_also_rejects_https_downgrade(self):
        headers = Message()
        headers["Location"] = "http://official.example/import"
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(
            fetcher,
            "_request",
            return_value=(302, headers, b""),
        ) as request:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher.fetch_import_url(
                    "https://official.example/import",
                    "webpage",
                )

        self.assertEqual(request.call_count, 1)
        self.assertEqual(raised.exception.category, "https_downgrade_rejected")

    def test_run_budget_counts_robots_redirects_retries_and_failed_requests(self):
        source = replace(_source(), source_url="http://official.example/scholarships")
        address = _address_info("93.184.216.34", 80)
        robots = _FakeSocket(
            _http_response(404, body=b"", headers=b"Content-Type: text/plain\r\n")
        )
        redirect = _FakeSocket(
            _http_response(
                302,
                headers=b"Location: /scholarships/current\r\n",
            )
        )
        page = _FakeSocket(
            _http_response(
                200,
                body=b"<html><main>Official scholarship details.</main></html>",
            )
        )
        budget = DiscoveryRunBudget(
            max_http_attempts=3,
            max_pages=1,
            duration_seconds=60,
            start_deadline_timer=False,
        )
        fetcher = OfficialSourceFetcher(
            _settings(max_retries=0),
            resolver=_FakeDNSResolver({"A": [address]}),
            connector=_pinned_connector(robots, redirect, page),
            run_budget=budget,
        )
        try:
            fetched = fetcher.crawl(source)
            self.assertEqual(len(fetched), 1)
            self.assertEqual(budget.snapshot()["http_attempts"], 3)
            self.assertEqual(budget.snapshot()["pages_started"], 1)
            self.assertEqual(budget.snapshot()["pages_fetched"], 1)
        finally:
            budget.close()

        retry_budget = DiscoveryRunBudget(
            max_http_attempts=2,
            duration_seconds=60,
            sleep=lambda _delay: None,
            start_deadline_timer=False,
        )
        first_failure = _FakeSocket(_http_response(503, body=b""))
        retry_success = _FakeSocket(_http_response(200))
        retry_fetcher = OfficialSourceFetcher(
            _settings(max_retries=1),
            resolver=_FakeDNSResolver({"A": [address]}),
            connector=_pinned_connector(first_failure, retry_success),
            run_budget=retry_budget,
        )
        try:
            retry_fetcher._fetch_bytes(source, source.source_url)
            self.assertEqual(retry_budget.snapshot()["http_attempts"], 2)
        finally:
            retry_budget.close()

    def test_http_and_page_caps_prevent_additional_outbound_requests(self):
        source = replace(_source(), source_url="http://official.example/scholarships")
        address = _address_info("93.184.216.34", 80)
        budget = DiscoveryRunBudget(
            max_http_attempts=1,
            duration_seconds=60,
            start_deadline_timer=False,
        )
        first_failure = _FakeSocket(_http_response(503, body=b""))
        second_request = _FakeSocket(_http_response(200))
        connector = _pinned_connector(first_failure, second_request)
        fetcher = OfficialSourceFetcher(
            _settings(max_retries=1),
            resolver=_FakeDNSResolver({"A": [address]}),
            connector=connector,
            run_budget=budget,
            sleep=lambda _delay: None,
        )
        try:
            with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                fetcher._fetch_bytes(source, source.source_url)
            self.assertEqual(raised.exception.resource, "http_attempts")
            connector.assert_called_once()
            self.assertEqual(budget.snapshot()["http_attempts"], 1)
        finally:
            budget.close()

        page_budget = DiscoveryRunBudget(
            max_pages=1,
            max_pages_per_source=3,
            duration_seconds=60,
            start_deadline_timer=False,
        )
        robots = _FakeSocket(
            _http_response(404, body=b"", headers=b"Content-Type: text/plain\r\n")
        )
        root = _FakeSocket(
            _http_response(
                200,
                body=(
                    b'<html><main>Official scholarship details. '
                    b'<a href="/scholarship">Scholarship details</a></main></html>'
                ),
            )
        )
        page_connector = _pinned_connector(robots, root)
        page_fetcher = OfficialSourceFetcher(
            _settings(max_pages_per_source=5, max_retries=0),
            resolver=_FakeDNSResolver({"A": [address]}),
            connector=page_connector,
            run_budget=page_budget,
        )
        try:
            with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                page_fetcher.crawl(source)
            self.assertEqual(raised.exception.resource, "pages")
            self.assertEqual(page_connector.call_count, 2)
            self.assertEqual(page_budget.snapshot()["pages_started"], 1)
            self.assertEqual(page_budget.snapshot()["pages_fetched"], 1)
        finally:
            page_budget.close()

    def test_redirect_limit_preserves_last_status_and_attempt_metadata(self):
        source = _source()
        headers = Message()
        headers["Location"] = "/redirect"
        fetcher = OfficialSourceFetcher(_settings(max_retries=1), sleep=Mock())
        with patch("app.services.scholarship_discovery_fetch.MAX_REDIRECTS", 2):
            with patch.object(fetcher, "_request", return_value=(302, headers, b"")) as request:
                with self.assertRaises(DiscoveryFetchError) as raised:
                    fetcher._fetch_bytes(source, source.source_url)

        self.assertEqual(request.call_count, 3)
        self.assertEqual(raised.exception.category, "content_validation_failed")
        self.assertEqual(raised.exception.status_code, 302)
        self.assertEqual(raised.exception.attempt_count, 1)
        self.assertEqual(raised.exception.attempt_limit, 2)

    def test_crawl_preserves_root_page_when_linked_page_fails(self):
        root = _page(
            "Root scholarship information.",
            links=(("/scholarships/broken", "Broken link"),),
        )
        fetcher = OfficialSourceFetcher(_settings())

        def fake_fetch(_source_arg, url):
            if url == _source().source_url:
                return root
            raise DiscoveryFetchError("response body must not be logged")

        with patch.object(fetcher, "fetch", side_effect=fake_fetch):
            with self.assertLogs("app.services.scholarship_discovery_fetch", level="WARNING") as logs:
                pages = fetcher.crawl(_source())

        self.assertEqual(pages, [root])
        self.assertNotIn("response body", "\n".join(logs.output))
        self.assertNotIn("/scholarships/broken", "\n".join(logs.output))
        self.assertTrue(any("stage=linked_page" in line for line in logs.output))
        self.assertTrue(any("page_stage=linked_page" in line for line in logs.output))
        self.assertTrue(any("category=unknown" in line for line in logs.output))

    def test_robots_failure_preserves_safe_status_and_stage_diagnostics(self):
        page_url = _source().source_url + "?lang=en"
        source = replace(_source(), source_url=page_url)
        fetcher = OfficialSourceFetcher(_settings())
        robots_error = DiscoveryFetchError(
            "sensitive response body",
            status_code=503,
            attempt_count=2,
            attempt_limit=3,
        )

        with patch.object(fetcher, "_fetch_bytes", side_effect=robots_error):
            with self.assertLogs("app.services.scholarship_discovery_fetch", level="WARNING") as logs:
                with self.assertRaises(DiscoveryFetchError) as raised:
                    fetcher.fetch(source, page_url)

        self.assertEqual(raised.exception.category, "robots_check_failed")
        self.assertEqual(raised.exception.cause_category, "http_status")
        self.assertEqual(raised.exception.stage, "robots")
        self.assertEqual(raised.exception.page_stage, "root_fetch")
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.attempt_count, 2)
        self.assertEqual(raised.exception.attempt_limit, 3)
        diagnostic_output = "\n".join(logs.output) + str(raised.exception)
        self.assertNotIn("sensitive response body", diagnostic_output)
        self.assertNotIn("lang=en", diagnostic_output)

    def test_cached_robots_failure_uses_each_requests_source_and_page_context(self):
        first_source = replace(_source(), source_id="first-source")
        second_source = replace(
            _source(),
            source_id="second-source",
            source_url="https://official.example/another-root",
        )
        fetcher = OfficialSourceFetcher(_settings())
        robots_error = DiscoveryFetchError(
            "sensitive robots response",
            status_code=503,
            category="http_status",
            attempt_count=2,
            attempt_limit=3,
            cause_type="TimeoutError",
        )

        with patch.object(fetcher, "_fetch_bytes", side_effect=robots_error) as fetch_bytes:
            with self.assertRaises(DiscoveryFetchError) as first:
                fetcher.fetch(first_source, "https://official.example/linked-page")
            with self.assertRaises(DiscoveryFetchError) as second:
                fetcher.fetch(second_source, second_source.source_url)

        self.assertIsNot(first.exception, second.exception)
        self.assertEqual(first.exception.source_id, "first-source")
        self.assertEqual(first.exception.page_stage, "linked_page")
        self.assertEqual(second.exception.source_id, "second-source")
        self.assertEqual(second.exception.page_stage, "root_fetch")
        for error in (first.exception, second.exception):
            self.assertEqual(error.stage, "robots")
            self.assertEqual(error.status_code, 503)
            self.assertEqual(error.attempt_count, 2)
            self.assertEqual(error.attempt_limit, 3)
            self.assertEqual(error.cause_type, "TimeoutError")
            self.assertEqual(error.cause_category, "http_status")
        self.assertEqual(fetch_bytes.call_count, 1)

    def test_crawl_continues_to_other_queued_pages_after_linked_page_failure(self):
        valid_url = "https://official.example/scholarships/valid"
        root = _page(
            "Root scholarship information.",
            links=(
                ("/scholarships/broken", "Broken link"),
                (valid_url, "Valid scholarship"),
            ),
        )
        valid_page = _page("Valid linked scholarship information.", url=valid_url)
        fetcher = OfficialSourceFetcher(_settings())

        def fake_fetch(_source_arg, url):
            if url == _source().source_url:
                return root
            if url.endswith("/broken"):
                raise DiscoveryFetchError("response body must not be logged")
            return valid_page

        with patch.object(fetcher, "fetch", side_effect=fake_fetch) as fetch:
            with self.assertLogs("app.services.scholarship_discovery_fetch", level="WARNING"):
                pages = fetcher.crawl(_source())

        self.assertEqual(pages, [root, valid_page])
        self.assertIn(valid_url, [call.args[1] for call in fetch.call_args_list])
        self.assertEqual(fetcher.last_crawl_stats["linked_urls_discovered"], 2)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_fetched"], 1)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_failed"], 1)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_skipped"], 0)

    def test_crawl_queues_registered_subdomains_but_not_deceptive_or_external_domains(self):
        www_url = "https://www.official.example/scholarships/apply"
        nested_url = "https://portal.europe.official.example/scholarships/award"
        root = _page(
            "Root scholarship information.",
            links=(
                (www_url, "Apply"),
                (nested_url, "Award"),
                ("https://official.example.attacker.com/scholarships/fake", "Fake"),
                ("https://other.example/scholarships/fake", "External"),
            ),
        )
        fetcher = OfficialSourceFetcher(_settings())
        fetched_pages = {
            _source().source_url: root,
            www_url: _page("Apply page", url=www_url),
            nested_url: _page("Award page", url=nested_url),
        }

        with patch.object(fetcher, "fetch", side_effect=lambda _src, url: fetched_pages[url]) as fetch:
            pages = fetcher.crawl(_source())

        self.assertEqual(len(pages), 3)
        self.assertEqual(
            [call.args[1] for call in fetch.call_args_list],
            [_source().source_url, www_url, nested_url],
        )

    def test_fetcher_respects_robots_and_response_size_limits(self):
        robots = MagicMock()
        robots.can_fetch.return_value = False
        fetcher = OfficialSourceFetcher(_settings())
        robot_headers = Message()
        robot_headers["Content-Type"] = "text/plain; charset=utf-8"
        with patch.object(fetcher, "_fetch_bytes", return_value=(_source().source_url, robot_headers, b"")):
            with patch("app.services.scholarship_discovery_fetch.urllib.robotparser.RobotFileParser",
                       return_value=robots):
                with self.assertRaisesRegex(DiscoveryFetchError, "robots.txt"):
                    fetcher.fetch(_source(), _source().source_url)

        response_socket = _FakeSocket(_http_response(body=b"x" * 17))
        fetcher = OfficialSourceFetcher(
            _settings(max_response_bytes=16),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34", 80)]}),
            connector=_pinned_connector(response_socket),
        )
        with self.assertRaisesRegex(DiscoveryFetchError, "size limit"):
            fetcher._request(_source(), "http://official.example/scholarships")
        self.assertTrue(response_socket.closed)

    def test_request_rejects_sensitive_and_signed_query_parameters_before_transport(self):
        resolver = _FakeDNSResolver({"A": [_address_info("93.184.216.34", 443)]})
        connector = MagicMock()
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=resolver,
            connector=connector,
        )
        urls = (
            "https://official.example/apply?access_token=private-value&lang=en",
            "https://official.example/apply?signature=private-signature&expires=2026",
            "https://official.example/apply?hmac=private-hmac&expires=2026",
            "https://official.example/apply?hmacsha256=private-hash&cycle=2026",
            "https://official.example/apply?hash=private-hash",
            "https://official.example/apply?mac=private-mac",
            "https://official.example/apply?sig=private-sig",
            "https://official.example/apply?credential=private-credential",
            "https://official.example/apply?x-sig=private-x-sig",
            "https://official.example/apply?auth_key=private-auth-key",
            "https://official.example/apply?auth_code=private-auth-code",
            "https://official.example/apply?x_auth=private-x-auth",
            "https://official.example/apply?x_session=private-x-session",
            "https://official.example/apply?oauth_state=private-oauth-state",
            "https://official.example/apply?AUTH-CODE=private-separated-auth-code",
            "https://official.example/apply?X-AUTH=private-uppercase-auth",
            "https://official.example/apply?X-Session=private-separated-session",
            "https://official.example/apply?OAuth-State=private-separated-oauth-state",
            "https://official.example/apply?x_signature=private-x-signature",
            "https://official.example/apply?signed=private-signed",
            "https://official.example/apply?X_SIG=private-uppercase-sig",
            "https://official.example/apply?AUTH-Key=private-separated-key",
            "https://official.example/apply?X__Signature=private-separated-signature",
            "https://official.example/apply?accesskey=private-accesskey",
            "https://official.example/apply?apikey=private-apikey",
            "https://official.example/apply?awsaccesskeyid=private-aws-key",
            "https://official.example/apply?authorization=private-authorization",
            "https://official.example/apply?authorizationcode=private-authorization-code",
            "https://official.example/apply?auth=private-auth",
            "https://official.example/apply?bearer=private-bearer",
            "https://official.example/apply?clientsecret=private-client-secret",
            "https://official.example/apply?code=private-code",
            "https://official.example/apply?codeverifier=private-code-verifier",
            "https://official.example/apply?jwt=private-jwt",
            "https://official.example/apply?privatekey=private-private-key",
            "https://official.example/apply?session=private-session",
            "https://official.example/apply?sessionid=private-session-id",
            "https://official.example/apply?sign=private-sign",
            "https://official.example/apply?credentials=private-credentials",
            "https://official.example/apply?password=private-password",
            "https://official.example/apply?passwd=private-passwd",
            "https://official.example/apply?secret=private-secret",
            "https://official.example/apply?key=private-key",
            "https://official.example/apply?x-token=private-x-token",
            "https://official.example/apply?oauth_signature=private-oauth-signature",
            "https://official.example/apply?aws_secret_access_key=private-aws-secret",
            "https://official.example/apply?xgoog_signature=private-google-signature",
        )

        for url in urls:
            with self.subTest(query=url.split("?", 1)[1].split("=", 1)[0]):
                with self.assertRaises(DiscoveryFetchError) as raised:
                    fetcher._request(_source(), url)
                self.assertEqual(raised.exception.category, "sensitive_query_rejected")
                self.assertNotIn("private-value", str(raised.exception))
                self.assertNotIn("private-signature", str(raised.exception))
                self.assertNotIn("private-hmac", str(raised.exception))
                self.assertNotIn("private-hash", str(raised.exception))
                self.assertNotIn("private-mac", str(raised.exception))
                self.assertNotIn("private-sig", str(raised.exception))
                self.assertNotIn("private-credential", str(raised.exception))
                self.assertNotIn("private-x-sig", str(raised.exception))
                self.assertNotIn("private-auth-key", str(raised.exception))
                self.assertNotIn("private-x-signature", str(raised.exception))
                self.assertNotIn("private-signed", str(raised.exception))
                self.assertNotIn("private-uppercase-sig", str(raised.exception))
                self.assertNotIn("private-separated-key", str(raised.exception))
                self.assertNotIn("private-separated-signature", str(raised.exception))
                self.assertNotIn("private-", str(raised.exception))

        self.assertEqual(resolver.calls, [])
        connector.assert_not_called()

    def test_request_preserves_harmless_query_parameters(self):
        response_socket = _FakeSocket(_http_response())
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34", 80)]}),
            connector=_pinned_connector(response_socket),
        )

        status, _headers, _body = fetcher._request(
            _source(),
            "http://official.example/scholarships/apply?page=2&lang=en&category=masters&sign_up=1",
        )

        self.assertEqual(status, 200)
        self.assertIn(
            b"GET /scholarships/apply?page=2&lang=en&category=masters&sign_up=1 HTTP/1.1",
            response_socket.sent,
        )

    def test_crawler_skips_sensitive_links_and_deduplicates_fragment_variants(self):
        root_url = _source().source_url
        harmless_url = "https://official.example/scholarships/apply?lang=en"
        root_html = (
            b"<p>Official scholarship application details.</p>"
            b"<a href='/scholarships/apply?token=private-value'>Application</a>"
            b"<a href='/scholarships/signed?signature=private-signature&expires=2026'>Application</a>"
            b"<a href='/scholarships/apply?lang=en#form'>Application</a>"
            b"<a href='/scholarships/apply?lang=en#details'>Application</a>"
        )
        linked_html = b"<p>Application details with harmless query parameters.</p>"
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        fetcher = OfficialSourceFetcher(_settings())
        request_urls = []

        def fake_fetch_bytes(_source_arg, url, allowed_types=None, *, on_request_attempt=None):
            request_urls.append(url)
            if on_request_attempt is not None:
                on_request_attempt()
            body = root_html if url == root_url else linked_html
            return url, headers, body

        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(fetcher, "_fetch_bytes", side_effect=fake_fetch_bytes):
                with self.assertLogs(
                    "app.services.scholarship_discovery_fetch",
                    level="INFO",
                ) as logs:
                    pages = fetcher.crawl(_source())

        self.assertEqual(len(pages), 2)
        self.assertEqual(request_urls, [root_url, harmless_url])
        self.assertEqual(fetcher.last_crawl_stats["linked_urls_discovered"], 4)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_attempted"], 1)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_fetched"], 1)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_failed"], 0)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_skipped_safety"], 2)
        self.assertNotIn("private-value", str(request_urls))
        self.assertNotIn("private-signature", str(request_urls))
        diagnostic_output = "\n".join(logs.output)
        self.assertIn("category=sensitive_query_rejected", diagnostic_output)
        self.assertNotIn("private-value", diagnostic_output)
        self.assertNotIn("private-signature", diagnostic_output)

    def test_crawler_attempt_counts_exclude_queued_pages_past_page_limit(self):
        root_url = _source().source_url
        first_url = "https://official.example/scholarships/first"
        failed_url = "https://official.example/scholarships/failed?cycle=one"
        unattempted_url = "https://official.example/scholarships/failed?cycle=two"
        root_html = (
            b"<p>Root scholarship information.</p>"
            b"<a href='/scholarships/first#top'>Scholarship details</a>"
            b"<a href='/scholarships/first#bottom'>Scholarship details</a>"
            b"<a href='/scholarships/failed?cycle=one'>Scholarship details</a>"
            b"<a href='/scholarships/failed?cycle=two'>Scholarship details</a>"
        )
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        fetcher = OfficialSourceFetcher(_settings(max_pages_per_source=3))
        request_urls = []

        def fake_fetch_bytes(_source_arg, url, allowed_types=None, *, on_request_attempt=None):
            request_urls.append(url)
            if on_request_attempt is not None:
                on_request_attempt()
            if url == failed_url:
                raise DiscoveryFetchError("sanitized linked fetch failure")
            body = root_html if url == root_url else b"<p>Fetched scholarship details.</p>"
            return url, headers, body

        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(fetcher, "_fetch_bytes", side_effect=fake_fetch_bytes):
                with self.assertLogs(
                    "app.services.scholarship_discovery_fetch",
                    level="WARNING",
                ):
                    pages = fetcher.crawl(_source())

        self.assertEqual(len(pages), 2)
        self.assertEqual(request_urls, [root_url, first_url, failed_url])
        self.assertNotIn(unattempted_url, request_urls)
        self.assertEqual(fetcher.last_crawl_stats["linked_urls_discovered"], 4)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_attempted"], 2)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_fetched"], 1)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_failed"], 1)

    def test_fetcher_extracts_html_text_and_same_domain_links(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        body = (
            b"<html><script>ignore this</script><p>Official Master's scholarship</p>"
            b"<a href='/scholarships/master'>Master scholarship</a></html>"
        )
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(fetcher, "_fetch_bytes", return_value=(_source().source_url, headers, body)):
                page = fetcher.fetch(_source(), _source().source_url)
        self.assertIn("Official Master's scholarship", page.text)
        self.assertNotIn("ignore this", page.text)
        self.assertEqual(page.links, (("/scholarships/master", "Master scholarship"),))

    def test_html_extraction_prioritizes_main_and_article_and_filters_boilerplate(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        body = (
            b"<nav>Navigation scholarship menu</nav><header>Site header</header>"
            b"<main><h1>Primary scholarship award</h1>"
            b"<article><p>Eligibility requires postgraduate study and funding is provided.</p>"
            b"<a href='/application'>Application instructions</a></article></main>"
            b"<p>Additional scholarship deadline is 30 June.</p>"
            b"<div id='cookie-consent-banner'>Accept all cookies</div>"
            b"<form id='site-search'><p>Search scholarships</p><input></form>"
            b"<form><p>Application instructions remain visible outside utility forms.</p>"
            b"<input></form><footer>Footer scholarship menu</footer>"
            b"<script>script scholarship text</script>"
        )
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(
                fetcher,
                "_fetch_bytes",
                return_value=(_source().source_url, headers, body),
            ):
                page = fetcher.fetch(_source(), _source().source_url)

        self.assertLess(page.text.index("Primary scholarship award"), page.text.index(
            "Additional scholarship deadline",
        ))
        self.assertIn("Eligibility requires postgraduate study", page.text)
        self.assertIn("Application instructions remain visible", page.text)
        for boilerplate in (
            "Navigation scholarship menu",
            "Site header",
            "Accept all cookies",
            "Search scholarships",
            "Footer scholarship menu",
            "script scholarship text",
        ):
            self.assertNotIn(boilerplate, page.text)
        self.assertEqual(page.links, (("/application", "Application instructions"),))

    def test_malformed_html_recovers_at_main_and_keeps_non_main_content(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        body = (
            b"<nav>Unclosed navigation"
            b"<main><article>Scholarship details with eligibility and funding.</article></main>"
            b"<p>Additional application instructions outside main.</p>"
        )
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(
                fetcher,
                "_fetch_bytes",
                return_value=(_source().source_url, headers, body),
            ):
                page = fetcher.fetch(_source(), _source().source_url)

        self.assertIn("Scholarship details with eligibility and funding", page.text)
        self.assertIn("Additional application instructions outside main", page.text)
        self.assertNotIn("Unclosed navigation", page.text)

    def test_empty_and_insufficient_html_are_reported_without_provider_content(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        fetcher = OfficialSourceFetcher(_settings(min_extracted_chars=20))
        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(fetcher, "_fetch_bytes", return_value=(_source().source_url, headers, b"")):
                empty_page = fetcher.fetch(_source(), _source().source_url)
            with patch.object(
                fetcher,
                "_fetch_bytes",
                return_value=(_source().source_url, headers, b"<p>Short page</p>"),
            ):
                short_page = fetcher.fetch(_source(), _source().source_url)

        self.assertEqual(empty_page.text, "")
        self.assertTrue(empty_page.insufficient_content)
        self.assertEqual(empty_page.original_text_length, 0)
        self.assertEqual(short_page.text, "Short page")
        self.assertTrue(short_page.insufficient_content)

    def test_fetcher_reports_original_and_retained_text_lengths_on_truncation(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        body = b"<p>" + (b"A" * 150) + b"</p>"
        fetcher = OfficialSourceFetcher(
            _settings(max_extracted_chars=100, min_extracted_chars=20),
        )
        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(
                fetcher,
                "_fetch_bytes",
                return_value=(_source().source_url, headers, body),
            ):
                page = fetcher.fetch(_source(), _source().source_url)

        self.assertEqual(page.original_text_length, 150)
        self.assertEqual(page.retained_text_length, 100)
        self.assertEqual(len(page.text), 100)
        self.assertTrue(page.text_truncated)
        self.assertEqual(page.page_texts, (page.text,))

    def test_link_discovery_covers_scholarship_terms_and_reports_safe_counts(self):
        source = replace(
            _source(),
            trusted_external_domains=("portal.example",),
            trusted_external_domains_reviewed=True,
            trusted_external_domain_trust_basis="Synthetic test-only reviewed portal",
        )
        relevant_paths = (
            ("eligibility", "Eligibility"),
            ("deadlines", "Deadline"),
            ("application", "Application"),
            ("benefits", "Benefits"),
            ("requirements", "Requirements"),
            ("postgraduate", "Postgraduate"),
            ("scholarship-details", "Scholarship details"),
        )
        linked_urls = [
            f"https://official.example/{path}"
            for path, _label in relevant_paths
        ]
        root = _page(
            "Root scholarship information.",
            links=tuple(
                (url, label)
                for url, (_path, label) in zip(linked_urls, relevant_paths)
            ) + (
                ("/about", "About this website"),
                ("https://portal.example/eligibility", "External eligibility page"),
            ),
        )
        fetched_pages = {
            source.source_url: root,
            **{
                url: _page("Linked scholarship details.", url=url)
                for url in linked_urls
            },
        }
        fetcher = OfficialSourceFetcher(_settings(max_pages_per_source=20))

        with patch.object(
            fetcher,
            "fetch",
            side_effect=lambda _src, url: fetched_pages[url],
        ) as fetch:
            pages = fetcher.crawl(source)

        self.assertEqual(len(pages), 1 + len(linked_urls))
        self.assertEqual(fetcher.last_crawl_stats["linked_urls_discovered"], 9)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_fetched"], 7)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_failed"], 0)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_skipped_safety"], 1)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_skipped_relevance"], 1)
        self.assertEqual(fetcher.last_crawl_stats["linked_pages_skipped"], 2)
        self.assertNotIn("https://portal.example/eligibility", [
            call.args[1] for call in fetch.call_args_list
        ])

    def test_fetcher_honors_text_robots_rules_and_allows_missing_robots_file(self):
        headers = Message()
        headers["Content-Type"] = "text/plain; charset=utf-8"
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(fetcher, "_request", return_value=(200, headers, b"User-agent: *\nDisallow: /")):
            self.assertFalse(fetcher._robots_allowed(_source(), _source().source_url))

        missing_fetcher = OfficialSourceFetcher(_settings())
        with patch.object(missing_fetcher, "_request", return_value=(404, Message(), b"")):
            self.assertTrue(missing_fetcher._robots_allowed(_source(), _source().source_url))

    def test_fetcher_extracts_pdf_text_and_page_count(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF is not installed")

        document = fitz.open()
        document.new_page().insert_text((72, 72), "Official Master's scholarship")
        body = document.tobytes()
        document.close()
        headers = Message()
        headers["Content-Type"] = "application/pdf"
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(fetcher, "_fetch_bytes", return_value=(_source().source_url, headers, body)):
                page = fetcher.fetch(_source(), _source().source_url)
        self.assertIn("Official Master's scholarship", page.text)
        self.assertEqual(page.page_count, 1)

    def test_fetcher_blocks_redirects_outside_registered_domain(self):
        headers = Message()
        headers["Location"] = "https://127.0.0.1/private"
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(fetcher, "_request", return_value=(302, headers, b"")) as request:
            with self.assertRaisesRegex(DiscoveryFetchError, "registered official domain"):
                fetcher._fetch_bytes(_source(), _source().source_url)
        request.assert_called_once_with(_source(), _source().source_url)

    def test_mixed_public_and_private_dns_answers_are_rejected_before_connecting(self):
        connector = MagicMock()
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [
                _address_info("93.184.216.34"),
                _address_info("10.0.0.8"),
            ]}),
            connector=connector,
        )

        with self.assertRaisesRegex(DiscoveryFetchError, "exclusively to public"):
            fetcher._request(_source(), _source().source_url)
        connector.assert_not_called()

    def test_a_and_aaaa_queries_share_one_six_second_deadline(self):
        now = [10.0]
        calls = []

        def resolve(host, record_type, *, lifetime, search):
            calls.append((host, dns.rdatatype.to_text(record_type), lifetime, search))
            if dns.rdatatype.to_text(record_type) == "A":
                now[0] += 2.0
                return [SimpleNamespace(address="93.184.216.34")]
            raise dns.resolver.NoAnswer()

        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=resolve,
            clock=lambda: now[0],
        )

        addresses = fetcher._resolve_public_addresses("official.example", 443)

        self.assertEqual(len(addresses), 1)
        self.assertEqual([call[2] for call in calls], [6.0, 4.0])
        self.assertEqual([call[1] for call in calls], ["A", "AAAA"])
        self.assertTrue(all(call[3] is False for call in calls))

    def test_dns_timeout_and_unsupported_configuration_fail_before_connecting(self):
        connector = MagicMock()
        timeout_fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver(errors={
                ("official.example", "A"): dns.exception.Timeout(),
            }),
            connector=connector,
        )
        with self.assertRaisesRegex(DiscoveryFetchError, "safe public addresses") as raised:
            timeout_fetcher._fetch_bytes(_source(), _source().source_url)
        self.assertEqual(raised.exception.category, "dns_error")
        self.assertEqual(raised.exception.immediate_cause_type, "Timeout")
        self.assertEqual(raised.exception.attempt_count, 1)
        self.assertEqual(raised.exception.attempt_limit, 1)
        connector.assert_not_called()

        configured_fetcher = OfficialSourceFetcher(_settings(), connector=connector)
        with patch(
            "app.services.scholarship_discovery_fetch.dns.resolver.Resolver",
            side_effect=NotImplementedError("resolver configuration unavailable"),
        ):
            with patch("app.services.scholarship_discovery_fetch.socket.getaddrinfo") as getaddrinfo:
                with self.assertRaisesRegex(DiscoveryFetchError, "configuration is unsupported"):
                    configured_fetcher._request(_source(), _source().source_url)
        getaddrinfo.assert_not_called()
        connector.assert_not_called()

    def test_genuine_resolver_oserror_remains_a_dns_error(self):
        resolver_error = socket.gaierror(socket.EAI_NONAME, "resolver failure")
        fetcher = OfficialSourceFetcher(_settings(), resolver=Mock(side_effect=resolver_error))

        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher._resolve_public_addresses("official.example", 443)

        self.assertEqual(raised.exception.category, "dns_error")
        self.assertEqual(raised.exception.cause_type, "gaierror")

    def test_empty_and_malformed_dns_answers_fail_closed(self):
        for resolver in (
            _FakeDNSResolver(),
            _FakeDNSResolver({"A": ["not-an-ip-address"]}),
        ):
            with self.subTest(resolver=resolver):
                connector = MagicMock()
                fetcher = OfficialSourceFetcher(_settings(), resolver=resolver, connector=connector)
                with self.assertRaises(DiscoveryFetchError):
                    fetcher._request(_source(), _source().source_url)
                connector.assert_not_called()

    def test_unexpected_dns_resolver_errors_are_classified_as_unknown(self):
        for error in (AttributeError("bad resolver shape"), IndexError("bad record"), TypeError("bad type")):
            with self.subTest(error=type(error).__name__):
                fetcher = OfficialSourceFetcher(_settings(), resolver=Mock(side_effect=error))
                with self.assertRaises(DiscoveryFetchError) as raised:
                    fetcher._resolve_public_addresses("official.example", 443)
                self.assertEqual(raised.exception.category, "unknown")
                self.assertEqual(raised.exception.cause_type, type(error).__name__)

    def test_pinned_connector_receives_exact_validated_sockaddr_without_second_resolution(self):
        address = _address_info("93.184.216.34", 80)
        response_socket = _FakeSocket(_http_response())
        resolver = _FakeDNSResolver({"A": [address]})
        connector = _pinned_connector(response_socket)
        fetcher = OfficialSourceFetcher(_settings(), resolver=resolver, connector=connector)

        status, _headers, body = fetcher._request(_source(), "http://official.example/scholarships")

        self.assertEqual((status, body), (200, b"ok"))
        self.assertEqual(
            [(call[0], call[1], call[3]) for call in resolver.calls],
            [("official.example", "A", False), ("official.example", "AAAA", False)],
        )
        connector.assert_called_once_with(
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            ("93.184.216.34", 80),
            2,
        )
        self.assertTrue(response_socket.closed)

    def test_ipv4_and_ipv6_addresses_are_pinned_with_complete_sockaddrs(self):
        for ip, expected_sockaddr in (
            ("93.184.216.34", ("93.184.216.34", 80)),
            ("2606:2800:220:1:248:1893:25c8:1946", ("2606:2800:220:1:248:1893:25c8:1946", 80, 0, 0)),
        ):
            with self.subTest(ip=ip):
                address = _address_info(ip, 80)
                response_socket = _FakeSocket(_http_response())
                connector = _pinned_connector(response_socket)
                fetcher = OfficialSourceFetcher(
                    _settings(),
                    resolver=_FakeDNSResolver({
                        "AAAA" if ":" in ip else "A": [address],
                    }),
                    connector=connector,
                )

                fetcher._request(_source(), "http://official.example/scholarships")

                self.assertEqual(connector.call_args.args[3], expected_sockaddr)
                self.assertEqual(
                    connector.call_args.args[0],
                    socket.AF_INET6 if ":" in ip else socket.AF_INET,
                )

    def test_retry_resolves_again_and_rejects_a_new_private_answer(self):
        resolver = _FakeDNSResolver(sequences={
            "A": [
                [_address_info("93.184.216.34", 80)],
                [_address_info("192.168.1.10", 80)],
            ],
        })
        connector = MagicMock(side_effect=OSError("connection failed"))
        fetcher = OfficialSourceFetcher(
            _settings(max_retries=1),
            resolver=resolver,
            connector=connector,
            sleep=lambda _delay: None,
        )

        with self.assertRaisesRegex(DiscoveryFetchError, "public addresses"):
            fetcher._fetch_bytes(_source(), "http://official.example/scholarships")

        self.assertEqual(
            sum(call[1] == "A" for call in resolver.calls),
            2,
        )
        connector.assert_called_once()

    def test_redirect_target_is_resolved_and_validated_independently(self):
        redirect_headers = Message()
        redirect_headers["Location"] = "/scholarships/current"
        resolver = _FakeDNSResolver(sequences={
            "A": [
                [_address_info("93.184.216.34", 80)],
                [_address_info("93.184.216.35", 80)],
            ],
        })
        first_socket = _FakeSocket(_http_response(302, headers=b"Location: /scholarships/current\r\n"))
        second_socket = _FakeSocket(_http_response())
        connector = _pinned_connector(first_socket, second_socket)
        fetcher = OfficialSourceFetcher(_settings(), resolver=resolver, connector=connector)

        final_url, _headers, body = fetcher._fetch_bytes(_source(), "http://official.example/scholarships")

        self.assertEqual(final_url, "http://official.example/scholarships/current")
        self.assertEqual(body, b"ok")
        self.assertEqual(
            sum(call[1] == "A" for call in resolver.calls),
            2,
        )
        self.assertEqual(
            [call.args[3] for call in connector.call_args_list],
            [("93.184.216.34", 80), ("93.184.216.35", 80)],
        )
        self.assertTrue(first_socket.closed)
        self.assertTrue(second_socket.closed)

    def test_registered_redirect_with_unsafe_dns_answer_is_rejected(self):
        first_socket = _FakeSocket(
            _http_response(
                302,
                headers=b"Location: https://www.official.example/next\r\n",
            )
        )
        connector = _pinned_connector(first_socket)
        resolver = _FakeDNSResolver(sequences={
            ("official.example", "A"): [[_address_info("93.184.216.34", 80)]],
            ("www.official.example", "A"): [[_address_info("10.0.0.8", 443)]],
        })
        fetcher = OfficialSourceFetcher(_settings(), resolver=resolver, connector=connector)

        with self.assertRaisesRegex(DiscoveryFetchError, "public addresses"):
            fetcher._fetch_bytes(_source(), "http://official.example/scholarships")

        connector.assert_called_once()
        self.assertTrue(first_socket.closed)

    def test_peer_mismatch_port_and_malformed_peer_fail_closed_and_close_socket(self):
        for peer in (
            ("93.184.216.35", 443),
            ("93.184.216.34", 444),
            ("not-an-ip-address", 443),
            None,
        ):
            with self.subTest(peer=peer):
                response_socket = _FakeSocket(_http_response())
                response_socket.peer = peer
                connector = MagicMock(return_value=response_socket)
                fetcher = OfficialSourceFetcher(
                    _settings(),
                    resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34")]}),
                    connector=connector,
                )
                with self.assertRaisesRegex(DiscoveryFetchError, "Fetch failed"):
                    fetcher._fetch_bytes(_source(), _source().source_url)
                connector.assert_called_once()
                self.assertTrue(response_socket.closed)

    def test_original_hostname_is_used_for_http_host_and_https_sni(self):
        http_socket = _FakeSocket(_http_response())
        http_fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34", 80)]}),
            connector=_pinned_connector(http_socket),
        )
        http_fetcher._request(_source(), "http://official.example/scholarships")
        self.assertIn(b"Host: official.example\r\n", http_socket.sent)

        https_socket = _FakeSocket(_http_response())
        context = _RecordingSSLContext()
        https_fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34")]}),
            connector=_pinned_connector(https_socket),
        )
        with patch("app.services.scholarship_discovery_fetch.ssl.create_default_context",
                   return_value=context) as create_context:
            https_fetcher._request(_source(), _source().source_url)

        create_context.assert_called_once_with()
        self.assertEqual(context.server_hostname, "official.example")
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertIn(b"Host: official.example\r\n", https_socket.sent)
        self.assertTrue(https_socket.closed)

    def test_default_tls_context_keeps_certificate_and_hostname_verification(self):
        context = ssl.create_default_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_environment_proxy_settings_do_not_change_pinned_connection(self):
        address = _address_info("93.184.216.34", 80)
        response_socket = _FakeSocket(_http_response())
        resolver = _FakeDNSResolver({"A": [address]})
        connector = _pinned_connector(response_socket)
        fetcher = OfficialSourceFetcher(_settings(), resolver=resolver, connector=connector)
        proxy_vars = {
            "HTTP_PROXY": "http://proxy.invalid:8080",
            "HTTPS_PROXY": "http://proxy.invalid:8080",
            "ALL_PROXY": "http://proxy.invalid:8080",
            "http_proxy": "http://proxy.invalid:8080",
            "https_proxy": "http://proxy.invalid:8080",
            "all_proxy": "http://proxy.invalid:8080",
        }

        with patch.dict(os.environ, proxy_vars):
            fetcher._request(_source(), "http://official.example/scholarships")

        self.assertEqual(
            [(call[0], call[1], call[3]) for call in resolver.calls],
            [("official.example", "A", False), ("official.example", "AAAA", False)],
        )
        connector.assert_called_once()

    def test_failed_pinned_connection_does_not_fall_back_to_hostname_transport(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34", 80)]}),
            connector=MagicMock(side_effect=OSError("connection failed")),
        )
        with patch("urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(DiscoveryFetchError, "Fetch failed"):
                fetcher._fetch_bytes(_source(), "http://official.example/scholarships")
        urlopen.assert_not_called()

    def test_socket_creation_closes_socket_when_connect_fails(self):
        sock = MagicMock()
        sock.connect.side_effect = OSError("connection failed")
        with patch("app.services.scholarship_discovery_fetch.socket.socket", return_value=sock):
            with self.assertRaisesRegex(OSError, "connection failed"):
                from app.services.scholarship_discovery_fetch import _connect_validated_address
                _connect_validated_address(
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    ("93.184.216.34", 443),
                    2,
                )
        sock.close.assert_called_once()

    def test_tls_handshake_failure_closes_pinned_socket(self):
        class FailingTLSContext:
            def wrap_socket(self, _sock, server_hostname):
                raise OSError("TLS handshake failed for " + server_hostname)

        pinned_socket = _FakeSocket(b"")
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34")]}),
            connector=_pinned_connector(pinned_socket),
        )
        with patch(
            "app.services.scholarship_discovery_fetch.ssl.create_default_context",
            return_value=FailingTLSContext(),
        ):
            with self.assertRaisesRegex(OSError, "TLS handshake failed"):
                fetcher._request(_source(), _source().source_url)
        self.assertTrue(pinned_socket.closed)

    def test_successful_request_closes_response_socket(self):
        response_socket = _FakeSocket(_http_response())
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34", 80)]}),
            connector=_pinned_connector(response_socket),
        )

        self.assertEqual(fetcher._request(_source(), "http://official.example/scholarships")[0], 200)
        self.assertTrue(response_socket.closed)

    def test_connection_closes_when_response_close_raises(self):
        response_headers = Message()
        response_headers["Content-Length"] = "2"
        response = MagicMock()
        response.status = 200
        response.headers = response_headers
        response.read.return_value = b"ok"
        response.close.side_effect = RuntimeError("response close failed")
        connection = MagicMock()
        connection.getresponse.return_value = response
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeDNSResolver({"A": [_address_info("93.184.216.34", 80)]}),
        )

        with patch(
            "app.services.scholarship_discovery_fetch._PinnedHTTPConnection",
            return_value=connection,
        ):
            with self.assertRaisesRegex(RuntimeError, "response close failed"):
                fetcher._request(_source(), "http://official.example/scholarships")

        response.close.assert_called_once()
        connection.close.assert_called_once()


class MockedDiscoveryPersistenceTests(unittest.TestCase):
    def test_pending_review_records_are_not_in_student_visible_catalog_queries(self):
        from app.services.student_scholarship_visibility import get_student_scholarships

        class FakeQuery:
            def filter(self, *_args):
                return self

            def order_by(self, *_args):
                return self

            def all(self):
                return []

        class FakeSession:
            def __init__(self):
                self.queried_models = []
                self.pending_review_items = [
                    SimpleNamespace(review_status="pending"),
                ]

            def query(self, model):
                self.queried_models.append(model)
                return FakeQuery()

        session = FakeSession()
        self.assertEqual(get_student_scholarships(session), [])
        self.assertEqual(session.queried_models, [Scholarship])
        self.assertNotIn(ScholarshipDiscoveryReviewItem, session.queried_models)

    def test_valid_candidates_are_queued_and_duplicates_are_not_counted_twice(self):
        source = _source()
        page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants. "
            "Study in Finland."
        )
        candidate = _candidate(source=source, page=page, funding_type="full")

        class FakeSession:
            def __init__(self):
                self.run = None

            def add(self, value):
                self.run = value

            def commit(self):
                return None

        session = FakeSession()
        fetcher = MagicMock()
        fetcher.crawl.return_value = [page]
        fetcher.last_crawl_stats = {}
        extractor = MagicMock()
        extractor.extract.return_value = [candidate, candidate]
        extractor.last_rejected_count = 1
        extractor.last_rejection_reasons = ["invalid_candidate"]
        identities = set()
        persisted_items = []

        def persist_review_candidate(_db, _run_id, _source, _page, incoming, reason, *_args, **_kwargs):
            identity = (
                incoming.values["name"].casefold(),
                incoming.values["country"].casefold(),
            )
            item = SimpleNamespace(review_status="pending")
            if identity in identities:
                return item, False
            identities.add(identity)
            persisted_items.append((item, reason, incoming.values))
            return item, True

        def save_run(_db, run, summary, source_results, status, _lock_check=None):
            run.summary = dict(summary)
            run.source_results = list(source_results)
            run.status = status
            run.finished_at = (
                datetime.now(timezone.utc)
                if status != "running"
                else None
            )

        with (
            patch("app.services.scholarship_discovery._last_successful_fetch", return_value=None),
            patch("app.services.scholarship_discovery.record_publication_source_success"),
            patch("app.services.scholarship_discovery.find_identity_record", return_value=None),
            patch("app.services.scholarship_discovery.has_open_review_for_identity", return_value=False),
            patch("app.services.scholarship_discovery.find_possible_duplicate_records", return_value=[]),
            patch(
                "app.services.scholarship_discovery.persist_review_candidate",
                side_effect=persist_review_candidate,
            ) as persist,
            patch("app.services.scholarship_discovery._save_run", side_effect=save_run),
        ):
            result = run_discovery(
                session,
                settings=_settings(),
                sources=(source,),
                fetcher=fetcher,
                extractor=extractor,
                trigger_type="scheduled",
            )

        self.assertEqual(persist.call_count, 2)
        self.assertEqual(len(persisted_items), 1)
        item, reason, values = persisted_items[0]
        self.assertEqual(item.review_status, "pending")
        self.assertEqual(reason, "admin_review_required")
        self.assertEqual(values["funding_type"], "full")
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(result["summary"]["candidates_accepted"], 2)
        self.assertEqual(result["summary"]["candidates_rejected"], 1)
        self.assertEqual(
            result["sources"][0]["candidate_rejection_reasons"],
            {"invalid_candidate": 1},
        )

    def test_failed_source_is_recorded_as_failed_with_fetch_details(self):
        source = _source()

        class FakeSession:
            def add(self, _value):
                return None

            def commit(self):
                return None

        fetcher = MagicMock()
        fetcher.crawl.side_effect = DiscoveryFetchError(
            "offline fetch failure",
            status_code=403,
            category="http_status",
            stage="root_fetch",
            page_stage="root_fetch",
            attempt_count=1,
            attempt_limit=3,
        )

        def save_run(_db, run, summary, source_results, status, _lock_check=None):
            run.summary = dict(summary)
            run.source_results = list(source_results)
            run.status = status
            run.finished_at = datetime.now(timezone.utc) if status != "running" else None

        with (
            patch("app.services.scholarship_discovery._last_successful_fetch", return_value=None),
            patch("app.services.scholarship_discovery.record_publication_source_failure"),
            patch("app.services.scholarship_discovery._save_run", side_effect=save_run),
        ):
            result = run_discovery(
                FakeSession(),
                settings=_settings(),
                sources=(source,),
                fetcher=fetcher,
                extractor=MagicMock(),
                trigger_type="scheduled",
            )

        source_result = result["sources"][0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(source_result["status"], "failed")
        self.assertEqual(source_result["error_category"], "http_status")
        self.assertEqual(source_result["http_status"], 403)
        self.assertEqual(source_result["failure_stage"], "root_fetch")
        self.assertEqual(source_result["attempt_count"], 1)


class DiscoveryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants.",
            content_hash="d" * 64,
        )
        self.fetcher = MagicMock()
        self.fetcher.crawl.return_value = [self.page]
        self.extractor = MagicMock()
        self.extractor.last_rejected_count = 0
        self.extractor.extract.return_value = [_candidate(page=self.page)]

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _run(self, **run_options):
        sources = run_options.pop("sources", (_source(),))
        if "trigger_type" not in run_options:
            run_options["trigger_type"] = (
                "manual" if run_options.get("run_budget") is not None else "scheduled"
            )
        return run_discovery(
            self.db,
            settings=_settings(),
            sources=sources,
            fetcher=self.fetcher,
            extractor=self.extractor,
            **run_options,
        )

    def test_sanitized_gemini_error_category_is_persisted_for_admin_history(self):
        self.extractor.extract.side_effect = ScholarshipExtractionError(
            "private provider detail",
            category="quota_error",
            http_status=429,
        )

        result = self._run()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["sources"][0]["error"], "quota_error")
        self.assertEqual(result["sources"][0]["http_status"], 429)
        self.assertNotIn("private provider detail", str(result))

    def test_candidate_budget_stop_preserves_pending_review_and_canonical_records(self):
        canonical = self._add_existing_scholarship(living_stipend="Original amount")
        sources = controlled_manual_sources()
        budget_page = _page(url=sources[0].source_url)
        self.fetcher.crawl.return_value = [budget_page]
        first_candidate = _candidate(
            source=sources[0],
            page=budget_page,
            living_stipend="New amount requiring review",
        )
        second_candidate = _candidate(
            source=sources[0],
            page=budget_page,
            name="Second Finland Master's Award",
        )
        self.extractor.extract.return_value = [first_candidate, second_candidate]
        budget = DiscoveryRunBudget(
            max_candidates=1,
            duration_seconds=60,
            start_deadline_timer=False,
        )

        try:
            with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                self._run(
                    sources=sources,
                    run_id="candidate-budget-stop",
                    run_budget=budget,
                )
        finally:
            budget.close()

        self.assertEqual(raised.exception.resource, "candidates")
        self.db.refresh(canonical)
        self.assertEqual(canonical.living_stipend, "Original amount")
        self.assertEqual(self.db.query(Scholarship).count(), 1)
        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        self.assertEqual(review_item.review_status, "pending")
        self.assertEqual(review_item.extracted_values["living_stipend"], "New amount requiring review")
        self.assertEqual(self.db.query(ScholarshipSourceDocument).count(), 0)
        stopped_run = self.db.get(ScholarshipDiscoveryRun, "candidate-budget-stop")
        self.assertEqual(stopped_run.status, "failed")
        self.assertEqual(
            stopped_run.summary["stop_reason"]["resource"],
            "candidates",
        )
        self.assertEqual(
            stopped_run.summary["resource_budget"]["candidates_persisted"],
            1,
        )

    def test_controlled_manual_run_rejects_legacy_source_before_creating_run(self):
        budget = DiscoveryRunBudget(
            duration_seconds=60,
            start_deadline_timer=False,
        )
        try:
            with self.assertRaises(ControlledManualSourceConfigurationError):
                self._run(
                    sources=(SOURCES_BY_ID["daad"],),
                    run_budget=budget,
                )
        finally:
            budget.close()

        self.fetcher.crawl.assert_not_called()
        self.assertEqual(
            self.db.query(ScholarshipDiscoveryRun).count(),
            0,
        )

    def _add_existing_scholarship(self, candidate=None, **overrides):
        values = dict((candidate or _candidate(page=self.page)).values)
        values.update(overrides)
        item = Scholarship(**values)
        self.db.add(item)
        self.db.commit()
        return item

    def _add_publication_source(self, checked_at, content_hash="a" * 64):
        scholarship = self._add_existing_scholarship()
        publication = ScholarshipDiscoveryPublication(
            canonical_scholarship_id=scholarship.id,
        )
        self.db.add(publication)
        self.db.flush()
        source_url = _source().source_url
        source = ScholarshipDiscoveryPublicationSource(
            publication_id=publication.id,
            source_id="timestamp-test",
            source_name="Timestamp test source",
            source_classification="government_authority",
            source_url=source_url,
            normalized_url=source_url,
            last_checked_at=checked_at,
            last_successful_check_at=checked_at,
            observed_content_hash=content_hash,
            source_check_status="succeeded",
        )
        self.db.add(source)
        self.db.commit()
        return source

    def _assert_source_timestamp(self, source, attribute, expected):
        self.db.refresh(source, attribute_names=[attribute])
        actual = getattr(source, attribute)
        self.assertIsNotNone(actual)
        if actual.tzinfo is None:
            actual = actual.replace(tzinfo=timezone.utc)
        else:
            actual = actual.astimezone(timezone.utc)
        self.assertEqual(actual, expected.astimezone(timezone.utc))

    def test_complete_candidate_is_queued_without_creating_a_scholarship(self):
        result = self._run()
        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()

        self.assertEqual(result["summary"]["new_records_created"], 0)
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(review_item.review_status, "pending")
        self.assertEqual(review_item.candidate_name, "Finland Master's Award")
        self.assertEqual(review_item.host_country, "Finland")
        self.assertEqual(review_item.source_id, "test-finland")
        self.assertEqual(review_item.source_url, self.page.url)
        self.assertEqual(review_item.extracted_values["degree_level"], "Master")
        self.assertEqual(review_item.field_sources["degree_level"]["source_id"], "test-finland")
        self.assertEqual(
            review_item.evidence_excerpts[0]["evidence_excerpts"]["name"],
            "Finland Master's Award",
        )
        self.assertEqual(self.db.query(Scholarship).count(), 0)
        self.assertEqual(self.db.query(ScholarshipAuditLog).count(), 0)
        self.assertEqual(self.db.query(ScholarshipSourceDocument).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDocumentVersion).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDocumentChunk).count(), 0)
        self.assertEqual(self.db.query(ScholarshipChunkEmbedding).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDiscoveryRun).one().status, "completed")

    def test_persisted_discovery_references_remove_sensitive_url_parameters(self):
        self.page = _page(
            "The Finland Master's Award scholarship is available to Master's applicants. "
            "See https://official.example/guide?token=body-secret&lang=en.",
            url="https://official.example/scholarships?session=page-secret&lang=en#details",
        )
        self.fetcher.crawl.return_value = [self.page]
        candidate = _candidate(page=self.page)
        candidate.values["official_application_url"] = (
            "https://official.example/apply?campaign=summer&access_token=link-secret#form"
        )
        candidate.values["additional_source_urls"] = [
            "https://official.example/more?api_key=link-secret&source=official#info",
        ]
        candidate.evidence["source_reference"] = (
            "See https://official.example/guide?token=quote-secret&lang=en."
        )
        self.extractor.extract.return_value = [candidate]

        self._run()

        item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        self.assertEqual(
            item.source_url,
            "https://official.example/scholarships?lang=en",
        )
        self.assertEqual(
            item.extracted_values["official_application_url"],
            "https://official.example/apply?campaign=summer",
        )
        self.assertEqual(
            item.extracted_values["additional_source_urls"],
            ["https://official.example/more?source=official"],
        )
        self.assertEqual(
            item.evidence_excerpts[0]["evidence_excerpts"]["source_reference"],
            "See https://official.example/guide?lang=en.",
        )
        self.assertIn(
            "https://official.example/guide?lang=en",
            item.evidence_excerpts[0]["_rag_page_snapshot"]["text"],
        )
        persisted_references = (
            str(item.source_url)
            + str(item.extracted_values)
            + str(item.evidence_excerpts)
        )
        for secret in ("page-secret", "link-secret", "quote-secret", "body-secret"):
            self.assertNotIn(secret, persisted_references)

        scholarship = self._add_existing_scholarship(
            candidate=candidate,
            verification_status="verified",
            verification_basis="official_source",
            last_verified_date=date.today(),
        )
        _register_evidence(self.db, scholarship, _source(), candidate.values, self.page)
        self.db.commit()
        document_version = self.db.query(ScholarshipDocumentVersion).one()
        self.assertIn(
            "https://official.example/guide?lang=en",
            document_version.extracted_text,
        )
        self.assertNotIn("body-secret", document_version.extracted_text)

    def test_scheduled_trigger_and_slot_are_persisted(self):
        scheduled_for = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        result = self._run(trigger_type="scheduled", scheduled_for=scheduled_for)
        run = self.db.query(ScholarshipDiscoveryRun).one()
        stored_scheduled_for = run.scheduled_for
        if stored_scheduled_for.tzinfo is None:
            stored_scheduled_for = stored_scheduled_for.replace(tzinfo=timezone.utc)
        self.assertEqual(run.trigger_type, "scheduled")
        self.assertEqual(stored_scheduled_for, scheduled_for)
        self.assertEqual(result["trigger_type"], "scheduled")
        self.assertEqual(result["scheduled_for"], run.scheduled_for.isoformat())
        self.assertEqual(result["summary"]["new_records_created"], 0)
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(self.db.query(ScholarshipDiscoveryReviewItem).count(), 1)
        self.assertEqual(self.db.query(Scholarship).count(), 0)

    def test_run_records_link_text_and_valid_empty_diagnostics(self):
        retained_text = self.page.text
        self.page = replace(
            self.page,
            original_text_length=len(retained_text) + 25,
            retained_text_length=len(retained_text),
            text_truncated=True,
        )
        self.fetcher.crawl.return_value = [self.page]
        self.fetcher.last_crawl_stats = {
            "linked_urls_discovered": 4,
            "linked_pages_attempted": 2,
            "linked_pages_fetched": 2,
            "linked_pages_failed": 1,
            "linked_pages_skipped_safety": 1,
            "linked_pages_skipped_relevance": 1,
            "linked_pages_skipped": 2,
        }
        self.extractor.extract.return_value = []

        result = self._run(run_id="diagnostic-empty-run")

        self.assertEqual(result["summary"]["valid_empty"], 1)
        self.assertEqual(result["summary"]["linked_urls_discovered"], 4)
        self.assertEqual(result["summary"]["linked_pages_attempted"], 2)
        self.assertEqual(result["summary"]["linked_pages_fetched"], 2)
        self.assertEqual(result["summary"]["linked_pages_failed"], 1)
        self.assertEqual(result["summary"]["linked_pages_skipped"], 2)
        self.assertEqual(result["summary"]["truncated_pages"], 1)
        self.assertEqual(result["summary"]["truncated_original_chars"], len(retained_text) + 25)
        self.assertEqual(result["summary"]["truncated_retained_chars"], len(retained_text))
        source_result = result["sources"][0]
        self.assertEqual(source_result["extraction_diagnostics"]["valid_empty"], 1)
        self.assertEqual(
            source_result["text_truncations"],
            [{
                "source_id": "test-finland",
                "page_index": 1,
                "original_length": len(retained_text) + 25,
                "retained_length": len(retained_text),
            }],
        )

        history = _discovery_run_history(
            self.db.get(ScholarshipDiscoveryRun, "diagnostic-empty-run"),
            datetime.now(timezone.utc),
        )
        self.assertEqual(history.fetch_diagnostics.linked_pages_failed, 1)
        self.assertEqual(history.fetch_diagnostics.linked_pages_attempted, 2)
        self.assertEqual(
            history.fetch_diagnostics.text_truncations[0].original_length,
            len(retained_text) + 25,
        )
        self.assertEqual(history.extraction_diagnostics.valid_empty, 1)

    def test_insufficient_page_content_skips_provider_and_is_counted(self):
        self.page = replace(
            self.page,
            text="",
            original_text_length=0,
            retained_text_length=0,
            insufficient_content=True,
        )
        self.fetcher.crawl.return_value = [self.page]

        result = self._run(run_id="insufficient-content-run")

        self.extractor.extract.assert_not_called()
        self.assertEqual(result["sources"][0]["status"], "fetched")
        self.assertEqual(
            result["sources"][0]["extraction_diagnostics"]["insufficient_page_content"],
            1,
        )
        self.assertEqual(result["summary"]["insufficient_page_content"], 1)
        self.assertEqual(result["summary"]["provider_error"], 0)

    def test_provider_and_malformed_extraction_errors_have_distinct_counters(self):
        for error_category, outcome_key in (
            ("provider_error", "provider_error"),
            ("malformed_response", "malformed_response"),
        ):
            with self.subTest(error_category=error_category):
                self.extractor.extract.side_effect = ScholarshipExtractionError(
                    "sanitized extraction failure",
                    category=error_category,
                )
                result = self._run(run_id=f"diagnostic-{error_category}")
                self.assertEqual(result["sources"][0]["status"], "partial_failure")
                self.assertEqual(result["sources"][0]["extraction_diagnostics"][outcome_key], 1)
                self.assertEqual(result["summary"][outcome_key], 1)
                self.extractor.extract.side_effect = None

    def test_request_preflight_rejection_is_not_counted_as_provider_error(self):
        self.extractor.extract.side_effect = ScholarshipExtractionError(
            "request exceeded the configured payload budget",
            category="payload_too_large",
        )

        result = self._run(run_id="request-preflight-rejection")

        self.assertEqual(result["summary"]["request_rejected"], 1)
        self.assertEqual(result["summary"]["provider_error"], 0)
        self.assertEqual(
            result["sources"][0]["extraction_diagnostics"]["request_rejected"],
            1,
        )
        self.assertEqual(result["sources"][0]["extraction_diagnostics"]["provider_error"], 0)
        history = _discovery_run_history(
            self.db.get(ScholarshipDiscoveryRun, "request-preflight-rejection"),
            datetime.now(timezone.utc),
        )
        self.assertEqual(history.extraction_diagnostics.request_rejected, 1)
        self.assertEqual(history.extraction_diagnostics.provider_error, 0)

    def test_manual_run_works_when_scheduler_is_disabled_without_changing_scheduled_slot(self):
        scheduled_for = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        scheduled_run = ScholarshipDiscoveryRun(
            id="scheduled-slot",
            started_at=scheduled_for,
            scheduled_for=scheduled_for,
            trigger_type="scheduled",
            status="completed",
            summary={},
            source_results=[],
        )
        self.db.add(scheduled_run)
        self.db.commit()
        started_run_ids = []
        self.fetcher.crawl.return_value = []

        result = run_discovery(
            self.db,
            settings=_settings(enabled=False),
            sources=controlled_manual_sources(),
            fetcher=self.fetcher,
            extractor=self.extractor,
            run_id="manual-run-id",
            on_run_started=started_run_ids.append,
        )

        manual_run = self.db.get(ScholarshipDiscoveryRun, "manual-run-id")
        self.db.refresh(scheduled_run)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(manual_run.trigger_type, "manual")
        self.assertIsNone(manual_run.scheduled_for)
        self.assertEqual(started_run_ids, ["manual-run-id"])
        stored_scheduled_for = scheduled_run.scheduled_for
        if stored_scheduled_for.tzinfo is None:
            stored_scheduled_for = stored_scheduled_for.replace(tzinfo=timezone.utc)
        self.assertEqual(stored_scheduled_for, scheduled_for)

    def test_scheduler_classified_catch_up_trigger_is_persisted_and_returned(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        scheduled_for, trigger_type = calculate_next_run(
            now - timedelta(hours=49),
            now,
            24,
        )
        self.assertEqual(trigger_type, "catch_up")

        result = self._run(trigger_type=trigger_type, scheduled_for=scheduled_for)

        run = self.db.query(ScholarshipDiscoveryRun).one()
        self.assertEqual(run.trigger_type, "catch_up")
        self.assertEqual(result["trigger_type"], "catch_up")
        self.assertEqual(result["scheduled_for"], run.scheduled_for.isoformat())

    def test_discovery_only_source_skips_crawl_and_extraction(self):
        source = replace(_source(discovery_only=True), crawl_enabled=True)
        result = run_discovery(
            self.db,
            settings=_settings(),
            sources=(source,),
            fetcher=self.fetcher,
            extractor=self.extractor,
            trigger_type="scheduled",
        )

        self.fetcher.crawl.assert_not_called()
        self.extractor.extract.assert_not_called()
        self.assertEqual(result["summary"]["sources_skipped"], 1)
        self.assertEqual(result["summary"]["sources_successfully_fetched"], 0)
        self.assertEqual(result["sources"][0]["status"], "skipped")
        self.assertEqual(result["sources"][0]["pages_fetched"], 0)

    def test_unreviewed_listing_source_is_not_fetched(self):
        source = _source(
            source_classification="trusted_listing",
            trust_basis=None,
            trust_reviewed=False,
        )
        result = run_discovery(
            self.db,
            settings=_settings(),
            sources=(source,),
            fetcher=self.fetcher,
            extractor=self.extractor,
            trigger_type="scheduled",
        )

        self.fetcher.crawl.assert_not_called()
        self.extractor.extract.assert_not_called()
        self.assertEqual(result["sources"][0]["status"], "trust_review_required")

    def test_unreviewed_official_source_is_not_fetched(self):
        source = replace(
            SOURCES_BY_ID["deutschlandstipendium"],
            trust_basis=None,
            trust_reviewed=False,
        )
        result = run_discovery(
            self.db,
            settings=_settings(),
            sources=(source,),
            fetcher=self.fetcher,
            extractor=self.extractor,
            trigger_type="scheduled",
        )

        self.fetcher.crawl.assert_not_called()
        self.extractor.extract.assert_not_called()
        self.assertEqual(result["summary"]["sources_skipped"], 1)
        self.assertEqual(result["sources"][0]["status"], "trust_review_required")

    def test_reviewed_but_crawl_disabled_source_is_not_fetched(self):
        source = SOURCES_BY_ID["polimi-merit-scholarships"]
        self.assertTrue(source.trust_reviewed)
        self.assertFalse(source.crawl_enabled)
        result = run_discovery(
            self.db,
            settings=_settings(),
            sources=(source,),
            fetcher=self.fetcher,
            extractor=self.extractor,
            trigger_type="scheduled",
        )

        self.fetcher.crawl.assert_not_called()
        self.extractor.extract.assert_not_called()
        self.assertEqual(result["summary"]["sources_skipped"], 1)
        self.assertEqual(result["sources"][0]["status"], "skipped")

    def test_incomplete_candidate_is_persisted_without_creating_scholarship(self):
        values = dict(self.extractor.extract.return_value[0].values)
        values.pop("country")
        self.extractor.extract.return_value = [
            ExtractedScholarship(
                values=values,
                evidence={"name": "Finland Master's Award"},
                missing_required_fields=("country",),
                review_reasons=("missing_scholarship_identity",),
            ),
        ]

        result = self._run()

        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(self.db.query(Scholarship).count(), 0)
        self.assertEqual(review_item.review_status, "pending")
        self.assertEqual(review_item.missing_required_fields, ["country"])
        self.assertEqual(review_item.source_classification, "government_authority")
        self.assertEqual(review_item.evidence_excerpts[0]["evidence_excerpts"]["name"], "Finland Master's Award")
        self.assertEqual(review_item.discovery_run_id, self.db.query(ScholarshipDiscoveryRun).one().id)

    def test_acceptance_creates_only_an_unverified_scholarship(self):
        values = dict(self.extractor.extract.return_value[0].values)
        values.pop("country")
        self.extractor.extract.return_value = [
            ExtractedScholarship(
                values=values,
                evidence={"name": "Finland Master's Award"},
                missing_required_fields=("country",),
                review_reasons=("missing_scholarship_identity",),
            ),
        ]
        self._run()
        item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        admin = User(
            email="reviewer@example.com",
            hashed_password="test-hash",
            full_name="Reviewer",
            role="admin",
        )
        self.db.add(admin)
        self.db.commit()

        apply_review_action(self.db, item, decision="reviewed", admin=admin)
        accepted = apply_review_action(
            self.db,
            item,
            decision="accepted",
            admin=admin,
            values={"country": "Finland"},
            note="Reviewed extracted evidence",
        )

        scholarship = self.db.query(Scholarship).one()
        self.assertEqual(accepted.review_status, "accepted")
        self.assertEqual(accepted.accepted_scholarship_id, scholarship.id)
        self.assertEqual((scholarship.verification_status, scholarship.verification_basis),
                         ("unverified", "not_verified"))
        self.assertEqual(self.db.query(ScholarshipDocumentVersion).count(), 0)
        self.assertEqual(self.db.query(ScholarshipChunkEmbedding).count(), 0)
        publication = self.db.query(ScholarshipDiscoveryPublication).one()
        self.assertEqual(publication.canonical_scholarship_id, scholarship.id)
        self.assertEqual(publication.status, "published")
        self.assertEqual(
            self.db.query(ScholarshipDiscoveryPublicationVersion).one().approval_decision,
            "accepted",
        )

    def test_rejected_candidate_is_never_created_as_a_scholarship(self):
        values = dict(self.extractor.extract.return_value[0].values)
        values.pop("country")
        self.extractor.extract.return_value = [
            ExtractedScholarship(
                values=values,
                evidence={"name": "Finland Master's Award"},
                missing_required_fields=("country",),
                review_reasons=("missing_scholarship_identity",),
            ),
        ]
        self._run()
        item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        admin = User(
            email="reviewer@example.com",
            hashed_password="test-hash",
            full_name="Reviewer",
            role="admin",
        )
        self.db.add(admin)
        self.db.commit()

        apply_review_action(self.db, item, decision="reviewed", admin=admin)
        rejected = apply_review_action(
            self.db,
            item,
            decision="rejected",
            admin=admin,
            note="Source evidence was insufficient",
        )

        self.assertEqual(rejected.review_status, "rejected")
        self.assertEqual(self.db.query(Scholarship).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDiscoveryPublication).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDiscoveryPublicationVersion).count(), 0)

    def test_link_and_publish_defers_rag_preparation_until_explicit_admin_action(self):
        scholarship = self._add_existing_scholarship(
            verification_status="verified",
            verification_basis="official_source",
            last_verified_date=date.today(),
        )
        self._run()
        item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        admin = User(
            email="reviewer@example.com",
            hashed_password="test-hash",
            full_name="Reviewer",
            role="admin",
        )
        self.db.add(admin)
        self.db.commit()

        self.assertEqual(self.db.query(ScholarshipSourceDocument).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDocumentVersion).count(), 0)
        apply_review_action(self.db, item, decision="reviewed", admin=admin)

        with patch("app.services.scholarship_discovery.SOURCES", (_source(),)):
            linked = apply_review_action(
                self.db,
                item,
                decision="link_and_publish",
                admin=admin,
                link_to_scholarship_id=scholarship.id,
                note="Confirmed this is the same opportunity",
            )
            retry = apply_review_action(
                self.db,
                item,
                decision="link_and_publish",
                admin=admin,
                link_to_scholarship_id=scholarship.id,
                note="Confirmed this is the same opportunity",
            )

        publication = self.db.query(ScholarshipDiscoveryPublication).one()
        version = self.db.query(ScholarshipDiscoveryPublicationVersion).one()
        document_version = self.db.query(ScholarshipDocumentVersion).one()
        self.assertEqual(linked.review_status, "accepted")
        self.assertEqual(retry.id, linked.id)
        self.assertEqual(linked.accepted_scholarship_id, scholarship.id)
        self.assertEqual(version.approval_decision, "link_and_publish")
        self.assertEqual(publication.canonical_scholarship_id, scholarship.id)
        self.assertEqual(self.db.query(Scholarship).count(), 1)
        self.assertEqual(self.db.query(ScholarshipDiscoveryPublicationSource).count(), 1)
        self.assertEqual(self.db.query(ScholarshipDiscoveryPublicationEvent).count(), 1)
        self.assertEqual(document_version.review_status, "pending")
        self.assertEqual(document_version.indexing_status, "pending")
        self.assertEqual(document_version.verification_status_snapshot, "verified")
        self.assertEqual(self.db.query(ScholarshipChunkEmbedding).count(), 0)

    def test_publication_source_freshness_preserves_last_success_after_failure(self):
        scholarship = self._add_existing_scholarship()
        self._run()
        item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        admin = User(
            email="reviewer@example.com",
            hashed_password="test-hash",
            full_name="Reviewer",
            role="admin",
        )
        self.db.add(admin)
        self.db.commit()
        apply_review_action(self.db, item, decision="reviewed", admin=admin)
        apply_review_action(
            self.db,
            item,
            decision="link_and_publish",
            admin=admin,
            link_to_scholarship_id=scholarship.id,
        )
        publication = self.db.query(ScholarshipDiscoveryPublication).one()
        source = self.db.query(ScholarshipDiscoveryPublicationSource).one()
        record_publication_source_success(
            self.db,
            source.source_id,
            source.source_url,
            "f" * 64,
        )
        self.db.flush()
        self.assertEqual(source.source_check_status, "content_changed")
        self.assertEqual(source.observed_content_hash, "f" * 64)
        successful_at = source.last_successful_check_at

        record_publication_source_failure(self.db, source.source_id)
        self.db.flush()
        self.assertEqual(source.source_check_status, "failed")
        self.assertEqual(source.last_successful_check_at, successful_at)
        self.assertEqual(source.observed_content_hash, "f" * 64)
        revoked = transition_publication(
            self.db,
            publication.id,
            admin,
            decision="revoke",
            reason="The source confirms the opportunity is no longer available",
        )
        self.assertEqual(revoked.status, "revoked")
        self.assertEqual(revoked.revoked_by_id, admin.id)
        self.assertEqual(self.db.query(ScholarshipDiscoveryPublicationEvent).count(), 2)

    def test_publication_source_success_orders_naive_and_aware_observations(self):
        initial = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        source = self._add_publication_source(initial)
        self.db.expire(source, ["last_checked_at"])
        self.assertIsNone(source.last_checked_at.tzinfo)

        older = initial - timedelta(hours=1)
        self.assertEqual(
            record_publication_source_success(
                self.db,
                source.source_id,
                source.source_url,
                "b" * 64,
                checked_at=older,
            ),
            1,
        )
        self.db.flush()
        self._assert_source_timestamp(source, "last_checked_at", initial)
        self.assertEqual(source.observed_content_hash, "a" * 64)

        self.assertEqual(
            record_publication_source_success(
                self.db,
                source.source_id,
                source.source_url,
                "b" * 64,
                checked_at=initial,
            ),
            1,
        )
        self.db.flush()
        self._assert_source_timestamp(source, "last_checked_at", initial)
        self.assertEqual(source.observed_content_hash, "b" * 64)
        self.assertEqual(source.source_check_status, "content_changed")

        newer = initial + timedelta(hours=2)
        offset_aware_newer = newer.astimezone(timezone(timedelta(hours=5, minutes=30)))
        self.assertEqual(
            record_publication_source_success(
                self.db,
                source.source_id,
                source.source_url,
                "c" * 64,
                checked_at=offset_aware_newer,
            ),
            1,
        )
        self.db.flush()
        self._assert_source_timestamp(source, "last_checked_at", newer)
        self.assertEqual(source.observed_content_hash, "c" * 64)

        naive_newer = newer + timedelta(hours=1)
        self.assertEqual(
            record_publication_source_success(
                self.db,
                source.source_id,
                source.source_url,
                "d" * 64,
                checked_at=naive_newer.replace(tzinfo=None),
            ),
            1,
        )
        self.db.flush()
        self._assert_source_timestamp(source, "last_checked_at", naive_newer)
        self.assertEqual(source.observed_content_hash, "d" * 64)

    def test_publication_source_failure_normalizes_times_and_preserves_success_metadata(self):
        initial = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        source = self._add_publication_source(initial)
        successful_at = initial
        content_hash = source.observed_content_hash

        naive_failure_at = initial + timedelta(hours=1)
        self.assertEqual(
            record_publication_source_failure(
                self.db,
                source.source_id,
                checked_at=naive_failure_at.replace(tzinfo=None),
            ),
            1,
        )
        self.db.flush()
        self.assertEqual(source.source_check_status, "failed")
        self._assert_source_timestamp(source, "last_checked_at", naive_failure_at)
        self._assert_source_timestamp(source, "last_successful_check_at", successful_at)
        self.assertEqual(source.observed_content_hash, content_hash)

        aware_failure_at = initial + timedelta(hours=2)
        offset_aware_failure_at = aware_failure_at.astimezone(
            timezone(timedelta(hours=-4))
        )
        self.assertEqual(
            record_publication_source_failure(
                self.db,
                source.source_id,
                checked_at=offset_aware_failure_at,
            ),
            1,
        )
        self.db.flush()
        self.assertEqual(source.source_check_status, "failed")
        self._assert_source_timestamp(source, "last_checked_at", aware_failure_at)
        self._assert_source_timestamp(source, "last_successful_check_at", successful_at)
        self.assertEqual(source.observed_content_hash, content_hash)

    def test_publication_source_import_orders_against_sqlite_naive_timestamp(self):
        initial = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        source = self._add_publication_source(initial)
        publication = (
            self.db.query(ScholarshipDiscoveryPublication)
            .filter(ScholarshipDiscoveryPublication.id == source.publication_id)
            .one()
        )
        self.db.expire(source, ["last_checked_at"])
        self.assertIsNone(source.last_checked_at.tzinfo)

        older = initial - timedelta(hours=1)
        _publication_source(
            self.db,
            publication,
            {
                "source_id": source.source_id,
                "source_url": source.source_url,
                "observed_at": older,
                "content_hash": "b" * 64,
            },
        )
        self.db.flush()
        self._assert_source_timestamp(source, "last_checked_at", initial)
        self.assertEqual(source.observed_content_hash, "a" * 64)

        newer = initial + timedelta(hours=2)
        _publication_source(
            self.db,
            publication,
            {
                "source_id": source.source_id,
                "source_url": source.source_url,
                "observed_at": newer.astimezone(timezone(timedelta(hours=3))),
                "content_hash": "c" * 64,
            },
        )
        self.db.flush()
        self._assert_source_timestamp(source, "last_checked_at", newer)
        self.assertEqual(source.observed_content_hash, "c" * 64)
        self.assertEqual(source.source_check_status, "content_changed")

    def test_database_enforces_one_publication_per_canonical_scholarship(self):
        scholarship = self._add_existing_scholarship()
        self.db.add(ScholarshipDiscoveryPublication(canonical_scholarship_id=scholarship.id))
        self.db.commit()
        self.db.add(ScholarshipDiscoveryPublication(canonical_scholarship_id=scholarship.id))

        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()

    def test_review_acceptance_keeps_existing_duplicate_protection(self):
        values = dict(self.extractor.extract.return_value[0].values)
        values.pop("country")
        self.extractor.extract.return_value = [
            ExtractedScholarship(
                values=values,
                evidence={"name": "Finland Master's Award"},
                missing_required_fields=("country",),
                review_reasons=("missing_scholarship_identity",),
            ),
        ]
        self._run()
        item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        existing = Scholarship(
            name="Finland Master's Award",
            country="Finland",
            verification_status="unverified",
            verification_basis="not_verified",
        )
        self.db.add(existing)
        item.host_country = "Finland"
        item.extracted_values = {**item.extracted_values, "country": "Finland"}
        admin = User(
            email="reviewer@example.com",
            hashed_password="test-hash",
            full_name="Reviewer",
            role="admin",
        )
        self.db.add(admin)
        self.db.commit()
        apply_review_action(self.db, item, decision="reviewed", admin=admin)

        with self.assertRaises(HTTPException) as error:
            apply_review_action(
                self.db,
                item,
                decision="accepted",
                admin=admin,
                values={"country": "Finland"},
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.query(Scholarship).count(), 1)
        self.assertEqual(item.review_status, "reviewed")

    def test_trusted_listing_candidate_is_queued_not_auto_created(self):
        source = _source(
            source_classification="trusted_listing",
            trust_basis="Manually reviewed scholarship-listing policy",
        )
        candidate = self.extractor.extract.return_value[0]
        candidate.values.pop("official_info_url", None)
        fetcher = MagicMock()
        fetcher.crawl.return_value = [self.page]
        result = run_discovery(
            self.db,
            settings=_settings(),
            sources=(source,),
            fetcher=fetcher,
            extractor=self.extractor,
            trigger_type="scheduled",
        )

        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(self.db.query(Scholarship).count(), 0)
        self.assertEqual(review_item.source_classification, "trusted_listing")
        self.assertNotIn("official_info_url", review_item.extracted_values)
        self.assertEqual(self.db.query(ScholarshipSourceDocument).count(), 0)

    def test_conflicting_listing_and_official_evidence_are_preserved_with_official_preference(self):
        listing_source = _source(
            source_classification="trusted_listing",
            trust_basis="Manually reviewed scholarship-listing policy",
        )
        listing_candidate = _candidate(page=self.page, living_stipend="Listing amount")
        listing_candidate.values.pop("official_info_url", None)
        listing_extractor = MagicMock()
        listing_extractor.extract.return_value = [listing_candidate]
        listing_extractor.last_rejected_count = 0
        listing_fetcher = MagicMock()
        listing_fetcher.crawl.return_value = [self.page]
        run_discovery(
            self.db,
            settings=_settings(),
            sources=(listing_source,),
            fetcher=listing_fetcher,
            extractor=listing_extractor,
            trigger_type="scheduled",
        )

        official_candidate = _candidate(page=self.page, living_stipend="Official amount")
        official_extractor = MagicMock()
        official_extractor.extract.return_value = [official_candidate]
        official_extractor.last_rejected_count = 0
        official_fetcher = MagicMock()
        official_fetcher.crawl.return_value = [self.page]
        run_discovery(
            self.db,
            settings=_settings(),
            sources=(_source(),),
            fetcher=official_fetcher,
            extractor=official_extractor,
            trigger_type="scheduled",
        )

        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        stipend_conflict = next(
            conflict for conflict in review_item.conflicting_values
            if conflict["field"] == "living_stipend"
        )
        self.assertEqual(review_item.extracted_values["living_stipend"], "Official amount")
        self.assertEqual(stipend_conflict["preferred_value"], "Official amount")
        self.assertEqual(stipend_conflict["preferred_source"]["source_classification"], "government_authority")
        self.assertEqual(len(review_item.evidence_excerpts), 2)
        self.assertEqual(self.db.query(Scholarship).count(), 0)

    def test_normal_source_still_crawls_and_processes_candidates(self):
        result = self._run()

        self.fetcher.crawl.assert_called_once_with(_source())
        self.extractor.extract.assert_called_once_with(self.page, _source())
        self.assertEqual(result["summary"]["sources_successfully_fetched"], 1)
        self.assertEqual(result["summary"]["new_records_created"], 0)
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(result["summary"]["candidates_accepted"], 1)
        self.assertEqual(result["summary"]["candidates_rejected"], 0)
        self.assertEqual(self.db.query(Scholarship).count(), 0)

    def test_run_records_link_text_and_valid_empty_diagnostics(self):
        retained_text = self.page.text
        self.page = replace(
            self.page,
            original_text_length=len(retained_text) + 25,
            retained_text_length=len(retained_text),
            text_truncated=True,
        )
        self.fetcher.crawl.return_value = [self.page]
        self.fetcher.last_crawl_stats = {
            "linked_urls_discovered": 4,
            "linked_pages_fetched": 2,
            "linked_pages_failed": 1,
            "linked_pages_skipped_safety": 1,
            "linked_pages_skipped_relevance": 1,
            "linked_pages_skipped": 2,
        }
        self.extractor.extract.return_value = []

        result = self._run(run_id="diagnostic-empty-run")

        self.assertEqual(result["summary"]["valid_empty"], 1)
        self.assertEqual(result["summary"]["linked_urls_discovered"], 4)
        self.assertEqual(result["summary"]["linked_pages_fetched"], 2)
        self.assertEqual(result["summary"]["linked_pages_failed"], 1)
        self.assertEqual(result["summary"]["linked_pages_skipped"], 2)
        self.assertEqual(result["summary"]["truncated_pages"], 1)
        self.assertEqual(result["summary"]["truncated_original_chars"], len(retained_text) + 25)
        self.assertEqual(result["summary"]["truncated_retained_chars"], len(retained_text))
        source_result = result["sources"][0]
        self.assertEqual(source_result["extraction_diagnostics"]["valid_empty"], 1)
        self.assertEqual(
            source_result["text_truncations"],
            [{
                "source_id": "test-finland",
                "page_index": 1,
                "original_length": len(retained_text) + 25,
                "retained_length": len(retained_text),
            }],
        )

        history = _discovery_run_history(
            self.db.get(ScholarshipDiscoveryRun, "diagnostic-empty-run"),
            datetime.now(timezone.utc),
        )
        self.assertEqual(history.fetch_diagnostics.linked_pages_failed, 1)
        self.assertEqual(history.fetch_diagnostics.text_truncations[0].original_length, len(retained_text) + 25)
        self.assertEqual(history.extraction_diagnostics.valid_empty, 1)

    def test_insufficient_page_content_skips_provider_and_is_counted(self):
        self.page = replace(
            self.page,
            text="",
            original_text_length=0,
            retained_text_length=0,
            insufficient_content=True,
        )
        self.fetcher.crawl.return_value = [self.page]

        result = self._run(run_id="insufficient-content-run")

        self.extractor.extract.assert_not_called()
        self.assertEqual(result["sources"][0]["status"], "fetched")
        self.assertEqual(result["sources"][0]["extraction_diagnostics"]["insufficient_page_content"], 1)
        self.assertEqual(result["summary"]["insufficient_page_content"], 1)
        self.assertEqual(result["summary"]["provider_error"], 0)

    def test_provider_and_malformed_extraction_errors_have_distinct_counters(self):
        for error_category, outcome_key in (
            ("provider_error", "provider_error"),
            ("malformed_response", "malformed_response"),
        ):
            with self.subTest(error_category=error_category):
                self.extractor.extract.side_effect = ScholarshipExtractionError(
                    "sanitized extraction failure",
                    category=error_category,
                )
                result = self._run(run_id=f"diagnostic-{error_category}")
                self.assertEqual(result["sources"][0]["status"], "partial_failure")
                self.assertEqual(result["sources"][0]["extraction_diagnostics"][outcome_key], 1)
                self.assertEqual(result["summary"][outcome_key], 1)
                self.extractor.extract.side_effect = None

    def test_lock_loss_stops_before_persisting_the_next_candidate(self):
        first_candidate = _candidate(page=self.page)
        second_candidate = _candidate(page=self.page, name="Finland Regional Award")
        self.extractor.extract.return_value = [first_candidate, second_candidate]
        checks = {"count": 0}

        def verify_lock(_db):
            checks["count"] += 1
            if checks["count"] >= 9:
                raise DiscoveryLockLost("simulated lock-connection loss")
            return True

        lock_guard = MagicMock(check=verify_lock)

        with self.assertRaises(DiscoveryLockLost):
            self._run(lock_guard=lock_guard)

        self.assertEqual(checks["count"], 10)
        self.assertEqual(self.db.query(Scholarship).count(), 0)
        review_items = self.db.query(ScholarshipDiscoveryReviewItem).all()
        self.assertEqual(len(review_items), 1)
        self.assertEqual(review_items[0].candidate_name, first_candidate.values["name"])
        self.assertEqual(self.db.query(ScholarshipDiscoveryRun).one().status, "running")

    def test_lock_loss_after_fetch_stops_before_publication_or_extraction(self):
        state = {"fetched": False}

        def crawl(_source):
            state["fetched"] = True
            return [self.page]

        def verify_lock(_db):
            if state["fetched"]:
                raise DiscoveryLockLost("simulated lock loss after fetch")
            return True

        self.fetcher.crawl.side_effect = crawl

        with patch(
            "app.services.scholarship_discovery.record_publication_source_success"
        ) as publication:
            with self.assertRaises(DiscoveryLockLost):
                self._run(lock_guard=MagicMock(check=verify_lock))

        publication.assert_not_called()
        self.extractor.extract.assert_not_called()
        self.assertEqual(self.db.query(ScholarshipDiscoveryReviewItem).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDiscoveryRun).one().status, "running")

    def test_lock_loss_after_extraction_stops_before_candidate_persistence(self):
        state = {"extracted": False}

        def extract(*_args):
            state["extracted"] = True
            return [_candidate(page=self.page)]

        def verify_lock(_db):
            if state["extracted"]:
                raise DiscoveryLockLost("simulated lock loss after extraction")
            return True

        self.extractor.extract.side_effect = extract

        with patch("app.services.scholarship_discovery.persist_review_candidate") as persist:
            with self.assertRaises(DiscoveryLockLost):
                self._run(lock_guard=MagicMock(check=verify_lock))

        persist.assert_not_called()
        self.assertEqual(self.db.query(ScholarshipDiscoveryReviewItem).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDiscoveryRun).one().status, "running")

    def test_database_error_verifying_lock_is_unsafe(self):
        lock_guard = MagicMock(check=MagicMock(side_effect=SQLAlchemyError("database unavailable")))

        with self.assertRaises(DiscoveryLockLost):
            self._run(lock_guard=lock_guard)

        self.assertEqual(self.db.query(ScholarshipDiscoveryRun).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDiscoveryReviewItem).count(), 0)

    def test_verification_wait_count_is_per_source_not_per_candidate(self):
        first_candidate = _candidate(page=self.page)
        second_candidate = _candidate(page=self.page, name="Finland Regional Award")
        self._add_existing_scholarship(
            first_candidate,
            verification_status="unverified",
            verification_basis="not_verified",
        )
        self._add_existing_scholarship(
            second_candidate,
            verification_status="unverified",
            verification_basis="not_verified",
        )
        self.extractor.extract.return_value = [first_candidate, second_candidate]

        result = self._run()
        self.assertEqual(result["summary"]["new_records_created"], 0)
        self.assertEqual(result["summary"]["review_candidates_queued"], 2)
        self.assertEqual(result["summary"]["sources_waiting_for_scholarship_verification"], 1)
        self.assertEqual(self.db.query(Scholarship).count(), 2)

    def test_register_evidence_rechecks_urls_before_creating_source_documents(self):
        scholarship = self._add_existing_scholarship()
        values = {
            "official_application_url": (
                "https://apply.example.org/form?campaign=summer&token=link-secret#apply"
            ),
            "additional_source_urls": [
                "../more?utm_source=official&api_key=link-secret#details",
                "https://official.example.attacker.com/scholarships/fake",
                "https://attacker.com/scholarships/fake",
            ],
        }
        source = _source(
            trusted_external_domains=("apply.example.org",),
            trusted_external_domains_reviewed=True,
            trusted_external_domain_trust_basis="Synthetic test-only reviewed portal",
        )

        with self.assertLogs("app.services.scholarship_discovery", level="WARNING") as logs:
            _register_evidence(self.db, scholarship, source, values, self.page)
        self.db.commit()

        normalized_urls = {
            item.normalized_url for item in self.db.query(ScholarshipSourceDocument).all()
        }
        self.assertIn(
            "https://apply.example.org/form?campaign=summer",
            normalized_urls,
        )
        self.assertIn("https://official.example/more?utm_source=official", normalized_urls)
        self.assertNotIn(
            "https://official.example.attacker.com/scholarships/fake",
            normalized_urls,
        )
        self.assertNotIn("https://attacker.com/scholarships/fake", normalized_urls)
        self.assertNotIn("link-secret", str(normalized_urls))
        self.assertEqual(logs.output.count(
            "WARNING:app.services.scholarship_discovery:Scholarship evidence URL rejected for "
            "test-finland: invalid_trusted_domain"
        ), 2)

    def test_verified_record_gets_no_rag_documents_before_admin_approval(self):
        self._add_existing_scholarship(
            verification_status="verified",
            verification_basis="official_source",
            last_verified_date=date.today(),
        )

        result = self._run()
        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        self.assertEqual(review_item.review_status, "pending")
        self.assertEqual(self.db.query(Scholarship).count(), 1)
        self.assertEqual(result["summary"]["rag_source_versions_prepared_pending"], 0)
        self.assertEqual(result["summary"]["documents_awaiting_admin_review"], 0)
        self.assertEqual(self.db.query(ScholarshipSourceDocument).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDocumentVersion).count(), 0)
        self.assertEqual(self.db.query(ScholarshipChunkEmbedding).count(), 0)
        self.assertEqual(
            review_item.evidence_excerpts[0]["_rag_page_snapshot"]["text"],
            self.page.text,
        )
        response_data = AdminDiscoveryReviewItem.model_validate(review_item).model_dump()
        self.assertNotIn("_rag_page_snapshot", str(response_data))

        with patch.dict("os.environ", {"MINILM_MODEL_REVISION": "0123456789abcdef0123456789abcdef01234567"}):
            with patch.object(rag_service, "embed_query", return_value=[0.1] * 384):
                self.assertEqual(rag_service.retrieve(self.db, "question").status, rag_service.STATUS_NO_SOURCES)

    def test_repeated_discovery_does_not_prepare_rag_documents_before_review(self):
        self._add_existing_scholarship(
            verification_status="verified",
            verification_basis="official_source",
            last_verified_date=date.today(),
        )
        self._run()

        result = self._run()
        self.assertEqual(result["summary"]["rag_source_versions_prepared_pending"], 0)
        self.assertEqual(result["summary"]["documents_awaiting_admin_review"], 0)
        self.assertEqual(self.db.query(ScholarshipSourceDocument).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDocumentVersion).count(), 0)

    def test_failed_source_keeps_last_success_timestamp_and_records_failure(self):
        successful = self._run()
        last_success = successful["sources"][0]["last_success_at"]
        self.fetcher.crawl.side_effect = DiscoveryFetchError(
            "sensitive source detail",
            status_code=503,
            attempt_count=3,
            attempt_limit=3,
        )

        with self.assertLogs("app.services.scholarship_discovery", level="WARNING") as logs:
            failed = self._run()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["summary"]["sources_failed"], 1)
        self.assertEqual(failed["sources"][0]["error"], "DiscoveryFetchError")
        self.assertEqual(failed["sources"][0]["error_category"], "http_status")
        self.assertEqual(failed["sources"][0]["failure_stage"], "root_fetch")
        self.assertEqual(failed["sources"][0]["http_status"], 503)
        self.assertEqual(failed["sources"][0]["attempt_count"], 3)
        self.assertEqual(failed["sources"][0]["attempt_limit"], 3)
        self.assertEqual(failed["sources"][0]["last_success_at"], last_success)
        self.assertNotIn("sensitive source detail", str(failed))
        self.assertIn("stage=root_fetch", "\n".join(logs.output))
        self.assertIn("category=http_status", "\n".join(logs.output))
        self.assertIn("http_status=503", "\n".join(logs.output))
        self.assertNotIn("sensitive source detail", "\n".join(logs.output))

    def test_matching_existing_scholarship_is_queued_as_a_possible_duplicate(self):
        item = self._add_existing_scholarship(
            verification_status="unverified",
            verification_basis="not_verified",
            record_version=4,
            data_flags=[],
        )

        result = self._run()

        self.db.refresh(item)
        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        possible_duplicate = next(
            conflict for conflict in review_item.conflicting_values
            if conflict["field"] == "possible_duplicate"
        )
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(review_item.review_status, "pending")
        self.assertEqual(possible_duplicate["values"][0]["value"]["id"], item.id)
        self.assertEqual(self.db.query(Scholarship).count(), 1)
        self.assertEqual(item.record_version, 4)
        self.assertEqual(item.data_flags, [])
        self.assertEqual(self.db.query(ScholarshipAuditLog).count(), 0)

    def test_potential_duplicate_is_queued_with_existing_record_identity(self):
        item = Scholarship(
            country="Finland",
            name="Finland Award",
            verification_status="verified",
            verification_basis="official_source",
            last_verified_date=date.today(),
            record_version=3,
            data_flags=[],
        )
        self.db.add(item)
        self.db.commit()

        result = self._run()

        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        possible_duplicate = next(
            conflict for conflict in review_item.conflicting_values
            if conflict["field"] == "possible_duplicate"
        )
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(result["summary"]["ambiguous_duplicates_queued"], 1)
        self.assertEqual(possible_duplicate["values"][0]["value"]["id"], item.id)
        self.assertEqual(self.db.query(Scholarship).count(), 1)
        self.assertEqual(item.record_version, 3)
        self.assertEqual(item.data_flags, [])
        self.assertEqual(self.db.query(ScholarshipAuditLog).count(), 0)

    def test_conflicting_existing_values_are_queued_without_mutating_the_record(self):
        item = Scholarship(
            country="Finland",
            name="Finland Master's Award",
            living_stipend="Existing reviewed amount",
            verification_status="verified",
            verification_basis="official_source",
            official_info_url=self.page.url,
            last_verified_date=date.today(),
            record_version=4,
        )
        self.db.add(item)
        self.db.commit()
        original_data_flags = item.data_flags
        self.assertIsNone(original_data_flags)
        self.extractor.extract.return_value = [
            _candidate(page=self.page, living_stipend="New extracted amount"),
        ]
        result = self._run()

        self.db.refresh(item)
        review_item = self.db.query(ScholarshipDiscoveryReviewItem).one()
        stipend_conflict = next(
            conflict for conflict in review_item.conflicting_values
            if conflict["field"] == "living_stipend"
        )
        self.assertEqual(item.living_stipend, "Existing reviewed amount")
        self.assertEqual(item.data_flags, original_data_flags)
        self.assertEqual(item.record_version, 4)
        self.assertEqual(result["summary"]["existing_records_flagged_for_review"], 0)
        self.assertEqual(result["summary"]["review_candidates_queued"], 1)
        self.assertEqual(stipend_conflict["values"][0]["value"], "Existing reviewed amount")
        self.assertEqual(stipend_conflict["values"][1]["value"], "New extracted amount")
        self.assertEqual(self.db.query(ScholarshipAuditLog).count(), 0)

    def test_repeated_candidate_is_deduplicated_in_the_review_queue(self):
        self._run()
        result = self._run()
        self.assertEqual(self.db.query(Scholarship).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDiscoveryReviewItem).count(), 1)
        self.assertEqual(result["summary"]["review_candidates_queued"], 0)
        self.assertEqual(result["summary"]["new_records_created"], 0)

    def test_discovery_table_is_not_created_by_application_startup(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        create_application_schema(bind=engine)
        tables = set(inspect(engine).get_table_names())
        self.assertNotIn("scholarship_discovery_runs", tables)
        self.assertNotIn("scholarship_discovery_review_items", tables)
        self.assertNotIn("scholarship_discovery_publications", tables)
        self.assertNotIn("scholarship_discovery_publication_versions", tables)
        self.assertNotIn("scholarship_discovery_publication_sources", tables)
        self.assertNotIn("scholarship_discovery_publication_events", tables)

    def test_settings_validate_ranges_and_default_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = scholarship_discovery_settings()
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.model, "gemini-3-flash-preview")
        self.assertEqual(settings.interval_hours, 24)
        self.assertEqual(settings.stale_run_timeout_hours, 12)
        with patch.dict("os.environ", {"SCHOLARSHIP_DISCOVERY_MAX_PAGES_PER_SOURCE": "0"}):
            with self.assertRaisesRegex(RuntimeError, "between"):
                scholarship_discovery_settings()
        with patch.dict("os.environ", {"SCHOLARSHIP_DISCOVERY_INTERVAL_HOURS": "6"}):
            self.assertEqual(scholarship_discovery_settings().interval_hours, 6)
        with patch.dict("os.environ", {"SCHOLARSHIP_DISCOVERY_STALE_RUN_TIMEOUT_HOURS": "24"}):
            self.assertEqual(scholarship_discovery_settings().stale_run_timeout_hours, 24)


if __name__ == "__main__":
    unittest.main()
