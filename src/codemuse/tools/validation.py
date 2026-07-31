"""Validate model-provided tool arguments before policy or execution."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


class ToolArgumentValidationError(ValueError):
    """Raised when a tool call does not satisfy its advertised JSON Schema."""

    def __init__(self, tool_name: str, errors: list[str]) -> None:
        self.tool_name = tool_name
        self.errors = tuple(errors)
        joined = "; ".join(errors)
        super().__init__(f"Invalid arguments for tool '{tool_name}': {joined}")


def validate_tool_arguments(tool_name: str, arguments: Any, schema: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a shallow copy of valid object arguments or raise a typed error."""
    errors: list[str] = []
    root_schema = dict(schema or {"type": "object"})
    _validate(arguments, root_schema, "$", root_schema, errors)
    if not isinstance(arguments, dict):
        if not errors:
            errors.append("$ must be an object")
    if errors:
        raise ToolArgumentValidationError(tool_name, errors)
    return dict(arguments)


def _validate(value: Any, schema: Any, path: str, root_schema: Mapping[str, Any], errors: list[str]) -> None:
    if isinstance(schema, bool):
        if not schema:
            errors.append(f"{path} is not allowed by the schema")
        return
    if not isinstance(schema, Mapping):
        errors.append(f"{path} has an invalid tool schema")
        return

    resolved = _resolve_ref(schema, root_schema)
    if resolved is None:
        errors.append(f"{path} references an unknown schema")
        return
    schema = resolved

    if "allOf" in schema:
        for candidate in _schema_list(schema["allOf"]):
            _validate(value, candidate, path, root_schema, errors)
    if "anyOf" in schema and not _matches_any(value, schema["anyOf"], path, root_schema, exactly_one=False):
        errors.append(f"{path} must match at least one allowed schema")
        return
    if "oneOf" in schema and not _matches_any(value, schema["oneOf"], path, root_schema, exactly_one=True):
        errors.append(f"{path} must match exactly one allowed schema")
        return
    if "not" in schema:
        nested_errors: list[str] = []
        _validate(value, schema["not"], path, root_schema, nested_errors)
        if not nested_errors:
            errors.append(f"{path} matches a forbidden schema")
            return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']!r}")

    expected = schema.get("type")
    if expected is not None and not _matches_type(value, expected):
        expected_text = ", ".join(expected) if isinstance(expected, list) else str(expected)
        errors.append(f"{path} must be of type {expected_text}; got {_json_type(value)}")
        return

    if isinstance(value, Mapping):
        _validate_object(value, schema, path, root_schema, errors)
    elif isinstance(value, list):
        _validate_array(value, schema, path, root_schema, errors)
    elif isinstance(value, str):
        _validate_string(value, schema, path, errors)
    elif _is_number(value):
        _validate_number(value, schema, path, errors)


def _validate_object(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
    path: str,
    root_schema: Mapping[str, Any],
    errors: list[str],
) -> None:
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for name in required:
        if name not in value:
            errors.append(f"{path}.{name} is required")
    for name, item in value.items():
        item_path = f"{path}.{name}"
        if name in properties:
            _validate(item, properties[name], item_path, root_schema, errors)
            continue
        additional = schema.get("additionalProperties", True)
        if additional is False:
            errors.append(f"{item_path} is not an allowed property")
        elif isinstance(additional, (Mapping, bool)):
            _validate(item, additional, item_path, root_schema, errors)
    _check_size(len(value), schema, path, errors, "Properties")


def _validate_array(
    value: list[Any],
    schema: Mapping[str, Any],
    path: str,
    root_schema: Mapping[str, Any],
    errors: list[str],
) -> None:
    _check_size(len(value), schema, path, errors, "Items")
    if schema.get("uniqueItems"):
        serialized = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
        if len(serialized) != len(set(serialized)):
            errors.append(f"{path} must contain unique items")
    prefix_items = schema.get("prefixItems")
    if isinstance(prefix_items, Sequence) and not isinstance(prefix_items, (str, bytes)):
        for index, item_schema in enumerate(prefix_items):
            if index < len(value):
                _validate(value[index], item_schema, f"{path}[{index}]", root_schema, errors)
        start = len(prefix_items)
    else:
        start = 0
    item_schema = schema.get("items")
    if item_schema is not None:
        for index in range(start, len(value)):
            _validate(value[index], item_schema, f"{path}[{index}]", root_schema, errors)


def _validate_string(value: str, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    minimum = schema.get("minLength")
    maximum = schema.get("maxLength")
    if minimum is not None and len(value) < int(minimum):
        errors.append(f"{path} must contain at least {minimum} characters")
    if maximum is not None and len(value) > int(maximum):
        errors.append(f"{path} must contain at most {maximum} characters")
    pattern = schema.get("pattern")
    if pattern is not None:
        try:
            matched = re.search(str(pattern), value) is not None
        except re.error:
            errors.append(f"{path} has an invalid pattern in its tool schema")
        else:
            if not matched:
                errors.append(f"{path} must match pattern {pattern!r}")


def _validate_number(value: int | float, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path} must be a finite number")
        return
    limits = (
        ("minimum", lambda actual, bound: actual >= bound, ">="),
        ("maximum", lambda actual, bound: actual <= bound, "<="),
        ("exclusiveMinimum", lambda actual, bound: actual > bound, ">"),
        ("exclusiveMaximum", lambda actual, bound: actual < bound, "<"),
    )
    for keyword, predicate, operator in limits:
        if keyword in schema and not predicate(value, schema[keyword]):
            errors.append(f"{path} must be {operator} {schema[keyword]}")
    multiple = schema.get("multipleOf")
    if multiple is not None and multiple != 0:
        quotient = value / multiple
        if not math.isclose(quotient, round(quotient), rel_tol=1e-9, abs_tol=1e-9):
            errors.append(f"{path} must be a multiple of {multiple}")


def _check_size(size: int, schema: Mapping[str, Any], path: str, errors: list[str], suffix: str) -> None:
    minimum = schema.get(f"min{suffix}")
    maximum = schema.get(f"max{suffix}")
    if minimum is not None and size < int(minimum):
        errors.append(f"{path} must contain at least {minimum} {suffix.lower()}")
    if maximum is not None and size > int(maximum):
        errors.append(f"{path} must contain at most {maximum} {suffix.lower()}")


def _matches_any(
    value: Any,
    candidates: Any,
    path: str,
    root_schema: Mapping[str, Any],
    *,
    exactly_one: bool,
) -> bool:
    matches = 0
    for candidate in _schema_list(candidates):
        nested_errors: list[str] = []
        _validate(value, candidate, path, root_schema, nested_errors)
        if not nested_errors:
            matches += 1
    return matches == 1 if exactly_one else matches > 0


def _schema_list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _resolve_ref(schema: Mapping[str, Any], root_schema: Mapping[str, Any]) -> Mapping[str, Any] | None:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    target: Any = root_schema
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, Mapping) or part not in target:
            return None
        target = target[part]
    if not isinstance(target, Mapping):
        return None
    return {**target, **{key: value for key, value in schema.items() if key != "$ref"}}


def _matches_type(value: Any, expected: Any) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    return any(
        {
            "object": lambda: isinstance(value, Mapping),
            "array": lambda: isinstance(value, list),
            "string": lambda: isinstance(value, str),
            "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda: _is_number(value),
            "boolean": lambda: isinstance(value, bool),
            "null": lambda: value is None,
        }.get(str(name), lambda: False)()
        for name in names
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _json_type(value: Any) -> str:
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__
