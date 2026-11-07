from datetime import date, datetime, timedelta, timezone
import re

from app.services.source_url_safety import UnsafeSourceURL, validate_source_url

STALE_AFTER_DAYS = 180
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


def source_freshness_issue(source_url, verified_on, today=None):
    today = today or date.today()
    try:
        validate_source_url(source_url)
    except UnsafeSourceURL:
        return "No valid official information page is recorded."
    if not verified_on:
        return "No official-source verification date is recorded."
    if verified_on > today:
        return "The official-source verification date is in the future."
    if verified_on < today - timedelta(days=STALE_AFTER_DAYS):
        return f"The official-source review is over {STALE_AFTER_DAYS} days old."
    return None


def source_check_datetime(check):
    if not isinstance(check, dict):
        return None
    value = check.get("checked_at")
    if not isinstance(value, str):
        return None
    try:
        checked_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        return None
    return checked_at.astimezone(timezone.utc)


def document_source_issue(
    source_url,
    source_checks,
    today=None,
    source_document_id=None,
    expected_content_hash=None,
):
    today = today or date.today()
    try:
        validate_source_url(source_url)
    except UnsafeSourceURL:
        return "The document source URL is invalid."

    matching_checks = [
        check for check in (source_checks or [])
        if isinstance(check, dict)
        and check.get("url") == source_url
        and (
            source_document_id is None
            or check.get("source_document_id") in (None, source_document_id)
        )
    ]
    if not matching_checks:
        return "No source check is recorded for this document URL."

    if not isinstance(expected_content_hash, str) or not _SHA256_HEX.fullmatch(expected_content_hash):
        return "The indexed document has no valid content hash."

    check = matching_checks[-1]
    if check.get("status") != "ok":
        return "The document source URL has no successful source check."
    checked_at = source_check_datetime(check)
    if checked_at is None:
        return "The document source check has no valid timestamp."
    if checked_at.date() > today:
        return "The document source check date is in the future."
    if checked_at.date() < today - timedelta(days=STALE_AFTER_DAYS):
        return f"The document source check is over {STALE_AFTER_DAYS} days old."
    checked_content_hash = check.get("content_hash")
    if (
        not isinstance(checked_content_hash, str)
        or not _SHA256_HEX.fullmatch(checked_content_hash)
        or checked_content_hash != expected_content_hash
    ):
        return "The checked source content does not match the indexed document version."
    return None


def has_current_successful_document_source_check(
    source_url,
    source_checks,
    today=None,
    source_document_id=None,
    expected_content_hash=None,
):
    return document_source_issue(
        source_url,
        source_checks,
        today,
        source_document_id,
        expected_content_hash,
    ) is None


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
    additional_urls = getattr(scholarship, "additional_source_urls", None) or []
    if not isinstance(additional_urls, (list, tuple)):
        additional_urls = [additional_urls]
    configured_urls = {
        url
        for url in (
            getattr(scholarship, "official_info_url", None),
            getattr(scholarship, "official_application_url", None),
            *additional_urls,
        )
        if isinstance(url, str) and url
    }
    if any(
        isinstance(check, dict)
        and check.get("status") == "broken"
        and check.get("url") in configured_urls
        for check in getattr(scholarship, "source_checks", None) or []
    ):
        return "A recorded source link was reported broken."
    if any(flag in {"outdated_source", "broken_source", "needs_reverification", "conflicting_information"}
           or flag.startswith("review:") for flag in getattr(scholarship, "data_flags", None) or []):
        return "This record has an open review flag."
    return None


def is_currently_verified(scholarship, today=None):
    return scholarship_source_issue(scholarship, today) is None
