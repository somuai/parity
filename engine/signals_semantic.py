"""Deterministic semantic-adjacent signals for Tier 2 matching.

The sentence-transformers dependency and model are loaded lazily: importing
this module never downloads a model or performs network I/O.  Callers can
inject an already constructed encoder in tests or in the batch runner.

An embedding failure may use a dependency-free lexical fallback, but that
fallback is always identified by ``backend == "lexical_fallback"`` and
``embedding_similarity is None``.  It must not be reported as an embedding
score in a match rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
import re
from typing import Any, Literal, Protocol, Sequence

from config.schema import CanonicalRecord


DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

_WHITESPACE_RE = re.compile(r"\s+")
_REFERENCE_NOISE_RE = re.compile(r"[^a-z0-9]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class SentenceEncoder(Protocol):
    """Small portion of SentenceTransformer's interface used here."""

    def encode(
        self,
        sentences: Sequence[str],
        *,
        normalize_embeddings: bool = False,
    ) -> Any: ...


SemanticBackend = Literal[
    "sentence_transformers",
    "fixed_test_encoder",
    "injected_encoder",
    "lexical_fallback",
    "no_text",
]


@dataclass(frozen=True, slots=True)
class SemanticSignalResult:
    """Semantic scores plus enough provenance for a grounded rationale.

    ``semantic_similarity`` is the usable description/counterparty score.
    ``embedding_similarity`` is populated only when an embedding model
    actually produced that score.  ``reference_similarity`` is ``None`` if
    either side has no usable reference, because missing evidence is not
    negative evidence.
    """

    semantic_similarity: float
    embedding_similarity: float | None
    reference_similarity: float | None
    backend: SemanticBackend
    model_name: str | None
    fallback_reason: str | None = None

    def as_signal_scores(self) -> dict[str, float]:
        """Return only numeric evidence suitable for ``MatchDecision``."""

        scores = {"semantic": self.semantic_similarity}
        if self.embedding_similarity is not None:
            scores["embedding_similarity"] = self.embedding_similarity
        if self.reference_similarity is not None:
            scores["reference_similarity"] = self.reference_similarity
        return scores


def normalize_text(value: str | None) -> str:
    """Normalize human-readable text without destroying token boundaries."""

    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value.casefold()).strip()


def normalize_reference(value: str | None) -> str:
    """Normalize formatting noise in identifiers while retaining characters."""

    return _REFERENCE_NOISE_RE.sub("", normalize_text(value))


def normalized_levenshtein_similarity(left: str, right: str) -> float:
    """Return ``1 - edit_distance / max_length`` in the closed interval [0, 1]."""

    if left == right:
        return 1.0
    if not left or not right:
        return 0.0

    # Keep the dynamic-programming row proportional to the shorter string.
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current

    return _bounded(1.0 - previous[-1] / max(len(left), len(right)))


def reference_similarity(left: str | None, right: str | None) -> float | None:
    """Score exact or typo-corrupted references; return None when one is missing."""

    normalized_left = normalize_reference(left)
    normalized_right = normalize_reference(right)
    if not normalized_left or not normalized_right:
        return None
    return normalized_levenshtein_similarity(normalized_left, normalized_right)


def lexical_semantic_similarity(left: str, right: str) -> float:
    """Dependency-free fallback for text, intentionally not called an embedding.

    Character edit similarity retains value for misspellings; token Jaccard
    captures reordered short narrations and counterparties.
    """

    normalized_left = normalize_text(left)
    normalized_right = normalize_text(right)
    if not normalized_left or not normalized_right:
        return 0.0

    character_score = normalized_levenshtein_similarity(
        normalized_left, normalized_right
    )
    left_tokens = set(_TOKEN_RE.findall(normalized_left))
    right_tokens = set(_TOKEN_RE.findall(normalized_right))
    union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(union) if union else 0.0
    return _bounded(0.5 * character_score + 0.5 * token_score)


def record_semantic_text(record: CanonicalRecord) -> str:
    """Build the embedding input with field labels to preserve field meaning."""

    parts: list[str] = []
    description = normalize_text(record.description)
    counterparty = normalize_text(record.counterparty)
    if description:
        parts.append(f"description: {description}")
    if counterparty:
        parts.append(f"counterparty: {counterparty}")
    return " | ".join(parts)


def embedding_similarity(
    left_text: str,
    right_text: str,
    *,
    encoder: SentenceEncoder,
) -> float:
    """Compute cosine similarity, clamped to [0, 1], from two embeddings."""

    if not normalize_text(left_text) or not normalize_text(right_text):
        return 0.0
    vectors = encoder.encode(
        [left_text, right_text],
        normalize_embeddings=True,
    )
    if len(vectors) != 2:
        raise ValueError("semantic encoder must return exactly two embeddings")
    left_vector = list(vectors[0])
    right_vector = list(vectors[1])
    if len(left_vector) != len(right_vector) or not left_vector:
        raise ValueError("semantic encoder returned incompatible embeddings")

    # Recompute norms rather than trusting an injected/test encoder to honor
    # normalize_embeddings=True.
    dot_product = sum(float(a) * float(b) for a, b in zip(left_vector, right_vector))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left_vector))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right_vector))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("semantic encoder returned a zero-length embedding")
    cosine = dot_product / (left_norm * right_norm)
    # Negative semantic correlation is no stronger than zero match evidence.
    return _bounded(cosine)


def score_semantic_pair(
    left: CanonicalRecord,
    right: CanonicalRecord,
    *,
    encoder: SentenceEncoder | None = None,
    encoder_backend: SemanticBackend | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    allow_lexical_fallback: bool = True,
) -> SemanticSignalResult:
    """Compute description/counterparty and corrupt-reference-aware signals.

    When no encoder is injected, SentenceTransformer is imported and
    instantiated here (never at module import time).  Set
    ``allow_lexical_fallback=False`` when model availability is mandatory.
    """

    left_text = record_semantic_text(left)
    right_text = record_semantic_text(right)
    ref_score = reference_similarity(left.reference, right.reference)

    if not left_text or not right_text:
        return SemanticSignalResult(
            semantic_similarity=0.0,
            embedding_similarity=None,
            reference_similarity=ref_score,
            backend="no_text",
            model_name=None,
            fallback_reason="one or both records have no description/counterparty text",
        )

    try:
        if encoder is None:
            resolved_encoder = _load_sentence_transformer(
                model_name, DEFAULT_MODEL_REVISION
            )
            resolved_backend: SemanticBackend = "sentence_transformers"
        else:
            resolved_encoder = encoder
            resolved_backend = _injected_encoder_backend(
                encoder, explicit_backend=encoder_backend
            )
        score = embedding_similarity(left_text, right_text, encoder=resolved_encoder)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        if not allow_lexical_fallback:
            raise RuntimeError(
                f"semantic embedding unavailable for model {model_name!r}"
            ) from exc
        return SemanticSignalResult(
            semantic_similarity=lexical_semantic_similarity(left_text, right_text),
            embedding_similarity=None,
            reference_similarity=ref_score,
            backend="lexical_fallback",
            model_name=None,
            fallback_reason=f"{type(exc).__name__}: {exc}",
        )

    return SemanticSignalResult(
        semantic_similarity=score,
        embedding_similarity=score,
        reference_similarity=ref_score,
        backend=resolved_backend,
        model_name=model_name if resolved_backend == "sentence_transformers" else None,
    )


# A descriptive alias for orchestration code that treats every signal module
# as a ``compute_*_signals`` function.
compute_semantic_signals = score_semantic_pair


@lru_cache(maxsize=2)
def _load_sentence_transformer(
    model_name: str, revision: str = DEFAULT_MODEL_REVISION
) -> SentenceEncoder:
    """Load each selected small model once per process, on first use only."""

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, revision=revision)


def _injected_encoder_backend(
    encoder: SentenceEncoder,
    *,
    explicit_backend: SemanticBackend | None,
) -> SemanticBackend:
    """Return honest provenance for injected encoders.

    Test doubles may expose ``semantic_backend``.  An injected real
    SentenceTransformer is recognized from its defining module; every other
    injected object is labeled generically unless the caller supplies a more
    specific non-production label.
    """

    requested = explicit_backend or getattr(
        encoder, "semantic_backend", "injected_encoder"
    )
    if requested not in {
        "sentence_transformers",
        "fixed_test_encoder",
        "injected_encoder",
    }:
        raise ValueError(f"invalid injected encoder backend: {requested!r}")
    is_real_sentence_transformer = type(encoder).__module__.startswith(
        "sentence_transformers"
    )
    if requested == "sentence_transformers" and not is_real_sentence_transformer:
        raise ValueError(
            "sentence_transformers backend requires a real SentenceTransformer"
        )
    if is_real_sentence_transformer:
        return "sentence_transformers"
    return requested


def _bounded(value: float) -> float:
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError("semantic score must be finite")
    return max(0.0, min(1.0, numeric_value))
