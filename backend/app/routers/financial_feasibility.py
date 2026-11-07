from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.opportunity import Program, Scholarship, ScholarshipProgramLink
from app.models.user import StudentFinancialPlan, StudentProfile, User
from app.core.permissions import require_complete_profile
from app.schemas.financial import (
    BudgetUpdate,
    ExpenseInputs,
    FinancialPlanResponse,
    FeasibilityResult,
    MoneyInput,
    ScholarshipFeasibilityRequest,
)
from app.services.exchange_rates import EUR_RATES, convert, rates_info
from app.services.financial_feasibility import calculate_feasibility
from app.services.scholarship_matching import match_for_financial
from app.services.source_verification import scholarship_source_issue, source_freshness_issue

router = APIRouter(prefix="/financial-feasibility", tags=["Financial Feasibility"])


def _profile_budget(db: Session, user: User) -> Optional[MoneyInput]:
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    if not profile:
        return None
    if profile.budget_usd is not None:
        return MoneyInput(amount=profile.budget_usd, currency="USD")
    # Tuition and living budgets are spending limits, not the total funds available
    # for the complete study period.
    return None


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


def _budget(db: Session, user: User, plan: Optional[StudentFinancialPlan], request_budget=None):
    if request_budget is not None:
        return request_budget, "request"
    if plan and plan.budget_amount is not None:
        return MoneyInput(amount=plan.budget_amount, currency=plan.budget_currency), "saved"
    profile_budget = _profile_budget(db, user)
    return (profile_budget, "profile") if profile_budget else (None, "not_provided")


def _confirmed_cost_programs(db: Session, scholarship: Scholarship, today: date):
    links = (
        db.query(ScholarshipProgramLink)
        .filter(
            ScholarshipProgramLink.scholarship_id == scholarship.id,
            ScholarshipProgramLink.outcome == "confirmed",
            ScholarshipProgramLink.verification_status == "verified",
        )
        .order_by(ScholarshipProgramLink.program_id)
        .all()
    )
    programs = []
    for link in links:
        if not link.evidence or not link.source_url or not link.last_verified:
            continue
        if source_freshness_issue(link.source_url, link.last_verified, today):
            continue
        program = db.query(Program).filter(Program.id == link.program_id).first()
        if not program:
            continue
        match = match_for_financial(db, scholarship, program)
        if match and match["outcome"] == "confirmed":
            programs.append((program, match))
    return programs


def _unresolved_result(scholarship, currency, budget, budget_source, explanation):
    issue = scholarship_source_issue(scholarship)
    budget_amount = convert(budget.amount, budget.currency, currency) if budget else None
    missing = [explanation]
    if budget and budget_amount is None:
        missing.append(f"No configured exchange rate is available from {budget.currency} to {currency}.")
    if issue:
        missing.append(f"Scholarship source needs verification: {issue}")
    return {
        "status": "insufficient_data",
        "currency": currency,
        "program": None,
        "scholarship": {
            "id": scholarship.id,
            "name": scholarship.name,
            "funding_type": scholarship.funding_type,
            "verification_status": scholarship.verification_status,
            "verification_issue": issue,
            "last_verified": scholarship.last_verified_date.isoformat() if scholarship.last_verified_date else None,
            "source_url": scholarship.official_info_url,
            "applicable": False,
            "counted": False,
            "match_outcome": "needs_verification",
            "match_label": "Needs Verification",
            "match_explanation": explanation,
        },
        "duration_months": None,
        "costs": [],
        "tuition_cost": None,
        "living_cost": None,
        "other_costs": 0.0,
        "total_estimated_cost": None,
        "funding": [],
        "confirmed_funding": 0.0,
        "potential_funding": 0.0,
        "scholarship_coverage": {"tuition": 0.0, "living": 0.0, "combined_package": 0.0, "other": 0.0, "total": 0.0},
        "remaining_cost": None,
        "budget": {
            "amount": budget_amount,
            "original_amount": budget.amount if budget else None,
            "original_currency": budget.currency if budget else None,
            "source": budget_source,
        },
        "funding_gap": None,
        "surplus": None,
        "coverage_percent": None,
        "exchange_rates": {**rates_info(), "used": bool(budget and budget.currency != currency and budget_amount is not None)},
        "explanation": ["Affordability cannot be determined from the available scholarship-linked cost data."],
        "missing_data": missing,
        "uncertainties": [],
    }


def _run(db: Session, user: User, request: ScholarshipFeasibilityRequest) -> dict:
    scholarship = db.query(Scholarship).filter(Scholarship.id == request.scholarship_id).first()
    if not scholarship:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    plan = _get_plan(db, user)
    saved_budget, budget_source = _budget(db, user, plan, request.budget)
    currency = request.currency or (saved_budget.currency if saved_budget else "USD")
    today = date.today()
    cost_programs = _confirmed_cost_programs(db, scholarship, today)
    if len(cost_programs) != 1:
        explanation = (
            "More than one current, confirmed cost record is linked to this scholarship; a single affordability result would be ambiguous."
            if cost_programs else
            "No unique current, confirmed scholarship-linked cost record is available."
        )
        return _unresolved_result(scholarship, currency, saved_budget, budget_source, explanation)

    program, match = cost_programs[0]
    expenses = request.expenses
    if expenses is None and plan:
        saved = (plan.expenses or {}).get(f"scholarship:{scholarship.id}") or (plan.expenses or {}).get(str(program.id))
        expenses = ExpenseInputs.model_validate(saved) if saved else None
    result = calculate_feasibility(
        program,
        scholarship=scholarship,
        match=match,
        budget=request.budget,
        saved_budget=saved_budget if budget_source == "saved" else None,
        profile_budget=saved_budget if budget_source == "profile" else None,
        currency=currency,
        expenses=expenses,
        today=today,
    )
    result["program"] = None
    return result


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


@router.put("/plan/scholarships/{scholarship_id}/expenses", response_model=FinancialPlanResponse)
def save_expenses(
    scholarship_id: int,
    data: ExpenseInputs,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Save the signed-in student's cost inputs for one scholarship affordability check."""
    if not db.query(Scholarship.id).filter(Scholarship.id == scholarship_id).first():
        raise HTTPException(status_code=404, detail="Scholarship not found")
    plan = _get_or_create_plan(db, current_user)
    plan.expenses = {**(plan.expenses or {}), f"scholarship:{scholarship_id}": data.model_dump(exclude_none=True)}
    db.commit()
    db.refresh(plan)
    return _plan_response(plan)


@router.post("/calculate", response_model=FeasibilityResult)
def calculate(
    request: ScholarshipFeasibilityRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Estimate whether a scholarship's confirmed funding fits the student's budget and linked costs."""
    return _run(db, current_user, request)
