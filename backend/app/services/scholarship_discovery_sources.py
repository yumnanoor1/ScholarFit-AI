"""Curated official entry points; domains must be reviewed before they are added."""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class DiscoverySource:
    source_id: str
    name: str
    official_domain: str
    category: str
    country_or_region: str
    source_url: str
    country: Optional[str] = None
    discovery_only: bool = False


SOURCES: Tuple[DiscoverySource, ...] = (
    DiscoverySource(
        "erasmus-mundus",
        "Erasmus Mundus Catalogue",
        "eacea.ec.europa.eu",
        "official_european_programme",
        "European Union",
        "https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en",
        discovery_only=True,
    ),
    DiscoverySource(
        "daad",
        "DAAD Scholarship Database",
        "daad.de",
        "national_academic_exchange",
        "Germany",
        "https://www.daad.de/en/studying-in-germany/scholarships/",
        country="Germany",
    ),
    DiscoverySource(
        "stipendium-hungaricum",
        "Stipendium Hungaricum",
        "stipendiumhungaricum.hu",
        "government_scholarship_programme",
        "Hungary",
        "https://stipendiumhungaricum.hu/",
        country="Hungary",
    ),
    DiscoverySource(
        "swedish-institute",
        "Swedish Institute Scholarships",
        "si.se",
        "government_scholarship_provider",
        "Sweden",
        "https://si.se/en/apply/scholarships/",
        country="Sweden",
    ),
    DiscoverySource(
        "government-of-ireland",
        "Government of Ireland International Education Scholarships",
        "hea.ie",
        "government_scholarship_programme",
        "Ireland",
        "https://hea.ie/policy/internationalisation/goi-ies/",
        country="Ireland",
    ),
    DiscoverySource(
        "master-mind",
        "Master Mind Scholarship",
        "studyinflanders.be",
        "regional_ministry_scholarship",
        "Flanders, Belgium",
        "https://www.studyinflanders.be/scholarships/master-mind-scholarships",
        country="Belgium",
    ),
    DiscoverySource(
        "oead-grants",
        "OeAD grants.at",
        "grants.at",
        "public_scholarship_database",
        "Austria",
        "https://grants.at/en/",
        country="Austria",
    ),
    DiscoverySource(
        "nawa-poland",
        "Polish National Agency for Academic Exchange",
        "nawa.gov.pl",
        "national_scholarship_agency",
        "Poland",
        "https://www.nawa.gov.pl/en/students/foreign-students/the-banach-scholarship-programme/about-the-programme",
        country="Poland",
    ),
    DiscoverySource(
        "study-in-italy",
        "Study in Italy",
        "studyinitaly.esteri.it",
        "ministry_scholarship_portal",
        "Italy",
        "https://studyinitaly.esteri.it/",
        country="Italy",
    ),
    DiscoverySource(
        "oxford-clarendon",
        "Clarendon Fund",
        "ox.ac.uk",
        "official_university_scholarship",
        "United Kingdom",
        "https://www.ox.ac.uk/admissions/graduate/fees-and-funding/funding/clarendon",
        country="United Kingdom",
    ),
)

SOURCES_BY_ID = {source.source_id: source for source in SOURCES}

EUROPEAN_COUNTRIES = {
    "Albania": "Albania",
    "Andorra": "Andorra",
    "Austria": "Austria",
    "Belarus": "Belarus",
    "Belgium": "Belgium",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Bulgaria": "Bulgaria",
    "Croatia": "Croatia",
    "Czechia": "Czechia",
    "Czech Republic": "Czechia",
    "Denmark": "Denmark",
    "Estonia": "Estonia",
    "Finland": "Finland",
    "France": "France",
    "Germany": "Germany",
    "Greece": "Greece",
    "Hungary": "Hungary",
    "Iceland": "Iceland",
    "Ireland": "Ireland",
    "Italy": "Italy",
    "Latvia": "Latvia",
    "Liechtenstein": "Liechtenstein",
    "Lithuania": "Lithuania",
    "Luxembourg": "Luxembourg",
    "Malta": "Malta",
    "Moldova": "Moldova",
    "Monaco": "Monaco",
    "Montenegro": "Montenegro",
    "Netherlands": "Netherlands",
    "North Macedonia": "North Macedonia",
    "Norway": "Norway",
    "Poland": "Poland",
    "Portugal": "Portugal",
    "Romania": "Romania",
    "San Marino": "San Marino",
    "Serbia": "Serbia",
    "Slovakia": "Slovakia",
    "Slovenia": "Slovenia",
    "Spain": "Spain",
    "Sweden": "Sweden",
    "Switzerland": "Switzerland",
    "Ukraine": "Ukraine",
    "United Kingdom": "United Kingdom",
    "UK": "United Kingdom",
    "Vatican City": "Vatican City",
}

# Transcontinental cases are accepted only for these specifically European host cities.
TRANS_EUROPEAN_HOST_CITIES = {
    "Kazakhstan": {"oral"},
    "Russia": {"moscow", "saint petersburg", "st petersburg", "kazan"},
    "Turkey": {"edirne", "tekirdag", "kirklareli"},
}

COUNTRIES_REQUIRING_HOST_CITY = {
    "Denmark", "France", "Netherlands", "Norway", "Portugal", "Spain", "United Kingdom",
}

# Ambiguous borders and non-European territories are held for manual geography review.
GEOGRAPHY_REVIEW_TERMS = {
    "abkhazia", "crimea", "donetsk", "luhansk", "nagorno-karabakh", "northern cyprus",
    "south ossetia", "transnistria", "french guiana", "guadeloupe", "martinique",
    "reunion", "réunion", "canary islands", "sint maarten", "aruba", "curaçao", "curacao",
    "greenland",
}
