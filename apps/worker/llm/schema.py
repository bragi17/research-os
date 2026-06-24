"""JSON-schema helpers for structured LLM output."""

from typing import Any

from pydantic import BaseModel, Field, create_model


def json_schema_to_pydantic(schema: dict[str, Any]) -> type[BaseModel]:
    """
    Convert a JSON schema dict to a dynamic Pydantic model.

    Handles common types: string, number, integer, boolean, array, object.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for name, prop in properties.items():
        field_type = _resolve_type(prop)
        if name in required:
            fields[name] = (field_type, ...)
        else:
            fields[name] = (field_type, Field(default=None))

    if not fields:
        fields["data"] = (dict[str, Any], Field(default_factory=dict))

    return create_model("DynamicSchema", **fields)


def _resolve_type(prop: dict[str, Any]) -> type:
    """Resolve a JSON schema property to a Python type."""
    schema_type = prop.get("type", "string")
    if schema_type == "string":
        return str | None
    if schema_type == "number":
        return float | None
    if schema_type == "integer":
        return int | None
    if schema_type == "boolean":
        return bool | None
    if schema_type == "array":
        return list[Any]
    if schema_type == "object":
        return dict[str, Any]
    return str | None


def build_generic_model_from_prompt(messages: list[dict[str, str]]) -> type[BaseModel]:
    """
    Infer expected JSON keys from a system prompt and build a Pydantic model.

    Looks for prompt patterns such as "- key_name: type".
    """
    system_content = ""
    for msg in messages:
        if msg["role"] == "system":
            system_content = msg["content"]
            break

    fields: dict[str, Any] = {}
    key_pattern = re_find_schema_keys(system_content)
    for name, type_hint in key_pattern:
        normalized = type_hint.lower()
        if "list" in normalized or "[" in type_hint or "array" in normalized:
            fields[name] = (list[Any], Field(default_factory=list))
        elif normalized in ("str", "string"):
            fields[name] = (str, Field(default=""))
        elif normalized in ("int", "integer", "float", "number"):
            fields[name] = (float | None, Field(default=None))
        elif normalized in ("bool",):
            fields[name] = (bool, Field(default=False))
        elif normalized in ("dict", "object"):
            fields[name] = (dict[str, Any], Field(default_factory=dict))
        else:
            fields[name] = (str | None, Field(default=None))

    if not fields:
        fields["result"] = (dict[str, Any], Field(default_factory=dict))
        fields["items"] = (list[Any], Field(default_factory=list))
        fields["summary"] = (str, Field(default=""))

    return create_model("InferredOutput", **fields)


def re_find_schema_keys(system_content: str) -> list[tuple[str, str]]:
    """Extract simple '- key: type' schema hints from a prompt."""
    import re

    return re.findall(
        r"[-*]\s+(\w+):\s+(str|string|int|float|number|bool|\[.*?\]|list|array|dict|object)",
        system_content,
        re.IGNORECASE,
    )
