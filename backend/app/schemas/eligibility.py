from typing import List
from pydantic import BaseModel


class RequirementResult(BaseModel):
    requirement: str
    message: str


class EligibilityResult(BaseModel):
    program_id: int
    program_name: str
    university_name: str
    eligible: bool
    matched_requirements: List[RequirementResult]
    missing_requirements: List[RequirementResult]
    notes: List[str]