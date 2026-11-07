"""
FitScholar AI Assistant. Answers a student's question from their own saved data and the verified catalogue.

There is no language model here, and nothing is invented: every figure and requirement is read from the existing
services (profile improvement guidance, scholarship eligibility, deadlines). This module
only picks which of their results answers the question and words the reply.

The one exception is general scholarship-information questions, which are answered from approved official
documents by rag_service (a language model may word that answer). Those documents must have been ingested,
approved and indexed beforehand; otherwise the reply says no approved source was found.
"""
import re
from datetime import date
from typing import Callable, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.opportunity import Scholarship
from app.models.user import StudentProfile, User
from app.services import rag_service
from app.services.source_url_safety import safe_source_url, safe_source_urls_in_text
from app.services.profile_completion import profile_completion
from app.services.scholarship_eligibility import evaluate_scholarship
from app.services.scholarship_recommendations import NOT_A_PROBABILITY, recommend_for_student

PROFILE_ROUTE = "/profile?edit=1"
IMPROVEMENT_ROUTE = "/improvement"
NOT_GUARANTEED = "This is guidance, not a promise of receiving a scholarship."
DOCUMENTS_NOTE = "Uploaded documents are tracked in your browser, so I can't see them here. Open Documents to check."

SUGGESTIONS = [
    "How can I improve my profile?",
    "What's my best next action?",
    "Why am I not eligible for a scholarship?",
    "Which requirements am I missing?",
    "How can I improve my chances of getting a scholarship?",
    "What are my best scholarship matches?",
]

KIND_BY_TYPE = {"unmet": "required", "missing_information": "required", "manual_verification": "manual_check", "optional": "optional"}
GENERIC_LABELS = {
    "/scholarships": "Explore Scholarships",
    "/recommendations": "View Recommendations",
    "/financial": "Check Financial Feasibility",
}
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
STOP_WORDS = {"scholarship", "scholarships", "program", "programme", "programs", "master", "masters", "degree",
              "the", "for", "and", "award", "fellowship", "university", "msc"}
SCHOLARSHIP_NAME_STOP_WORDS = STOP_WORDS | {
    "grant", "grants", "awards", "fellowships", "what", "does", "do", "tell", "me", "about", "how",
    "can", "i", "is", "are", "who", "where", "when", "why", "cover", "covers", "coverage", "benefit",
    "benefits", "include", "includes", "offer", "offers", "provide", "provides", "apply", "application",
    "requirement", "requirements", "eligible", "eligibility", "explain", "describe", "overview", "more",
    "information", "info", "generally", "general", "usually", "typically", "all", "any", "other",
    "another", "it", "its", "this", "that", "these", "those", "international", "student", "students",
    "foundation", "fund", "trust", "merit", "need", "based", "graduate", "undergraduate", "global",
    "world", "academic", "education", "excellence", "development", "foreign", "national", "study",
    "studies", "research", "joint",
}
SCHOLARSHIP_REFERENCE_WORDS = {
    "scholarship", "scholarships", "grant", "grants", "fellowship", "fellowships", "award", "awards",
}

Guidance = Callable[..., dict]


def action(label: str, route: str, state: Optional[dict] = None) -> dict:
    return {"label": label, "route": route, "state": state}


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _mentions(message: str, name: str) -> Optional[int]:
    """How specifically the message names this record (higher is better), or None."""
    text = " ".join(_words(message))
    for variant in (name, re.split(r"\s*[(\u2013\u2014-]\s", name)[0]):
        phrase = " ".join(_words(variant))
        if phrase and f" {phrase} " in f" {text} ":
            return 100 + len(phrase)
    tokens = {word for word in _words(name) if len(word) >= 3 and word not in STOP_WORDS}
    if tokens and tokens <= set(text.split()):
        return len(tokens)
    return None


def _best_match(message: str, records) -> Optional[object]:
    scored = [(score, record) for record in records if (score := _mentions(message, record.name)) is not None]
    return max(scored, key=lambda pair: pair[0])[1] if scored else None


def _name_variants(name: str) -> List[str]:
    return [name, re.split(r"\s*[(\u2013\u2014-]\s", name)[0]]


def _exact_name_mentioned(message: str, name: str) -> bool:
    text = " " + " ".join(_words(message)) + " "
    return any(
        phrase and f" {phrase} " in text
        for phrase in (" ".join(_words(variant)) for variant in _name_variants(name))
    )


def _scholarship_name_tokens(text: str) -> Set[str]:
    return {
        word for word in _words(text)
        if len(word) >= 4 and word not in SCHOLARSHIP_NAME_STOP_WORDS
    }


def _has_explicit_scholarship_name_anchor(message: str, token: str) -> bool:
    words = _words(message)
    return any(
        (left == token and right in SCHOLARSHIP_REFERENCE_WORDS)
        or (right == token and left in SCHOLARSHIP_REFERENCE_WORDS)
        for left, right in zip(words, words[1:])
    )


def _resolve_scholarship_mention(message: str, records):
    exact_matches = [record for record in records if _exact_name_mentioned(message, record.name)]
    if exact_matches:
        return (exact_matches[0], []) if len(exact_matches) == 1 else (None, exact_matches)

    message_tokens = _scholarship_name_tokens(message)
    overlaps = []
    confident_matches = []
    token_record_counts = {}
    for record in records:
        for token in _scholarship_name_tokens(record.name):
            token_record_counts[token] = token_record_counts.get(token, 0) + 1

    for record in records:
        name_tokens = _scholarship_name_tokens(record.name)
        overlap = message_tokens & name_tokens
        if not overlap:
            continue
        overlaps.append((len(overlap), record))
        has_distinctive_anchor = any(
            len(token) >= 5
            and token_record_counts[token] == 1
            and _has_explicit_scholarship_name_anchor(message, token)
            for token in overlap
        )
        if has_distinctive_anchor or (len(overlap) >= 2 and len(overlap) / len(name_tokens) >= 0.5):
            confident_matches.append(record)

    if len(confident_matches) == 1 and len(overlaps) == 1:
        return confident_matches[0], []
    if not overlaps:
        return None, []

    possible_matches = [record for _, record in sorted(overlaps, key=lambda item: (-item[0], item[1].name, item[1].id))]
    return None, possible_matches


def _is_general_scholarship_question(message: str) -> bool:
    words = _words(message)
    text = " ".join(words)
    return (
        "scholarships" in words
        or any(term in words for term in ("grants", "fellowships", "awards"))
        or any(phrase in text for phrase in (
            "in general", "generally", "typically", "usually", "all scholarships", "any scholarship",
            "a scholarship", "a grant", "a fellowship", "an award",
        ))
    )


def _is_scholarship_follow_up(message: str) -> bool:
    words = set(_words(message))
    if "another" in words or "different" in words or ("new" in words and words & SCHOLARSHIP_REFERENCE_WORDS):
        return False
    text = " " + " ".join(_words(message)) + " "
    return bool(words & {"it", "its", "this", "that", "these", "those"}) or any(
        f" {phrase} " in text for phrase in ("the scholarship", "the grant")
    )


def _needs_scholarship_clarification(message: str) -> bool:
    return bool(set(_words(message)) & SCHOLARSHIP_REFERENCE_WORDS)


def detect_intent(message: str) -> str:
    text = " ".join(_words(message))
    has = lambda *terms: any(term in text for term in terms)  # noqa: E731
    if has("what if", "if i improve", "if i raise", "if i increase", "if i get a higher", "if i retake") and has("cgpa", "gpa", "grade", "ielts", "toefl", "english"):
        return "what_if"
    if has("next action", "best next", "what should i do", "do first", "do next", "what next", "what now", "where do i start",
           "where should i start", "after that", "what else", "something else", "another action", "then what"):
        return "next_action"
    if has("why") and has("eligible", "qualify", "ineligible", "rejected", "not meet") or has("not eligible", "ineligible"):
        return "why_not_eligible"
    if has("missing") and has("requirement", "requirements", "information", "info"):
        return "missing_requirements"
    if has("chance", "chances") or (has("scholarship") and has("win", "stronger", "stand out", "better my")):
        return "improve_chances"
    if has("deadline", "due date", "closing"):
        return "deadlines"
    if has("afford", "tuition", "budget", "financial", "cost", "money", "fund my"):
        return "financial"
    if has("document", "transcript", "sop", "statement of purpose", "recommendation letter", "upload"):
        return "documents"
    if has("improve", "profile", "weak", "strength", "gap", "better student"):
        return "improve_profile"
    if has(
            "best scholarship matches", "best scholarship match", "best scholarships", "top scholarships",
            "recommended scholarships", "recommended scholarship", "scholarship recommendations",
            "scholarship matches", "scholarship match", "scholarships match",
            "scholarships to prioritize", "scholarship to prioritize",
            "which scholarships should i prioritize", "what scholarships should i prioritize",
            "which scholarships do you recommend", "what scholarships do you recommend",
            "which scholarship is recommended", "which scholarships are recommended",
            "what scholarship is recommended", "what scholarships are recommended",
            "recommend scholarships", "recommend some scholarships", "recommend a scholarship",
            "recommend me scholarships", "recommend me a scholarship",
    ):
        return "scholarship_recommendations"
    if has("scholarship", "fellowship", "stipend", "funding", "award", "grant") and has(
            "cover", "coverage", "benefit", "include", "offer", "provide", "how to apply", "how do i apply",
            "how can i apply", "tell me about", "what is", "what does", "what are", "who can", "who is", "requirements for",
            "explain", "describe", "overview", "about this", "is about", "more about", "more information", "more info"):
        return "scholarship_info"
    return "help"


# ---------- Shared pieces built from the existing results ----------

def _page_for(related: dict) -> tuple:
    return f"/scholarships/sch-db-{related['id']}", "Check Eligibility"


def _action_for(rec: dict) -> Optional[dict]:
    route, related = rec["action_route"], rec["related"]
    english = rec["category"] == "English Language Preparation"
    if english and rec["result_type"] == "unmet" and related:
        return action("Explore Language Requirements", _page_for(related[0])[0])
    if route.startswith("/profile"):
        return action("Complete Profile" if rec["result_type"] != "unmet" else "Update Profile", route)
    if route == "/financial":
        return action(GENERIC_LABELS[route], route)
    if related:
        page, label = _page_for(related[0])
        return action(label, page)
    return action(GENERIC_LABELS.get(route, "Open"), route)


def _target(rec: dict) -> Optional[str]:
    seen = []
    for related in rec["related"]:
        text = related.get("requirement_text")
        if text:
            seen.append(f"{text} ({related['name']})")
    return "; ".join(seen[:3]) or None


def _item(rec: dict) -> dict:
    return {
        "id": rec["id"], "title": rec["title"], "priority": rec["priority"], "kind": KIND_BY_TYPE[rec["result_type"]],
        "status": rec["profile_information"], "target": _target(rec), "why": rec["why_it_matters"],
        "steps": rec["suggested_action"], "benefit": rec["expected_benefit"], "action": _action_for(rec),
    }


def _context(context: dict, topic: str, **changes) -> dict:
    return {**context, "topic": topic, **changes}


def _reply(context: dict, intent: str, summary: str, **fields) -> dict:
    return {
        "intent": intent, "summary": summary, "context": context, "suggestions": fields.pop("suggestions", []),
        "notes": fields.pop("notes", []), "sections": fields.pop("sections", []), "guidance": fields.pop("guidance", []),
        **fields,
    }


def _status_line(guidance: dict, completion) -> str:
    summary = guidance["summary"]
    return (f"Your profile is {completion.percent}% complete. I compared it with {summary['opportunities_evaluated']} "
            f"opportunities ({guidance['scope']['description'].lower()}): {summary['eligible']} eligible, "
            f"{summary['not_eligible']} not eligible, {summary['missing_information']} missing information, "
            f"{summary['not_evaluated']} that need a manual check.")


def _deadline_text(deadline: dict) -> Optional[str]:
    if deadline.get("status") != "open" or not deadline.get("date"):
        return None
    left = deadline.get("days_left")
    return f"{deadline['date']} ({left} day{'' if left == 1 else 's'} left)" if left is not None else deadline["date"]


def _scholarship_results(db: Session, profile: StudentProfile, today: date) -> List[dict]:
    query = db.query(Scholarship).filter(Scholarship.verification_status == "verified", Scholarship.archived_at.is_(None))
    return [evaluate_scholarship(item, profile, today=today) for item in query.order_by(Scholarship.id).all()]


# ---------- FR-13: profile improvement ----------

def _improve_profile(context, guidance, completion):
    items = [_item(rec) for rec in guidance["recommendations"]]
    shown = items[:4]
    summary = _status_line(guidance, completion)
    sections = []
    if len(items) > len(shown):
        sections.append({"heading": "More", "items": [f"{len(items) - len(shown)} more suggestions are on the full guidance page."]})
    if not items:
        summary += " I found nothing to improve for the opportunities I checked."
    return _reply(
        _context(context, "improve_profile"), "improve_profile", summary, guidance=shown, sections=sections,
        action=action("View Full Guidance", IMPROVEMENT_ROUTE),
        notes=["Required items come from the opportunities' own stated requirements; optional ones are not required by any of them.",
               DOCUMENTS_NOTE, NOT_GUARANTEED],
        suggestions=["What's my best next action?", "Which requirements am I missing?", "What if I improve my CGPA?"],
    )


def _missing_requirements(context, guidance, completion):
    items = [_item(rec) for rec in guidance["recommendations"] if rec["result_type"] in ("unmet", "missing_information")]
    manual = [rec for rec in guidance["recommendations"] if rec["result_type"] == "manual_verification"]
    sections = []
    if manual:
        sections.append({"heading": "Needs a manual check on the official page",
                         "items": [f"{rec['title']} ({len(rec['related'])})" for rec in manual[:5]]})
    summary = (f"{len(items)} required item{'' if len(items) == 1 else 's'} need attention."
               if items else "I found no unmet or missing requirements among the opportunities I could check.")
    return _reply(
        _context(context, "missing_requirements"), "missing_requirements", summary, guidance=items[:5], sections=sections,
        action=action("View Full Guidance", IMPROVEMENT_ROUTE),
        notes=[DOCUMENTS_NOTE, NOT_GUARANTEED],
        suggestions=["What should I do first?", "Why am I not eligible for a scholarship?"],
    )


def _improve_chances(context, guidance, scholarship_results):
    related_recs = [rec for rec in guidance["recommendations"]
                    if rec["result_type"] != "optional" and any(item["kind"] == "scholarship" for item in rec["related"])]
    optional = [rec for rec in guidance["recommendations"] if rec["result_type"] == "optional"]
    items = [_item(rec) for rec in (related_recs[:3] + optional[:1])]
    eligible = [result for result in scholarship_results if result["eligible"]]
    sections = []
    if eligible:
        sections.append({"heading": "You already meet the stated requirements for",
                         "items": [result["scholarship_name"] + (f" · deadline {_deadline_text(result['deadline'])}" if _deadline_text(result["deadline"]) else "")
                                   for result in eligible[:5]]})
    summary = ("Here is what the scholarships' own stated requirements ask of you." if related_recs
               else "I found no unmet scholarship requirement to work on. Optional profile details can still help.")
    return _reply(
        _context(context, "improve_chances"), "improve_chances", summary, guidance=items, sections=sections,
        action=action("Explore Scholarships", "/scholarships"),
        notes=["Meeting the requirements does not mean you will be selected or receive funding."],
        suggestions=["Why am I not eligible for a scholarship?", "What's my best next action?"],
    )


# ---------- Why am I not eligible ----------

def _group(items: List[dict]) -> List[str]:
    lines = []
    for item in items:
        line = f"{item['label']}: {item['reason']}"
        if item.get("source_text"):
            line += f" Stated: \u201c{item['source_text']}\u201d"
        lines.append(line)
    return lines


def _why_scholarship(context, scholarship: Scholarship, profile):
    result = evaluate_scholarship(scholarship, profile)
    sections = [section for section in (
        {"heading": "Requirements you don't meet", "items": _group(result["not_satisfied"])},
        {"heading": "Missing from your profile", "items": _group(result["missing_information"])},
        {"heading": "Needs a manual check", "items": _group(result["needs_verification"])},
    ) if section["items"]]
    ctx = _context(context, "eligibility", scholarship_id=scholarship.id)
    next_action = (action("Complete Profile", PROFILE_ROUTE) if result["missing_information"] and not result["not_satisfied"]
                   else action("Check Eligibility", f"/scholarships/sch-db-{scholarship.id}"))
    return _reply(ctx, "why_not_eligible", f"{scholarship.name}: {result['summary']}", title=scholarship.name,
                  sections=sections, action=next_action,
                  notes=result["notes"][:2],
                  suggestions=["What if I improve my CGPA?", "What should I do first?"])


def _why_not_eligible(db, context, profile, message, scholarship_results):
    scholarships = db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).all()
    named_scholarship = _best_match(message, scholarships)
    if named_scholarship:
        return _why_scholarship(context, named_scholarship, profile)
    if context.get("scholarship_id"):
        known = next((item for item in scholarships if item.id == context["scholarship_id"]), None)
        if known:
            return _why_scholarship(context, known, profile)

    blocked = [result for result in scholarship_results if result["status"] == "not_eligible"]
    if not blocked:
        return _reply(_context(context, "eligibility"), "why_not_eligible",
                      "I found no verified scholarship that you are ruled out of. Name a scholarship and I'll explain its requirements.",
                      action=action("Explore Scholarships", "/scholarships"), suggestions=["Which requirements am I missing?"])
    lines = [f"{result['scholarship_name']}: {result['not_satisfied'][0]['label']} \u2013 {result['not_satisfied'][0]['reason']}"
             for result in blocked[:5]]
    return _reply(_context(context, "eligibility"), "why_not_eligible",
                  f"You don't meet at least one stated requirement for {len(blocked)} verified scholarship{'' if len(blocked) == 1 else 's'}. "
                  "Ask about one by name for the full detail.",
                  sections=[{"heading": "Where you fall short", "items": lines}], action=action("Explore Scholarships", "/scholarships"),
                  suggestions=[f"Why am I not eligible for {result['scholarship_name']}?" for result in blocked[:2]])


# ---------- What if ----------

def _what_if(context, guidance, message):
    text = " ".join(_words(message))
    english = any(term in text for term in ("ielts", "toefl", "english"))
    unmet_id, missing_id = ("unmet-english", "missing-information-english") if english else ("unmet-academic", "missing-information-academic")
    subject = "English score" if english else "CGPA"
    by_id = {rec["id"]: rec for rec in guidance["recommendations"]}
    ctx = _context(context, "what_if")
    suggestions = ["What should I do first?", "How can I improve my profile?"]

    if missing_id in by_id:
        return _reply(ctx, "what_if", f"Your {subject} isn't in your profile, so I can't compare it with any requirement yet.",
                      action=action("Complete Profile", PROFILE_ROUTE), suggestions=suggestions)
    rec = by_id.get(unmet_id)
    if not rec:
        return _reply(ctx, "what_if", f"Your {subject} already meets every stated minimum I could check, so raising it would not change those results.",
                      action=action("View Recommendations", "/recommendations"), suggestions=suggestions,
                      notes=[NOT_GUARANTEED])
    lines = [f"{item['name']}: {item['requirement_text'] or item['result']}" for item in rec["related"][:6]]
    return _reply(ctx, "what_if",
                  f"Reaching the stated minimum would clear the {subject} requirement for {len(rec['related'])} "
                  f"opportunit{'y' if len(rec['related']) == 1 else 'ies'}. Their other requirements still apply.",
                  sections=[{"heading": f"Stated {subject} minimums you are below", "items": lines},
                            {"heading": "Keep in mind", "items": [rec["suggested_action"]]}],
                  action=action("View Recommendations", "/recommendations"), suggestions=suggestions, notes=[NOT_GUARANTEED])


# ---------- Deadlines, financial, documents ----------

def _deadlines(context, scholarship_results):
    upcoming = sorted((result for result in scholarship_results
                       if result["status"] in ("eligible", "missing_information") and _deadline_text(result["deadline"])),
                      key=lambda result: result["deadline"]["days_left"])
    ctx = _context(context, "deadlines")
    if not upcoming:
        return _reply(ctx, "deadlines", "None of the scholarships you currently qualify for lists an open deadline I can read.",
                      action=action("Explore Scholarships", "/scholarships"), suggestions=["What's my best next action?"])
    return _reply(ctx, "deadlines", "These are the closest listed deadlines among scholarships you qualify for or could qualify for.",
                  sections=[{"heading": "Upcoming deadlines",
                             "items": [f"{result['scholarship_name']}: {_deadline_text(result['deadline'])}" for result in upcoming[:5]]}],
                  action=action("Check Eligibility", f"/scholarships/sch-db-{upcoming[0]['scholarship_id']}"),
                  notes=["Confirm every date on the official page before relying on it."],
                  suggestions=["What's my best next action?"])


def _scholarship_recommendations(db, profile, context):
    result = recommend_for_student(db, profile)
    ranked = []
    for item in result["recommendations"]:
        eligibility = item.get("eligibility") or {}
        deadline = item.get("deadline") or {}
        if (
            item.get("recommended") is True
            and item.get("score") is not None
            and eligibility.get("status") != "not_eligible"
            and deadline.get("status") != "closed"
        ):
            ranked.append(item)
    ranked = ranked[:5]
    eligible, needs_verification = [], []
    for item in ranked:
        eligibility = item.get("eligibility") or {}
        if (
            eligibility.get("status") == "eligible"
            and eligibility.get("outcome") == "eligible"
            and item.get("category") in {"strong", "good", "possible"}
        ):
            eligible.append(item)
        else:
            needs_verification.append(item)

    excluded = result["excluded"]

    def format_recommendation(item, rank, confirmed_eligible):
        funding = item.get("funding") or {}
        deadline = item.get("deadline") or {}
        deadline_status = str(deadline.get("status") or "unknown").replace("_", " ")
        deadline_date = deadline.get("date") or deadline.get("opens_on")
        deadline_text = f"{deadline_status.capitalize()}"
        if deadline_date:
            deadline_text += f" ({deadline_date})"
        funding_text = funding.get("label") or "Not confirmed"
        if funding.get("summary"):
            funding_text += f" — {funding['summary']}"

        why = next(iter(item.get("positive") or []), None) or item.get("category_reason")
        details = [
            f"{rank}. {item['scholarship_name']} (ID {item['scholarship_id']}) — "
            f"{item['score']}/100, {item.get('category_label') or item.get('category') or 'Match'}.",
            f"Country: {item.get('country') or 'Not listed'}; "
            f"funding: {funding_text}; deadline: {deadline_text}.",
        ]
        if confirmed_eligible and why:
            details.append(f"Why it matches: {why}")
        elif not confirmed_eligible:
            eligibility = item.get("eligibility") or {}
            status = str(eligibility.get("status") or "unknown").replace("_", " ")
            explanation = item.get("category_reason") or eligibility.get("summary") or "Eligibility needs review."
            details.append(f"Needs verification ({status}): {explanation}")
        warnings = item.get("warnings") or []
        if warnings:
            details.append(f"Important warning: {'; '.join(warnings[:2])}")
        return " ".join(details)

    sections = [{
        "heading": "Top eligible matches",
        "items": [
            format_recommendation(item, rank, True)
            for rank, item in enumerate(eligible, start=1)
        ] or ["No confirmed eligible matches were found in the verified records for your current profile."],
    }]
    if needs_verification:
        sections.append({
            "heading": f"Needs verification ({len(needs_verification)})",
            "items": [
                format_recommendation(item, rank, False)
                for rank, item in enumerate(needs_verification, start=1)
            ],
        })
    if excluded:
        excluded_lines = []
        for item in excluded[:3]:
            reasons = [entry["reason"] for entry in item.get("exclusions", []) if entry.get("reason")]
            reason = "; ".join(reasons[:2]) or item.get("category_reason") or "Needs verification."
            excluded_lines.append(f"{item['scholarship_name']} (ID {item['scholarship_id']}): {reason}")
        if len(excluded) > len(excluded_lines):
            excluded_lines.append(f"{len(excluded) - len(excluded_lines)} more excluded scholarships.")
        sections.append({
            "heading": f"Excluded (not recommended) — {len(excluded)}",
            "items": excluded_lines,
        })

    summary = f"Found {len(eligible)} confirmed eligible match(es)."
    if needs_verification:
        summary += f" {len(needs_verification)} additional candidate(s) need verification."
    elif not eligible:
        summary = "No confirmed eligible matches or candidates needing verification were found for your current profile."
    notes = list(result.get("notes") or [])
    if NOT_A_PROBABILITY not in notes:
        notes.append(NOT_A_PROBABILITY)

    return _reply(
        _context(context, "scholarship_recommendations"),
        "scholarship_recommendations",
        summary,
        title="Your scholarship matches",
        sections=sections,
        action=action("View Recommendations", "/recommendations"),
        notes=notes,
        suggestions=["What's my best next action?", "Which requirements am I missing?"],
    )


def _financial(context):
    state = {"scholarshipId": context.get("scholarship_id")} if context.get("scholarship_id") else None
    return _reply(_context(context, "financial"), "financial",
                  "The Financial Feasibility page compares a scholarship's confirmed funding with available linked cost records and your budget. "
                  "If costs are missing or ambiguous, the result says so rather than guessing.",
                  action=action("Check Financial Feasibility", "/financial", state),
                  suggestions=["What's my best next action?"])


def _documents(context):
    return _reply(_context(context, "documents"), "documents", DOCUMENTS_NOTE,
                  action=action("Upload Documents", "/documents"), suggestions=["What's my best next action?"])


def _help(context):
    return _reply(_context(context, "help"), "help",
                  "I can look at your saved profile and verified scholarship records. Try one of these questions.",
                  suggestions=SUGGESTIONS)


# ---------- FR-16: best next action ----------

def _next_action(context, guidance, completion, scholarship_results, message):
    shown = list(context.get("shown_actions") or [])
    wants_another = any(term in message.lower() for term in ("after that", "else", "another", "then", "next one"))
    skip = set(shown) if wants_another else set()
    deadlines = {result["scholarship_id"]: result["deadline"] for result in scholarship_results}
    candidates = []

    def add(rank, ident, title, why, steps, priority, act, deadline=None):
        if ident not in skip:
            candidates.append((rank, len(candidates), {"id": ident, "title": title, "why": why, "steps": steps,
                                                       "priority": priority, "action": act, "deadline": deadline}))

    if not completion.complete:
        add(0, "profile-incomplete", "Complete your profile", "Eligibility can't be judged for missing details.",
            "Add: " + ", ".join(completion.missing[:4]) + ".", "High", action("Complete Profile", PROFILE_ROUTE))
    for result in scholarship_results:
        text = _deadline_text(result["deadline"])
        if text and result["status"] in ("eligible", "missing_information") and result["deadline"]["days_left"] <= 45:
            urgent = result["deadline"]["days_left"] <= 14
            add(1 if urgent else 3, f"deadline-{result['scholarship_id']}", f"Review {result['scholarship_name']} before it closes",
                "You meet its stated requirements." if result["eligible"] else "You may qualify once your profile information is complete.",
                "Open the scholarship, read the official page and prepare what it asks for.", "High" if urgent else "Medium",
                action("Check Eligibility", f"/scholarships/sch-db-{result['scholarship_id']}"), text)
    for rec in guidance["recommendations"]:
        if rec["result_type"] in ("unmet", "missing_information") and rec["actionability"] != "not_changeable" and rec["priority"] == "High":
            nearest = next((_deadline_text(deadlines[item["id"]]) for item in rec["related"]
                            if item["kind"] == "scholarship" and item["id"] in deadlines and _deadline_text(deadlines[item["id"]])), None)
            add(2, rec["id"], rec["title"], rec["why_it_matters"], rec["suggested_action"], "High", _action_for(rec), nearest)
    for rec in guidance["recommendations"]:
        if rec["result_type"] != "optional" and rec["priority"] != "High" or rec["id"] == "optional-budget":
            add(4, rec["id"], rec["title"], rec["why_it_matters"], rec["suggested_action"], rec["priority"], _action_for(rec))
    if guidance["summary"]["eligible"]:
        add(5, "explore-eligible", "Compare your eligible opportunities", "You meet the stated requirements for some of them.",
            "Review your recommendations and shortlist the ones that fit you.", "Medium", action("View Recommendations", "/recommendations"))
    add(6, "explore", "Explore scholarships", "Nothing urgent is pending on your profile.",
        "Browse scholarship matches and save the ones you like.", "Low", action("View Recommendations", "/recommendations"))

    _, _, best = min(candidates, key=lambda entry: (entry[0], entry[1]))
    ctx = _context(context, "next_action", shown_actions=(shown + [best["id"]])[-12:])
    return _reply(ctx, "next_action", best["why"], title=f"Your Best Next Action: {best['title']}",
                  priority=best["priority"], deadline=best["deadline"],
                  sections=[{"heading": "What to do", "items": [best["steps"]]}], action=best["action"],
                  notes=[NOT_GUARANTEED], suggestions=["What should I do after that?", "How can I improve my profile?"])


# ---------- General scholarship information (RAG over approved official documents) ----------

def _scholarship_info(db: Session, context: dict, message: str) -> dict:
    scholarship_id = context.get("scholarship_id")
    if isinstance(scholarship_id, bool) or not isinstance(scholarship_id, int) or scholarship_id <= 0:
        scholarship_id = None
    records = db.query(Scholarship.id, Scholarship.name).all()

    explicit_id = re.search(r"\bscholarship\s+id\s*[:#]?\s*(\d+)\b", message, re.I)
    if explicit_id:
        requested_id = int(explicit_id.group(1))
        if not any(record.id == requested_id for record in records):
            ctx = _context(context, "scholarship_info", scholarship_id=None)
            return _reply(ctx, "scholarship_info",
                          f"I couldn't find a scholarship with ID {requested_id}. Check the ID or provide its name.",
                          action=action("Explore Scholarships", "/scholarships"), suggestions=SUGGESTIONS)
        scholarship_id = requested_id
    else:
        match, ambiguous = _resolve_scholarship_mention(message, records)
        if ambiguous:
            matches = ambiguous[:5]
            ctx = _context(context, "scholarship_info", scholarship_id=None)
            options = [f"{item.name} (scholarship ID {item.id})" for item in matches]
            if len(ambiguous) > len(matches):
                options.append("More matches exist. Reply with the full scholarship name or its ID.")
            return _reply(
                ctx, "scholarship_info",
                "I couldn't identify a single scholarship confidently. Please clarify by full name or scholarship ID before I search its documents.",
                sections=[{"heading": "Possible matches", "items": options}],
                action=action("Explore Scholarships", "/scholarships"),
                suggestions=[f"Tell me about scholarship ID {item.id}" for item in matches[:3]],
            )
        if match:
            scholarship_id = match.id
        elif _is_general_scholarship_question(message):
            scholarship_id = None
        elif scholarship_id is not None and _is_scholarship_follow_up(message):
            pass
        elif _needs_scholarship_clarification(message):
            ctx = _context(context, "scholarship_info", scholarship_id=None)
            return _reply(
                ctx, "scholarship_info",
                "Please clarify which scholarship you mean by giving its full name or scholarship ID.",
                action=action("Explore Scholarships", "/scholarships"), suggestions=SUGGESTIONS,
            )
        else:
            scholarship_id = None
    # The ID only narrows the search; every approval and eligibility filter still runs in the database query
    ctx = _context(context, "scholarship_info", scholarship_id=scholarship_id)
    result = rag_service.answer_question(db, message, scholarship_id=scholarship_id)
    if result.status == rag_service.STATUS_UNAVAILABLE:
        return _reply(ctx, "scholarship_info",
                      "I can't search the official scholarship documents right now. Please try again later, or open the scholarship's page.",
                      action=action("Explore Scholarships", "/scholarships"), suggestions=SUGGESTIONS)
    if result.status == rag_service.STATUS_NO_SOURCES:
        return _reply(ctx, "scholarship_info",
                      "I couldn't find an approved official source that answers this, so I won't guess. "
                      "Please check the scholarship's official page.",
                      action=action("Explore Scholarships", "/scholarships"), suggestions=SUGGESTIONS)
    if result.status == rag_service.STATUS_WEAK_EVIDENCE:
        return _reply(ctx, "scholarship_info",
                      "I found approved official documents, but not passages relevant enough to answer this "
                      "question. I won't guess; please check the scholarship's official page or ask about a "
                      "specific requirement, benefit, deadline, or application step.",
                      action=action("Explore Scholarships", "/scholarships"), suggestions=SUGGESTIONS)
    if result.status == rag_service.STATUS_CONFLICT:
        conflict_items = []
        for conflict in result.conflicts:
            for statement in conflict.statements:
                location = []
                if statement.section_heading:
                    location.append(statement.section_heading)
                if statement.page_label:
                    location.append(statement.page_label)
                provenance = f"document {statement.source_document_id}, version {statement.document_version_id}"
                if location:
                    provenance += f", {'; '.join(location)}"
                source_url = safe_source_url(statement.source_url) or "Source URL unavailable"
                conflict_items.append(
                    f"{conflict.scholarship_name} — {conflict.fact_label}: {statement.value}. "
                    f"Source text: \"{safe_source_urls_in_text(statement.statement)}\" "
                    f"({provenance}; source: {source_url})"
                )
        sections = [{"heading": "Conflicting official statements", "items": conflict_items}]
        if result.chunks:
            source_items, seen = [], set()
            for chunk in result.chunks[:3]:
                source_url = chunk.citation_url or "Source URL unavailable"
                line = f"{chunk.scholarship_name}: {source_url}"
                if line not in seen:
                    seen.add(line)
                    source_items.append(line)
            sections.append({"heading": "Sources for other retrieved evidence", "items": source_items})
        return _reply(
            ctx, "scholarship_info", result.text, sections=sections,
            action=action("Explore Scholarships", "/scholarships"),
            notes=["Please verify conflicting details with the cited official source or scholarship authority."],
            suggestions=SUGGESTIONS,
        )
    source_chunks = result.chunks if result.generated else result.chunks[:3]
    sources, seen = [], set()
    for chunk in source_chunks:
        source_url = chunk.citation_url or "Source URL unavailable"
        line = f"{chunk.scholarship_name}: {source_url}"
        if line not in seen:
            seen.add(line)
            sources.append(line)
    sources_heading = "Retrieved sources" if result.generated else "Sources"
    notes = ["Confirm every detail on the official page before relying on it."]
    if not result.generated:
        notes.insert(0, "These are excerpts from approved sources, not a written summary.")
    return _reply(ctx, "scholarship_info", result.text, sections=[{"heading": sources_heading, "items": sources}],
                  action=action("Explore Scholarships", "/scholarships"), notes=notes, suggestions=SUGGESTIONS)


# ---------- Entry point ----------

def respond(db: Session, user: User, profile: StudentProfile, message: str, context: dict, guidance: Guidance,
            today: Optional[date] = None) -> dict:
    today = today or date.today()
    intent = detect_intent(message)
    if intent == "help" and context.get("scholarship_id") and _is_scholarship_follow_up(message):
        intent = "scholarship_info"
    if intent == "help":
        return _help(context)
    if intent == "scholarship_info":
        return _scholarship_info(db, context, message)
    if intent == "scholarship_recommendations":
        return _scholarship_recommendations(db, profile, context)
    completion = profile_completion(db, user)
    if intent == "financial":
        return _financial(context)
    if intent == "documents":
        return _documents(context)

    data = guidance()
    results = _scholarship_results(db, profile, today) if intent in ("next_action", "why_not_eligible", "improve_chances", "deadlines") else []
    if intent == "improve_profile":
        return _improve_profile(context, data, completion)
    if intent == "missing_requirements":
        return _missing_requirements(context, data, completion)
    if intent == "improve_chances":
        return _improve_chances(context, data, results)
    if intent == "what_if":
        return _what_if(context, data, message)
    if intent == "deadlines":
        return _deadlines(context, results)
    if intent == "why_not_eligible":
        return _why_not_eligible(db, context, profile, message, results)
    return _next_action(context, data, completion, results, message)
