import hashlib
import math
import os
import unittest
from unittest.mock import Mock, patch

from app.services import rag_service
from app.services.scholarship_document_indexing import (
    DocumentChunk,
    DocumentInputTooLargeError,
    MAX_DOCUMENT_INPUT_CHARS,
    chunk_document_text,
    generate_document_embeddings,
)

TEST_REVISION = "0123456789ABCDEF0123456789ABCDEF01234567"


class FakeTokenizer:
    model_max_length = 16
    special_tokens = 2

    def num_special_tokens_to_add(self, pair=False):
        return self.special_tokens

    def __call__(
        self,
        text,
        *,
        add_special_tokens=True,
        truncation=False,
        return_offsets_mapping=False,
    ):
        offsets = [(index, index + 1) for index, char in enumerate(text) if not char.isspace()]
        input_ids = [index + 10 for index in range(len(offsets))]
        if add_special_tokens:
            input_ids = [1] + input_ids + [2]
        result = {"input_ids": input_ids}
        if return_offsets_mapping:
            result["offset_mapping"] = offsets
        return result


class SingleTokenTokenizer:
    model_max_length = 512

    def __init__(self):
        self.calls = 0

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(
        self,
        text,
        *,
        add_special_tokens=True,
        truncation=False,
        return_offsets_mapping=False,
    ):
        self.calls += 1
        input_ids = [100]
        if add_special_tokens:
            input_ids = [101] + input_ids + [102]
        result = {"input_ids": input_ids}
        if return_offsets_mapping:
            result["offset_mapping"] = [(0, len(text))]
        return result


class DocumentChunkingTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer = FakeTokenizer()

    def chunk(self, text, *, token_limit=8, overlap=2, model_limit=16):
        return chunk_document_text(
            text,
            tokenizer=self.tokenizer,
            model_max_seq_length=model_limit,
            max_chunk_tokens=token_limit,
            overlap_tokens=overlap,
        )

    def assert_exact_offsets(self, text, chunks):
        for chunk in chunks:
            self.assertEqual(text[chunk.start_offset:chunk.end_offset], chunk.chunk_text)

    def test_empty_and_whitespace_only_text_are_rejected_without_loading_model(self):
        with patch.object(rag_service, "_load_model") as load_model:
            for text in ("", " \t\n"):
                with self.subTest(text=repr(text)):
                    with self.assertRaises(ValueError):
                        chunk_document_text(text)
        load_model.assert_not_called()

    def test_short_text_is_preserved_in_one_chunk(self):
        text = "  Scholarship details: tuition and housing. \n"
        chunks = self.chunk(text, token_limit=64, overlap=24, model_limit=80)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_text, text)
        self.assertEqual((chunks[0].start_offset, chunks[0].end_offset), (0, len(text)))

    def test_document_input_just_below_and_at_limit_is_preserved(self):
        for length in (MAX_DOCUMENT_INPUT_CHARS - 1, MAX_DOCUMENT_INPUT_CHARS):
            with self.subTest(length=length):
                text = "x" * length
                tokenizer = SingleTokenTokenizer()
                chunks = chunk_document_text(
                    text,
                    tokenizer=tokenizer,
                    model_max_seq_length=tokenizer.model_max_length,
                )

                self.assertEqual(len(chunks), 1)
                self.assertEqual(chunks[0].chunk_text, text)
                self.assertEqual((chunks[0].start_offset, chunks[0].end_offset), (0, length))
                self.assertGreater(tokenizer.calls, 0)

    def test_document_input_above_limit_is_rejected_before_tokenization_or_model_load(self):
        tokenizer = SingleTokenTokenizer()
        with patch.object(rag_service, "_load_model_with_revision") as load_model:
            with self.assertRaisesRegex(DocumentInputTooLargeError, str(MAX_DOCUMENT_INPUT_CHARS)):
                chunk_document_text(
                    "x" * (MAX_DOCUMENT_INPUT_CHARS + 1),
                    tokenizer=tokenizer,
                    model_max_seq_length=tokenizer.model_max_length,
                )

        self.assertEqual(tokenizer.calls, 0)
        load_model.assert_not_called()

    def test_token_dense_text_is_bounded_by_token_limit(self):
        text = "abcdefghijklmnopqrs!!!uvwxyz"
        chunks = self.chunk(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(
            len(self.tokenizer(chunk.chunk_text, add_special_tokens=True)["input_ids"]) <= 8
            for chunk in chunks
        ))
        self.assert_exact_offsets(text, chunks)

    def test_long_words_and_punctuation_are_split_on_token_boundaries(self):
        text = "supercalifragilisticexpialidocious" + "!?.,:;" * 8
        chunks = self.chunk(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.chunk_text) <= 6 for chunk in chunks))
        self.assert_exact_offsets(text, chunks)

    def test_unicode_text_keeps_exact_python_character_offsets(self):
        text = " A雪🙂e\u0301B Z "
        chunks = self.chunk(text)

        self.assert_exact_offsets(text, chunks)
        self.assertEqual(chunks[0].start_offset, 0)
        self.assertEqual(chunks[-1].end_offset, len(text))

    def test_token_overlap_is_deterministic_and_preserves_ordinals_and_hashes(self):
        text = "abcdefghijklmno"
        first = self.chunk(text)
        second = self.chunk(text)

        self.assertEqual(first, second)
        self.assertEqual([chunk.ordinal for chunk in first], list(range(len(first))))
        for previous, current in zip(first, first[1:]):
            self.assertEqual(previous.end_offset - current.start_offset, 2)
        for chunk in first:
            self.assertEqual(
                chunk.chunk_hash,
                hashlib.sha256(chunk.chunk_text.encode("utf-8")).hexdigest(),
            )

    def test_special_tokens_are_included_in_the_configured_total_limit(self):
        text = "abcdefghijkl"
        chunks = self.chunk(text, token_limit=8, overlap=1, model_limit=12)

        self.assertTrue(all(
            len(self.tokenizer(chunk.chunk_text, add_special_tokens=True)["input_ids"]) <= 8
            for chunk in chunks
        ))
        self.assertEqual(self.tokenizer.num_special_tokens_to_add(pair=False), 2)
        self.assertEqual(len(chunks[0].chunk_text), 6)

    def test_configured_limit_must_be_below_model_maximum(self):
        with self.assertRaisesRegex(ValueError, "below the model maximum"):
            self.chunk("some text", token_limit=16, model_limit=16)

    def test_chunking_with_injected_tokenizer_does_not_load_model(self):
        with patch.object(rag_service, "_load_model") as load_model:
            self.chunk("tokenizer injection keeps tests local")
        load_model.assert_not_called()

    def test_explicit_revision_is_used_for_chunking_when_configuration_changes(self):
        model = Mock(tokenizer=self.tokenizer, max_seq_length=self.tokenizer.model_max_length)
        changed_revision = "fedcba9876543210fedcba9876543210fedcba98"
        with patch.object(
            rag_service,
            "get_model_revision",
            side_effect=[TEST_REVISION, changed_revision],
        ) as get_model_revision, patch.object(
            rag_service,
            "_load_model_with_revision",
            return_value=(model, TEST_REVISION.lower()),
        ) as load_model:
            chunks = chunk_document_text(
                "revision stays fixed",
                model_revision=TEST_REVISION,
                max_chunk_tokens=12,
                overlap_tokens=2,
            )

        self.assertTrue(chunks)
        get_model_revision.assert_not_called()
        load_model.assert_called_once_with(TEST_REVISION.lower())


class DocumentEmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer = FakeTokenizer()

    def _chunks(self, count):
        return [
            DocumentChunk(index, f"chunk-{index}", str(index) * 64, index, index + 1)
            for index in range(count)
        ]

    @staticmethod
    def _unit_vector(index):
        vector = [0.0] * 384
        vector[index] = 1.0
        return vector

    def _model(self):
        model = Mock()
        model.tokenizer = self.tokenizer
        model.max_seq_length = self.tokenizer.model_max_length
        return model

    def test_missing_and_invalid_model_revision_are_rejected(self):
        chunks = self._chunks(1)
        for revision in (None, "main", "abc"):
            with self.subTest(revision=revision):
                env = {} if revision is None else {"MINILM_MODEL_REVISION": revision}
                with patch.dict(os.environ, env, clear=False):
                    if revision is None:
                        os.environ.pop("MINILM_MODEL_REVISION", None)
                    with self.assertRaises(rag_service.RagUnavailable):
                        generate_document_embeddings(chunks)

    def test_batch_output_aligns_with_chunks_and_loads_model_once(self):
        chunks = self._chunks(5)
        model = self._model()
        model.encode.side_effect = [
            [self._unit_vector(index) for index in range(2)],
            [self._unit_vector(index) for index in range(2, 4)],
            [self._unit_vector(4)],
        ]
        with patch.dict(os.environ, {"MINILM_MODEL_REVISION": TEST_REVISION}), \
                patch.object(
                    rag_service,
                    "_load_model_with_revision",
                    return_value=(model, TEST_REVISION.lower()),
                ) as load_model:
            embeddings = generate_document_embeddings(chunks, batch_size=2, max_chunk_tokens=12)

        self.assertEqual([max(range(384), key=vector.__getitem__) for vector in embeddings], list(range(5)))
        self.assertEqual(
            [call.args[0] for call in model.encode.call_args_list],
            [["chunk-0", "chunk-1"], ["chunk-2", "chunk-3"], ["chunk-4"]],
        )
        self.assertTrue(all(call.kwargs["normalize_embeddings"] for call in model.encode.call_args_list))
        load_model.assert_called_once_with(TEST_REVISION.lower())

    def test_explicit_revision_is_used_when_configuration_changes(self):
        chunks = self._chunks(1)
        model = self._model()
        model.encode.return_value = [self._unit_vector(0)]
        changed_revision = "fedcba9876543210fedcba9876543210fedcba98"
        with patch.object(
            rag_service,
            "get_model_revision",
            side_effect=[TEST_REVISION, changed_revision],
        ) as get_model_revision, patch.object(
            rag_service,
            "_load_model_with_revision",
            return_value=(model, TEST_REVISION.lower()),
        ) as load_model:
            generate_document_embeddings(chunks, model_revision=TEST_REVISION, max_chunk_tokens=12)

        get_model_revision.assert_not_called()
        load_model.assert_called_once_with(TEST_REVISION.lower())

    def test_loaded_model_revision_must_match_explicit_revision(self):
        model = self._model()
        changed_revision = "fedcba9876543210fedcba9876543210fedcba98"
        with patch.object(
            rag_service,
            "_load_model_with_revision",
            return_value=(model, changed_revision),
        ):
            with self.assertRaisesRegex(rag_service.RagUnavailable, "does not match"):
                generate_document_embeddings(self._chunks(1), model_revision=TEST_REVISION)

    def test_wrong_embedding_dimensions_are_rejected(self):
        model = self._model()
        model.encode.return_value = [[1.0] * 383]
        with patch.dict(os.environ, {"MINILM_MODEL_REVISION": TEST_REVISION}), \
                patch.object(
                    rag_service,
                    "_load_model_with_revision",
                    return_value=(model, TEST_REVISION.lower()),
                ):
            with self.assertRaisesRegex(ValueError, "dimensions"):
                generate_document_embeddings(self._chunks(1), max_chunk_tokens=12)

    def test_nan_and_infinite_embedding_values_are_rejected(self):
        for invalid_value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=invalid_value):
                vector = self._unit_vector(0)
                vector[1] = invalid_value
                model = self._model()
                model.encode.return_value = [vector]
                with patch.dict(os.environ, {"MINILM_MODEL_REVISION": TEST_REVISION}), \
                        patch.object(
                            rag_service,
                            "_load_model_with_revision",
                            return_value=(model, TEST_REVISION.lower()),
                        ):
                    with self.assertRaisesRegex(ValueError, "non-finite"):
                        generate_document_embeddings(self._chunks(1), max_chunk_tokens=12)

    def test_unnormalized_embedding_is_rejected(self):
        model = self._model()
        model.encode.return_value = [[2.0] + [0.0] * 383]
        with patch.dict(os.environ, {"MINILM_MODEL_REVISION": TEST_REVISION}), \
                patch.object(
                    rag_service,
                    "_load_model_with_revision",
                    return_value=(model, TEST_REVISION.lower()),
                ):
            with self.assertRaisesRegex(ValueError, "not normalized"):
                generate_document_embeddings(self._chunks(1), max_chunk_tokens=12)

    def test_oversized_chunk_is_rejected_before_encoding(self):
        model = self._model()
        chunk = DocumentChunk(0, "abcdefghijk", "a" * 64, 0, 11)
        with patch.dict(os.environ, {"MINILM_MODEL_REVISION": TEST_REVISION}), \
                patch.object(
                    rag_service,
                    "_load_model_with_revision",
                    return_value=(model, TEST_REVISION.lower()),
                ):
            with self.assertRaisesRegex(ValueError, "exceeds the model"):
                generate_document_embeddings([chunk], max_chunk_tokens=8)
        model.encode.assert_not_called()

    def test_model_loading_failure_is_propagated(self):
        with patch.dict(os.environ, {"MINILM_MODEL_REVISION": TEST_REVISION}), \
                patch.object(
                    rag_service,
                    "_load_model_with_revision",
                    side_effect=OSError("model unavailable"),
                ):
            with self.assertRaisesRegex(OSError, "model unavailable"):
                generate_document_embeddings(self._chunks(1))

    def test_empty_batch_returns_without_loading_model(self):
        with patch.object(rag_service, "_load_model") as load_model:
            self.assertEqual(generate_document_embeddings([]), [])
        load_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
