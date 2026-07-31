"""Canonical artifact vector selection and delivery mappings."""

from __future__ import annotations

from typing import Any

# Strict enums used for validation and schema prompts. Runtime selection is
# always driven by a category's explicit ``category_vectors`` declaration.
VALID_ARTIFACT_DELIVERY_METHODS: tuple[str, ...] = (
    "text_file",
    "document_pdf_hidden",
    "document_pdf_metadata",
    "document_pdf_visible",
    "document_pdf_background",
    "image_ocr",
    "image_background_ocr",
    "csv_injection",
    "audio_tts",
    "qr",
)

VALID_CATEGORY_VECTORS: tuple[str, ...] = (
    "text",
    "pdf_hidden",
    "pdf_metadata",
    "pdf_visible",
    "pdf",
    "image_text",
    "csv",
    "audio_tts",
    "qr",
)

# category_vector -> (payload generator, delivery/vector_type)
ARTIFACT_VECTOR_SPECS: dict[str, tuple[str, str]] = {
    "text": ("text", "text_file"),
    "csv": ("csv", "csv_injection"),
    "pdf_visible": ("pdf_visible", "document_pdf_visible"),
    "pdf_hidden": ("pdf_hidden", "document_pdf_hidden"),
    "pdf_metadata": ("pdf_metadata", "document_pdf_metadata"),
    "pdf": ("pdf", "document_pdf_background"),
    "image_text": ("image_text", "image_ocr"),
    "qr": ("qr", "qr"),
    "audio_tts": ("audio_tts", "audio_tts"),
}
VALID_ARTIFACT_VECTORS = tuple(ARTIFACT_VECTOR_SPECS)
ARTIFACT_GENERATOR_TYPES = tuple(
    generator for generator, _delivery in ARTIFACT_VECTOR_SPECS.values()
)


def _category_label(category: dict[str, Any]) -> str:
    return str(
        category.get("id")
        or category.get("name")
        or category.get("mandate")
        or "<unknown>"
    ).strip()


def artifact_vectors_for_category(category: dict[str, Any]) -> tuple[str, ...]:
    """Return validated artifact vectors declared by ``category_vectors``.

    Missing, empty, and unmapped declarations are configuration errors. In
    particular, text/code/url vectors are not file generators.
    """
    if not isinstance(category, dict):
        raise ValueError("Artifact vector selection requires a category object.")
    label = _category_label(category)
    if "category_vectors" not in category:
        raise ValueError(
            f"Artifact category '{label}' is missing required category_vectors."
        )
    raw = category.get("category_vectors")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError(
            f"Artifact category '{label}' must declare non-empty category_vectors."
        )

    vectors: list[str] = []
    unmapped: list[str] = []
    for value in raw:
        vector = str(value or "").strip()
        if not vector or vector not in ARTIFACT_VECTOR_SPECS:
            unmapped.append(vector or "<empty>")
        elif vector not in vectors:
            vectors.append(vector)
    if unmapped:
        raise ValueError(
            f"Artifact category '{label}' has unmapped category_vectors: "
            f"{', '.join(unmapped)}. Supported artifact vectors: "
            f"{', '.join(VALID_ARTIFACT_VECTORS)}. "
            "text, code, and url are not multimodal artifact generators."
        )
    if not vectors:
        raise ValueError(
            f"Artifact category '{label}' must select at least one artifact vector."
        )
    return tuple(vectors)


def artifact_generators_for_category(category: dict[str, Any]) -> tuple[str, ...]:
    """Map a category's validated vectors to payload generators."""
    return tuple(
        ARTIFACT_VECTOR_SPECS[vector][0]
        for vector in artifact_vectors_for_category(category)
    )


def artifact_delivery_methods_for_category(category: dict[str, Any]) -> tuple[str, ...]:
    """Map a category's validated vectors to delivery/vector_type values."""
    return tuple(
        ARTIFACT_VECTOR_SPECS[vector][1]
        for vector in artifact_vectors_for_category(category)
    )


def is_artifact_category(category: dict[str, Any]) -> bool:
    """Return whether the category explicitly declares the artifact channel."""
    return category.get("channel") == "artifact"
