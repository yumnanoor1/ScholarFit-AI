"""Deterministic document chunking and MiniLM embedding generation."""
from dataclasses import dataclass
import hashlib
import math
from typing import List, Optional, Sequence

from app.models.scholarship_knowledge import EMBEDDING_DIMENSIONS
from app.services import rag_service

MAX_CHUNK_TOKENS = 192
CHUNK_OVERLAP_TOKENS = 24
EMBEDDING_BATCH_SIZE = 32
# Bounds full-document tokenizer memory; matches the largest supported discovery extraction.
MAX_DOCUMENT_INPUT_CHARS = 100_000


class DocumentInputTooLargeError(ValueError):
    """Raised when extracted text exceeds the indexing input limit."""


def validate_document_input_size(extracted_text: str) -> None:
    if len(extracted_text) > MAX_DOCUMENT_INPUT_CHARS:
        raise DocumentInputTooLargeError(
            f"Extracted document exceeds the {MAX_DOCUMENT_INPUT_CHARS}-character indexing limit"
        )


@dataclass(frozen=True)
class DocumentChunk:
    ordinal: int
    chunk_text: str
    chunk_hash: str
    start_offset: int
    end_offset: int


def _resolve_tokenizer(tokenizer=None, model_max_seq_length=None, model_revision=None):
    if tokenizer is None:
        if model_max_seq_length is not None:
            raise ValueError("model_max_seq_length requires an injected tokenizer")
        revision = rag_service.get_model_revision() if model_revision is None else (
            rag_service._validate_model_revision(model_revision)
        )
        model, loaded_revision = rag_service._load_model_with_revision(revision)
        if loaded_revision != revision:
            raise rag_service.RagUnavailable(
                "loaded embedding model revision does not match the requested revision"
            )
        tokenizer = model.tokenizer
        model_max_seq_length = model.max_seq_length
    elif model_max_seq_length is None:
        model_max_seq_length = getattr(tokenizer, "model_max_length", None)

    if isinstance(model_max_seq_length, bool) or not isinstance(model_max_seq_length, int):
        raise ValueError("the tokenizer's model maximum sequence length is unavailable")
    if model_max_seq_length < 1:
        raise ValueError("the tokenizer's model maximum sequence length must be positive")
    return tokenizer, model_max_seq_length


def _special_token_count(tokenizer) -> int:
    count = tokenizer.num_special_tokens_to_add(pair=False)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("the tokenizer returned an invalid special-token count")
    return count


def _tokenizer_output(tokenizer, text: str, *, add_special_tokens: bool, offsets: bool = False):
    encoded = tokenizer(
        text,
        add_special_tokens=add_special_tokens,
        truncation=False,
        return_offsets_mapping=offsets,
    )
    try:
        input_ids = list(encoded["input_ids"])
    except (KeyError, TypeError) as exc:
        raise ValueError("the tokenizer returned invalid input IDs") from exc
    if input_ids and isinstance(input_ids[0], (list, tuple)):
        raise ValueError("the tokenizer unexpectedly returned a batch")
    if not offsets:
        return input_ids, None

    try:
        token_offsets = [tuple(offset) for offset in encoded["offset_mapping"]]
    except (KeyError, TypeError) as exc:
        raise ValueError("the tokenizer must provide fast-tokenizer character offsets") from exc
    if len(input_ids) != len(token_offsets):
        raise ValueError("the tokenizer returned mismatched IDs and offsets")
    return input_ids, token_offsets


def _validate_token_limit(
    tokenizer,
    model_max_seq_length: int,
    max_chunk_tokens: int,
    overlap_tokens: int,
) -> int:
    if isinstance(max_chunk_tokens, bool) or not isinstance(max_chunk_tokens, int) or max_chunk_tokens < 1:
        raise ValueError("max_chunk_tokens must be a positive integer")
    if max_chunk_tokens >= model_max_seq_length:
        raise ValueError("max_chunk_tokens must be below the model maximum sequence length")

    content_token_limit = max_chunk_tokens - _special_token_count(tokenizer)
    if content_token_limit < 1:
        raise ValueError("max_chunk_tokens leaves no room for content after special tokens")
    if (
        isinstance(overlap_tokens, bool)
        or not isinstance(overlap_tokens, int)
        or overlap_tokens < 0
        or overlap_tokens >= content_token_limit
    ):
        raise ValueError("overlap_tokens must be non-negative and smaller than the content-token limit")
    return content_token_limit


def chunk_document_text(
    extracted_text: str,
    *,
    model_revision: Optional[str] = None,
    tokenizer=None,
    model_max_seq_length=None,
    max_chunk_tokens: int = MAX_CHUNK_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> List[DocumentChunk]:
    """Split text by pinned-tokenizer windows, preserving exact source slices and offsets.

    max_chunk_tokens includes special tokens and is deliberately below the model's actual sequence limit.
    """
    if not isinstance(extracted_text, str):
        raise TypeError("extracted_text must be a string")
    validate_document_input_size(extracted_text)
    if not extracted_text.strip():
        raise ValueError("extracted_text must not be empty or whitespace-only")

    tokenizer, model_max_seq_length = _resolve_tokenizer(
        tokenizer,
        model_max_seq_length,
        model_revision,
    )
    content_token_limit = _validate_token_limit(
        tokenizer,
        model_max_seq_length,
        max_chunk_tokens,
        overlap_tokens,
    )
    input_ids, offsets = _tokenizer_output(
        tokenizer,
        extracted_text,
        add_special_tokens=False,
        offsets=True,
    )
    if not input_ids:
        raise ValueError("extracted_text contains no tokens for the configured tokenizer")
    for start, end in offsets:
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(extracted_text)
        ):
            raise ValueError("the tokenizer returned invalid character offsets")

    chunks = []
    token_start = 0
    previous_char_end = 0
    while token_start < len(input_ids):
        token_end = min(token_start + content_token_limit, len(input_ids))
        char_start = 0 if token_start == 0 else min(previous_char_end, offsets[token_start][0])

        while token_end > token_start:
            char_end = len(extracted_text) if token_end == len(input_ids) else offsets[token_end - 1][1]
            if char_end <= char_start:
                token_end -= 1
                continue
            chunk_text = extracted_text[char_start:char_end]
            encoded_chunk, _ = _tokenizer_output(
                tokenizer,
                chunk_text,
                add_special_tokens=True,
            )
            if len(encoded_chunk) <= max_chunk_tokens and len(encoded_chunk) <= model_max_seq_length:
                break
            token_end -= 1

        if token_end <= token_start:
            raise ValueError("a tokenizer token cannot fit within the configured chunk token limit")

        chunks.append(
            DocumentChunk(
                ordinal=len(chunks),
                chunk_text=chunk_text,
                chunk_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                start_offset=char_start,
                end_offset=char_end,
            )
        )
        previous_char_end = char_end
        if token_end == len(input_ids):
            break
        token_start = max(token_end - overlap_tokens, token_start + 1)
    return chunks


def _validated_embedding_rows(encoded, expected_count: int) -> List[List[float]]:
    try:
        rows = list(encoded)
    except TypeError as exc:
        raise ValueError("embedding model returned an invalid batch") from exc
    if len(rows) != expected_count:
        raise ValueError("embedding model returned a different number of vectors than input chunks")

    embeddings = []
    for row in rows:
        try:
            components = list(row)
        except TypeError as exc:
            raise ValueError("embedding model returned an invalid vector") from exc
        if len(components) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"embedding model returned {len(components)} dimensions; expected {EMBEDDING_DIMENSIONS}"
            )

        vector = []
        for component in components:
            if isinstance(component, (bool, str, bytes)):
                raise ValueError("embedding model returned a non-numeric value")
            try:
                value = float(component)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("embedding model returned a non-numeric value") from exc
            if not math.isfinite(value):
                raise ValueError("embedding model returned a non-finite value")
            vector.append(value)

        if not math.isclose(math.hypot(*vector), 1.0, rel_tol=1e-4, abs_tol=1e-4):
            raise ValueError("embedding model returned a vector that is not normalized")
        embeddings.append(vector)
    return embeddings


def generate_document_embeddings(
    chunks: Sequence[DocumentChunk],
    *,
    model_revision: Optional[str] = None,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    max_chunk_tokens: int = MAX_CHUNK_TOKENS,
) -> List[List[float]]:
    """Generate normalized, dimension-checked vectors in chunk order using the pinned MiniLM model."""
    if isinstance(chunks, (str, bytes)):
        raise TypeError("chunks must be a sequence of DocumentChunk values")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")

    chunk_list = list(chunks)
    if not chunk_list:
        return []
    if any(not isinstance(chunk, DocumentChunk) for chunk in chunk_list):
        raise TypeError("chunks must contain only DocumentChunk values")

    revision = rag_service.get_model_revision() if model_revision is None else (
        rag_service._validate_model_revision(model_revision)
    )
    model, loaded_revision = rag_service._load_model_with_revision(revision)
    if loaded_revision != revision:
        raise rag_service.RagUnavailable("loaded embedding model revision does not match the requested revision")
    tokenizer, model_max_seq_length = _resolve_tokenizer(model.tokenizer, model.max_seq_length)
    _validate_token_limit(tokenizer, model_max_seq_length, max_chunk_tokens, 0)
    for chunk in chunk_list:
        encoded, _ = _tokenizer_output(
            tokenizer,
            chunk.chunk_text,
            add_special_tokens=True,
        )
        if len(encoded) > max_chunk_tokens or len(encoded) > model_max_seq_length:
            raise ValueError("document chunk exceeds the model's effective input token limit")

    embeddings = []
    for batch_start in range(0, len(chunk_list), batch_size):
        batch = chunk_list[batch_start:batch_start + batch_size]
        encoded = model.encode(
            [chunk.chunk_text for chunk in batch],
            normalize_embeddings=True,
        )
        embeddings.extend(_validated_embedding_rows(encoded, len(batch)))
    return embeddings
