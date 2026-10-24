from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.permissions import require_admin
from app.models.opportunity import Scholarship
from app.schemas.opportunity import (
    ScholarshipCreate,
    ScholarshipUpdate,
    ScholarshipResponse,
)

router = APIRouter(prefix="/scholarships", tags=["Scholarships"])


@router.get("/", response_model=List[ScholarshipResponse])
def list_scholarships(
    country: Optional[str] = Query(None, description="Country contains, e.g. Germany"),
    funding_type: Optional[str] = Query(None, description="e.g. Fully Funded or Partially Funded"),
    degree_level: Optional[str] = Query(None, description="e.g. Master"),
    pakistan_eligible_only: bool = Query(False, description="Only scholarships open to Pakistan"),
    include_unverified: bool = Query(False, description="Also show unverified records"),
    search: Optional[str] = Query(None, description="Search in the scholarship name"),
    skip: int = 0,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    """List scholarships with optional filters. Anyone can view.
    Unverified records are hidden unless include_unverified=true."""
    query = db.query(Scholarship)

    if not include_unverified:
        query = query.filter(Scholarship.verification_status == "verified")
    if country:
        query = query.filter(Scholarship.country.ilike(f"%{country}%"))
    if funding_type:
        query = query.filter(Scholarship.funding_type.ilike(f"%{funding_type}%"))
    if degree_level:
        query = query.filter(Scholarship.degree_level.ilike(f"%{degree_level}%"))
    if pakistan_eligible_only:
        query = query.filter(Scholarship.pakistan_eligible.ilike("yes%"))
    if search:
        query = query.filter(Scholarship.name.ilike(f"%{search}%"))

    return query.order_by(Scholarship.name).offset(skip).limit(limit).all()


@router.get("/{scholarship_id}", response_model=ScholarshipResponse)
def get_scholarship(scholarship_id: int, db: Session = Depends(get_db)):
    """Get a single scholarship by id"""
    item = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return item


@router.post("/", response_model=ScholarshipResponse, status_code=201)
def create_scholarship(
    data: ScholarshipCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Add a new scholarship (admin only)"""
    item = Scholarship(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{scholarship_id}", response_model=ScholarshipResponse)
def update_scholarship(
    scholarship_id: int,
    data: ScholarshipUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Update only the fields that are sent (admin only).
    Admin can also set verification_status to verified or unverified."""
    item = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scholarship not found")

    changes = data.model_dump(exclude_unset=True)
    status_value = changes.get("verification_status")
    if status_value is not None and status_value not in ("verified", "unverified"):
        raise HTTPException(
            status_code=400,
            detail="verification_status must be 'verified' or 'unverified'",
        )

    for field, value in changes.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{scholarship_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scholarship(
    scholarship_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Delete a scholarship (admin only)"""
    item = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    db.delete(item)
    db.commit()