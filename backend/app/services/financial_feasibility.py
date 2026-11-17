"""
Financial feasibility for one Master's program, with or without a scholarship.

All amounts are converted to one response currency using app.services.exchange_rates.
Nothing missing is ever treated as zero: missing essentials give "insufficient_data",
and missing optional expenses are reported as uncertainties.

Classification (shortfall = remaining cost after confirmed funding - budget):
  insufficient_data  tuition, program duration, living costs or budget is unknown,
                     or one of them cannot be converted to the response currency
  feasible           shortfall <= 0, every expense category has an amount, and none of
                     them is an unconfirmed planning estimate
  partially_feasible shortfall <= 0 but some expenses are unknown or only planning estimates,
                     or the shortfall is at most 20% of the remaining cost
  not_feasible       shortfall is more than 20% of the remaining cost

Cost priority: the student's own figure for this program, then a sourced program_costs record,
then the program's legacy living_cost_usd_per_year. For a published range the upper end is used, so a
result is never better than the source supports. A record can state that another category is already
inside it (e.g. health insurance in a living-cost figure); that category then counts once.

Scholarship benefits are counted only when the scholarship record is verified, applies to the
program's country, and its text states the benefit unambiguously (full / single percentage /
explicit amount in a convertible currency, with a known coverage period). Each benefit is capped
at the cost it pays for, and a package that covers tuition and living together is counted once.
In-kind benefits ("visa costs covered", "return economy ticket") count against the matching expense
when that expense is known; allowances without an amount are listed but not counted.
"""
import re
from datetime import date
from typing import Optional

from app.services.exchange_rates import convert, rates_info
from app.services.source_verification import scholarship_source_issue, source_freshness_issue

NEAR_MISS_SHARE = 0.20

EXPENSE_CATEGORIES = [
    # (request field, label, essential)
    ("living_costs", "Living costs (accommodation and food)", True),
    ("university_fees", "University fees (semester or union fees)", False),
    ("health_insurance", "Health insurance", False),
    ("visa", "Visa and residence permit", False),
    ("travel", "Travel", False),
    ("application_fees", "Application fees", False),
    ("other", "Other fees", False),
]

CURRENCY_TOKENS = {
    "EUR": "EUR", "€": "EUR", "USD": "USD", "US$": "USD", "GBP": "GBP", "£": "GBP", "SEK": "SEK",
    "CHF": "CHF", "AUD": "AUD", "TRY": "TRY", "HUF": "HUF", "PLN": "PLN", "CZK": "CZK",
}
_CUR = r"(EUR|€|US\$|USD|GBP|£|SEK|CHF|AUD|TRY|HUF|PLN|CZK)"
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
AMOUNT_RE = re.compile(rf"{_CUR}\s*\$?\s*{_NUM}|{_NUM}\s*{_CUR}")
RANGE_RE = re.compile(r"\d[\d,]*\s*[-–]\s*\d[\d,]*\s*(?:/|per|a\s)")
PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
HEDGE_RE = re.compile(
    r"\b(approx|approximately|around|commonly|up to|may|might|varies|vary|depending|not guaranteed|"
    r"some scholarships|where offered|tiers?|example|subject to)\b",
    re.I,
)
NOT_OFFERED_RE = re.compile(r"^\s*(no\b|not covered|not specified|n/a|none)|\bNOT covered\b", re.I)
NOT_VERIFIED_RE = re.compile(r"not verified", re.I)
EXTENSION_RE = re.compile(r"\b(extendable|renewable|renewed|can be extended|may increase|conditional)\b", re.I)


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def _parse_amounts(text: str):
    """[(amount, currency, period)] for every explicit money amount in the text."""
    found = []
    # Bracketed detail is a breakdown or side note ("EUR 300 (EUR 150 + EUR 150)", "admin fee of about EUR 170"),
    # not another award amount
    text = re.sub(r"[(][^)]*[)]", " ", text or "")
    for match in AMOUNT_RE.finditer(text):
        token = match.group(1) or match.group(4)
        number = match.group(2) or match.group(3)
        try:
            amount = float(number.replace(",", ""))
        except ValueError:
            continue
        after = text[match.end():match.end() + 30].lower()
        if re.search(r"^\s*(/\s*month|per month|a month|monthly)", after):
            period = "monthly"
        elif re.search(r"^\s*(/\s*year|per year|per academic year|per annum|a year|annual|yearly)", after):
            period = "yearly"
        else:
            period = None
        found.append((amount, CURRENCY_TOKENS[token], period))
    # "monthly stipend of €992": the period word comes before the amount
    lower = text.lower()
    has_month = bool(re.search(r"\bmonth(ly)?\b", lower))
    has_year = bool(re.search(r"\b(year|annum|annual|yearly)\b", lower))
    if has_month != has_year:
        fallback = "monthly" if has_month else "yearly"
        found = [(amount, cur, period or fallback) for amount, cur, period in found]
    return found


def _coverage_months(duration_text: Optional[str], program_months: int):
    """(months the scholarship pays for, note). None when the text gives no usable length."""
    text = (duration_text or "").strip()
    if not text or NOT_VERIFIED_RE.search(text):
        return None, "Scholarship duration is not stated in the record."
    lower = text.lower()
    if re.search(r"first year only|one-time", lower):
        return min(12, program_months), "Paid for the first year only."
    note = "Only the guaranteed period is counted; extensions are not." if EXTENSION_RE.search(text) else None
    if re.search(r"matching|duration of the (master|programme|program|course)|standard (master|length|duration)|"
                 r"full master|minimum standard|for the duration", lower):
        return program_months, note
    years = re.search(r"(\d+)\s*(?:-\s*\d+\s*)?[\s-]*(?:academic\s+)?years?", lower)
    months = re.search(r"(\d+)\s*(?:-\s*\d+\s*)?months", lower)
    if months:
        return min(int(months.group(1)), program_months), note
    if years:
        return min(int(years.group(1)) * 12, program_months), note
    return None, "Scholarship duration could not be read from the record."


def _not_counted(category, label, reason, text=None):
    return {"category": category, "label": label, "amount": None, "counted": False, "reason": reason,
            "source_text": text}


def _tuition_benefit(text, tuition_total, annual_tuition, coverage_months, convert_amount=convert):
    """Funding line for the tuition benefit, or a package line covering tuition and living."""
    label = "Tuition coverage"
    if not text or NOT_OFFERED_RE.search(text):
        return None
    if NOT_VERIFIED_RE.search(text):
        return _not_counted("tuition", label, "Tuition benefit is not verified in the record.", text)
    amounts = _parse_amounts(text)
    percents = sorted({int(p) for p in PERCENT_RE.findall(text)})

    if amounts:
        if len(amounts) > 1 or RANGE_RE.search(text) or HEDGE_RE.search(text):
            return _not_counted("tuition", label, "The listed amount varies or is approximate.", text)
        amount, cur, period = amounts[0]
        converted = convert_amount(amount, cur)
        if converted is None:
            return _not_counted("tuition", label, f"No exchange rate available for {cur}.", text)
        is_package = bool(re.search(r"living", text, re.I))
        if period == "yearly" or re.search(r"academic year", text, re.I):
            if coverage_months is None:
                return _not_counted("tuition", label, "Coverage period is unknown.", text)
            total = converted * coverage_months / 12
        else:
            total = converted  # a one-off amount
        if is_package:
            return {"category": "tuition_and_living", "label": "Scholarship package (tuition and living)",
                    "amount": total, "counted": True, "reason": "Fixed package amount from the record.",
                    "source_text": text}
        return {"category": "tuition", "label": label, "amount": min(total, tuition_total), "counted": True,
                "reason": "Fixed amount toward tuition, capped at the tuition cost.", "source_text": text}

    if HEDGE_RE.search(text) or len(percents) > 1:
        return _not_counted("tuition", label, "The coverage varies by award, so it can't be confirmed.", text)
    if coverage_months is None:
        return _not_counted("tuition", label, "Coverage period is unknown.", text)
    conditional = bool(re.search(r"\bconditional\b", text, re.I)) and coverage_months > 12
    if conditional:
        # e.g. "second-year waiver conditional on first-year results": only the first year is guaranteed
        coverage_months = 12
    covered_share = coverage_months / 12
    if percents and percents[0] < 100:
        share = percents[0] / 100
        reason = f"{percents[0]}% of tuition."
    elif percents or re.search(r"\b(full|complete|exempt|exemption|waiv|tuition-free|covered|paid|offset)", text, re.I):
        share = 1.0
        reason = "Full tuition."
    else:
        return _not_counted("tuition", label, "The tuition benefit is not stated clearly.", text)
    if conditional:
        reason += " Only the first year is counted; later years are conditional."
    return {"category": "tuition", "label": label, "amount": min(annual_tuition * covered_share * share, tuition_total),
            "counted": True, "reason": reason, "source_text": text}


def _living_benefit(text, living_total, coverage_months, in_package, convert_amount=convert):
    label = "Living stipend"
    if not text or NOT_OFFERED_RE.search(text):
        return None
    if in_package or re.search(r"included within", text, re.I):
        return _not_counted("living_costs", label, "Included in the scholarship package above.", text)
    if NOT_VERIFIED_RE.search(text):
        return _not_counted("living_costs", label, "Stipend is not verified in the record.", text)
    amounts = _parse_amounts(text)
    if not amounts:
        return _not_counted("living_costs", label, "The stipend amount is not stated.", text)
    if RANGE_RE.search(text) or HEDGE_RE.search(text):
        return _not_counted("living_costs", label, "The stipend amount varies or is approximate.", text)
    # Several rates (e.g. outside / inside London): use the lowest
    amount, cur, period = min(amounts, key=lambda item: item[0])
    if period is None:
        return _not_counted("living_costs", label, "The stipend's payment period is not stated.", text)
    converted = convert_amount(amount, cur)
    if converted is None:
        return _not_counted("living_costs", label, f"No exchange rate available for {cur}.", text)
    if coverage_months is None:
        return _not_counted("living_costs", label, "Coverage period is unknown.", text)
    months = coverage_months
    paid = re.search(r"for (\d+)(?: or \d+)? months", text)
    if period == "monthly" and paid:
        months = min(months, int(paid.group(1)))
    total = converted * months if period == "monthly" else converted * months / 12
    reason = "Stipend at the lowest listed rate." if len(amounts) > 1 else "Stipend from the record."
    return {"category": "living_costs", "label": label, "amount": min(total, living_total), "counted": True,
            "reason": reason + " Capped at your living costs.", "source_text": text}


INSTITUTION_RE = re.compile(
    r"\b(universit(y|é|à|eit|at)|institute of technology|politecnico|polytechnique|sciences po|college)\b", re.I
)
GENERIC_NAME_WORDS = {"university", "of", "the", "technology", "institute", "royal", "de", "di", "and"}


def _name_tokens(name: str) -> set:
    return {word for word in re.findall(r"[a-zà-ÿ]+", name.lower()) if word not in GENERIC_NAME_WORDS and len(word) > 2}


def _scholarship_applies(scholarship, program_country: Optional[str], program_university: Optional[str]):
    """(applies, reason when it doesn't). Country must match; a university's own scholarship
    must also belong to the program's university."""
    scholarship_country = scholarship.country
    if not scholarship_country or not program_country:
        return False, "The scholarship's or program's country is not recorded."
    sc = scholarship_country.lower()
    pc = program_country.lower()
    if sc.startswith("european union"):
        # e.g. Erasmus Mundus: funds only its own joint Master's programmes
        return False, "This scholarship funds specific multi-country programmes only; it can't be applied to this program."
    if pc not in sc:
        return False, f"This scholarship is for study in {scholarship_country}, not {program_country}."
    # Provider's own name, before any "(funded by ...)" or ", in partnership with ..." detail
    provider = re.split(r"[(,]", scholarship.provider or "")[0].strip()
    if provider and INSTITUTION_RE.search(provider) and program_university:
        if not (_name_tokens(provider) & _name_tokens(program_university)):
            return False, f"This scholarship is offered by {provider} for its own students, not {program_university}."
    return True, None


def _period_total(amount, period, months):
    """Amount for the whole study period. Annual, semester and monthly fees are never mixed up."""
    if period == "total":
        return amount
    if period == "monthly":
        return amount * months
    if period == "semester":
        return amount * months / 6
    return amount * months / 12


IN_KIND_RE = re.compile(r"\b(covered|included|coverage|cover|ticket|airfare|paid)\b", re.I)
PARTIAL_BENEFIT_RE = re.compile(r"\b(allowance|contribution|subsid\w*|up to|partial|where applicable|top-up)\b", re.I)


def _other_benefit(label, category, text, cost_amount, convert_amount=convert):
    """Benefit paying for one expense (health insurance, visa, travel). None when not offered."""
    if not text or NOT_OFFERED_RE.search(text) or re.match(r"\s*not specified", text, re.I):
        return None
    main = re.sub(r"[(][^)]*[)]", " ", text)
    amounts = _parse_amounts(text)
    if cost_amount is None:
        return _not_counted(category, label, "This expense is unknown, so the benefit can't be applied.", text)
    if len(amounts) == 1 and not HEDGE_RE.search(main):
        amount, cur, _ = amounts[0]
        converted = convert_amount(amount, cur)
        if converted is None:
            return _not_counted(category, label, f"No exchange rate available for {cur}.", text)
        return {"category": category, "label": label, "amount": min(converted, cost_amount), "counted": True,
                "reason": "Stated amount, capped at this expense.", "source_text": text}
    if re.match(r"\s*yes\b", main, re.I) and IN_KIND_RE.search(main) and not PARTIAL_BENEFIT_RE.search(main) \
            and not HEDGE_RE.search(main):
        return {"category": category, "label": label, "amount": cost_amount, "counted": True,
                "reason": "Covered by the scholarship; counted up to your cost for this expense.", "source_text": text}
    return _not_counted(category, label, "Listed benefit without a usable amount.", text)


def calculate_feasibility(program, scholarship=None, budget=None, saved_budget=None, profile_budget_usd=None,
                          currency=None, expenses=None, today=None, match=None, profile_budget=None):
    """
    program: Program row (with .university and .costs); scholarship: Scholarship row or None.
    match: scholarship_matching result for this pair, or None when there's no relationship information.
    budget: MoneyInput sent with this calculation; falls back to saved_budget (a MoneyInput),
    then the currency-aware profile budget, then legacy profile_budget_usd. expenses: ExpenseInputs or None.
    Returns a dict matching schemas.financial.FeasibilityResult.
    """
    university = getattr(program, "university", None)
    today = today or date.today()
    tuition_currency = (program.tuition_currency or "").upper() or None
    currency = currency or tuition_currency or "USD"
    months = program.duration_months
    missing, uncertainties, explanation = [], [], []
    rates_used = False

    def to_currency(amount, cur):
        nonlocal rates_used
        if amount is None:
            return None
        if cur != currency:
            rates_used = True
        return convert(amount, cur, currency)

    # ---- Tuition (from the program record, published per year) ----
    annual_tuition = None
    if program.tuition_amount is not None and tuition_currency:
        annual_tuition = to_currency(program.tuition_amount, tuition_currency)
        if annual_tuition is None:
            missing.append(f"No exchange rate from {tuition_currency} to {currency} for the tuition fee.")
    elif program.tuition_usd_per_year is not None:
        annual_tuition = to_currency(program.tuition_usd_per_year, "USD")
        if annual_tuition is None:
            missing.append(f"No exchange rate from USD to {currency} for the tuition fee.")
    else:
        missing.append("The program record has no tuition fee.")
    if not months:
        missing.append("The program record has no duration, so totals for the study period can't be calculated.")

    tuition_total = annual_tuition * months / 12 if annual_tuition is not None and months else None
    tuition_source_issue = source_freshness_issue(
        getattr(program, "source_url", None), getattr(program, "last_verified", None), today
    )
    if tuition_total is not None and tuition_source_issue:
        missing.append(f"The program tuition source needs verification: {tuition_source_issue}")
    costs = [{
        "category": "tuition", "label": "Tuition", "amount": tuition_total,
        "original_amount": program.tuition_amount if program.tuition_amount is not None else program.tuition_usd_per_year,
        "original_currency": tuition_currency or ("USD" if program.tuition_usd_per_year is not None else None),
        "period": "yearly", "source": "program_record", "is_estimate": False,
        "note": "Published annual fee × program duration." if tuition_total is not None else None,
        "source_url": getattr(program, "source_url", None),
        "last_verified": getattr(program, "last_verified", None).isoformat()
        if getattr(program, "last_verified", None) else None,
    }]

    # ---- Living and other expenses ----
    has_unknown_optional = False
    has_planning_estimate = False
    records = {cost.category: cost for cost in (getattr(program, "costs", None) or [])}
    included_in = {}
    for cost in records.values():
        if not (expenses and getattr(expenses, cost.category, None)):  # the record's figure is the one in use
            for category in (getattr(cost, "includes", None) or "").split(","):
                if category.strip():
                    included_in[category.strip()] = cost
    for field, label, essential in EXPENSE_CATEGORIES:
        expense = getattr(expenses, field, None) if expenses else None
        record = records.get(field)
        if field in included_in and record is None:
            included_source = included_in[field]
            source_issue = source_freshness_issue(
                included_source.source_url, included_source.last_verified, today
            )
            costs.append({"category": field, "label": label, "amount": 0.0, "original_amount": None,
                          "original_currency": None, "period": None, "source": "included", "is_estimate": False,
                          "note": f"Already included in {included_source.category.replace('_', ' ')}."})
            if source_issue:
                reason = f"{label} inclusion source needs verification: {source_issue}"
                if essential:
                    missing.append(reason)
                else:
                    has_unknown_optional = True
                    uncertainties.append(reason)
            continue
        line = {"category": field, "label": label, "amount": None, "original_amount": None,
                "original_currency": None, "period": None, "source": "not_provided", "is_estimate": False,
                "note": None}
        if expense is None and record is not None:
            record_max = getattr(record, "amount_max", None)
            source_issue = source_freshness_issue(record.source_url, record.last_verified, today)
            line.update(original_amount=record.amount, original_amount_max=record_max,
                        original_currency=record.currency, period=record.period,
                        source="program_record", is_estimate=bool(record.is_estimate),
                        note=getattr(record, "note", None),
                        source_name=record.source_name, source_url=record.source_url,
                        last_verified=record.last_verified.isoformat() if record.last_verified else None)
            if source_issue:
                line["is_estimate"] = True
                line["note"] = " ".join(filter(None, [line["note"], source_issue]))
                if essential:
                    missing.append(f"{label} source needs verification: {source_issue}")
                else:
                    has_unknown_optional = True
                    uncertainties.append(f"{label} source needs verification: {source_issue}")
            converted = to_currency(record_max if record_max is not None else record.amount, record.currency)
            if converted is None:
                line["note"] = f"No exchange rate from {record.currency} to {currency}."
            elif months or record.period == "total":
                line["amount"] = _period_total(converted, record.period, months or 0)
            if record.is_estimate:
                detail = " Calculated with the upper end of the published range." if record_max is not None else ""
                uncertainties.append(f"{label} is an estimate published by the source, not an exact figure.{detail}")
        elif expense is None and field == "living_costs" and program.living_cost_usd_per_year is not None:
            line.update(original_amount=program.living_cost_usd_per_year, original_currency="USD",
                        period="yearly", source="program_record")
            converted = to_currency(program.living_cost_usd_per_year, "USD")
            if converted is not None and months:
                line["amount"] = converted * months / 12
        elif expense is not None:
            line.update(original_amount=expense.amount, original_currency=expense.currency,
                        period=expense.period, source=expense.source,
                        is_estimate=expense.source == "planning_estimate")
            converted = to_currency(expense.amount, expense.currency)
            if converted is None:
                line["note"] = f"No exchange rate from {expense.currency} to {currency}."
            elif months or expense.period == "total":
                line["amount"] = _period_total(converted, expense.period, months or 0)
            if expense.source == "planning_estimate":
                has_planning_estimate = True

        if line["amount"] is None:
            reason = line["note"] or "not provided"
            if essential:
                missing.append(f"{label}: {reason}. Living costs are never assumed to be zero.")
            else:
                has_unknown_optional = True
                uncertainties.append(f"{label} is unknown ({reason}); it is not included in the total.")
        costs.append(line)

    living_line = next(line for line in costs if line["category"] == "living_costs")
    living_total = living_line["amount"]

    # ---- Budget ----
    chosen_budget = budget if budget is not None else saved_budget
    if chosen_budget is not None:
        budget_amount = to_currency(chosen_budget.amount, chosen_budget.currency)
        budget_info = {"amount": budget_amount, "original_amount": chosen_budget.amount,
                       "original_currency": chosen_budget.currency,
                       "source": "request" if budget is not None else "saved"}
        if budget_amount is None:
            missing.append(f"No exchange rate from {chosen_budget.currency} to {currency} for your budget.")
    elif profile_budget is not None:
        budget_amount = to_currency(profile_budget.amount, profile_budget.currency)
        budget_info = {"amount": budget_amount, "original_amount": profile_budget.amount,
                       "original_currency": profile_budget.currency, "source": "profile"}
        if budget_amount is None:
            missing.append(f"No exchange rate from {profile_budget.currency} to {currency} for your profile budget.")
    elif profile_budget_usd is not None:
        budget_amount = to_currency(profile_budget_usd, "USD")
        budget_info = {"amount": budget_amount, "original_amount": profile_budget_usd,
                       "original_currency": "USD", "source": "profile"}
        if budget_amount is None:
            missing.append(f"No exchange rate from USD to {currency} for your profile budget.")
    else:
        budget_amount = None
        budget_info = {"amount": None, "original_amount": None, "original_currency": None, "source": "not_provided"}
        missing.append("No total study budget is recorded; enter the amount available for the full study period.")

    # ---- Scholarship ----
    funding = []
    scholarship_info = None
    if scholarship is not None:
        verification_issue = scholarship_source_issue(scholarship, today)
        verified = verification_issue is None
        last_verified = getattr(scholarship, "last_verified_date", None) or getattr(scholarship, "last_verified", None)
        if hasattr(last_verified, "isoformat"):
            last_verified = last_verified.isoformat()
        applies, not_applicable_reason = _scholarship_applies(
            scholarship, university.country if university else None, university.name if university else None)
        scholarship_info = {
            "id": scholarship.id, "name": scholarship.name, "funding_type": scholarship.funding_type,
            "verification_status": "verified" if verified else "unverified",
            "verification_issue": verification_issue,
            "last_verified": last_verified,
            "source_url": getattr(scholarship, "official_info_url", None)
            or getattr(scholarship, "official_url", None),
            "applicable": applies, "counted": False,
            "match_outcome": match["outcome"] if match else None,
            "match_label": match["label"] if match else None,
            "match_explanation": match["explanation"] if match else None,
        }
        if match and match["outcome"] == "not_a_match":
            applies, not_applicable_reason = False, match["explanation"]
            scholarship_info["applicable"] = False
        if not verified:
            funding.append(_not_counted("all", "All benefits",
                                        verification_issue or
                                        "This scholarship record is not verified, so none of its funding is counted."))
        elif not applies:
            funding.append(_not_counted("all", "All benefits", not_applicable_reason))
        elif tuition_total is None or not months:
            funding.append(_not_counted("all", "All benefits", "Tuition or duration is missing, so funding can't be applied."))
        else:
            coverage, coverage_note = _coverage_months(scholarship.duration, months)
            if coverage_note:
                uncertainties.append(f"{scholarship.name}: {coverage_note}")
            tuition_line = _tuition_benefit(
                scholarship.tuition_coverage, tuition_total, annual_tuition, coverage, to_currency
            )
            in_package = bool(tuition_line and tuition_line["category"] == "tuition_and_living")
            if tuition_line and in_package:
                cap = tuition_total + (living_total or 0)
                tuition_line["amount"] = min(tuition_line["amount"], cap)
                tuition_line["reason"] += " Capped at tuition plus living costs."
            if tuition_line:
                funding.append(tuition_line)
            living = _living_benefit(
                scholarship.living_stipend, living_total if living_total is not None else 0,
                coverage, in_package, to_currency
            )
            if living:
                if living_total is None and living["counted"]:
                    living = _not_counted("living_costs", living["label"],
                                          "Your living costs are unknown, so the stipend can't be applied.",
                                          living["source_text"])
                funding.append(living)
            line_amount = {line["category"]: line["amount"] for line in costs}
            for field, category, label in [("health_insurance", "health_insurance", "Health insurance"),
                                           ("travel_airfare", "travel", "Travel / airfare"),
                                           ("visa_support", "visa", "Visa support")]:
                benefit = _other_benefit(label, category, getattr(scholarship, field, None),
                                         line_amount.get(category), to_currency)
                if benefit:
                    funding.append(benefit)
            # Documented, but with no matching expense or fixed value
            for field, label in [("accommodation", "Accommodation"), ("other_benefits", "Other benefits")]:
                text = getattr(scholarship, field, None)
                if text and not NOT_OFFERED_RE.search(text) and not re.match(r"\s*not specified", text, re.I):
                    funding.append(_not_counted("listed", label, "Listed benefit without a usable amount; not counted.", text))
            # An unconfirmed relationship is shown as possible funding and left out of every total
            if match and match["outcome"] in ("potential", "needs_verification"):
                for line in funding:
                    if line["counted"]:
                        line.update(counted=False, potential=True,
                                    reason=f"Not confirmed for this program ({match['label']}). {line['reason']}")
            scholarship_info["counted"] = any(line["counted"] for line in funding)

    for line in funding:
        if not line["counted"] and line["category"] != "listed":
            uncertainties.append(f"Not counted - {line['label']}: {line['reason']}")

    confirmed_funding = sum(line["amount"] for line in funding if line["counted"])
    potential_funding = sum(line["amount"] for line in funding if line.get("potential"))

    rates = rates_info(today)
    if rates["stale"] and rates_used:
        missing.append(
            "The configured exchange-rate data is outdated; converted amounts can't support a current affordability result."
        )

    # ---- Totals and status ----
    essentials_known = not missing
    total_cost = None
    if tuition_total is not None and living_total is not None:
        total_cost = sum(line["amount"] for line in costs if line["amount"] is not None)
    confirmed_funding = min(confirmed_funding, total_cost) if total_cost is not None else confirmed_funding
    remaining = max(0.0, total_cost - confirmed_funding) if total_cost is not None else None

    counted_by = {}
    for line in funding:
        if line["counted"]:
            group = line["category"] if line["category"] in ("tuition", "living_costs", "tuition_and_living") else "other"
            counted_by[group] = counted_by.get(group, 0.0) + line["amount"]
    other_costs = sum(line["amount"] or 0 for line in costs if line["category"] not in ("tuition", "living_costs"))

    funding_gap = surplus = coverage_percent = None
    if remaining is not None and budget_amount is not None:
        funding_gap = max(0.0, remaining - budget_amount)
        surplus = max(0.0, budget_amount - remaining)
    if total_cost:
        coverage_percent = confirmed_funding / total_cost * 100
    elif total_cost == 0:
        coverage_percent = 100.0

    if not essentials_known or funding_gap is None:
        status = "insufficient_data"
        explanation.append("Some essential information is missing, so affordability can't be assessed.")
    else:
        explanation.append(
            f"Estimated cost for {months} months is {currency} {total_cost:,.0f}; confirmed funding covers "
            f"{currency} {confirmed_funding:,.0f}, leaving {currency} {remaining:,.0f}."
        )
        if funding_gap <= 0:
            if has_unknown_optional or has_planning_estimate:
                status = "partially_feasible"
                explanation.append(
                    f"Your budget of {currency} {budget_amount:,.0f} covers the known costs, but some expenses "
                    "are unknown or only planning estimates, so affordability is not confirmed."
                )
            else:
                status = "feasible"
                explanation.append(
                    f"Your budget of {currency} {budget_amount:,.0f} covers the remaining cost with "
                    f"{currency} {surplus:,.0f} to spare."
                )
        elif remaining > 0 and funding_gap <= remaining * NEAR_MISS_SHARE:
            status = "partially_feasible"
            explanation.append(
                f"Your budget falls short by {currency} {funding_gap:,.0f}, which is within 20% of the remaining cost."
            )
        else:
            status = "not_feasible"
            explanation.append(f"Your budget falls short by {currency} {funding_gap:,.0f}.")

    if rates["stale"] and rates_used:
        uncertainties.append(
            f"Exchange rates are from {rates['date']} ({rates['age_days']} days old), so converted amounts may be out of date.")

    return {
        "status": status,
        "currency": currency,
        "program": {
            "id": program.id, "name": program.name,
            "university": university.name if university else None,
            "country": university.country if university else None,
            "duration_months": months,
            "tuition_annual": program.tuition_amount if program.tuition_amount is not None else program.tuition_usd_per_year,
            "tuition_currency": tuition_currency or ("USD" if program.tuition_usd_per_year is not None else None),
            "last_verified": program.last_verified.isoformat() if getattr(program, "last_verified", None) else None,
            "source_url": program.source_url,
        },
        "scholarship": scholarship_info,
        "duration_months": months,
        "costs": [{**line, "amount": _round(line["amount"])} for line in costs],
        "tuition_cost": _round(tuition_total),
        "living_cost": _round(living_total),
        "other_costs": _round(other_costs),
        "total_estimated_cost": _round(total_cost),
        "funding": [{**line, "amount": _round(line["amount"])} for line in funding],
        "confirmed_funding": _round(confirmed_funding) or 0.0,
        "potential_funding": _round(potential_funding) or 0.0,
        "scholarship_coverage": {
            "tuition": _round(counted_by.get("tuition", 0.0)),
            "living": _round(counted_by.get("living_costs", 0.0)),
            "combined_package": _round(counted_by.get("tuition_and_living", 0.0)),
            "other": _round(counted_by.get("other", 0.0)),
            "total": _round(confirmed_funding) or 0.0,
        },
        "remaining_cost": _round(remaining),
        "budget": {**budget_info, "amount": _round(budget_info["amount"])},
        "funding_gap": _round(funding_gap),
        "surplus": _round(surplus),
        "coverage_percent": _round(coverage_percent),
        "exchange_rates": {**rates, "used": rates_used},
        "explanation": explanation,
        "missing_data": missing,
        "uncertainties": uncertainties,
    }
