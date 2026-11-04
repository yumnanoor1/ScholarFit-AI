from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.permissions import require_admin
from app.models.opportunity import University
from app.schemas.opportunity import (
    UniversityCreate,
    UniversityUpdate,
    UniversityResponse,
)

router = APIRouter(prefix="/universities", tags=["Universities"])


def _normalized_name(value):
    return " ".join((value or "").casefold().split())


def _reject_duplicate(db: Session, name: str, country: str, exclude_id: Optional[int] = None):
    normalized_name = _normalized_name(name)
    normalized_country = _normalized_name(country)
    duplicate = next(
        (
            item for item in db.query(University).all()
            if item.id != exclude_id
            and _normalized_name(item.name) == normalized_name
            and _normalized_name(item.country) == normalized_country
        ),
        None,
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A university with this name and country already exists")


@router.get("/", response_model=List[UniversityResponse])
def list_universities(
    country: Optional[str] = Query(None, description="Filter by country, e.g. Germany"),
    search: Optional[str] = Query(None, description="Search in the university name"),
    skip: int = 0,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    """List universities with optional filters. Anyone can view."""
    query = db.query(University)
    if country:
        query = query.filter(University.country.ilike(country))
    if search:
        query = query.filter(University.name.ilike(f"%{search}%"))
    return query.order_by(University.name).offset(skip).limit(limit).all()


@router.get("/{university_id}", response_model=UniversityResponse)
def get_university(university_id: int, db: Session = Depends(get_db)):
    """Get a single university by id"""
    uni = db.query(University).filter(University.id == university_id).first()
    if not uni:
        raise HTTPException(status_code=404, detail="University not found")
    return uni


@router.post("/", response_model=UniversityResponse, status_code=201)
def create_university(
    data: UniversityCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Add a new university (admin only); duplicate names within a country are rejected."""
    _reject_duplicate(db, data.name, data.country)
    uni = University(**data.model_dump())
    db.add(uni)
    db.commit()
    db.refresh(uni)
    return uni


@router.put("/{university_id}", response_model=UniversityResponse)
def update_university(
    university_id: int,
    data: UniversityUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Update only the fields that are sent (admin only)"""
    uni = db.query(University).filter(University.id == university_id).first()
    if not uni:
        raise HTTPException(status_code=404, detail="University not found")

    changes = data.model_dump(exclude_unset=True)
    _reject_duplicate(db, changes.get("name", uni.name), changes.get("country", uni.country), uni.id)
    for field, value in changes.items():
        setattr(uni, field, value)

    db.commit()
    db.refresh(uni)
    return uni


@router.delete("/{university_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_university(
    university_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Delete a university (admin only). Its programs must be deleted first."""
    uni = db.query(University).filter(University.id == university_id).first()
    if not uni:
        raise HTTPException(status_code=404, detail="University not found")
    if uni.programs:
        raise HTTPException(
            status_code=400,
            detail="This university still has programs. Delete them first",
        )
    db.delete(uni)
    db.commit()