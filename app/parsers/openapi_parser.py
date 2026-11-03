"""OpenAPI 3.x / Swagger 2.0 specification parser.

* YAML is loaded with ``yaml.safe_load`` (no arbitrary object construction).
* Local ``$ref`` pointers are resolved with cycle protection.
* Spec validity is checked with ``openapi-spec-validator``; validation problems
  are reported as warnings so that slightly invalid specs can still be audited.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import urlparse

import yaml

from app.core.logging_config import get_logger
from app.core.models import ApiModel, EndpointSpec, Parameter, ResponseSpec, SchemaField
from app.nlp.text_normalization import (
    HTTP_METHODS,
    canonical_path,
    normalize_identifier,
    normalize_type,
    normalize_whitespace,
    path_template,
)
from app.parsers.blocks import DocumentParseError

logger = get_logger(__name__)

MAX_SCHEMA_DEPTH = 6
_SCHEME_TYPES = {"apikey": "api_key", "oauth2": "oauth2", "openidconnect": "openid_connect"}


def load_spec_document(data: bytes, source_name: str) -> dict[str, Any]:
    """Decode JSON or YAML bytes into a dictionary."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("The specification is not valid UTF-8 text.") from exc
    if not text.strip():
        raise DocumentParseError("The specification file is empty.")
    is_json = source_name.lower().endswith(".json")
    try:
        spec = json.loads(text) if is_json else yaml.safe_load(text)
    except json.JSONDecodeError as exc:
        raise DocumentParseError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise DocumentParseError(f"Invalid YAML{where}: {getattr(exc, 'problem', exc)}") from exc
    if not isinstance(spec, dict):
        raise DocumentParseError("The specification must be a JSON/YAML object at the top level.")
    if "openapi" not in spec and "swagger" not in spec:
        raise DocumentParseError("Not an OpenAPI document: missing 'openapi' (3.x) or 'swagger' (2.0) field.")
    if not isinstance(spec.get("paths"), dict):
        raise DocumentParseError("The specification has no 'paths' object.")
    return spec


def _validate(spec: dict[str, Any]) -> list[str]:
    try:
        from openapi_spec_validator import validate

        validate(spec)
        return []
    except ImportError:  # pragma: no cover
        return []
    except Exception as exc:  # noqa: BLE001 - any validation failure becomes a warning
        message = normalize_whitespace(str(getattr(exc, "message", exc)))[:300]
        return [f"Specification does not fully conform to the OpenAPI schema: {message}"]


class _RefResolver:
    def __init__(self, root: dict[str, Any]) -> None:
        self.root = root

    def resolve(self, node: Any, seen: frozenset[str] = frozenset()) -> tuple[Any, frozenset[str]]:
        """Follow ``$ref`` chains. Returns the target and the set of refs visited (for cycle detection)."""
        while isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen:
                return {}, seen
            seen = seen | {ref}
            target: Any = self.root
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                target = target.get(part, {}) if isinstance(target, dict) else {}
            node = target
        return node, seen


def _schema_type(schema: dict[str, Any]) -> Optional[str]:
    raw = schema.get("type")
    if isinstance(raw, list):  # OpenAPI 3.1 allows ["string", "null"]
        raw = next((t for t in raw if t != "null"), None)
    if raw:
        return normalize_type(str(raw))
    if "properties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return None


def _raw_type(schema: dict[str, Any]) -> str:
    raw = schema.get("type", "")
    if isinstance(raw, list):
        raw = "/".join(raw)
    fmt = schema.get("format")
    return f"{raw} ({fmt})" if raw and fmt else str(raw or "")


class SchemaFlattener:
    """Flatten a JSON schema into dotted field paths (``items[].sku``)."""

    def __init__(self, resolver: _RefResolver) -> None:
        self.resolver = resolver

    def _merge(self, schema: Any, seen: frozenset[str]) -> tuple[dict[str, Any], frozenset[str]]:
        schema, seen = self.resolver.resolve(schema, seen)
        if not isinstance(schema, dict):
            return {}, seen
        if "allOf" in schema:
            merged: dict[str, Any] = {k: v for k, v in schema.items() if k != "allOf"}
            props = dict(merged.get("properties", {}))
            required = list(merged.get("required", []))
            for part in schema["allOf"]:
                sub, seen = self._merge(part, seen)
                props.update(sub.get("properties", {}))
                required.extend(sub.get("required", []))
                merged.setdefault("type", sub.get("type"))
            merged["properties"], merged["required"] = props, required
            return merged, seen
        for key in ("oneOf", "anyOf"):
            if key in schema and schema[key]:
                # Compare against the first alternative; documented as a known limitation.
                first, seen = self._merge(schema[key][0], seen)
                return {**{k: v for k, v in schema.items() if k != key}, **first}, seen
        return schema, seen

    def root_type(self, schema: Any) -> Optional[str]:
        merged, _ = self._merge(schema, frozenset())
        return _schema_type(merged) if merged else None

    def flatten(self, schema: Any, prefix: str = "", seen: frozenset[str] = frozenset(),
                depth: int = 0, parent_required: bool = True) -> list[SchemaField]:
        merged, seen = self._merge(schema, seen)
        if not merged or depth > MAX_SCHEMA_DEPTH:
            return []
        if _schema_type(merged) == "array" and not prefix:
            # Root arrays: describe the item structure without a prefix.
            return self.flatten(merged.get("items", {}), "", seen, depth + 1)
        fields: list[SchemaField] = []
        required = set(merged.get("required", []) or [])
        for name, prop in (merged.get("properties") or {}).items():
            prop_merged, prop_seen = self._merge(prop, seen)
            path = f"{prefix}{name}"
            ftype = _schema_type(prop_merged)
            fields.append(SchemaField(
                path=path, normalized_path=normalize_field_path(path), name=name, type=ftype,
                raw_type=_raw_type(prop_merged), required=name in required and parent_required,
                description=normalize_whitespace(prop_merged.get("description", "")),
                evidence=f"schema property '{path}'",
            ))
            if ftype == "object":
                fields.extend(self.flatten(prop_merged, f"{path}.", prop_seen, depth + 1, name in required))
            elif ftype == "array":
                items, item_seen = self._merge(prop_merged.get("items", {}), prop_seen)
                if _schema_type(items) == "object":
                    fields.extend(self.flatten(items, f"{path}[].", item_seen, depth + 1, name in required))
        return fields


def normalize_field_path(path: str) -> str:
    """Normalize each segment of a dotted field path, keeping array markers."""
    out = []
    for seg in path.split("."):
        is_array = seg.endswith("[]")
        base = normalize_identifier(seg[:-2] if is_array else seg)
        out.append(base + ("[]" if is_array else ""))
    return ".".join(out)


def _security_methods(requirements: Any, schemes: dict[str, str]) -> Optional[list[str]]:
    if requirements is None:
        return None
    methods: list[str] = []
    for requirement in requirements or []:
        for name in (requirement or {}):
            method = schemes.get(name)
            if method and method not in methods:
                methods.append(method)
    return methods


def _security_schemes(spec: dict[str, Any]) -> dict[str, str]:
    raw = spec.get("components", {}).get("securitySchemes") or spec.get("securityDefinitions") or {}
    schemes: dict[str, str] = {}
    for name, scheme in raw.items():
        if not isinstance(scheme, dict):
            continue
        stype = str(scheme.get("type", "")).lower()
        if stype == "http":
            schemes[name] = "bearer" if str(scheme.get("scheme", "")).lower() == "bearer" else str(scheme.get("scheme", "basic")).lower()
        elif stype == "basic":
            schemes[name] = "basic"
        else:
            schemes[name] = _SCHEME_TYPES.get(stype, stype)
    return schemes


def _base_path(spec: dict[str, Any]) -> str:
    if "basePath" in spec:
        return canonical_path(spec["basePath"])
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict) and servers[0].get("url"):
        path = urlparse(str(servers[0]["url"])).path
        return canonical_path(path) if path and path != "/" else ""
    return ""


def _parse_parameter(raw: dict[str, Any], resolver: _RefResolver, location_ref: str) -> Optional[Parameter]:
    param, _ = resolver.resolve(raw)
    if not isinstance(param, dict) or "name" not in param:
        return None
    schema, _ = resolver.resolve(param.get("schema", param))  # Swagger 2 keeps type on the parameter
    location = str(param.get("in", "")).lower()
    return Parameter(
        name=str(param["name"]), normalized_name=normalize_identifier(str(param["name"])),
        location=location or None, type=_schema_type(schema) if isinstance(schema, dict) else None,
        raw_type=_raw_type(schema) if isinstance(schema, dict) else None,
        required=bool(param.get("required", location == "path")),
        description=normalize_whitespace(param.get("description", "")),
        evidence=f"{location_ref} parameter '{param['name']}' (in: {location})",
    )


def _pick_json_schema(content: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not content:
        return None
    for media, body in content.items():
        if "json" in media.lower():
            return (body or {}).get("schema")
    first = next(iter(content.values()))
    return (first or {}).get("schema")


def parse_openapi(data: bytes, source_name: str = "openapi.yaml") -> ApiModel:
    spec = load_spec_document(data, source_name)
    resolver = _RefResolver(spec)
    flattener = SchemaFlattener(resolver)
    schemes = _security_schemes(spec)
    global_security = _security_methods(spec.get("security"), schemes)
    info = spec.get("info") or {}

    model = ApiModel(
        title=str(info.get("title", "")), version=str(info.get("version", "")),
        base_path=_base_path(spec), source_name=source_name,
        source_type="openapi-json" if source_name.lower().endswith(".json") else "openapi-yaml",
        auth_methods=sorted(set(schemes.values())), global_security=global_security,
        warnings=_validate(spec),
    )

    for raw_path, path_item in spec["paths"].items():
        path_item, _ = resolver.resolve(path_item)
        if not isinstance(path_item, dict):
            continue
        path = canonical_path(str(raw_path))
        shared = [p for p in (path_item.get("parameters") or [])]
        for method, op in path_item.items():
            if method.upper() not in HTTP_METHODS or not isinstance(op, dict):
                continue
            ref = f"paths.{raw_path}.{method}"
            params: dict[tuple[str, str], Parameter] = {}
            request_fields: list[SchemaField] = []
            request_root: Optional[str] = None
            for raw in shared + list(op.get("parameters") or []):
                resolved, _ = resolver.resolve(raw)
                if isinstance(resolved, dict) and resolved.get("in") in ("body", "formData"):
                    # Swagger 2.0 request body
                    if resolved.get("in") == "body":
                        request_root = flattener.root_type(resolved.get("schema", {}))
                        request_fields = flattener.flatten(resolved.get("schema", {}))
                    else:
                        p = _parse_parameter(resolved, resolver, ref)
                        if p:
                            request_fields.append(SchemaField(path=p.name, normalized_path=p.normalized_name,
                                                              name=p.name, type=p.type, raw_type=p.raw_type,
                                                              required=p.required, description=p.description,
                                                              evidence=p.evidence))
                    continue
                p = _parse_parameter(raw, resolver, ref)
                if p:
                    params[(p.normalized_name, p.location or "")] = p  # operation-level overrides path-level

            body, _ = resolver.resolve(op.get("requestBody"))
            if isinstance(body, dict) and body:
                schema = _pick_json_schema(body.get("content") or {})
                if schema is not None:
                    request_root = flattener.root_type(schema)
                    request_fields = flattener.flatten(schema)

            responses: list[ResponseSpec] = []
            for code, resp in (op.get("responses") or {}).items():
                resp, _ = resolver.resolve(resp)
                if not isinstance(resp, dict):
                    continue
                schema = _pick_json_schema(resp.get("content") or {}) if "content" in resp else resp.get("schema")
                responses.append(ResponseSpec(
                    status_code=str(code), description=normalize_whitespace(resp.get("description", "")),
                    root_type=flattener.root_type(schema) if schema else None,
                    fields=flattener.flatten(schema) if schema else [],
                    evidence=f"{ref}.responses.{code}",
                ))

            security = _security_methods(op["security"], schemes) if "security" in op else global_security
            model.endpoints.append(EndpointSpec(
                method=method.upper(), path=path, normalized_path=path_template(path),
                summary=normalize_whitespace(op.get("summary", "")),
                description=normalize_whitespace(op.get("description", "")),
                operation_id=op.get("operationId"), parameters=list(params.values()),
                request_root_type=request_root, request_fields=request_fields, responses=responses,
                security=security, deprecated=bool(op.get("deprecated", False)), source_location=ref,
            ))

    if not model.endpoints:
        model.warnings.append("The specification defines no operations under 'paths'.")
    logger.info("Parsed OpenAPI spec '%s': %d operations", source_name, len(model.endpoints))
    return model

