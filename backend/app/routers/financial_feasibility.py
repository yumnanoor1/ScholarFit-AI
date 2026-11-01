from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.opportunity import Program, Scholarship
from app.models.user import StudentFinancialPlan, StudentProfile, User
from app.core.permissions import require_complete_profile
from app.schemas.financial import (
    BudgetUpdate,
    CompareRequest,
    ExpenseInputs,
    FeasibilityRequest,
    FinancialPlanResponse,
    FeasibilityResult,
    MoneyInput,
)
from app.services.exchange_rates import EUR_RATES
from app.services.financial_feasibility import calculate_feasibility
from app.services.scholarship_matching import match_for_financial

router = APIRouter(prefix="/financial-feasibility", tags=["Financial Feasibility"])


def _profile_budget(db: Session, user: User) -> Optional[float]:
    # The budget always comes from the signed-in student's own profile
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    return profile.budget_usd if profile else None


def _get_plan(db: Session, user: User) -> Optional[StudentFinancialPlan]:
    return db.query(StudentFinancialPlan).filter(StudentFinancialPlan.user_id == user.id).first()


def _get_or_create_plan(db: Session, user: User) -> StudentFinancialPlan:
    plan = _get_plan(db, user)
    if not plan:
        plan = StudentFinancialPlan(user_id=user.id, expenses={})
        db.add(plan)
    return plan


def _plan_response(plan: Optional[StudentFinancialPlan]) -> dict:
    has_budget = plan is not None and plan.budget_amount is not None
    return {
        "budget": {"amount": plan.budget_amount, "currency": plan.budget_currency} if has_budget else None,
        "expenses": (plan.expenses or {}) if plan else {},
        "updated_at": (plan.updated_at or plan.created_at) if plan else None,
        "supported_currencies": sorted(EUR_RATES),
    }


def _load(db: Session, program_id: int, scholarship_id: Optional[int]):
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    scholarship = None
    if scholarship_id is not None:
        scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
        if not scholarship:
            raise HTTPException(status_code=404, detail="Scholarship not found")
    return program, scholarship


def _run(db: Session, user: User, request: FeasibilityRequest) -> dict:
    program, scholarship = _load(db, request.program_id, request.scholarship_id)
    plan = _get_plan(db, user)
    saved_budget = None
    if plan and plan.budget_amount is not None:
        saved_budget = MoneyInput(amount=plan.budget_amount, currency=plan.budget_currency)
    expenses = request.expenses
    if expenses is None and plan:
        saved = (plan.expenses or {}).get(str(program.id))
        expenses = ExpenseInputs.model_validate(saved) if saved else None
    return calculate_feasibility(
        program,
        scholarship=scholarship,
        match=match_for_financial(db, scholarship, program) if scholarship else None,
        budget=request.budget,
        saved_budget=saved_budget,
        profile_budget_usd=_profile_budget(db, user),
        currency=request.currency,
        expenses=expenses,
    )


@router.get("/plan", response_model=FinancialPlanResponse)
def get_plan(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """The signed-in student's saved budget and expense estimates."""
    return _plan_response(_get_plan(db, current_user))


@router.put("/plan/budget", response_model=FinancialPlanResponse)
def save_budget(
    data: BudgetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Create or update the signed-in student's budget."""
    if data.currency not in EUR_RATES:
        raise HTTPException(status_code=422, detail=f"Budget currency must be one of: {', '.join(sorted(EUR_RATES))}")
    plan = _get_or_create_plan(db, current_user)
    plan.budget_amount = data.amount
    plan.budget_currency = data.currency
    db.commit()
    db.refresh(plan)
    return _plan_response(plan)


@router.put("/plan/expenses/{program_id}", response_model=FinancialPlanResponse)
def save_expenses(
    program_id: int,
    data: ExpenseInputs,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Save the signed-in student's own expense estimates for one program."""
    _load(db, program_id, None)
    plan = _get_or_create_plan(db, current_user)
    # A new dict so SQLAlchemy sees the JSON column change
    plan.expenses = {**(plan.expenses or {}), str(program_id): data.model_dump(exclude_none=True)}
    db.commit()
    db.refresh(plan)
    return _plan_response(plan)


@router.post("/calculate", response_model=FeasibilityResult)
def calculate(
    request: FeasibilityRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Estimate whether a program (optionally with a scholarship) fits the student's budget."""
    return _run(db, current_user, request)


@router.post("/compare", response_model=List[FeasibilityResult])
def compare(
    request: CompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Run up to six program / funding scenarios side by side."""
    return [_run(db, current_user, scenario) for scenario in request.scenarios]


@router.get("/{program_id}", response_model=FeasibilityResult)
def feasibility_for_program(
    program_id: int,
    scholarship_id: Optional[int] = Query(None, gt=0),
    currency: Optional[str] = Query(None, min_length=3, max_length=3),
    budget_amount: Optional[float] = Query(None, ge=0),
    budget_currency: Optional[str] = Query(None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Feasibility from stored data only: program and scholarship records plus the student's saved plan.
    Expenses nobody has stored are reported as missing."""
    budget = None
    if budget_amount is not None:
        if not budget_currency:
            raise HTTPException(status_code=422, detail="budget_currency is required with budget_amount")
        budget = MoneyInput(amount=budget_amount, currency=budget_currency)
    request = FeasibilityRequest(
        program_id=program_id,
        scholarship_id=scholarship_id,
        budget=budget,
        currency=currency.upper() if currency else None,
    )
    return _run(db, current_user, request)
