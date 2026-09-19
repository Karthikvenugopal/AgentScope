"""Accept JSON surrounded by prose/fences; never guess a review decision."""

import json

from pydantic import BaseModel, ValidationError


def structured_output[T: BaseModel](text: str, schema: type[T]) -> T:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text[:65536]):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
            if isinstance(value, dict):
                value = _normalize_explanatory_fields(value, schema.__name__)
            return schema.model_validate(value)
        except (ValueError, ValidationError):
            continue
    raise ValueError(f"No valid {schema.__name__} object in role output")


def _normalize_explanatory_fields(value: dict[str, object], schema_name: str) -> dict[str, object]:
    """Keep decisions strict while tolerating richer prose-shaped explanations."""
    normalized = dict(value)
    text_fields = {"Plan": ("analysis",), "Review": ("rationale",)}.get(schema_name, ())
    list_fields = {
        "Plan": ("steps", "files_likely_relevant"),
        "Review": ("issues", "suggested_changes"),
    }.get(schema_name, ())
    for field in text_fields:
        current = normalized.get(field)
        if current is not None and not isinstance(current, str):
            normalized[field] = json.dumps(current, sort_keys=True)
    for field in list_fields:
        current = normalized.get(field)
        if isinstance(current, list):
            normalized[field] = [
                item if isinstance(item, str) else json.dumps(item, sort_keys=True)
                for item in current
            ]
    return normalized
