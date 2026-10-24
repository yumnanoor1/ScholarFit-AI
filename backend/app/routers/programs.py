from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.permissions import require_admin
from app.models.opportunity import Program, University
from app.schemas.opportunity import ProgramCreate, ProgramUpdate, ProgramResponse

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