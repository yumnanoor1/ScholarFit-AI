from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class AssistantContext(BaseModel):
    """What the conversation is about, sent back by the browser so follow-ups make sense.
    It holds catalogue IDs only; the student's own data is always read from the signed-in account."""
    topic: Optional[str] = Field(None, max_length=40)
    program_id: Optional[int] = Field(None, gt=0)
    scholarship_id: Optional[int] = Field(None, gt=0)
    shown_actions: List[str] = Field(default_factory=list, max_length=12)

    @field_validator("shown_actions")
    @classmethod
    def _short_ids(cls, value: List[str]) -> List[str]:
        return [item[:80] for item in value]


class AssistantRequest(BaseModel):
    message: str = Field(..., max_length=500)
    context: AssistantContext = Field(default_factory=AssistantContext)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Type a question first.")
        return value


class AssistantAction(BaseModel):
    label: str
    route: str                              # an existing page of the app
    state: Optional[Dict[str, Optional[int]]] = None   # router state, such as IDs for the financial page


class AssistantGuidanceItem(BaseModel):
    id: str
    title: str
    priority: Literal["High", "Medium", "Low"]
    kind: Literal["required", "manual_check", "optional"]   # mandatory requirement, needs a manual check, or optional
    status: str                             # the student's current information
    target: Optional[str] = None            # the requirement as the records state it
    why: str
    steps: str
    benefit: Optional[str] = None
    action: Optional[AssistantAction] = None


class AssistantSection(BaseModel):
    heading: str
    items: List[str]


class AssistantReply(BaseModel):
    intent: str
    title: Optional[str] = None
    summary: str
    priority: Optional[Literal["High", "Medium", "Low"]] = None
    deadline: Optional[str] = None
    sections: List[AssistantSection] = Field(default_factory=list)
    guidance: List[AssistantGuidanceItem] = Field(default_factory=list)
    action: Optional[AssistantAction] = None
    suggestions: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    context: AssistantContext
