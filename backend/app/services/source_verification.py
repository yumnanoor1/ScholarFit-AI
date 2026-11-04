from datetime import date, timedelta
from urllib.parse import urlparse

STALE_AFTER_DAYS = 180


def source_freshness_issue(source_url, verified_on, today=None):
    today = today or date.today()
    parsed_url = urlparse(source_url or "")
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return "No valid official information page is recorded."
    if not verified_on:
        return "No official-source verification date is recorded."
    if verified_on > today:
        return "The official-source verification date is in the future."
    if verified_on < today - timedelta(days=STALE_AFTER_DAYS):
        return f"The official-source review is over {STALE_AFTER_DAYS} days old."
    return None


def scholarship_source_issue(scholarship, today=None):
    issue = source_freshness_issue(
        getattr(scholarship, "official_info_url", None),
        getattr(scholarship, "last_verified_date", None),
        today,
    )
    if issue:
        return issue
    if getattr(scholarship, "verification_status", None) != "verified":
        return "This scholarship record has not been verified against its official source."
    if getattr(scholarship, "verification_basis", None) != "official_source":
        return "Some details on this record aren't confirmed from an official source."
    if any(check.get("status") == "broken" for check in getattr(scholarship, "source_checks", None) or []):
        return "A recorded source link was reported broken."
    if any(flag in {"outdated_source", "broken_source", "needs_reverification", "conflicting_information"}
           or flag.startswith("review:") for flag in getattr(scholarship, "data_flags", None) or []):
        return "This record has an open review flag."
    return None


def is_currently_verified(scholarship, today=None):
    return scholarship_source_issue(scholarship, today) is None
