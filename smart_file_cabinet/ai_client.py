"""Utilities for interacting with the OpenAI API using the 1.x SDK."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional

from openai import APIError, OpenAI


class OpenAIClientError(RuntimeError):
    """Raised when the OpenAI client fails to complete a request."""


@dataclass(slots=True)
class DocumentClassification:
    """Structured result for document classification."""

    doc_type: str
    confidence: float
    raw_response: Mapping[str, Any]


@dataclass(slots=True)
class ExtractionResult:
    """Structured result for field extraction."""

    fields: Mapping[str, Any]
    raw_response: Mapping[str, Any]


@dataclass(slots=True)
class SummaryResult:
    """Structured result for generated summaries."""

    summary: str
    actions: List[str]
    raw_response: Mapping[str, Any]


def _default_json_loads(text: str) -> Mapping[str, Any]:
    """Attempt to parse JSON content, raising a descriptive error on failure."""

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise OpenAIClientError("The OpenAI response did not contain valid JSON.") from exc


class BusinessHubAI:
    """High-level helper for SmartFileCabinet's AI-powered workflows.

    The helper encapsulates the OpenAI Python SDK (v1.x) usage and provides
    small convenience wrappers for:

    * Document classification
    * Structured field extraction (invoice schema)
    * Business-oriented summarisation
    * Embedding generation for semantic recall
    """

    def __init__(
        self,
        *,
        client: Optional[OpenAI] = None,
        model: str = "gpt-4.1-mini",
        extraction_model: Optional[str] = None,
        embedding_model: str = "text-embedding-3-large",
        temperature: float = 0.2,
    ) -> None:
        self._client = client or OpenAI()
        self._model = model
        self._extraction_model = extraction_model or model
        self._embedding_model = embedding_model
        self._temperature = temperature

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    def _create_response(
        self,
        *,
        messages: Iterable[Mapping[str, Any]],
        model_override: Optional[str] = None,
        tools: Optional[List[Mapping[str, Any]]] = None,
    ) -> Mapping[str, Any]:
        """Invoke the Responses API and return the serialisable payload."""

        model = model_override or self._model
        try:
            response = self._client.responses.create(
                model=model,
                input=list(messages),
                temperature=self._temperature,
                tools=tools,
            )
        except APIError as exc:  # pragma: no cover - network error path
            raise OpenAIClientError(str(exc)) from exc

        return response.model_dump()

    @staticmethod
    def _collect_text_outputs(response: Mapping[str, Any]) -> str:
        """Collect all textual blocks from a Responses payload."""

        output = response.get("output") or []
        texts: List[str] = []
        for item in output:
            if item.get("type") == "output_text":
                content = item.get("content") or []
                for block in content:
                    if block.get("type") == "output_text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "text":  # compatibility with SDK 1.0.0
                        texts.append(block.get("text", ""))
            elif item.get("type") == "message":  # fallback format
                content = item.get("content") or []
                for block in content:
                    if block.get("type") == "output_text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "text":
                        texts.append(block.get("text", ""))
        if texts:
            return "\n".join(part.strip() for part in texts if part.strip())
        # final fallback to helper property
        maybe_text = response.get("output_text")
        if isinstance(maybe_text, str):
            return maybe_text.strip()
        raise OpenAIClientError("No textual content returned from Responses API.")

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------
    def classify_document(self, ocr_text: str) -> DocumentClassification:
        """Classify a document into a supported SmartFileCabinet type."""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict document classifier. "
                    "Return JSON with keys type and confidence."
                ),
            },
            {
                "role": "user",
                "content": ocr_text.strip(),
            },
        ]
        response = self._create_response(messages=messages)
        content = self._collect_text_outputs(response)
        parsed = _default_json_loads(content)
        doc_type = str(parsed.get("type", "other"))
        confidence = float(parsed.get("confidence", 0.0))
        return DocumentClassification(doc_type=doc_type, confidence=confidence, raw_response=parsed)

    def extract_invoice_fields(self, ocr_text: str) -> ExtractionResult:
        """Extract structured invoice fields as JSON."""

        messages = [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON with invoice fields. "
                    "Keys: vendor, invoice_number, invoice_date, due_date, currency, "
                    "total, tax, payment_terms, line_items (list of objects)."
                ),
            },
            {
                "role": "user",
                "content": ocr_text.strip(),
            },
        ]
        response = self._create_response(messages=messages, model_override=self._extraction_model)
        content = self._collect_text_outputs(response)
        parsed = _default_json_loads(content)
        return ExtractionResult(fields=parsed, raw_response=response)

    def summarise(self, ocr_text: str) -> SummaryResult:
        """Generate a compact summary and actionable list for a document."""

        messages = [
            {
                "role": "system",
                "content": (
                    "Summarise the following document for a business owner in 120 words or less. "
                    "Return JSON with keys summary and actions (array of strings)."
                ),
            },
            {
                "role": "user",
                "content": ocr_text.strip(),
            },
        ]
        response = self._create_response(messages=messages)
        content = self._collect_text_outputs(response)
        parsed = _default_json_loads(content)
        summary = str(parsed.get("summary", ""))
        actions_raw = parsed.get("actions") or []
        actions = [str(item) for item in actions_raw if isinstance(item, str)]
        return SummaryResult(summary=summary, actions=actions, raw_response=response)

    def create_embeddings(self, *, texts: Iterable[str]) -> List[List[float]]:
        """Generate embeddings for downstream semantic recall."""

        payload = [text.strip() for text in texts if text.strip()]
        if not payload:
            return []
        try:
            response = self._client.embeddings.create(
                model=self._embedding_model,
                input=payload,
            )
        except APIError as exc:  # pragma: no cover - network error path
            raise OpenAIClientError(str(exc)) from exc
        return [item.embedding for item in response.data]


__all__ = [
    "BusinessHubAI",
    "DocumentClassification",
    "ExtractionResult",
    "OpenAIClientError",
    "SummaryResult",
]
