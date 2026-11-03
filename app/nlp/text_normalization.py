"""Normalization of technical identifiers, types, paths and auth methods.

The goal is to map naming variations of the *same* entity to one canonical key
while the caller keeps the original value:

    customer_id, customerId, Customer-ID, CUSTOMER ID  ->  customer_id
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

# Abbreviations / variants that commonly appear in API naming. Kept intentionally
# small: aggressive synonym folding would hide genuine naming errors.
TOKEN_CANONICAL: dict[str, str] = {
    "identifier": "id",
    "qty": "quantity",
    "addr": "address",
    "desc": "description",
    "msg": "message",
    "num": "number",
    "pwd": "password",
    "img": "image",
    "cnt": "count",
}

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_WS = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace runs (incl. non-breaking spaces) into single spaces."""
    return _WS.sub(" ", (text or "").replace("\u00a0", " ")).strip()


@lru_cache(maxsize=8192)
def split_identifier(name: str) -> tuple[str, ...]:
    """Split an identifier into lower-case word tokens.

    Handles snake_case, kebab-case, camelCase, PascalCase, acronyms
    (``customerID`` -> customer, id) and stray punctuation/spaces.
    """
    if not name:
        return ()
    cleaned = name.strip().strip("`'\"*")
    parts: list[str] = []
    for chunk in _NON_ALNUM.split(cleaned):
        if not chunk:
            continue
        parts.extend(p for p in _CAMEL_BOUNDARY.split(chunk) if p)
    return tuple(TOKEN_CANONICAL.get(p.lower(), p.lower()) for p in parts)


def normalize_identifier(name: str) -> str:
    """Canonical snake_case key for an identifier (parameter, field, header)."""
    return "_".join(split_identifier(name))


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #
_TYPE_ALIASES: dict[str, str] = {
    "string": "string", "str": "string", "text": "string", "char": "string", "varchar": "string",
    "uuid": "string", "guid": "string", "date": "string", "datetime": "string", "date-time": "string",
    "timestamp": "string", "email": "string", "uri": "string", "url": "string", "enum": "string",
    "binary": "string", "byte": "string", "password": "string",
    "integer": "integer", "int": "integer", "int32": "integer", "int64": "integer", "long": "integer",
    "short": "integer",
    "number": "number", "float": "number", "double": "number", "decimal": "number", "numeric": "number",
    "boolean": "boolean", "bool": "boolean",
    "array": "array", "list": "array",
    "object": "object", "dict": "object", "map": "object", "json": "object", "hash": "object",
    "null": "null",
}

CANONICAL_TYPES: frozenset[str] = frozenset(_TYPE_ALIASES.values())


def normalize_type(raw: Optional[str]) -> Optional[str]:
    """Map a written type (``int64``, ``Array<string>``, ``uuid``) to a JSON-schema base type."""
    if not raw:
        return None
    text = normalize_whitespace(str(raw)).lower().strip("`*()[] ")
    if not text:
        return None
    if text.endswith("[]") or text.startswith(("array", "list")) or "array of" in text or "list of" in text:
        return "array"
    # "string (uuid)", "integer, int64", "string<date-time>"
    first = re.split(r"[\s,;/<(|]+", text, maxsplit=1)[0]
    if first in _TYPE_ALIASES:
        return _TYPE_ALIASES[first]
    for token in re.split(r"[^a-z0-9\-]+", text):
        if token in _TYPE_ALIASES:
            return _TYPE_ALIASES[token]
    return None


def infer_json_type(value: object) -> str:
    """JSON-schema type of an example value taken from a code sample."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


# --------------------------------------------------------------------------- #
# HTTP methods, status codes
# --------------------------------------------------------------------------- #
HTTP_METHODS: tuple[str, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


def normalize_method(method: str) -> str:
    return (method or "").strip().upper()


def normalize_status_code(code: object) -> str:
    text = str(code).strip().upper()
    return text if re.fullmatch(r"[1-5](\d\d|XX)|DEFAULT", text) else text


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# Path parameter notations: {id}, :id, <id>, <int:id>
_PATH_PARAM = re.compile(r"\{\s*([^}/]+?)\s*\}|(?<=/):([A-Za-z_][\w-]*)|<(?:[a-z]+:)?([A-Za-z_][\w-]*)>")
_VERSION_SEGMENT = re.compile(r"^v\d+(?:\.\d+)*$", re.IGNORECASE)


def canonical_path(path: str) -> str:
    """Clean a path as written: drop scheme/host/query, unify param notation to ``{name}``."""
    text = (path or "").strip().strip("`'\"")
    if "://" in text:
        text = urlparse(text).path or "/"
    text = text.split("?", 1)[0].split("#", 1)[0]
    text = _PATH_PARAM.sub(lambda m: "{" + next(g for g in m.groups() if g) + "}", text)
    text = re.sub(r"/{2,}", "/", text)
    if not text.startswith("/"):
        text = "/" + text
    if len(text) > 1:
        text = text.rstrip("/")
    return text


def path_parameters(path: str) -> list[str]:
    """Names of path parameters, in order of appearance."""
    return re.findall(r"\{([^}/]+)\}", canonical_path(path))


def path_segments(path: str) -> list[str]:
    return [s for s in canonical_path(path).split("/") if s]


def split_version(path: str) -> tuple[Optional[str], str]:
    """Separate a leading version segment: ``/v1/orders`` -> (``v1``, ``/orders``)."""
    segments = path_segments(path)
    if segments and _VERSION_SEGMENT.match(segments[0]):
        return segments[0].lower(), "/" + "/".join(segments[1:])
    return None, canonical_path(path)


def path_template(path: str, strip_version: bool = False) -> str:
    """Normalized structural key: static segments normalized, params replaced by ``{}``.

    ``/v2/Customer-Orders/{orderId}`` -> ``/v2/customer_orders/{}``
    """
    target = split_version(path)[1] if strip_version else canonical_path(path)
    out = []
    for seg in path_segments(target):
        out.append("{}" if seg.startswith("{") else normalize_identifier(seg) or seg.lower())
    return "/" + "/".join(out)


def strip_base_path(path: str, base_path: str) -> str:
    """Remove a server base path (e.g. ``/api/v2``) from a documented path if present."""
    base = canonical_path(base_path) if base_path else "/"
    cpath = canonical_path(path)
    if base != "/" and (cpath == base or cpath.startswith(base + "/")):
        return cpath[len(base):] or "/"
    return cpath


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
AUTH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bearer", re.compile(r"\bbearer\b|\bjwt\b|access[\s_-]?token", re.I)),
    ("api_key", re.compile(r"\bapi[\s_-]?key\b|x-api-key", re.I)),
    ("basic", re.compile(r"\bbasic\s+auth(entication)?\b|\bhttp\s+basic\b", re.I)),
    ("oauth2", re.compile(r"\boauth\s*2?(\.0)?\b", re.I)),
    ("openid_connect", re.compile(r"\bopenid\b|\boidc\b", re.I)),
]


def detect_auth_methods(text: str) -> list[str]:
    """Canonical auth methods mentioned in free text."""
    return [name for name, pattern in AUTH_PATTERNS if pattern.search(text or "")]
