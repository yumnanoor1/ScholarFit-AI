import io
import ipaddress
import os
import socket
import ssl
import unittest
from datetime import date
from email.message import Message
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import dns.exception
import dns.resolver
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import ScholarshipDiscoverySettings, scholarship_discovery_settings
from app.database import Base, create_application_schema
from app.models.opportunity import Scholarship, ScholarshipAuditLog
from app.models.scholarship_discovery import ScholarshipDiscoveryRun
from app.models.scholarship_knowledge import (
    ScholarshipChunkEmbedding,
    ScholarshipDocumentChunk,
    ScholarshipDocumentVersion,
    ScholarshipSourceDocument,
)
from app.services import rag_service
from app.services.scholarship_discovery import _register_evidence, run_discovery
from app.services.scholarship_discovery_extraction import (
    ExtractedScholarship,
    GeminiScholarshipExtractor,
    InvalidEvidenceURL,
    OutOfScopeScholarship,
    ScholarshipExtractionError,
    _validate_candidate,
)
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
)
from app.services.scholarship_discovery_sources import (
    EUROPEAN_COUNTRIES,
    SOURCES,
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
    reason = {200: b"OK", 302: b"Found"}[status]
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


def _source(discovery_only=False):
    return DiscoverySource(
        "test-finland",
        "Finnish Official Scholarships",
        "official.example",
        "government_scholarship_programme",
        "Finland",
        "https://official.example/scholarships",
        country="Finland",
        discovery_only=discovery_only,
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

    def test_explicit_european_host_evidence_accepts_international_applicants(self):
        result = self._validate_geographic_candidate(
            "Finland",
            "Master's study takes place at the University of Helsinki in Finland. "
            "Applicants from India and Nigeria may apply.",
        )
        self.assertEqual(result.values["country"], "Finland")
        labelled = self._validate_geographic_candidate("Finland", "Host country: Finland.")
        self.assertEqual(labelled.values["country"], "Finland")

    def test_applicant_country_references_do_not_establish_the_host(self):
        references = (
            "Applicants of Finnish nationality may apply.",
            "The University offers the award to applicants residing in Finland.",
            "Citizens of Finland are eligible for the award.",
            "Finland is mentioned on the scholarship page.",
        )
        for quote in references:
            with self.subTest(quote=quote):
                with self.assertRaises(OutOfScopeScholarship):
                    self._validate_geographic_candidate("Finland", quote)

    def test_multiple_host_countries_are_rejected(self):
        quotes = (
            "Study in France and Germany.",
            "The programme is offered in France or Germany.",
            "Studies take place across France and Germany.",
        )
        for quote in quotes:
            with self.subTest(quote=quote):
                with self.assertRaises(OutOfScopeScholarship):
                    self._validate_geographic_candidate("France", quote)

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

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].values["country"], "Finland")
        self.assertEqual(extractor.last_rejected_count, 2)
        self.assertEqual(
            extractor.last_rejection_reasons,
            ["ScholarshipExtractionError", "ScholarshipExtractionError"],
        )

    def test_non_european_host_is_rejected_despite_european_applicants(self):
        with self.assertRaises(OutOfScopeScholarship):
            self._validate_geographic_candidate(
                "Finland",
                "Study at the University of Toronto in Canada; applicants from Finland may apply.",
            )

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
        with self.assertRaises(OutOfScopeScholarship):
            self._validate_geographic_candidate(
                "Finland",
                "Study in Finland. The programme is hosted in Sweden.",
            )

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

    def test_extraction_rejects_external_and_deceptive_evidence_urls_with_safe_reason(self):
        source = _source()
        invalid_urls = (
            "https://attacker.com/scholarships/apply",
            "https://official.example.attacker.com/scholarships/apply",
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
            with self.assertRaises(DiscoveryFetchError):
                fetcher.crawl(_source())

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
        with self.assertRaisesRegex(DiscoveryFetchError, "safe public addresses"):
            timeout_fetcher._request(_source(), _source().source_url)
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

    def _run(self):
        return run_discovery(
            self.db,
            settings=_settings(),
            sources=(_source(),),
            fetcher=self.fetcher,
            extractor=self.extractor,
        )

    def test_new_records_are_unverified_audited_and_not_embedded(self):
        result = self._run()
        scholarship = self.db.query(Scholarship).one()
        audit = self.db.query(ScholarshipAuditLog).one()
        self.assertEqual(result["summary"]["new_records_created"], 1)
        self.assertEqual((scholarship.verification_status, scholarship.verification_basis),
                         ("unverified", "not_verified"))
        self.assertEqual((scholarship.record_version, scholarship.structured_data_version), (1, 1))
        self.assertEqual(audit.actor_email, "system:scholarship-discovery")
        self.assertIsNone(audit.actor_id)
        self.assertEqual(self.db.query(ScholarshipSourceDocument).count(), 1)
        self.assertEqual(self.db.query(ScholarshipDocumentVersion).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDocumentChunk).count(), 0)
        self.assertEqual(self.db.query(ScholarshipChunkEmbedding).count(), 0)
        self.assertEqual(self.db.query(ScholarshipDiscoveryRun).one().status, "completed")

    def test_discovery_only_source_skips_crawl_and_extraction(self):
        source = _source(discovery_only=True)
        result = run_discovery(
            self.db,
            settings=_settings(),
            sources=(source,),
            fetcher=self.fetcher,
            extractor=self.extractor,
        )

        self.fetcher.crawl.assert_not_called()
        self.extractor.extract.assert_not_called()
        self.assertEqual(result["summary"]["sources_skipped"], 1)
        self.assertEqual(result["summary"]["sources_successfully_fetched"], 0)
        self.assertEqual(result["sources"][0]["status"], "skipped")
        self.assertEqual(result["sources"][0]["pages_fetched"], 0)

    def test_normal_source_still_crawls_and_processes_candidates(self):
        result = self._run()

        self.fetcher.crawl.assert_called_once_with(_source())
        self.extractor.extract.assert_called_once_with(self.page, _source())
        self.assertEqual(result["summary"]["sources_successfully_fetched"], 1)
        self.assertEqual(result["summary"]["new_records_created"], 1)

    def test_verification_wait_count_is_per_source_not_per_candidate(self):
        self.extractor.extract.return_value = [
            _candidate(page=self.page),
            _candidate(page=self.page, name="Finland Regional Award"),
        ]
        result = self._run()
        self.assertEqual(result["summary"]["new_records_created"], 2)
        self.assertEqual(result["summary"]["sources_waiting_for_scholarship_verification"], 1)

    def test_register_evidence_rechecks_urls_before_creating_source_documents(self):
        self._run()
        scholarship = self.db.query(Scholarship).one()
        values = {
            "official_application_url": "https://portal.official.example/apply",
            "additional_source_urls": [
                "../more",
                "https://official.example.attacker.com/scholarships/fake",
                "https://attacker.com/scholarships/fake",
            ],
        }

        with self.assertLogs("app.services.scholarship_discovery", level="WARNING") as logs:
            _register_evidence(self.db, scholarship, _source(), values, self.page)
        self.db.commit()

        normalized_urls = {
            item.normalized_url for item in self.db.query(ScholarshipSourceDocument).all()
        }
        self.assertIn("https://portal.official.example/apply", normalized_urls)
        self.assertIn("https://official.example/more", normalized_urls)
        self.assertNotIn(
            "https://official.example.attacker.com/scholarships/fake",
            normalized_urls,
        )
        self.assertNotIn("https://attacker.com/scholarships/fake", normalized_urls)
        self.assertEqual(logs.output.count(
            "WARNING:app.services.scholarship_discovery:Scholarship evidence URL rejected for "
            "test-finland: invalid_registered_domain"
        ), 2)

    def test_verified_record_gets_pending_immutable_version_but_no_embedding(self):
        self._run()
        scholarship = self.db.query(Scholarship).one()
        scholarship.verification_status = "verified"
        scholarship.verification_basis = "official_source"
        scholarship.official_info_url = self.page.url
        scholarship.last_verified_date = date.today()
        self.db.commit()

        result = self._run()
        version = self.db.query(ScholarshipDocumentVersion).one()
        self.assertEqual(result["summary"]["rag_source_versions_prepared_pending"], 1)
        self.assertEqual(result["summary"]["documents_awaiting_admin_review"], 1)
        self.assertEqual(version.review_status, "pending")
        self.assertEqual(version.indexing_status, "pending")
        self.assertEqual(version.verification_status_snapshot, "verified")
        self.assertEqual(version.scholarship_record_version_snapshot, scholarship.record_version)
        self.assertEqual(self.db.query(ScholarshipChunkEmbedding).count(), 0)

        with patch.dict("os.environ", {"MINILM_MODEL_REVISION": "0123456789abcdef0123456789abcdef01234567"}):
            with patch.object(rag_service, "embed_query", return_value=[0.1] * 384):
                self.assertEqual(rag_service.retrieve(self.db, "question").status, rag_service.STATUS_NO_SOURCES)

    def test_pending_version_is_not_counted_as_new_on_later_runs(self):
        self._run()
        scholarship = self.db.query(Scholarship).one()
        scholarship.verification_status = "verified"
        scholarship.verification_basis = "official_source"
        scholarship.official_info_url = self.page.url
        scholarship.last_verified_date = date.today()
        self.db.commit()
        self._run()

        result = self._run()
        self.assertEqual(result["summary"]["rag_source_versions_prepared_pending"], 0)
        self.assertEqual(result["summary"]["documents_awaiting_admin_review"], 1)
        self.assertEqual(self.db.query(ScholarshipDocumentVersion).count(), 1)

    def test_failed_source_keeps_last_success_timestamp_and_records_failure(self):
        successful = self._run()
        last_success = successful["sources"][0]["last_success_at"]
        self.fetcher.crawl.side_effect = DiscoveryFetchError("sensitive source detail")

        failed = self._run()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["summary"]["sources_failed"], 1)
        self.assertEqual(failed["sources"][0]["error"], "DiscoveryFetchError")
        self.assertEqual(failed["sources"][0]["last_success_at"], last_success)
        self.assertNotIn("sensitive source detail", str(failed))

    def test_conflicting_existing_values_are_proposed_not_overwritten(self):
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
        self.extractor.extract.return_value = [
            _candidate(page=self.page, living_stipend="New extracted amount"),
        ]
        result = self._run()

        self.db.refresh(item)
        audit = self.db.query(ScholarshipAuditLog).one()
        self.assertEqual(item.living_stipend, "Existing reviewed amount")
        self.assertIn("conflicting_information", item.data_flags)
        self.assertEqual(item.record_version, 5)
        self.assertEqual(result["summary"]["existing_records_flagged_for_review"], 1)
        self.assertEqual(audit.action, "discovery_proposal")
        self.assertIn("proposed_values", audit.changes)
        self.assertEqual(audit.actor_email, "system:scholarship-discovery")

    def test_same_identity_is_skipped_without_creating_another_scholarship(self):
        self._run()
        result = self._run()
        self.assertEqual(self.db.query(Scholarship).count(), 1)
        self.assertEqual(result["summary"]["duplicates_skipped"], 1)

    def test_discovery_table_is_not_created_by_application_startup(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        create_application_schema(bind=engine)
        self.assertNotIn("scholarship_discovery_runs", inspect(engine).get_table_names())

    def test_settings_validate_ranges_and_default_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = scholarship_discovery_settings()
        self.assertFalse(settings.enabled)
        with patch.dict("os.environ", {"SCHOLARSHIP_DISCOVERY_MAX_PAGES_PER_SOURCE": "0"}):
            with self.assertRaisesRegex(RuntimeError, "between"):
                scholarship_discovery_settings()


if __name__ == "__main__":
    unittest.main()
