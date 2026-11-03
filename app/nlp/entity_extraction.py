"""Technical entity extraction.

Combines three signals:

1. Custom token/regex patterns for technical entities that spaCy's statistical
   NER does not know about (paths, status codes, headers, versions...).
2. spaCy linguistic analysis (POS tags, dependency parse, lemmas) to accept or
   reject ambiguous candidates, e.g. ``number`` in "phone number" (compound noun,
   not a data type) versus "an integer number".
3. spaCy ``Matcher`` patterns for prose constructions such as
   "the <noun> parameter" and dependency-based requiredness detection
   ("is required", "is not required", "may be omitted").

Spans are attached to the spaCy ``Doc`` (``doc.spans["tech"]``) so downstream
code can use sentence boundaries and token attributes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from spacy.matcher import Matcher
from spacy.tokens import Doc, Span
from spacy.util import filter_spans

from app.core.models import ExtractedEntity
from app.nlp.preprocessing import get_nlp
from app.nlp.text_normalization import (
    HTTP_METHODS,
    AUTH_PATTERNS,
    canonical_path,
    normalize_identifier,
    normalize_type,
    normalize_whitespace,
)

# --------------------------------------------------------------------------- #
# Candidate patterns
# --------------------------------------------------------------------------- #
_METHODS_ALT = "|".join(HTTP_METHODS)
_PATH_BODY = r"/[A-Za-z0-9_\-.~{}:<>]*(?:/[A-Za-z0-9_\-.~{}:<>]+)*/?"
ENDPOINT_RE = re.compile(rf"\b(?P<method>{_METHODS_ALT})\s+`?(?P<path>{_PATH_BODY})`?")
BARE_PATH_RE = re.compile(rf"(?<![\w/.:@-])(?P<path>/[A-Za-z][A-Za-z0-9_\-.~{{}}:<>]*(?:/[A-Za-z0-9_\-.~{{}}:<>]+)*/?)")
METHOD_RE = re.compile(rf"\b(?:{_METHODS_ALT})\b")
STATUS_RE = re.compile(r"\b([1-5][0-9]{2})\b")
VERSION_RE = re.compile(r"\b[vV]\d+(?:\.\d+)*\b|\bversion\s+\d+(?:\.\d+)*\b|\b\d+\.\d+\.\d+\b", re.I)
HEADER_RE = re.compile(
    r"\b(?:X-[A-Za-z0-9][A-Za-z0-9-]*|Authorization|Content-Type|Accept|Idempotency-Key|If-Match|"
    r"If-None-Match|ETag|Retry-After|Location|[A-Z][a-z]+(?:-[A-Z][a-z]+)+)\b"
)
CODE_SPAN_RE = re.compile(r"`([^`\n]{1,80})`")
IDENT_RE = re.compile(r"\b(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)+|[a-z][a-z0-9]*(?:[A-Z][a-z0-9]+)+)\b")
IDENT_FULL_RE = re.compile(r"^[A-Za-z_][\w\-]*(?:\.[\w\-]+|\[\])*$")
TYPE_WORD_RE = re.compile(
    r"\b(string|integer|int32|int64|int|boolean|bool|number|float|double|decimal|array|object|uuid|"
    r"date-time|datetime|timestamp)\b",
    re.I,
)

_STATUS_CONTEXT = re.compile(
    r"\b(status|code|http|return|returns|returned|respond|responds|response|error)\b", re.I
)
_REASON_PHRASES = re.compile(
    r"^\s*[-:(]?\s*(OK|Created|Accepted|No Content|Moved|Found|Not Modified|Bad Request|Unauthori[sz]ed|"
    r"Forbidden|Not Found|Method Not Allowed|Conflict|Gone|Unprocessable|Too Many Requests|"
    r"Internal Server Error|Bad Gateway|Service Unavailable)\b",
    re.I,
)
_PARAM_NOUNS = {"parameter", "param", "field", "attribute", "property", "argument", "header", "key"}
_LOCATION_WORDS = {"query": "query", "path": "path", "header": "header", "url": "path", "cookie": "cookie",
                   "body": "body", "querystring": "query"}
_REQUIRED_WORDS = {"require", "required", "mandatory", "must", "compulsory", "need"}
_OPTIONAL_WORDS = {"optional", "optionally", "omit", "omitted", "may"}

LABEL_PRIORITY = {"ENDPOINT": 0, "HEADER": 1, "AUTH_METHOD": 2, "STATUS_CODE": 3, "VERSION": 4,
                  "PARAMETER": 5, "DATA_TYPE": 6, "HTTP_METHOD": 7}


@dataclass
class ParameterMention:
    """A parameter described in prose, with attributes inferred from its sentence."""

    name: str
    normalized_name: str
    location: Optional[str] = None
    type: Optional[str] = None
    raw_type: Optional[str] = None
    required: Optional[bool] = None
    sentence: str = ""


@dataclass
class _Candidate:
    label: str
    start: int
    end: int
    normalized: str
    meta: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def _param_matcher() -> Matcher:
    """Matcher for "the <identifier/noun> (query|path) parameter" constructions."""
    nlp = get_nlp()
    matcher = Matcher(nlp.vocab)
    matcher.add(
        "PARAM_NOUN",
        [
            [{"POS": {"IN": ["NOUN", "PROPN", "X", "ADJ"]}, "IS_STOP": False, "IS_ALPHA": True},
             {"LOWER": {"IN": sorted(_LOCATION_WORDS)}, "OP": "?"},
             {"LEMMA": {"IN": sorted(_PARAM_NOUNS)}}],
        ],
    )
    return matcher


def _status_candidates(text: str) -> list[_Candidate]:
    out = []
    for m in STATUS_RE.finditer(text):
        before = text[max(0, m.start() - 30):m.start()]
        after = text[m.end():m.end() + 30]
        if _REASON_PHRASES.match(after) or _STATUS_CONTEXT.search(before):
            out.append(_Candidate("STATUS_CODE", m.start(), m.end(), m.group(1)))
    return out


def _regex_candidates(text: str) -> list[_Candidate]:
    cands: list[_Candidate] = []
    for m in ENDPOINT_RE.finditer(text):
        cands.append(_Candidate("ENDPOINT", m.start(), m.end(),
                                f"{m.group('method')} {canonical_path(m.group('path'))}",
                                {"method": m.group("method"), "path": canonical_path(m.group("path"))}))
    for m in BARE_PATH_RE.finditer(text):
        path = m.group("path")
        if path.count("/") >= 1 and len(path) > 2:
            cands.append(_Candidate("ENDPOINT", m.start(), m.end(), canonical_path(path),
                                    {"method": None, "path": canonical_path(path)}))
    for m in METHOD_RE.finditer(text):
        cands.append(_Candidate("HTTP_METHOD", m.start(), m.end(), m.group(0)))
    cands.extend(_status_candidates(text))
    for m in VERSION_RE.finditer(text):
        cands.append(_Candidate("VERSION", m.start(), m.end(), re.sub(r"(?i)version\s+", "v", m.group(0)).lower()))
    for m in HEADER_RE.finditer(text):
        cands.append(_Candidate("HEADER", m.start(), m.end(), m.group(0).lower()))
    for label_name, pattern in AUTH_PATTERNS:
        for m in pattern.finditer(text):
            cands.append(_Candidate("AUTH_METHOD", m.start(), m.end(), label_name))
    for m in CODE_SPAN_RE.finditer(text):
        inner = m.group(1).strip()
        if IDENT_FULL_RE.match(inner) and not normalize_type(inner) == inner.lower() and inner.upper() not in HTTP_METHODS:
            cands.append(_Candidate("PARAMETER", m.start(1), m.end(1), normalize_identifier(inner)))
    for m in IDENT_RE.finditer(text):
        cands.append(_Candidate("PARAMETER", m.start(), m.end(), normalize_identifier(m.group(0))))
    return cands


def _linguistic_candidates(doc: Doc) -> list[_Candidate]:
    """Candidates that require token-level linguistic context."""
    cands: list[_Candidate] = []
    # Data types: reject words used as the head of a compound noun ("phone number")
    for m in TYPE_WORD_RE.finditer(doc.text):
        span = doc.char_span(m.start(), m.end(), alignment_mode="expand")
        if span is None:
            continue
        token = span.root
        if any(child.dep_ == "compound" for child in token.children):
            continue
        canonical = normalize_type(m.group(0))
        if canonical:
            cands.append(_Candidate("DATA_TYPE", m.start(), m.end(), canonical, {"raw": m.group(0)}))
    # "the limit parameter", "the page query parameter"
    try:
        matches = _param_matcher()(doc)
    except ValueError:  # blank pipeline has no POS tags
        matches = []
    for _, start, end in matches:
        token = doc[start]
        if token.lower_ in _LOCATION_WORDS or token.lower_ in {"this", "that", "each", "following"}:
            continue
        cands.append(_Candidate("PARAMETER", token.idx, token.idx + len(token.text), normalize_identifier(token.text)))
    return cands


def _resolve_overlaps(cands: list[_Candidate]) -> list[_Candidate]:
    """Keep non-overlapping candidates, preferring longer spans then label priority."""
    ordered = sorted(cands, key=lambda c: (-(c.end - c.start), LABEL_PRIORITY.get(c.label, 99), c.start))
    taken: list[_Candidate] = []
    for cand in ordered:
        if all(cand.end <= t.start or cand.start >= t.end for t in taken):
            taken.append(cand)
    return sorted(taken, key=lambda c: c.start)


def analyze(text: str) -> tuple[Doc, list[_Candidate]]:
    """Run spaCy over ``text`` and attach technical entity spans to ``doc.spans['tech']``."""
    text = normalize_whitespace(text)
    doc = get_nlp()(text)
    cands = _resolve_overlaps(_regex_candidates(text) + _linguistic_candidates(doc))
    spans: list[Span] = []
    for cand in cands:
        span = doc.char_span(cand.start, cand.end, label=cand.label, alignment_mode="expand")
        if span is not None:
            spans.append(span)
    doc.spans["tech"] = filter_spans(spans)
    return doc, cands


def extract_entities(text: str, source: str = "") -> list[ExtractedEntity]:
    """Extract technical entities from free text."""
    if not text or not text.strip():
        return []
    doc, cands = analyze(text)
    entities: list[ExtractedEntity] = []
    for cand in cands:
        span = doc.char_span(cand.start, cand.end, alignment_mode="expand")
        sentence = span.sent.text if span is not None else ""
        entities.append(ExtractedEntity(label=cand.label, text=doc.text[cand.start:cand.end],
                                        normalized=cand.normalized, context=sentence[:300], source=source))
    return entities


def _nearest(cands: list[_Candidate], label: str, anchor: _Candidate, window: int) -> Optional[_Candidate]:
    best, best_dist = None, window + 1
    for c in cands:
        if c.label != label:
            continue
        dist = c.start - anchor.end if c.start >= anchor.end else anchor.start - c.end
        if 0 <= dist < best_dist:
            best, best_dist = c, dist
    return best


def _requiredness(sent: Span) -> Optional[bool]:
    """Infer requiredness from a sentence using lemmas and negation dependencies."""
    for token in sent:
        word = token.lemma_.lower() or token.lower_
        if token.lower_ in _OPTIONAL_WORDS or word in _OPTIONAL_WORDS:
            if token.lower_ == "may" and not any(t.lower_ in {"omit", "omitted", "skip", "skipped"} for t in sent):
                continue
            return False
        if token.lower_ in _REQUIRED_WORDS or word in _REQUIRED_WORDS:
            negated = any(c.dep_ == "neg" for c in token.children) or any(
                c.dep_ == "neg" for c in token.head.children
            ) or (token.i > 0 and token.doc[token.i - 1].lower_ in {"not", "never"})
            return not negated
    return None


def extract_parameter_mentions(text: str) -> list[ParameterMention]:
    """Find parameters described in prose and infer location, type and requiredness."""
    if not text or not text.strip():
        return []
    doc, cands = analyze(text)
    mentions: dict[str, ParameterMention] = {}
    for sent in doc.sents:
        in_sent = [c for c in cands if sent.start_char <= c.start < sent.end_char]
        params = [c for c in in_sent if c.label == "PARAMETER"]
        if not params:
            continue
        window = 200 if len(params) == 1 else 40
        required = _requiredness(sent) if len(params) == 1 else None
        for param in params:
            dtype = _nearest(in_sent, "DATA_TYPE", param, window)
            location = None
            lower = sent.text.lower()
            for word, loc in _LOCATION_WORDS.items():
                if re.search(rf"\b{word}\b", lower):
                    location = loc
                    break
            name = doc.text[param.start:param.end]
            mention = mentions.setdefault(param.normalized, ParameterMention(name=name, normalized_name=param.normalized))
            mention.sentence = mention.sentence or sent.text
            mention.location = mention.location or location
            if dtype and not mention.type:
                mention.type, mention.raw_type = dtype.normalized, dtype.meta.get("raw")
            if mention.required is None:
                mention.required = required
    return list(mentions.values())
