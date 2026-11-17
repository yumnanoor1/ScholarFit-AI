from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app import models  # noqa: F401
from app.database import application_tables, engine
from app.services import rag_service

router = APIRouter(tags=["Health"])
APPLICATION_TABLE_NAMES = frozenset(table.name for table in application_tables())


@router.get("/ready")
def readiness(request: Request):
    try:
        with engine.connect() as connection:
            if connection.execute(text("SELECT 1")).scalar_one() != 1:
                raise HTTPException(status_code=503, detail="Service is not ready")
            existing_tables = set(inspect(connection).get_table_names())
            if not APPLICATION_TABLE_NAMES.issubset(existing_tables):
                raise HTTPException(status_code=503, detail="Service is not ready")
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Service is not ready") from exc

    if getattr(request.app.state, "scholarship_knowledge_schema_ready", None) is not True:
        raise HTTPException(status_code=503, detail="Service is not ready")

    try:
        rag_service.get_model_revision()
    except rag_service.RagUnavailable as exc:
        raise HTTPException(status_code=503, detail="Service is not ready") from exc

    return {"status": "ready"}
