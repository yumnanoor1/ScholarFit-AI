"""
FitScholar AI Assistant. Answers a student's question from their own saved data and the verified catalogue.

There is no language model here, and nothing is invented: every figure and requirement is read from the existing
services (profile improvement guidance, the program and scholarship eligibility engines, deadlines). This module
only picks which of their results answers the question and words the reply.
"""
import re
from datetime import date
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.models.opportunity import Program, Scholarship
from app.models.user import StudentProfile, User
from app.services.eligibility_engine import check_program_eligibility
from app.services.profile_completion import profile_completion
from app.services.rag_service import retrieve_scholarships, generate_answer
from app.services.scholarship_eligibility import evaluate_scholarship

PROFILE_ROUTE = "/profile?edit=1"
IMPROVEMENT_ROUTE = "/improvement"
NOT_GUARANTEED = "This is guidance, not a promise of admission or funding."
DOCUMENTS_NOTE = "Uploaded documents are tracked in your browser, so I can't see them here. Open Documents to check."

SUGGESTIONS = [
    "How can I improve my profile?",
    "What's my best next action?",
    "Why am I not eligible for a scholarship?",
    "Which requirements am I missing?",
    "How can I improve my chances of getting a scholarship?",
]

KIND_BY_TYPE = {"unmet": "required", "missing_information": "required", "manual_verification": "manual_check", "optional": "optional"}
GENERIC_LABELS = {
    "/scholarships": "Explore Scholarships",
    "/recommendations": "View Recommendations",
    "/universities": "View Program Requirements",
    "/financial": "Check Financial Feasibility",
}
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
STOP_WORDS = {"scholarship", "scholarships", "program", "programme", "programs", "master", "masters", "degree",
              "the", "for", "and", "award", "fellowship", "university", "msc"}

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
    return "help"


# ---------- Shared pieces built from the existing results ----------

def _page_for(related: dict) -> tuple:
    if related["kind"] == "program":
        return f"/universities/{related['id']}", "View Program Requirements"
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
    ctx = _context(context, "eligibility", scholarship_id=scholarship.id, program_id=None)
    next_action = (action("Complete Profile", PROFILE_ROUTE) if result["missing_information"] and not result["not_satisfied"]
                   else action("Check Eligibility", f"/scholarships/sch-db-{scholarship.id}"))
    return _reply(ctx, "why_not_eligible", f"{scholarship.name}: {result['summary']}", title=scholarship.name,
                  sections=sections, action=next_action,
                  notes=result["notes"][:2],
                  suggestions=["What if I improve my CGPA?", "What should I do first?"])


def _why_program(context, program: Program, profile):
    result = check_program_eligibility(profile, program)
    unmet = [f"{check['message']}" for check in result["missing_requirements"]]
    sections = [{"heading": "What stops this program", "items": unmet}] if unmet else []
    if result["matched_requirements"]:
        sections.append({"heading": "Requirements you meet", "items": [check["message"] for check in result["matched_requirements"]]})
    ctx = _context(context, "eligibility", program_id=program.id, scholarship_id=None)
    return _reply(ctx, "why_not_eligible", f"{program.name}: {result['status'].replace('-', ' ')}.", title=program.name,
                  sections=sections, action=action("View Program Requirements", f"/universities/{program.id}"),
                  notes=result["notes"][:2], suggestions=["What if I improve my CGPA?", "What should I do first?"])


def _why_not_eligible(db, context, profile, message, scholarship_results):
    scholarships = db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).all()
    programs = db.query(Program).all()
    named_scholarship = _best_match(message, scholarships)
    named_program = _best_match(message, programs)
    if named_scholarship and (not named_program or _mentions(message, named_scholarship.name) >= _mentions(message, named_program.name)):
        return _why_scholarship(context, named_scholarship, profile)
    if named_program:
        return _why_program(context, named_program, profile)
    if context.get("scholarship_id"):
        known = next((item for item in scholarships if item.id == context["scholarship_id"]), None)
        if known:
            return _why_scholarship(context, known, profile)
    if context.get("program_id"):
        known = next((item for item in programs if item.id == context["program_id"]), None)
        if known:
            return _why_program(context, known, profile)

    blocked = [result for result in scholarship_results if result["status"] == "not_eligible"]
    if not blocked:
        return _reply(_context(context, "eligibility"), "why_not_eligible",
                      "I found no verified scholarship that you are ruled out of. Name a scholarship or program and I'll explain its requirements.",
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


def _financial(context):
    ids = {"programId": context.get("program_id"), "scholarshipId": context.get("scholarship_id")}
    state = ids if ids["programId"] else None
    return _reply(_context(context, "financial"), "financial",
                  "The Financial Feasibility page compares a program's costs, any confirmed scholarship funding and your budget. "
                  "Amounts that aren't published are marked missing and never guessed.",
                  action=action("Check Financial Feasibility", "/financial", state),
                  suggestions=["What's my best next action?"])


def _documents(context):
    return _reply(_context(context, "documents"), "documents", DOCUMENTS_NOTE,
                  action=action("Upload Documents", "/documents"), suggestions=["What's my best next action?"])


def _help(context):
    return _reply(_context(context, "help"), "help",
                  "I can look at your saved profile and the programs and scholarships we hold. Try one of these questions.",
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
    add(6, "explore", "Explore programs and scholarships", "Nothing urgent is pending on your profile.",
        "Browse matches and save the ones you like.", "Low", action("View Recommendations", "/recommendations"))

    _, _, best = min(candidates, key=lambda entry: (entry[0], entry[1]))
    ctx = _context(context, "next_action", shown_actions=(shown + [best["id"]])[-12:])
    return _reply(ctx, "next_action", best["why"], title=f"Your Best Next Action: {best['title']}",
                  priority=best["priority"], deadline=best["deadline"],
                  sections=[{"heading": "What to do", "items": [best["steps"]]}], action=best["action"],
                  notes=[NOT_GUARANTEED], suggestions=["What should I do after that?", "How can I improve my profile?"])


# ---------- Entry point ----------
def _rag_reply(db: Session, context: dict, message: str) -> dict:
    sources = retrieve_scholarships(db, message, limit=5)
    answer = generate_answer(message, sources)

    source_items = [
        f"{source['name']} — {source.get('official_url') or 'Official URL not provided'}"
        for source in sources
    ]

    sections = (
        [{"heading": "Sources", "items": source_items}]
        if source_items else []
    )

    return _reply(
        _context(context, "scholarship_info"),
        "scholarship_info",
        answer,
        sections=sections,
        suggestions=SUGGESTIONS,
    )
def respond(db: Session, user: User, profile: StudentProfile, message: str, context: dict, guidance: Guidance,
            today: Optional[date] = None) -> dict:
    today = today or date.today()
    intent = detect_intent(message)
    if intent == "help":
      try:
         return _rag_reply(db, context, message)
      except Exception:
        return _help(context)
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
