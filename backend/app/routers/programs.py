from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.permissions import require_admin
from app.models.opportunity import Program, ProgramCost, University
from app.schemas.opportunity import (
    CostCategory,
    ProgramCostResponse,
    ProgramCostUpdate,
    ProgramCreate,
    ProgramResponse,
    ProgramUpdate,
)
from app.schemas.matching import MatchResult
from app.services.scholarship_matching import scholarships_for_program

router = APIRouter(prefix="/programs", tags=["Programs"])


@router.get("/", response_model=List[ProgramResponse])
def list_programs(
    country: Optional[str] = Query(None, description="Filter by university country, e.g. Germany"),
    field_of_study: Optional[str] = Query(None, description="Filter by field, e.g. Computer Science"),
    degree_level: Optional[str] = Query(None, description="Master or PhD"),
    max_tuition: Optional[float] = Query(None, description="Maximum tuition in USD per year"),
    deadline_before: Optional[str] = Query(None, description="Deadline on or before this date, e.g. 2027-01-31"),
    university_id: Optional[int] = Query(None, description="Programs of one university"),
    search: Optional[str] = Query(None, description="Search in the program name"),
    skip: int = 0,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    """List programs with optional filters. Anyone can view."""
    query = db.query(Program)

    if country:
        query = query.join(University).filter(University.country.ilike(country))
    if field_of_study:
        query = query.filter(Program.field_of_study.ilike(f"%{field_of_study}%"))
    if degree_level:
        query = query.filter(Program.degree_level.ilike(degree_level))
    if max_tuition is not None:
        query = query.filter(Program.tuition_usd_per_year <= max_tuition)
    if deadline_before:
        query = query.filter(Program.application_deadline <= deadline_before)
    if university_id:
        query = query.filter(Program.university_id == university_id)
    if search:
        query = query.filter(Program.name.ilike(f"%{search}%"))

    return query.order_by(Program.name).offset(skip).limit(limit).all()


@router.get("/{program_id}", response_model=ProgramResponse)
def get_program(program_id: int, db: Session = Depends(get_db)):
    """Get a single program by id"""
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    return program


@router.post("/", response_model=ProgramResponse, status_code=201)
def create_program(
    data: ProgramCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Add a new program (admin only)"""
    uni = db.query(University).filter(University.id == data.university_id).first()
    if not uni:
        raise HTTPException(status_code=404, detail="University not found")

    program = Program(**data.model_dump())
    db.add(program)
    db.commit()
    db.refresh(program)
    return program


@router.put("/{program_id}", response_model=ProgramResponse)
def update_program(
    program_id: int,
    data: ProgramUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Update only the fields that are sent (admin only)"""
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(program, field, value)

    db.commit()
    db.refresh(program)
    return program


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_program(
    program_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Delete a program (admin only)"""
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    db.delete(program)
    db.commit()


def _get_program(db: Session, program_id: int) -> Program:
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    return program


@router.get("/{program_id}/scholarships", response_model=List[MatchResult])
def program_scholarships(
    program_id: int,
    include_not_matches: bool = Query(False, description="Also return scholarships that are ruled out"),
    include_unverified: bool = Query(False, description="Also return unverified scholarship records"),
    db: Session = Depends(get_db),
):
    """Scholarships that may support this program, best evidence first. Anyone can view."""
    return scholarships_for_program(db, _get_program(db, program_id), include_not_matches=include_not_matches,
                                    include_unverified=include_unverified)


@router.get("/{program_id}/costs", response_model=List[ProgramCostResponse])
def list_program_costs(program_id: int, db: Session = Depends(get_db)):
    """Published costs stored for a program. A category with no row is unknown, not free."""
    return _get_program(db, program_id).costs


@router.put("/{program_id}/costs/{category}", response_model=ProgramCostResponse)
def set_program_cost(
    program_id: int,
    category: CostCategory,
    data: ProgramCostUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Add or replace a sourced cost for a program (admin only)"""
    _get_program(db, program_id)
    values = {**data.model_dump(), "source_url": str(data.source_url)}
    cost = db.query(ProgramCost).filter(ProgramCost.program_id == program_id, ProgramCost.category == category).first()
    if cost:
        for field, value in values.items():
            setattr(cost, field, value)
    else:
        cost = ProgramCost(program_id=program_id, category=category, **values)
        db.add(cost)
    db.commit()
    db.refresh(cost)
    return cost


@router.delete("/{program_id}/costs/{category}", status_code=status.HTTP_204_NO_CONTENT)
def delete_program_cost(
    program_id: int,
    category: CostCategory,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Remove a cost (admin only)"""
    cost = db.query(ProgramCost).filter(ProgramCost.program_id == program_id, ProgramCost.category == category).first()
    if not cost:
        raise HTTPException(status_code=404, detail="Cost not found")
    db.delete(cost)
    db.commit()
