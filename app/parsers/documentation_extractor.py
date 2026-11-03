"""Extract a structured :class:`ApiModel` from parsed documentation blocks.

Pipeline
--------
1. **Segmentation** - the block stream is split into endpoint sections. A
   section starts at a heading containing ``METHOD /path`` or at a block whose
   first line is ``METHOD /path`` (the preceding heading becomes its summary).
2. **Context tracking** - sub-headings and short label paragraphs
   ("Query parameters", "Request body", "Response 201 Created") tell the
   extractor how to interpret the following tables, lists and code samples.
3. **Element extraction** - parameter/field tables (column roles detected with
   fuzzy header matching), bulleted parameter lists, JSON examples (types
   inferred from values), status codes (spaCy-based entity extraction) and
   prose parameter mentions (dependency-based requiredness detection).
4. **Global context** - authentication methods, base URL and version are read
   from non-endpoint sections.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from rapidfuzz import fuzz

from app.core.models import ApiModel, EndpointSpec, Parameter, ResponseSpec, SchemaField
from app.nlp.entity_extraction import extract_entities, extract_parameter_mentions
from app.nlp.text_normalization import (
    HTTP_METHODS,
    canonical_path,
    detect_auth_methods,
    infer_json_type,
    normalize_identifier,
    normalize_type,
    normalize_whitespace,
    path_parameters,
    path_template,
)
from app.parsers.blocks import Block, BlockType, ParsedDocument
from app.parsers.openapi_parser import normalize_field_path

_METHODS = "|".join(HTTP_METHODS)
_ENDPOINT_IN_TEXT = re.compile(rf"\b(?P<method>{_METHODS})\s+`?(?P<path>(?:https?://[^\s/`]+)?/[^\s`|,;]*)`?")
_ENDPOINT_LINE = re.compile(rf"^\W*(?P<method>{_METHODS})\s+`?(?P<path>(?:https?://[^\s/`]+)?/[^\s`]*)`?\s*$")
_URL = re.compile(r"https?://[^\s`)\]>\"']+")
_STATUS_IN_TEXT = re.compile(r"\b([1-5]\d\d)\b")
_HTTP_STATUS_LINE = re.compile(r"^HTTP/\d(?:\.\d)?\s+([1-5]\d\d)", re.M)
_PUBLIC_RE = re.compile(
    r"\b(no authentication|does not require (any )?authentication|public endpoint|is public|unauthenticated|"
    r"without authentication|authentication is not required)\b", re.I
)
_LIST_PARAM = re.compile(
    r"^`?(?P<name>[A-Za-z_][\w.\-]*(?:\[\])?(?:\.[\w\-]+)*)`?\s*(?:\((?P<meta>[^)]*)\))?\s*"
    r"(?:[:\-\u2013\u2014]+\s*(?P<desc>.*))?$"
)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "parameter", "param", "field", "attribute", "property", "header", "key", "field name",
             "parameter name", "header name"),
    "type": ("type", "data type", "datatype", "format", "schema", "value type"),
    "required": ("required", "mandatory", "req", "required?", "optional"),
    "location": ("in", "location", "param type", "parameter type", "where", "source", "sent in"),
    "description": ("description", "details", "notes", "meaning", "desc", "summary"),
    "status": ("status", "status code", "code", "http status", "response code", "http code"),
}
_TRUE_WORDS = {"yes", "y", "true", "required", "mandatory", "\u2713", "\u2714", "x", "req", "always"}
_FALSE_WORDS = {"no", "n", "false", "optional", "not required"}
_LOCATIONS = {"query": "query", "path": "path", "header": "header", "headers": "header", "cookie": "cookie",
              "body": "body", "url": "path", "querystring": "query", "query string": "query"}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
@dataclass
class _Context:
    kind: Optional[str] = None  # params | query | path | header | request | response | status | auth | description
    status: Optional[str] = None


def classify_context(text: str) -> Optional[_Context]:
    """Interpret a sub-heading or label paragraph."""
    t = text.lower()
    status = _STATUS_IN_TEXT.search(t)
    if re.search(r"\b(status codes?|error codes?|errors|response codes)\b", t) and "example" not in t:
        return _Context("status")
    if "response" in t or (status and len(t) < 40):
        return _Context("response", status.group(1) if status else None)
    if "request" in t or "body" in t or "payload" in t:
        return _Context("request")
    if "header" in t:
        return _Context("header")
    if "query" in t:
        return _Context("query")
    if "path" in t and "param" in t:
        return _Context("path")
    if "param" in t or "argument" in t:
        return _Context("params")
    if "auth" in t:
        return _Context("auth")
    if "description" in t or "overview" in t:
        return _Context("description")
    return None


def map_columns(header: list[str]) -> dict[str, int]:
    """Assign table columns to roles using fuzzy matching of header labels."""
    roles: dict[str, int] = {}
    for idx, cell in enumerate(header):
        label = normalize_whitespace(cell).lower().strip(" :*")
        if not label:
            continue
        best_role, best_score = None, 0.0
        for role, aliases in COLUMN_ALIASES.items():
            score = max(fuzz.ratio(label, alias) for alias in aliases)
            if score > best_score:
                best_role, best_score = role, score
        if best_role and best_score >= 85 and best_role not in roles:
            roles[best_role] = idx
    return roles


def parse_required(cell: str, inverted: bool = False) -> Optional[bool]:
    t = normalize_whitespace(cell).lower().strip(" .")
    if not t or t in {"-", "\u2014", "n/a"}:
        return None
    value: Optional[bool] = None
    if t in _TRUE_WORDS or t.startswith(("required", "yes", "mandatory")):
        value = True
    elif t in _FALSE_WORDS or t.startswith(("optional", "no")):
        value = False
    if value is None:
        return None
    return (not value) if inverted else value


def _parse_location(cell: str) -> Optional[str]:
    t = normalize_whitespace(cell).lower()
    for word, loc in _LOCATIONS.items():
        if re.search(rf"\b{word}\b", t):
            return loc
    return None


def parse_json_example(text: str) -> tuple[Optional[Any], Optional[str]]:
    """Parse a JSON code sample leniently. Returns (value, status code from an HTTP status line)."""
    status_match = _HTTP_STATUS_LINE.search(text)
    status = status_match.group(1) if status_match else None
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        return None, status
    body = text[start:]
    body = re.sub(r"(?m)^\s*//.*$", "", body)  # full-line comments
    body = re.sub(r"(?m)(?<=[,{\[\]\"\deln])\s+//.*$", "", body)  # trailing comments
    body = re.sub(r"(?m)^\s*\.\.\.\s*,?\s*$", "", body)  # "..." placeholders
    body = re.sub(r",(\s*[}\]])", r"\1", body)  # trailing commas
    try:
        return json.loads(body), status
    except json.JSONDecodeError:
        return None, status


def flatten_example(value: Any, prefix: str = "", evidence: str = "", depth: int = 0) -> list[SchemaField]:
    """Turn a JSON example into dotted fields with inferred types (requiredness unknown)."""
    if depth > 6:
        return []
    if isinstance(value, list) and not prefix:
        first = next((v for v in value if isinstance(v, dict)), None)
        return flatten_example(first, "", evidence, depth + 1) if first else []
    if not isinstance(value, dict):
        return []
    fields: list[SchemaField] = []
    for key, val in value.items():
        path = f"{prefix}{key}"
        ftype = infer_json_type(val)
        fields.append(SchemaField(path=path, normalized_path=normalize_field_path(path), name=str(key),
                                  type=None if ftype == "null" else ftype, raw_type=f"example: {ftype}",
                                  evidence=evidence))
        if isinstance(val, dict):
            fields.extend(flatten_example(val, f"{path}.", evidence, depth + 1))
        elif isinstance(val, list):
            first = next((v for v in val if isinstance(v, dict)), None)
            if first:
                fields.extend(flatten_example(first, f"{path}[].", evidence, depth + 1))
    return fields


def _meta_type_required(meta: str) -> tuple[Optional[str], Optional[str], Optional[bool], Optional[str]]:
    """Parse "(string, required, query)" style metadata."""
    raw_type, required, location = None, None, None
    for part in re.split(r"[,;/|]", meta or ""):
        part = part.strip()
        if not part:
            continue
        if required is None and parse_required(part) is not None:
            required = parse_required(part)
        elif location is None and _parse_location(part) and normalize_type(part) is None:
            location = _parse_location(part)
        elif raw_type is None and normalize_type(part):
            raw_type = part
    return normalize_type(raw_type), raw_type, required, location


# --------------------------------------------------------------------------- #
# Section accumulator
# --------------------------------------------------------------------------- #
@dataclass
class _Section:
    method: str
    path: str
    level: int
    summary: str
    location: str
    description: list[str] = field(default_factory=list)
    params: dict[str, Parameter] = field(default_factory=dict)
    request_fields: dict[str, SchemaField] = field(default_factory=dict)
    request_root: Optional[str] = None
    responses: dict[str, ResponseSpec] = field(default_factory=dict)
    texts: list[str] = field(default_factory=list)
    context: _Context = field(default_factory=_Context)


def _merge_field(target: dict[str, SchemaField], new: SchemaField) -> None:
    """Merge field info; explicit (table) information wins over example-inferred information."""
    existing = target.get(new.normalized_path)
    if existing is None:
        target[new.normalized_path] = new
        return
    from_example = (existing.raw_type or "").startswith("example:")
    if new.type and (not existing.type or from_example) and not (new.raw_type or "").startswith("example:"):
        existing.type, existing.raw_type = new.type, new.raw_type
    if existing.required is None:
        existing.required = new.required
    existing.description = existing.description or new.description


class DocumentationExtractor:
    def __init__(self, parsed: ParsedDocument) -> None:
        self.parsed = parsed
        self.model = ApiModel(source_name=parsed.source_name, source_type=parsed.source_type,
                              warnings=list(parsed.warnings))
        self.sections: list[_Section] = []
        self.current: Optional[_Section] = None
        self.pending_heading: Optional[Block] = None
        self.global_texts: list[str] = []
        self.heading_level = 0

    # -- segmentation ------------------------------------------------------ #
    def _start_section(self, method: str, path: str, level: int, summary: str, location: str) -> None:
        self._close_section()
        self.current = _Section(method=method.upper(), path=canonical_path(path), level=level,
                                summary=normalize_whitespace(summary), location=location)

    def _close_section(self) -> None:
        if self.current is not None:
            self.sections.append(self.current)
            self.current = None

    def _endpoint_from_line(self, block: Block) -> Optional[re.Match[str]]:
        first_line = block.text.strip().splitlines()[0] if block.text.strip() else ""
        if "HTTP/" in first_line:
            return None  # raw HTTP request sample, not a declaration
        return _ENDPOINT_LINE.match(first_line.strip())

    def run(self) -> ApiModel:
        for block in self.parsed.blocks:
            if block.type == BlockType.HEADING:
                self._on_heading(block)
                continue
            match = self._endpoint_from_line(block) if block.type != BlockType.TABLE else None
            if match and not (self.current and self.current.method == match.group("method").upper()
                              and self.current.path == canonical_path(match.group("path"))):
                heading = self.pending_heading
                self._start_section(match.group("method"), match.group("path"),
                                    heading.level if heading else self.heading_level + 1,
                                    heading.text if heading else "", heading.location if heading else block.location)
                self.pending_heading = None
                continue
            self.pending_heading = None
            if self.current is None:
                self.global_texts.append(block.as_text())
                continue
            self._on_section_block(block)
        self._close_section()
        self._finalize()
        return self.model

    def _on_heading(self, block: Block) -> None:
        if not self.model.title and block.level <= 1:
            self.model.title = block.text
        match = _ENDPOINT_IN_TEXT.search(block.text)
        if match:
            summary = normalize_whitespace(_ENDPOINT_IN_TEXT.sub("", block.text)).strip(" -\u2013\u2014:|`")
            self._start_section(match.group("method"), match.group("path"), block.level, summary, block.location)
            self.pending_heading = None
            self.heading_level = block.level
            return
        if self.current is not None and block.level > self.current.level:
            self.current.context = classify_context(block.text) or _Context()
            self.current.texts.append(block.text)
            return
        self._close_section()
        self.heading_level = block.level
        self.pending_heading = block
        self.global_texts.append(block.text)

    # -- section content --------------------------------------------------- #
    def _on_section_block(self, block: Block) -> None:
        sec = self.current
        assert sec is not None
        if block.type == BlockType.TABLE:
            self._on_table(sec, block)
            return
        if block.type == BlockType.CODE:
            self._on_code(sec, block)
            return
        text = block.text.strip()
        sec.texts.append(text)
        label = classify_context(text) if len(text) <= 80 and (text.endswith(":") or len(text.split()) <= 6) else None
        if label is not None:
            sec.context = label
            return
        # Inline label: "Response 201 Created: returns the order." / "Possible errors: ..."
        prefix, sep, _rest = text.partition(":")
        inline_label = classify_context(prefix) if sep and len(prefix) <= 40 else None
        if inline_label is not None and inline_label.kind not in ("description", "auth"):
            sec.context = inline_label
            self._apply_prose(sec, text, block.location)
            return
        kind = sec.context.kind
        if block.type == BlockType.LIST_ITEM and kind in {"params", "query", "path", "header", "request", "response"}:
            if self._on_list_param(sec, block):
                return
        if kind in (None, "description"):
            if not re.match(r"^\s*(authentication|auth)\s*:", text, re.I):
                sec.description.append(text)
        self._apply_prose(sec, text, block.location)

    def _apply_prose(self, sec: _Section, text: str, location: str) -> None:
        """Use NLP parameter mentions and status-code entities found in prose."""
        for mention in extract_parameter_mentions(text):
            existing = sec.params.get(mention.normalized_name)
            if existing is not None:
                existing.type = existing.type or mention.type
                existing.raw_type = existing.raw_type or mention.raw_type
                if existing.required is None:
                    existing.required = mention.required
                existing.location = existing.location or mention.location
            elif mention.location in {"query", "path", "header"} and re.search(r"\b(parameter|param|header)\b",
                                                                                mention.sentence, re.I):
                sec.params[mention.normalized_name] = Parameter(
                    name=mention.name, normalized_name=mention.normalized_name, location=mention.location,
                    type=mention.type, raw_type=mention.raw_type, required=mention.required,
                    evidence=f"{location}: \"{mention.sentence[:160]}\"",
                )
        for ent in extract_entities(text, source=location):
            if ent.label == "STATUS_CODE" and ent.normalized not in sec.responses:
                sec.responses[ent.normalized] = ResponseSpec(status_code=ent.normalized, description=ent.context,
                                                             evidence=f"{location}: \"{ent.context[:160]}\"")

    def _add_param(self, sec: _Section, name: str, location: Optional[str], ftype: Optional[str],
                   raw_type: Optional[str], required: Optional[bool], description: str, evidence: str) -> None:
        norm = normalize_identifier(name)
        if not norm:
            return
        kind = sec.context.kind
        if location is None:
            location = {"query": "query", "path": "path", "header": "header"}.get(kind or "")
        if location is None and norm in {normalize_identifier(p) for p in path_parameters(sec.path)}:
            location = "path"
        if location == "body" or kind == "request":
            _merge_field(sec.request_fields, SchemaField(path=name, normalized_path=normalize_field_path(name),
                                                         name=name.split(".")[-1], type=ftype, raw_type=raw_type,
                                                         required=required, description=description,
                                                         evidence=evidence))
            return
        if kind == "response":
            code = sec.context.status or "2XX"
            resp = sec.responses.setdefault(code, ResponseSpec(status_code=code, evidence=evidence))
            resp.fields.append(SchemaField(path=name, normalized_path=normalize_field_path(name),
                                           name=name.split(".")[-1], type=ftype, raw_type=raw_type,
                                           required=required, description=description, evidence=evidence))
            return
        sec.params[norm] = Parameter(name=name, normalized_name=norm, location=location, type=ftype,
                                     raw_type=raw_type, required=required, description=description,
                                     evidence=evidence)

    def _on_table(self, sec: _Section, block: Block) -> None:
        header, rows = block.rows[0], block.rows[1:]
        roles = map_columns(header)
        evidence_base = f"{block.location} table [{' | '.join(header)}]"
        if "status" in roles and ("name" not in roles or sec.context.kind == "status"):
            for row in rows:
                cell = row[roles["status"]] if roles["status"] < len(row) else ""
                m = _STATUS_IN_TEXT.search(cell)
                if m:
                    desc = row[roles["description"]] if "description" in roles and roles["description"] < len(row) else ""
                    resp = sec.responses.setdefault(m.group(1), ResponseSpec(status_code=m.group(1)))
                    resp.description = resp.description or normalize_whitespace(desc)
                    resp.evidence = resp.evidence or f"{evidence_base}: {' | '.join(row)}"
            return
        if "name" not in roles:
            self.model.warnings.append(f"Skipped a table at {block.location}: no parameter/field name column found.")
            return
        inverted = header[roles["required"]].strip().lower().startswith("optional") if "required" in roles else False

        def cell(row: list[str], role: str) -> str:
            idx = roles.get(role)
            return row[idx] if idx is not None and idx < len(row) else ""

        for row in rows:
            name = cell(row, "name").strip().strip("`")
            if not name or not re.match(r"^[A-Za-z_][\w.\-\[\]]*$", name):
                continue
            raw_type = cell(row, "type") or None
            desc = normalize_whitespace(cell(row, "description"))
            required = parse_required(cell(row, "required"), inverted) if "required" in roles else None
            if required is None and desc:
                required = True if re.search(r"\brequired\b", desc, re.I) and not re.search(r"\bnot required\b", desc, re.I) \
                    else (False if re.search(r"\boptional\b", desc, re.I) else None)
            location = _parse_location(cell(row, "location")) if "location" in roles else None
            self._add_param(sec, name, location, normalize_type(raw_type), raw_type, required, desc,
                            f"{evidence_base}: {' | '.join(row)}")

    def _on_list_param(self, sec: _Section, block: Block) -> bool:
        m = _LIST_PARAM.match(block.text.strip())
        if not m:
            return False
        name, meta, desc = m.group("name"), m.group("meta") or "", (m.group("desc") or "").strip()
        ftype, raw_type, required, location = _meta_type_required(meta)
        if ftype is None and required is None and not meta:
            # No structured metadata: fall back to NLP analysis of the item text.
            mentions = [mt for mt in extract_parameter_mentions(block.text) if mt.normalized_name == normalize_identifier(name)]
            if not mentions:
                return False
            ftype, raw_type, required = mentions[0].type, mentions[0].raw_type, mentions[0].required
        self._add_param(sec, name, location, ftype, raw_type, required, desc, f"{block.location}: \"{block.text[:160]}\"")
        return True

    def _on_code(self, sec: _Section, block: Block) -> None:
        text = block.text
        if re.match(r"^\s*(curl|http|wget)\b", text, re.I) or block.language in {"bash", "sh", "shell", "http"} and not text.lstrip().startswith(("{", "[")):
            return
        value, http_status = parse_json_example(text)
        if value is None:
            return
        kind = sec.context.kind
        evidence = f"{block.location}: JSON example"
        if http_status or kind == "response" or (kind is None and sec.method in ("GET", "DELETE")):
            code = http_status or sec.context.status or "2XX"
            resp = sec.responses.setdefault(code, ResponseSpec(status_code=code, evidence=evidence))
            resp.root_type = resp.root_type or infer_json_type(value)
            existing = {f.normalized_path: f for f in resp.fields}
            for f in flatten_example(value, evidence=evidence):
                _merge_field(existing, f)
            resp.fields = list(existing.values())
        elif kind == "request" or kind is None:
            sec.request_root = sec.request_root or infer_json_type(value)
            for f in flatten_example(value, evidence=evidence):
                _merge_field(sec.request_fields, f)

    # -- finalisation ------------------------------------------------------ #
    def _finalize(self) -> None:
        global_text = "\n".join(self.global_texts)
        self.model.auth_methods = detect_auth_methods(global_text)
        self.model.global_security = list(self.model.auth_methods) if self.model.auth_methods else None
        for url in _URL.findall(global_text):
            path = urlparse(url).path
            if path and path != "/":
                self.model.base_path = canonical_path(path)
                break
        versions = [e for e in extract_entities(global_text[:4000], source="global") if e.label == "VERSION"]
        self.model.version = versions[0].normalized if versions else ""

        for sec in self.sections:
            section_text = " ".join(sec.texts)
            for p in path_parameters(sec.path):
                norm = normalize_identifier(p)
                if norm not in sec.params:
                    sec.params[norm] = Parameter(name=p, normalized_name=norm, location="path", required=True,
                                                 evidence=f"{sec.location}: path template {sec.path}")
                elif sec.params[norm].location is None:
                    sec.params[norm].location = "path"
            security: Optional[list[str]]
            if _PUBLIC_RE.search(section_text):
                security = []
            else:
                methods = detect_auth_methods(section_text)
                security = methods or None
            # Response fields documented without a status code are attached to "2XX" (unspecified success).
            responses = list(sec.responses.values())
            self.model.endpoints.append(EndpointSpec(
                method=sec.method, path=sec.path, normalized_path=path_template(sec.path),
                summary=sec.summary, description=normalize_whitespace(" ".join(sec.description)),
                parameters=list(sec.params.values()), request_root_type=sec.request_root,
                request_fields=list(sec.request_fields.values()), responses=responses, security=security,
                deprecated=bool(re.search(r"\bdeprecated\b", section_text, re.I)), source_location=sec.location,
            ))

        for block in self.parsed.blocks:
            if block.type in (BlockType.PARAGRAPH, BlockType.HEADING, BlockType.LIST_ITEM):
                self.model.entities.extend(extract_entities(block.text, source=block.location))
        if not self.model.endpoints:
            self.model.warnings.append(
                "No endpoint declarations (e.g. 'GET /resource') were found in the documentation."
            )


def extract_api_from_document(parsed: ParsedDocument) -> ApiModel:
    """Public entry point: parsed blocks -> ApiModel."""
    return DocumentationExtractor(parsed).run()
