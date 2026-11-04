
import os
from google import genai
from google.genai import types
from sqlalchemy import text
from sqlalchemy.orm import Session

EMBED_MODEL = "gemini-embedding-001"
CHAT_MODEL = "gemini-2.5-flash"
EMBED_DIM = 768
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def scholarship_text(s):
    fields = [
        "name", "country", "provider", "degree_level", "study_type",
        "eligible_nationalities", "pakistan_eligible", "eligible_fields",
        "min_academic_requirement", "bachelors_requirement",
        "english_requirement", "work_experience", "age_requirement",
        "funding_type", "tuition_coverage", "living_stipend",
        "travel_airfare", "accommodation", "health_insurance",
        "visa_support", "other_benefits", "duration", "deadline",
        "application_method", "admission_required", "nomination_required",
        "required_documents", "application_pathway", "official_url",
        "notes",
    ]
    return "\n".join(
        f"{field.replace('_', ' ').title()}: {getattr(s, field, None)}"
        for field in fields
        if getattr(s, field, None)
    )


def embed_text(content: str) -> list[float]:
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=content,
        config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
    )
    return result.embeddings[0].values


def setup_vector_table(db: Session):
    db.execute(text("""
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS scholarship_embeddings (
            scholarship_id INTEGER PRIMARY KEY
                REFERENCES scholarships(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            embedding vector(768) NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now()
        );
    """))
    db.commit()


def index_scholarships(db: Session) -> int:
    """Verified, non-archived scholarships ke embeddings create/upsert karta hai."""
    rows = db.execute(text("""
        SELECT id, name, country, provider, degree_level, study_type,
               eligible_nationalities, pakistan_eligible, eligible_fields,
               min_academic_requirement, bachelors_requirement,
               english_requirement, work_experience, age_requirement,
               funding_type, tuition_coverage, living_stipend,
               travel_airfare, accommodation, health_insurance,
               visa_support, other_benefits, duration, deadline,
               application_method, admission_required, nomination_required,
               required_documents, application_pathway, official_url, notes
        FROM scholarships
        WHERE verification_status = 'verified'
          AND archived_at IS NULL
    """)).mappings().all()

    indexed = 0
    for row in rows:
        content = "\n".join(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in row.items()
            if key != "id" and value is not None
        )
        vector = embed_text(content)

        db.execute(text("""
            INSERT INTO scholarship_embeddings
                (scholarship_id, content, embedding, updated_at)
            VALUES (:id, :content, CAST(:embedding AS vector), now())
            ON CONFLICT (scholarship_id)
            DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                updated_at = now()
        """), {
            "id": row["id"],
            "content": content,
            "embedding": "[" + ",".join(map(str, vector)) + "]",
        })
        indexed += 1

    db.commit()
    return indexed


def retrieve_scholarships(db: Session, question: str, limit: int = 5):
    query_vector = embed_text(question)

    results = db.execute(text("""
        SELECT s.id, s.name, s.country, s.provider, s.degree_level,
               s.funding_type, s.deadline, s.official_url,
               e.content, e.embedding <=> CAST(:embedding AS vector) AS distance
        FROM scholarship_embeddings e
        JOIN scholarships s ON s.id = e.scholarship_id
        WHERE s.verification_status = 'verified'
          AND s.archived_at IS NULL
        ORDER BY e.embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """), {
        "embedding": "[" + ",".join(map(str, query_vector)) + "]",
        "limit": limit,
    }).mappings().all()

    return [dict(row) for row in results]


def generate_answer(question: str, sources: list[dict]) -> str:
    if not sources:
        return (
            "Mujhe database mein is sawal ke liye koi verified scholarship "
            "source nahi mila. Scholarship ki official website par details "
            "verify karein."
        )

    context = "\n\n".join(
        f"Source {i + 1}:\n{source['content']}\n"
        f"Official URL: {source.get('official_url') or 'Not provided'}"
        for i, source in enumerate(sources)
    )

    response = client.models.generate_content(
        model=CHAT_MODEL,
        contents=f"""
You are a scholarship information assistant.
Answer using ONLY the source context below.
Do not invent eligibility, funding, deadlines, or requirements.
If information is missing, clearly say it is not specified.
Mention relevant scholarship names and official URLs.

Question:
{question}

Source context:
{context}
""",
    )
    return response.text or "Sorry no answer generated."
