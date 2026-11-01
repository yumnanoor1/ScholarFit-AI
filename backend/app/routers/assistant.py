from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import require_complete_profile
from app.core.rate_limit import ASSISTANT_MESSAGES_BY_USER, refuse_if_blocked
from app.database import get_db
from app.models.opportunity import Program, Scholarship
from app.models.user import StudentProfile, User
from app.routers import eligibility
from app.schemas.assistant import AssistantReply, AssistantRequest
from app.services.assistant import respond

router = APIRouter(prefix="/assistant", tags=["Assistant"])


@router.post("/chat", response_model=AssistantReply)
def chat(
    payload: AssistantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Answers from the signed-in student's own profile. The message text is never logged."""
    if current_user.role == "admin":
        raise HTTPException(status_code=403, detail="The assistant is for students.")
    key = str(current_user.id)
    refuse_if_blocked((ASSISTANT_MESSAGES_BY_USER, key))
    ASSISTANT_MESSAGES_BY_USER.hit(key)

    profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not created yet.")

    # Context IDs come from the browser, so keep only ones that exist
    context = payload.context.model_dump()
    if context["program_id"] is not None and db.get(Program, context["program_id"]) is None:
        context["program_id"] = None
    if context["scholarship_id"] is not None and db.get(Scholarship, context["scholarship_id"]) is None:
        context["scholarship_id"] = None

    def guidance(program_id=None, scholarship_id=None):
        return eligibility.profile_improvements(
            program_id=program_id, scholarship_id=scholarship_id, db=db, current_user=current_user)

    return respond(db, current_user, profile, payload.message, context, guidance)
