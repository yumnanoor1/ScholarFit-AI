"""
Scholarship eligibility for one student, using only what the scholarship record states.

Each original requirement column is free text, so each check reads a narrow, explicit pattern and
otherwise returns NOT_EVALUATED with the original text kept for the student. Nothing missing is
treated as met, and a keyword match is never treated as proof.

Records with structured fields are checked against those fields AND the original text. The text is
never skipped: when the two give opposite answers the requirement becomes not_evaluated with
conflict=True, so a structured value can't overrule a stated restriction. NULL means the record
doesn't say, never "unrestricted". Grades are only compared on the same scale; no conversion is assumed.

Requirement statuses
  satisfied            the record states a rule and the profile meets it
  not_satisfied        the record states a rule and the profile does not meet it
  missing_information  the record states a checkable rule but the profile lacks the data
  not_evaluated        the rule can't be checked automatically; verify it manually

Requirements whose text defers to the host university ("per the chosen programme's requirement")
are reported as not_evaluated with scope "admission": they are checked when the student applies
for the program, so they don't block the scholarship result. Every other not_evaluated requirement
has scope "scholarship" and does block "eligible".

Conditions the profile doesn't record (second Master's, other funding, residency, gender) are often
stated only in the notes or inside a requirement. check_stated_restrictions reports those sentences
as one not_evaluated requirement, so such a record can't reach "eligible". Finding one never makes a
student not_eligible: the rule may simply not apply to them.

Overall status
  not_evaluated        the scholarship record is not verified (its requirements are still shown)
  not_eligible         any requirement is not_satisfied
  missing_information  otherwise, any requirement is missing_information
  eligible             otherwise, nationality AND degree level were checked and satisfied, and no
                       scholarship-scope requirement is not_evaluated
  not_evaluated        anything else (too little could be checked automatically)

outcome is the three-way result for students: eligible, not_eligible, or verify_manually (which
covers missing_information and not_evaluated; status keeps the two apart so profile gaps stay fixable).

"eligible" means the student meets the requirements the record states. It is not selection,
and it does not guarantee funding. The deadline is reported separately and never changes the status.
"""
import re
from datetime import date
from typing import Optional

from app.services.eligibility_engine import _degree_rank
from app.services.source_verification import STALE_AFTER_DAYS, scholarship_source_issue

SATISFIED = "satisfied"
NOT_SATISFIED = "not_satisfied"
MISSING = "missing_information"
NOT_EVALUATED = "not_evaluated"

ELIGIBLE = "eligible"
NOT_ELIGIBLE = "not_eligible"
VERIFY_MANUALLY = "verify_manually"
VERIFICATION_MAX_AGE_DAYS = STALE_AFTER_DAYS

EU_EEA = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech republic", "czechia", "denmark", "estonia",
    "finland", "france", "germany", "greece", "hungary", "ireland", "italy", "latvia", "lithuania",
    "luxembourg", "malta", "netherlands", "poland", "portugal", "romania", "slovakia", "slovenia", "spain",
    "sweden", "iceland", "liechtenstein", "norway",
}
SWISS = {"switzerland"}
EEA_NOT_EU = {"iceland", "liechtenstein", "norway"}
REGIONS = {"EU": EU_EEA - EEA_NOT_EU, "EEA": EU_EEA, "EFTA": EEA_NOT_EU | SWISS}

# Restriction tags in the student's words. The profile can't confirm any of them, so each needs a manual check.
RESTRICTION_LABELS = {
    "former_citizenship_excluded": "former citizens are excluded",
    "dual_citizenship_excluded": "dual citizens are excluded",
    "first_time_applicant": "first-time applicants only",
    "second_masters_excluded": "not for a second Master's",
    "previous_scholarship_excluded": "earlier holders of this or a similar scholarship may be excluded",
    "high_income_study_excluded": "earlier study or work in a high-income country is excluded",
    "other_funding_excluded": "can't be combined with some other funding",
    "employee_excluded": "staff of the provider are excluded",
    "financial_need_required": "financial need must be shown",
    "eu_tax_household_excluded": "households filing taxes in the EU are excluded",
    "residency_required": "residency conditions apply",
    "participating_institution_only": "only at participating institutions",
    "enrolled_student_required": "you must be enrolled or about to enrol",
    "fee_paying_only": "only for students who pay tuition fees",
    "first_year_only": "first-year students only",
    "early_application_only": "only for early applicants",
    "admission_test_required": "an admission test is required",
    "minimum_work_experience": "work experience is required",
}
# These describe the award rather than who may hold it, so they are shown but don't block a result
AWARD_NOTES = {
    "nationality_cap": "The number of holders of one nationality is capped, which affects selection rather than eligibility.",
    "return_home_required": "Holders are expected to return home after the award.",
}

# Other names a country appears under in exclusion text ("except French nationals", "Türkiye")
COUNTRY_ALIASES = {
    "turkey": ["turkey", "türkiye", "turkiye", "turkish"],
    "france": ["france", "french"],
    "australia": ["australia", "australian"],
    "new zealand": ["new zealand"],
    "united kingdom": ["united kingdom", "uk", "british"],
    "germany": ["germany", "german"],
    "netherlands": ["netherlands", "dutch"],
    "suriname": ["suriname", "surinamese"],
    "switzerland": ["switzerland", "swiss"],
}
COUNTRY_CANONICAL = {"türkiye": "turkey", "turkiye": "turkey", "czechia": "czech republic", "uk": "united kingdom",
                     "great britain": "united kingdom", "the netherlands": "netherlands", "holland": "netherlands"}

# Text that says the rule is set by the university / programme the student applies to
DEFERS_TO_ADMISSION = re.compile(
    r"\b(per (the )?(chosen|specific|standard|respective|individual)|set (individually )?by (the|each)|"
    r"must meet the (\w+ )*(entry |admission |english )?(language )?requirement|as specified by|"
    r"determined by the|set by the (individual|specific|host)|host (uk )?university sets|"
    r"set individually|not fixed centrally|university partner sets|own (english |admission )?requirement)",
    re.I,
)
HEDGED = re.compile(r"\b(typically|commonly|indicative|approx|approximately|secondary source|some institution|"
                    r"not verified|may|varies)\b", re.I)
NOT_STATED = re.compile(r"^\s*(not specified|not stated|no age limit|none stated|n/a)", re.I)
NO_REQUIREMENT = re.compile(r"^\s*(no\b|not required)", re.I)

# Words that limit an "all fields" / "any field" statement
FIELD_LIMIT = re.compile(r"\b(exclu\w+|exceptions?|except|subject to|only|limited to|restricted to|participating|"
                         r"aligned to|relevant to)\b", re.I)
# A Pakistan "yes" that the record itself says must be confirmed again
RECHECK = re.compile(r"\bre-?(confirm|check)", re.I)
# Conditions on the applicant that sit beside a nationality rule
PERSONAL_CONDITION = re.compile(
    r"\b(women who|first-time|household|permanent residents?|residing|previous \w+ citizens|liable to pay|"
    r"participat\w+)\b", re.I)
# Sentences in the notes that limit who can receive the award. Competitiveness and post-award duties don't count.
STATED_RESTRICTION = re.compile(
    PERSONAL_CONDITION.pattern + r"|"
    r"\bnot (\S+-)?eligible\b|\bnot available\b|\bnot awarded\b|\bnot normally fund\b|\bnot suitable\b|\bnot every\b|"
    r"\bcannot be (combined|applied)\b|\bmust not\b|\bexcludes\b|\bare excluded\b|\bdisqualifies\b|"
    r"(?<!included )\bonly (to|for|open|available|certain|specific)\b|\bopen only\b|\brestricted to\b|"
    r"\bapplicants? must (not|be|have)\b|\bmust be self-funded\b|\bresidency\b|\bmeans test\b|\badditional (eligibility|rules)\b|"
    r"\bown additional rules\b|\b(list|countries)\b[^.]*\b(re-?check|re-?confirm|republished)", re.I)
SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<!max\.)(?<=\.)\s+")
# Türkiye Bursları: "75% (90% for Health Sciences fields: Medicine, Dentistry, Pharmacy)"
HEALTH_TIER = re.compile(r"\d\s*% for health sciences", re.I)
HEALTH_FIELD = re.compile(r"\b(health|medic|mbbs|dent|pharm|nursing)", re.I)

MONTHS ={m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
MONTH_NAMES = "|".join(list(MONTHS) + [m[:3] for m in MONTHS])
FULL_DATE_RE = re.compile(rf"\b(\d{{1,2}})\s+({MONTH_NAMES})\.?,?\s+(\d{{4}})\b", re.I)
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _norm_country(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    name = value.strip().lower()
    return COUNTRY_CANONICAL.get(name, name) or None


def _aliases(country: str):
    return COUNTRY_ALIASES.get(country, [country])


def _mentions(text: str, country: str) -> bool:
    lower = text.lower()
    return any(re.search(rf"\b{re.escape(alias)}\b", lower) for alias in _aliases(country))


def _req(key, label, status, reason, text=None, scope="scholarship", conflict=False):
    return {"requirement": key, "label": label, "status": status, "reason": reason,
            "source_text": text, "scope": scope, "conflict": conflict}


def _strip_brackets(text: str) -> str:
    return re.sub(r"[(][^)]*[)]", " ", text or "")


def _conflict(key, label, detail, text):
    return _req(key, label, NOT_EVALUATED,
                f"This record's details disagree ({detail}), so check the official page.", text, conflict=True)


def _reconcile(key, label, from_text, status, reason):
    """Combines the original text's answer with the structured one. Opposite answers are a conflict;
    a stated "not eligible" outlives an open structured answer; a structured answer settles unreadable text."""
    if from_text is None:
        return _req(key, label, status, reason)
    text = from_text["source_text"]
    firm = (SATISFIED, NOT_SATISFIED)
    if from_text["status"] in firm and status in firm and from_text["status"] != status:
        return _conflict(key, label, "the structured data and the original wording give different answers", text)
    if from_text["status"] == NOT_SATISFIED and status == NOT_EVALUATED:
        return from_text
    return _req(key, label, status, reason, text)


# ---------------------------------------------------------------------------
# Individual checks. Each returns a requirement dict, or None when the record states no rule.
# ---------------------------------------------------------------------------

def _nationality_rule(scholarship, nationality: str, country: str):
    """What the structured nationality fields say: (status, reason)."""
    scope = scholarship.nationality_scope
    excluded_countries = set()
    for item in getattr(scholarship, "excluded_countries", None) or []:
        normalized = _norm_country(item)
        if normalized:
            excluded_countries.add(normalized)
    excluded_regions = getattr(scholarship, "excluded_regions", None) or []
    eligible_countries = set()
    for item in getattr(scholarship, "eligible_countries", None) or []:
        normalized = _norm_country(item)
        if normalized:
            eligible_countries.add(normalized)
    eligible_regions = getattr(scholarship, "eligible_regions", None) or []
    excluded = set(excluded_countries)
    for region in excluded_regions:
        excluded |= REGIONS.get(region.upper(), set())
    listed = set(eligible_countries)
    for region in eligible_regions:
        listed |= REGIONS.get(region.upper(), set())
    if scope == "all":
        if excluded_countries or excluded_regions:
            return NOT_EVALUATED, "The record says all nationalities are eligible but also lists exclusions; verify the conflict."
        return SATISFIED, "Open to all nationalities."
    if scope == "all_except":
        if not excluded and not excluded_regions:
            return NOT_EVALUATED, "The record says exclusions apply but doesn't list any; check the official country rules."
        if any(region.upper() not in REGIONS for region in excluded_regions):
            return NOT_EVALUATED, "The record contains an unsupported excluded region; check the official country rules."
        if country in excluded:
            return NOT_SATISFIED, f"Citizens of {nationality} are excluded."
        return SATISFIED, f"Open to all nationalities except those listed; {nationality} is not excluded."
    if scope == "listed" and not listed and not eligible_regions:
        return NOT_EVALUATED, "The record says eligibility is limited to a list but doesn't include that list."
    if any(region.upper() not in REGIONS for region in eligible_regions):
        return NOT_EVALUATED, "The record contains an unsupported eligible region; check the official country rules."
    if country in excluded:
        return NOT_SATISFIED, f"Citizens of {nationality} are excluded."
    if country in listed:
        return SATISFIED, f"{nationality} is on the record's list of eligible countries."
    if scope == "listed":
        return NOT_SATISFIED, f"{nationality} is not on the record's list of eligible countries."
    return NOT_EVALUATED, "Eligibility depends on a published country list; check it on the official page."


def check_nationality(scholarship, nationality: Optional[str]):
    from_text = _nationality_from_text(scholarship, nationality)
    if not getattr(scholarship, "nationality_scope", None):
        return from_text
    label = "Nationality"
    country = _norm_country(nationality)
    if not country:
        return from_text or _req("nationality", label, MISSING, "Add your country of citizenship to your profile to check this.")
    # The record's own Pakistan column may ask for the list to be confirmed again
    if country == "pakistan" and (scholarship.pakistan_eligible or "").strip() and from_text["status"] == NOT_EVALUATED:
        return from_text
    status, reason = _nationality_rule(scholarship, nationality, country)
    result = _reconcile("nationality", label, from_text, status, reason)
    # "Belarus (democratic forces)": being listed comes with a condition
    wording = scholarship.eligible_nationalities or ""
    if result["status"] == SATISFIED and any(re.search(rf"\b{re.escape(alias)}\s*[(]", wording, re.I) for alias in _aliases(country)):
        return _req("nationality", label, NOT_EVALUATED, f"{nationality} is listed with a condition; check the wording.", wording)
    return result


def _nationality_from_text(scholarship, nationality: Optional[str]):
    label = "Nationality"
    text = scholarship.eligible_nationalities or ""
    pakistan_text = (scholarship.pakistan_eligible or "").strip()
    if not text and not pakistan_text:
        return None
    country = _norm_country(nationality)
    if not country:
        return _req("nationality", label, MISSING, "Add your country of citizenship to your profile to check this.",
                    text or pakistan_text)

    # The dataset records Pakistan eligibility explicitly in its own column
    if country == "pakistan" and pakistan_text:
        if re.match(r"yes\b", pakistan_text, re.I):
            if RECHECK.search(pakistan_text):
                return _req("nationality", label, NOT_EVALUATED,
                            "Pakistan was confirmed for an earlier cycle; check the current official country list.", pakistan_text)
            return _req("nationality", label, SATISFIED, "The record confirms Pakistani citizens are eligible.", pakistan_text)
        if re.match(r"no\b", pakistan_text, re.I):
            return _req("nationality", label, NOT_SATISFIED, "The record says Pakistani citizens are not eligible.", pakistan_text)
        return _req("nationality", label, NOT_EVALUATED,
                    "Pakistan's eligibility is not confirmed in the record; check the official country list.", pakistan_text)

    main = _strip_brackets(text)
    lower = main.lower()
    # "all countries except X, Y" / "any country except X"
    except_match = re.search(r"\b(all|any)\b[^.;]*?\bexcept\b([^.;]*)", lower)
    if except_match:
        excluded = except_match.group(2)
        if _mentions(excluded, country):
            return _req("nationality", label, NOT_SATISFIED, f"Citizens of {nationality} are excluded.", text)
        return _req("nationality", label, SATISFIED, f"Open to all nationalities except those listed; {nationality} is not excluded.", text)
    # "non-EU/EEA", "outside the EEA", optionally Swiss / EFTA too
    if re.search(r"\b(non-?\s?eu|non-?\s?eea|outside the (eu|eea)|non-european union)", lower):
        excluded = set(EU_EEA)
        if re.search(r"swiss|switzerland|efta", lower):
            excluded |= SWISS
        elif "eea" not in lower:   # "non-European Union state" leaves out Norway, Iceland and Liechtenstein
            excluded -= EEA_NOT_EU
        if _mentions(main, "suriname") and country == "suriname":
            return _req("nationality", label, NOT_SATISFIED, "Citizens of Suriname are excluded.", text)
        if country in excluded:
            return _req("nationality", label, NOT_SATISFIED,
                        f"Only for nationalities outside the EU/EEA; {nationality} is excluded.", text)
        return _req("nationality", label, SATISFIED, f"Open to non-EU/EEA nationalities, which includes {nationality}.", text)
    # "any country outside the United Kingdom"
    outside_match = re.search(r"\b(all|any)\b[^.;]*?\boutside\b([^.;]*)", lower)
    if outside_match:
        if _mentions(outside_match.group(2), country):
            return _req("nationality", label, NOT_SATISFIED, f"Citizens of {nationality} are excluded.", text)
        return _req("nationality", label, SATISFIED, f"Open to all nationalities except those listed; {nationality} is not excluded.", text)
    if re.search(r"\b(all|any) (nationalit|countr|international)", lower) and "list" not in lower:
        return _req("nationality", label, SATISFIED, "Open to all nationalities.", text)
    return _req("nationality", label, NOT_EVALUATED,
                "Eligibility depends on a published country list; check it on the official page.", text)


def check_degree_level(scholarship, profile):
    """Check the offered study level against the student's current or completed degree."""
    label = "Degree level"
    target = (getattr(scholarship, "degree_level", None) or "").strip()
    levels = getattr(scholarship, "eligible_degree_levels", None) or []
    target_ranks = {_degree_rank(level) for level in levels}
    target_ranks.discard(None)
    legacy_rank = _degree_rank(target)
    if levels:
        if legacy_rank is not None and target_ranks and legacy_rank not in target_ranks:
            return _conflict("degree_level", label, "the structured degree levels and the original wording differ", target)
        target = target or ", ".join(levels)
    elif legacy_rank is not None:
        target_ranks.add(legacy_rank)
    if not target and not levels:
        return None
    if not target_ranks:
        return _req("degree_level", label, NOT_EVALUATED,
                    f"The scholarship's study level ({target}) can't be mapped to a supported degree level; check it manually.",
                    target or None)

    required_text = (getattr(scholarship, "required_previous_degree", None) or "").strip()
    if not required_text:
        return _req("degree_level", label, NOT_EVALUATED,
                    "The record doesn't state the required previous degree; check the official eligibility rules.", target)
    required_rank = _degree_rank(required_text)
    if required_text and required_rank is None:
        return _req("degree_level", label, NOT_EVALUATED,
                    f"The required previous degree ({required_text}) can't be compared automatically; check it manually.", target)
    current = _degree_rank(profile.degree_level) if profile else None
    if current is None:
        return _req("degree_level", label, MISSING, "Add your current or completed degree to your profile.", target)

    if required_rank is not None:
        if current < required_rank:
            return _req("degree_level", label, NOT_SATISFIED,
                        f"A {required_text} degree is needed to apply; your profile shows {profile.degree_level}.", target)
        return _req("degree_level", label, SATISFIED,
                    f"Your {profile.degree_level} meets the stated previous-degree requirement ({required_text}).", target)

    # Where the record omits a previous-degree rule, compare only the usual
    # adjacent levels supported by the profile; bachelor's-entry requirements
    # can't be checked because the profile does not store secondary education.
    required_ranks = [rank - 1 for rank in target_ranks if rank > 1]
    if required_ranks and current >= min(required_ranks):
        return _req("degree_level", label, SATISFIED,
                    f"Your {profile.degree_level} meets the previous-degree level for at least one offered study level.", target)
    if required_ranks and current < min(required_ranks) and 1 not in target_ranks:
        required_name = {1: "Bachelor's", 2: "Master's"}.get(min(required_ranks))
        return _req("degree_level", label, NOT_SATISFIED,
                    f"A {required_name} degree is needed for the offered study level; your profile shows {profile.degree_level}.", target)
    return _req("degree_level", label, NOT_EVALUATED,
                "The previous-degree requirement for this study level isn't available to check; verify it with the provider.", target)


def check_bachelors_conditions(scholarship):
    """Extra conditions on the Bachelor's degree (relevance, length, class, graduation date)."""
    text = (scholarship.bachelors_requirement or "").strip()
    if not text or NO_REQUIREMENT.match(text) or NOT_STATED.match(text):
        return None
    detail = re.sub(r"^yes(,\s*implicitly)?\s*-?\s*", "", text, flags=re.I).strip()
    generic = re.fullmatch(
        r"(a |the )?(completed |completion of a )?(first university degree|bachelor'?s( degree| programme| or equivalent)?|"
        r"undergraduate degree)?\s*(is |are )?(required|a condition)?( for (admission to )?(the )?master'?s?( admission| study|-level (applicants|award|scholarship))?)?\.?",
        detail, re.I)
    if not detail or generic or re.fullmatch(r"(required for master'?s admission|as above)", detail, re.I):
        return None
    # "relevant bachelor's ... required for admission" is a program admission rule; dates, class or
    # length limits ("completed no earlier than 2024", "2:1") belong to the scholarship itself
    admission = bool(re.search(r"\b(admission|admitted|entry requirement)", text, re.I)) and not re.search(
        r"\d", _strip_brackets(text))
    return _req("bachelors_conditions", "Bachelor's degree conditions", NOT_EVALUATED,
                "The record sets conditions on your Bachelor's degree; check them manually.", text,
                scope="admission" if admission else "scholarship")


def check_field(scholarship, profile):
    label = "Field of study"
    text = (scholarship.eligible_fields or "").strip()
    scope = getattr(scholarship, "discipline_scope", None)
    preferred_fields = [
        item.strip() for item in (getattr(profile, "preferred_fields", None) or [])
        if isinstance(item, str) and item.strip()
    ] if profile else []
    limited = bool(FIELD_LIMIT.search(text))
    if scope == "all" and not limited:
        return _req("field", label, SATISFIED, "Open to all fields of study.", text or None)
    if scope == "not_specified":
        return _req("field", label, NOT_EVALUATED, "The record doesn't say which fields qualify; check the official page.", text or None)
    if scope in ("listed", "restricted"):
        disciplines = getattr(scholarship, "eligible_disciplines", None) or []
        named = ", ".join(disciplines)
        if not preferred_fields:
            return _req("field", label, MISSING, "Add your preferred study field to your profile to check this.", text or named or None)
        # Field names aren't a shared vocabulary, so a field that isn't listed word for word is never a "no"
        match = any(
            listed.strip().lower() == preferred.strip().lower()
            for preferred in preferred_fields for listed in disciplines
            if isinstance(listed, str)
        )
        if scope == "listed" and match and not limited:
            return _req("field", label, SATISFIED,
                        f"{', '.join(preferred_fields)} includes one of the listed fields.", text or named)
        listed = f" Listed: {named}." if named else ""
        return _req("field", label, NOT_EVALUATED,
                    f"Only certain fields or programmes qualify; check whether {', '.join(preferred_fields)} is accepted.{listed}",
                    text or None)
    if not text:
        return None
    if re.match(r"(all|any)\b", text, re.I) and not limited:
        return _req("field", label, SATISFIED, "Open to all fields of study.", text)
    hint = f" Your preferred fields are {', '.join(preferred_fields)}." if preferred_fields else ""
    return _req("field", label, NOT_EVALUATED,
                f"Only certain fields or programmes qualify; check the list.{hint}", text)


def _stated_minimum(main: str):
    """Return a stated minimum and its explicit scale; never infer grade equivalence."""
    fraction = [
        (float(value), float(scale))
        for value, scale in re.findall(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", main)
        if float(scale) > 0
    ]
    percent = re.search(r"(\d{2,3})\s*%", main)
    cgpa = re.search(r"\b(?:cgpa|gpa)\b[^\d]{0,15}(\d(?:\.\d+)?)", main, re.I)
    if fraction:
        scales = {scale for _, scale in fraction}
        if len(scales) != 1:
            return None, None, None
        scale = next(iter(scales))
        value = min(value for value, _ in fraction)
        return value, scale, f"{value:g}/{scale:g}"
    if percent and re.search(r"(achievement|average|grade|marks)", main, re.I):
        value = float(percent.group(1))
        if value <= 100:
            return value, 100.0, f"{value:g}%"
    if cgpa:
        value = float(cgpa.group(1))
        following = main[cgpa.end():cgpa.end() + 40]
        scale_match = re.match(r"\s*(?:out of|on a (?:scale of )?)\s*(\d+(?:\.\d+)?)", following, re.I)
        if scale_match and float(scale_match.group(1)) > 0:
            scale = float(scale_match.group(1))
            return value, scale, f"{value:g}/{scale:g}"
        return value, None, f"{value:g} (scale not stated)"
    return None, None, None


def _numeric_academic(scholarship, profile, text):
    """A structured minimum. The student's grade is only compared on the scale the minimum uses."""
    label = "Academic record"
    value = getattr(scholarship, "min_gpa", None)
    percentage = getattr(scholarship, "min_percentage", None)
    if value is not None:
        scale = getattr(scholarship, "min_gpa_scale", None)
        if not scale or scale <= 0:
            return _req("academic", label, NOT_EVALUATED,
                        f"The minimum of {value:g} has no grading scale on record; check it manually.", text)
        minimum, shown = value, f"{value:g}/{scale:g}"
    elif percentage is not None:
        scale, minimum, shown = 100.0, percentage, f"{percentage:g}%"
    else:
        return _req("academic", label, NOT_EVALUATED, "The record gives no minimum to compare; check it manually.", text)

    if text:
        stated, stated_scale, _ = _stated_minimum(_strip_brackets(text))
        if (HEDGED.search(_strip_brackets(text)) or stated is None or stated_scale is None
                or abs(stated_scale - scale) > 1e-9 or abs(stated - minimum) > 1e-6):
            return _conflict("academic", label, f"the structured minimum is {shown}", text)
    profile_scale = getattr(profile, "cgpa_scale", None) if profile else None
    if not profile or profile.cgpa is None or profile_scale is None or profile_scale <= 0:
        return _req("academic", label, MISSING, f"Add your CGPA and grading scale to your profile (minimum stated: {shown}).", text)
    yours = f"{profile.cgpa:g}/{profile.cgpa_scale:g}"
    if abs(profile.cgpa_scale - scale) > 1e-9:
        return _req("academic", label, NOT_EVALUATED,
                    f"Your CGPA {yours} and the minimum of {shown} use different scales, and there's no fixed conversion. "
                    "Check how the scholarship converts grades.", text)
    if profile.cgpa + 1e-9 < minimum:
        return _req("academic", label, NOT_SATISFIED, f"Your CGPA {yours} is below the stated minimum of {shown}.", text)
    target_fields = _preferred_profile_fields(profile)
    if HEALTH_TIER.search(text or "") and (
        not target_fields or any(HEALTH_FIELD.search(field) for field in target_fields)
    ):
        return _req("academic", label, NOT_EVALUATED,
                    f"Your CGPA {yours} meets {shown}, but a higher minimum applies to Health Sciences; check which applies.", text)
    return _req("academic", label, SATISFIED, f"Your CGPA {yours} meets the stated minimum of {shown}.", text)


def check_academic(scholarship, profile):
    condition = getattr(scholarship, "academic_condition", None)
    text = (scholarship.min_academic_requirement or "").strip()
    if condition == "numeric":
        return _numeric_academic(scholarship, profile, text or None)
    from_text = _academic_from_text(scholarship, profile)
    if not condition or (from_text and from_text["status"] == NOT_EVALUATED):
        return from_text
    label = "Academic record"
    if condition == "not_specified":
        return _req("academic", label, NOT_EVALUATED, "The record doesn't state an academic minimum, so check the official page.", text or None)
    if condition == "set_by_institution":
        return _req("academic", label, NOT_EVALUATED, "Set by the university you apply to; check its requirement.", text or None)
    # Merit, rank or class: a number in the wording has no stated scale, so it isn't compared
    return _req("academic", label, NOT_EVALUATED,
                "The grade requirement isn't a fixed number on a stated scale (e.g. rank or class); check it manually.", text or None)


def _academic_from_text(scholarship, profile):
    label = "Academic record"
    text = (scholarship.min_academic_requirement or "").strip()
    if not text or NOT_STATED.match(text):
        return None
    if DEFERS_TO_ADMISSION.search(text) and not re.search(r"\d", _strip_brackets(text)):
        return _req("academic", label, NOT_EVALUATED, "Set by the university you apply to; checked during admission.",
                    text, scope="admission")
    main = _strip_brackets(text)
    if HEDGED.search(main):
        return _req("academic", label, NOT_EVALUATED, "The stated grade requirement is approximate; check it manually.", text)

    minimum, scale, shown = _stated_minimum(main)
    if minimum is None:
        return _req("academic", label, NOT_EVALUATED,
                    "The grade requirement isn't a fixed number (e.g. rank or class); check it manually.", text)

    if scale is None:
        return _req("academic", label, NOT_EVALUATED,
                    f"The minimum ({shown}) has no stated grading scale; check it manually.", text)
    profile_scale = getattr(profile, "cgpa_scale", None) if profile else None
    if not profile or profile.cgpa is None or profile_scale is None or profile_scale <= 0:
        return _req("academic", label, MISSING,
                    f"Add your CGPA and grading scale to your profile (minimum stated: {shown}).", text)
    yours = f"{profile.cgpa:g}/{profile.cgpa_scale:g}"
    if abs(profile_scale - scale) > 1e-9:
        return _req("academic", label, NOT_EVALUATED,
                    f"Your CGPA {yours} and the minimum of {shown} use different scales, and there's no fixed conversion. "
                    "Check how the scholarship converts grades.", text)
    target_fields = _preferred_profile_fields(profile)
    if profile.cgpa + 1e-9 >= minimum:
        if HEALTH_TIER.search(text) and (
            not target_fields or any(HEALTH_FIELD.search(field) for field in target_fields)
        ):
            return _req("academic", label, NOT_EVALUATED,
                        f"Your CGPA {yours} meets {shown}, but a higher minimum applies to Health Sciences; check which applies.", text)
        return _req("academic", label, SATISFIED, f"Your CGPA {yours} meets the stated minimum of {shown}.", text)
    return _req("academic", label, NOT_SATISFIED, f"Your CGPA {yours} is below the stated minimum of {shown}.", text)


def _preferred_profile_fields(profile):
    return [
        item.strip() for item in (getattr(profile, "preferred_fields", None) or [])
        if isinstance(item, str) and item.strip()
    ] if profile else []


def _english_test_rule(scholarship, profile, text):
    """english_requirement_type "test_required": compares the scores the profile holds with stated minimums."""
    label = "English language"
    scores = [("IELTS", getattr(profile, "ielts_score", None), getattr(scholarship, "min_ielts", None)),
              ("TOEFL", getattr(profile, "toefl_score", None), getattr(scholarship, "min_toefl", None)),
              ("Duolingo English Test", None, getattr(scholarship, "min_duolingo", None))]
    language_test = getattr(profile, "language_test", None) or {}
    if isinstance(language_test, dict):
        test_type = language_test.get("test_type")
        overall_score = language_test.get("overall_score")
        if test_type and test_type != "No Test / Not Taken" and overall_score is not None:
            name = ("TOEFL" if test_type == "TOEFL iBT" else
                    "Duolingo English Test" if "duolingo" in test_type.lower() else test_type)
            matching_score = next((index for index, item in enumerate(scores) if item[0].lower() == name.lower()), None)
            if matching_score is not None:
                scores[matching_score] = (name, overall_score, scores[matching_score][2])
            else:
                minimum = (
                    getattr(scholarship, "min_ielts", None) if name == "IELTS"
                    else getattr(scholarship, "min_toefl", None) if name == "TOEFL"
                    else getattr(scholarship, "min_duolingo", None) if name == "Duolingo English Test"
                    else None
                )
                scores.append((name, overall_score, minimum))
    held = [item for item in scores if item[1] is not None]
    accepted = [name.lower() for name in getattr(scholarship, "accepted_english_tests", None) or []]
    usable = [item for item in held if not accepted or any(item[0].lower() in name for name in accepted)]
    ambiguous_toefl = [item for item in usable if item[0] == "TOEFL" and item[1] <= 6]
    comparable = [item for item in usable if item[2] is not None and item not in ambiguous_toefl]
    moi_recorded = isinstance(language_test, dict) and str(language_test.get("medium_of_instruction", "")).strip().lower() in {
        "yes", "true", "1",
    }
    moi_mentioned = bool(re.search(r"\b(moi|medium of instruction)\b", text or "", re.I))
    if not held:
        if moi_recorded and moi_mentioned:
            return _req("english", label, NOT_EVALUATED,
                        "Your profile indicates medium of instruction may apply, but an official exemption needs confirmation; it is not treated as a waiver.",
                        text)
        minimums = [f"{name} {minimum:g}" for name, _, minimum in scores if minimum is not None]
        needed = f" ({' or '.join(minimums)} required)" if minimums else ""
        return _req("english", label, MISSING, f"Add an English test score to your profile{needed}.", text)
    if not comparable:
        if ambiguous_toefl:
            return _req("english", label, NOT_EVALUATED,
                        "Your TOEFL score may use the 1-6 scale, while the scholarship minimum has no recorded scale; check the official requirement.",
                        text)
        return _req("english", label, NOT_EVALUATED,
                    "A test is required, but the record has no minimum for the test in your profile; check the official page.", text)
    passed = next((item for item in comparable if item[1] >= item[2]), None)
    if passed:
        name, score, minimum = passed
        if re.search(r"\b(band|section|listening|reading|writing|speaking)\b", text or "", re.I):
            return _req("english", label, NOT_EVALUATED,
                        f"Your {name} {score:g} meets the overall minimum of {minimum:g}, but section scores may also count; check them.", text)
        return _req("english", label, SATISFIED, f"Your {name} {score:g} meets the minimum of {minimum:g}.", text)
    name, score, minimum = comparable[0]
    if (len(comparable) < len(held) or ambiguous_toefl or moi_recorded and moi_mentioned
            or re.search(r"\b(exempt|waiv)", text or "", re.I)):
        return _req("english", label, NOT_EVALUATED,
                    f"Your {name} {score:g} is below {minimum:g}, but another test or an exemption may count; check the official page.", text)
    return _req("english", label, NOT_SATISFIED, f"Your {name} {score:g} is below the minimum of {minimum:g}.", text)


def check_english(scholarship, profile):
    kind = getattr(scholarship, "english_requirement_type", None)
    from_text = _english_from_text(scholarship, profile)
    if not kind:
        return from_text
    label = "English language"
    text = (scholarship.english_requirement or "").strip() or None
    stated = re.search(r"\bIELTS\b[^\d]{0,20}(\d(?:\.\d)?)", _strip_brackets(text or ""), re.I)
    min_ielts = getattr(scholarship, "min_ielts", None)
    if stated and (min_ielts is None or float(stated.group(1)) != min_ielts):
        return _conflict("english", label, "the structured minimum doesn't match the stated IELTS score", text)
    if min_ielts is not None and text and not stated:
        return _conflict("english", label, f"the structured minimum is IELTS {min_ielts:g}, which the wording doesn't state", text)
    if kind == "test_required":
        return _english_test_rule(scholarship, profile, text)
    if kind == "not_required":
        if from_text:
            return _conflict("english", label, "the structured data says no test is needed, but the wording states a requirement", text)
        return None
    if kind == "not_specified":
        return _req("english", label, NOT_EVALUATED,
                    "The record doesn't state an English requirement. That doesn't mean no test is needed, so check the official page.", text)
    return from_text or _req("english", label, NOT_EVALUATED, "Set by the university you apply to; checked during admission.",
                             text, scope="admission")


def _english_from_text(scholarship, profile):
    label = "English language"
    text = (scholarship.english_requirement or "").strip()
    if not text or NOT_STATED.match(text) or NO_REQUIREMENT.match(text):
        return None
    main = _strip_brackets(text)
    language_test = getattr(profile, "language_test", None) or {}
    nested_type = language_test.get("test_type") if isinstance(language_test, dict) else None
    nested_score = language_test.get("overall_score") if isinstance(language_test, dict) else None
    ielts_score = getattr(profile, "ielts_score", None)
    toefl_score = getattr(profile, "toefl_score", None)
    if nested_score is not None:
        if nested_type == "IELTS" and ielts_score is None:
            ielts_score = nested_score
        elif nested_type == "TOEFL iBT" and toefl_score is None:
            toefl_score = nested_score
    ielts = re.search(r"\bIELTS\b[^\d]{0,20}(\d(?:\.\d)?)", main, re.I)
    if ielts:
        minimum = float(ielts.group(1))
        if ielts_score is not None:
            if ielts_score >= minimum:
                return _req("english", label, SATISFIED, f"Your IELTS {ielts_score:g} meets the minimum of {minimum:g}.", text)
            return _req("english", label, NOT_SATISFIED, f"Your IELTS {ielts_score:g} is below the minimum of {minimum:g}.", text)
        if toefl_score is not None:
            return _req("english", label, NOT_EVALUATED,
                        f"The record gives IELTS {minimum:g} or an equivalent; compare your TOEFL score on the official page.", text)
        if nested_score is not None and nested_type not in (None, "No Test / Not Taken"):
            return _req("english", label, NOT_EVALUATED,
                        f"Your {nested_type} score cannot be compared directly with IELTS {minimum:g}; check the official equivalency.", text)
        return _req("english", label, MISSING, f"Add an English test score to your profile (IELTS {minimum:g} required).", text)
    if DEFERS_TO_ADMISSION.search(text) or re.match(r"yes\b", text, re.I) or re.search(r"required", text, re.I):
        return _req("english", label, NOT_EVALUATED, "Set by the university you apply to; checked during admission.",
                    text, scope="admission")
    return _req("english", label, NOT_EVALUATED, "The English requirement can't be checked automatically.", text,
                scope="admission")


def _age_on(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def _stated_age_rule(main: str):
    if m := re.search(r"\bunder (\d{2})\b", main, re.I):
        return "max_exclusive", int(m.group(1)), f"under {m.group(1)}"
    if m := re.search(r"\b(?:up to|not more than|no more than|maximum(?: age)?(?: of)?) (\d{2})\b", main, re.I):
        return "max", int(m.group(1)), f"{m.group(1)} or younger"
    if m := re.search(r"\b(\d{2}) (?:years )?(?:or older|and over)\b", main, re.I):
        return "min", int(m.group(1)), f"{m.group(1)} or older"
    return None


def check_age(scholarship, profile, today: date):
    label = "Age"
    from_text = _age_from_text(scholarship, profile, today)
    if not getattr(scholarship, "structured_data_version", None):
        return from_text
    min_age = getattr(scholarship, "min_age", None)
    max_age = getattr(scholarship, "max_age", None)
    text = (scholarship.age_requirement or "").strip() or None
    if from_text and from_text["status"] == NOT_EVALUATED:
        return from_text
    if from_text:
        kind, limit, _ = _stated_age_rule(_strip_brackets(text))
        stated = (limit, None) if kind == "min" else (None, limit - 1 if kind == "max_exclusive" else limit)
        if stated != (min_age, max_age):
            return _conflict("age", label, "the structured age limit doesn't match the original wording", text)
        return from_text
    if min_age is None and max_age is None:
        return None
    shown = " and ".join(filter(None, [f"{min_age} or older" if min_age is not None else None,
                                       f"{max_age} or younger" if max_age is not None else None]))
    if not profile or not profile.date_of_birth:
        return _req("age", label, MISSING, f"Add your date of birth to your profile (applicants must be {shown}).", text)
    age = _age_on(profile.date_of_birth, today)
    ok = (min_age is None or age >= min_age) and (max_age is None or age <= max_age)
    note = " Checked against today's date; the scholarship may use the application deadline."
    return _req("age", label, SATISFIED if ok else NOT_SATISFIED, f"You are {age}; applicants must be {shown}.{note}", text)


def _age_from_text(scholarship, profile, today: date):
    label = "Age"
    text = (scholarship.age_requirement or "").strip()
    if not text or NOT_STATED.match(text) or NO_REQUIREMENT.match(text):
        return None
    main = _strip_brackets(text)
    if re.search(r"only bachelor'?s|not specified for master", main, re.I):
        return None
    rule = _stated_age_rule(main)
    if rule is None:
        return _req("age", label, NOT_EVALUATED, "An age rule applies but isn't stated precisely; check the call.", text)
    if not profile or not profile.date_of_birth:
        return _req("age", label, MISSING, f"Add your date of birth to your profile (applicants must be {rule[2]}).", text)
    age = _age_on(profile.date_of_birth, today)
    kind, limit, shown = rule
    ok = age < limit if kind == "max_exclusive" else age <= limit if kind == "max" else age >= limit
    note = " Checked against today's date; the scholarship may use the application deadline."
    if ok:
        return _req("age", label, SATISFIED, f"You are {age}; applicants must be {shown}.{note}", text)
    return _req("age", label, NOT_SATISFIED, f"You are {age}; applicants must be {shown}.{note}", text)


def check_work_experience(scholarship):
    text = (scholarship.work_experience or "").strip()
    if not text or NOT_STATED.match(text) or NO_REQUIREMENT.match(text) or re.search(r"not (specified|required|a general)", text, re.I):
        return None
    return _req("work_experience", "Work experience", NOT_EVALUATED,
                "Your FitScholars profile doesn't record work experience; check this manually.", text)


def _sentences(text: Optional[str]):
    return [part.strip() for part in SENTENCE_END.split(text or "") if part.strip()]


def check_stated_restrictions(scholarship):
    """Conditions stated in free text that the profile can't confirm, quoted as the record gives them."""
    found = [part for part in _sentences(scholarship.eligible_nationalities) if PERSONAL_CONDITION.search(part)]
    found += [part for part in _sentences(getattr(scholarship, "notes", None)) if STATED_RESTRICTION.search(part)]
    tags = [tag for tag in getattr(scholarship, "applicant_restrictions", None) or [] if tag in RESTRICTION_LABELS
            and not (tag == "residency_required" and getattr(scholarship, "residency_requirement", None))]
    if not found and not tags:
        return None
    reason = "The record states conditions your profile can't confirm; check whether they apply to you."
    if tags:
        reason += " They include: " + "; ".join(RESTRICTION_LABELS[tag] for tag in tags) + "."
    quoted = " ".join(part if part.endswith(".") else f"{part}." for part in found)
    return _req("restrictions", "Other stated conditions", NOT_EVALUATED, reason,
                quoted or scholarship.eligible_nationalities or None)


def check_gender(scholarship):
    if not getattr(scholarship, "gender_restriction", None):
        return None
    return _req("gender", "Gender", NOT_EVALUATED,
                "This scholarship is for women only. Your FitScholars profile doesn't record gender, so confirm this yourself.",
                scholarship.eligible_nationalities)


def check_residency(scholarship):
    text = getattr(scholarship, "residency_requirement", None)
    if not text:
        return None
    return _req("residency", "Residency", NOT_EVALUATED,
                "Your FitScholars profile doesn't record where you live, so check this yourself.", text)


def check_record_review(scholarship):
    """An administrator's open flag holds a firm result back until the record has been reviewed."""
    flags = [flag for flag in getattr(scholarship, "data_flags", None) or []
             if flag == "conflicting_information" or flag.startswith("review:")]
    if not flags:
        return None
    return _req("record_review", "Record under review", NOT_EVALUATED,
                "This record's details are being reviewed, so check them on the official page.", conflict=True)


def check_source_evidence(scholarship, today=None):
    """Only records with current official evidence can produce a firm eligibility result."""
    issue = scholarship_source_issue(scholarship, today)
    if not issue:
        return None
    return _req("source_evidence", "Source of these details", NOT_EVALUATED,
                f"{issue} Confirm the current details on the official page.",
                getattr(scholarship, "official_info_url", None))


# ---------------------------------------------------------------------------
# Deadline
# ---------------------------------------------------------------------------

def deadline_status(text: Optional[str], today: date) -> dict:
    """status: open | closed | no_separate_deadline | unknown. Only dates with a year are used."""
    raw = (text or "").strip()
    result = {"status": "unknown", "date": None, "days_left": None, "text": raw or None}
    if not raw:
        return result
    if re.search(r"no separate (scholarship )?deadline|no separate application|automatically considered", raw, re.I):
        result["status"] = "no_separate_deadline"
        return result
    dates = []
    for day, month, year in FULL_DATE_RE.findall(raw):
        number = MONTHS.get(month.lower()) or MONTHS.get(next((m for m in MONTHS if m.startswith(month.lower()[:3])), ""), None)
        try:
            dates.append(date(int(year), number, int(day)))
        except (TypeError, ValueError):
            continue
    for year, month, day in ISO_DATE_RE.findall(raw):
        try:
            dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if not dates:
        return result
    upcoming = sorted(d for d in dates if d >= today)
    if upcoming:
        result.update(status="open", date=upcoming[0].isoformat(), days_left=(upcoming[0] - today).days)
    else:
        result.update(status="closed", date=max(dates).isoformat())
    return result


DEADLINE_MESSAGES = {
    "open": "Applications are open.",
    "closed": "The listed deadline has passed. This doesn't change whether you meet the requirements; check the official page for the next cycle.",
    "upcoming": "Applications haven't opened yet.",
    "rolling": "Applications are accepted on a rolling basis, with no fixed closing date on record.",
    "no_separate_deadline": "There's no separate scholarship deadline; you're considered through your admission application.",
    "unknown": "No exact deadline is on record for this cycle; check the official page.",
}


def scholarship_deadline(scholarship, today: date) -> dict:
    """Uses the structured deadline when the record has one, otherwise reads the text.
    status: open | closed | upcoming | rolling | no_separate_deadline | unknown. Vague text never becomes a date."""
    kind = getattr(scholarship, "deadline_type", None)
    if not kind:
        result = deadline_status(scholarship.deadline, today)
        return {**result, "opens_on": None, "message": DEADLINE_MESSAGES[result["status"]]}
    day = getattr(scholarship, "application_deadline_date", None)
    opens = getattr(scholarship, "application_open_date", None)
    result = {"status": "unknown", "date": None, "days_left": None, "text": (scholarship.deadline or "").strip() or None,
              "opens_on": opens.isoformat() if opens else None}
    if kind == "no_separate_deadline":
        result["status"] = "no_separate_deadline"
    elif kind == "rolling":
        result["status"] = "rolling"
    elif opens and opens > today:
        result.update(status="upcoming", date=day.isoformat() if day else None, days_left=(opens - today).days)
    elif day and day >= today:
        result.update(status="open", date=day.isoformat(), days_left=(day - today).days)
    elif day and deadline_status(scholarship.deadline, today)["status"] != "open":
        result.update(status="closed", date=day.isoformat())
    # A later date in the wording ("8 December 2026 or 6 January 2027") leaves a passed date unknown, not closed
    result["message"] = DEADLINE_MESSAGES[result["status"]]
    return result


# ---------------------------------------------------------------------------
# Overall evaluation
# ---------------------------------------------------------------------------

def evaluate_scholarship(scholarship, profile, today: Optional[date] = None) -> dict:
    today = today or date.today()
    nationality = getattr(profile, "nationality", None) if profile else None
    checks = [
        check_nationality(scholarship, nationality),
        check_degree_level(scholarship, profile),
        check_bachelors_conditions(scholarship),
        check_field(scholarship, profile),
        check_academic(scholarship, profile),
        check_english(scholarship, profile),
        check_age(scholarship, profile, today),
        check_work_experience(scholarship),
        check_gender(scholarship),
        check_residency(scholarship),
        check_stated_restrictions(scholarship),
        check_source_evidence(scholarship, today),
        check_record_review(scholarship),
    ]
    requirements = [item for item in checks if item]
    statuses = {item["requirement"]: item["status"] for item in requirements}
    verified = scholarship.verification_status == "verified" and not any(
        item["requirement"] == "source_evidence" for item in requirements
    )
    blocking_manual = [item for item in requirements if item["status"] == NOT_EVALUATED and item["scope"] == "scholarship"]
    notes = ["Meeting the stated requirements does not mean you will be selected or receive funding."]

    if not verified:
        status = NOT_EVALUATED
        summary = "This scholarship has not been verified using current official evidence, or its evidence needs review, so no result is given."
    elif any(item["status"] == NOT_SATISFIED for item in requirements):
        status = NOT_ELIGIBLE
        summary = "You don't meet at least one stated requirement."
    elif any(item["status"] == MISSING for item in requirements):
        status = MISSING
        summary = "Some information needed for this scholarship is missing from your profile."
    elif statuses.get("nationality") == SATISFIED and statuses.get("degree_level") == SATISFIED and not blocking_manual:
        status = ELIGIBLE
        summary = "You meet the requirements this scholarship states."
        if any(item["scope"] == "admission" for item in requirements):
            notes.append("Some requirements are set by the university you apply to and are checked during admission.")
    else:
        status = NOT_EVALUATED
        summary = ("Some requirements can't be checked automatically; verify them manually."
                   if blocking_manual else "Too few requirements could be checked to give a result.")

    deadline = scholarship_deadline(scholarship, today)
    if deadline["status"] == "closed":
        notes.append("The most recently listed deadline has passed; check the official page for the next cycle. "
                     "This is separate from your eligibility.")
    notes += [AWARD_NOTES[tag] for tag in getattr(scholarship, "applicant_restrictions", None) or [] if tag in AWARD_NOTES]

    return {
        "scholarship_id": scholarship.id,
        "scholarship_name": scholarship.name,
        "provider": scholarship.provider,
        "country": scholarship.country,
        "status": status,
        "outcome": status if status in (ELIGIBLE, NOT_ELIGIBLE) else VERIFY_MANUALLY,
        "eligible": status == ELIGIBLE,
        "summary": summary,
        "satisfied": [item for item in requirements if item["status"] == SATISFIED],
        "not_satisfied": [item for item in requirements if item["status"] == NOT_SATISFIED],
        "missing_information": [item for item in requirements if item["status"] == MISSING],
        "needs_verification": [item for item in requirements if item["status"] == NOT_EVALUATED],
        "deadline": deadline,
        "funding_type": scholarship.funding_type,
        "coverage": {
            "tuition": scholarship.tuition_coverage,
            "living_stipend": scholarship.living_stipend,
            "other_benefits": scholarship.other_benefits,
        },
        "verification_status": scholarship.verification_status,
        "last_verified": scholarship.last_verified,
        "official_url": scholarship.official_url,
        "source_name": scholarship.source_name,
        "match_score": None,
        "notes": notes,
    }
