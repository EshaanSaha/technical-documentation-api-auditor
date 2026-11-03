"""Shared domain models.

Both the OpenAPI specification and the free-form documentation are converted
into the same :class:`ApiModel` so that the validation engine can compare them
structurally. Every extracted element keeps its *original* value next to its
*normalized* value, plus an ``evidence`` snippet pointing back at the source.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Extracted API structure
# --------------------------------------------------------------------------- #
class Parameter(BaseModel):
    name: str
    normalized_name: str
    location: Optional[str] = None  # path | query | header | cookie
    type: Optional[str] = None  # canonical type (string, integer, number, boolean, array, object)
    raw_type: Optional[str] = None  # type as written in the source
    required: Optional[bool] = None  # None = not stated
    description: str = ""
    evidence: str = ""


class SchemaField(BaseModel):
    path: str  # dotted path using original names, arrays as ``items[].sku``
    normalized_path: str
    name: str
    type: Optional[str] = None
    raw_type: Optional[str] = None
    required: Optional[bool] = None
    description: str = ""
    evidence: str = ""


class ResponseSpec(BaseModel):
    status_code: str
    description: str = ""
    root_type: Optional[str] = None  # object | array | string ...
    fields: list[SchemaField] = Field(default_factory=list)
    evidence: str = ""


class EndpointSpec(BaseModel):
    method: str
    path: str
    normalized_path: str
    summary: str = ""
    description: str = ""
    operation_id: Optional[str] = None
    parameters: list[Parameter] = Field(default_factory=list)
    request_root_type: Optional[str] = None
    request_fields: list[SchemaField] = Field(default_factory=list)
    responses: list[ResponseSpec] = Field(default_factory=list)
    security: Optional[list[str]] = None  # canonical auth methods; None = not stated, [] = public
    deprecated: bool = False
    source_location: str = ""

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def full_description(self) -> str:
        parts = [p.strip() for p in (self.summary, self.description) if p and p.strip()]
        # Avoid repeating the summary when the description starts with it
        if len(parts) == 2 and parts[1].lower().startswith(parts[0].lower().rstrip(".")):
            parts = [parts[1]]
        return " ".join(parts)


class ExtractedEntity(BaseModel):
    label: str  # ENDPOINT, HTTP_METHOD, PARAMETER, DATA_TYPE, AUTH_METHOD, VERSION, STATUS_CODE, HEADER
    text: str
    normalized: str
    context: str = ""
    source: str = ""


class ApiModel(BaseModel):
    title: str = ""
    version: str = ""
    base_path: str = ""
    source_name: str = ""
    source_type: str = ""  # openapi-json | openapi-yaml | pdf | docx | markdown
    endpoints: list[EndpointSpec] = Field(default_factory=list)
    auth_methods: list[str] = Field(default_factory=list)  # canonical auth methods available/documented
    global_security: Optional[list[str]] = None
    entities: list[ExtractedEntity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Validation results
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Informational"


SEVERITY_ORDER: dict[str, int] = {s.value: i for i, s in enumerate(Severity)}


class IssueCategory(str, Enum):
    ENDPOINT = "Endpoint"
    PARAMETER = "Parameter"
    REQUEST_SCHEMA = "Request Schema"
    RESPONSE_SCHEMA = "Response Schema"
    STATUS_CODE = "Status Code"
    DESCRIPTION = "Description"
    AUTHENTICATION = "Authentication"


CATEGORY_PREFIX: dict[IssueCategory, str] = {
    IssueCategory.ENDPOINT: "EP",
    IssueCategory.PARAMETER: "PAR",
    IssueCategory.REQUEST_SCHEMA: "REQ",
    IssueCategory.RESPONSE_SCHEMA: "RES",
    IssueCategory.STATUS_CODE: "STS",
    IssueCategory.DESCRIPTION: "DSC",
    IssueCategory.AUTHENTICATION: "AUTH",
}


class Issue(BaseModel):
    issue_id: str = ""
    endpoint: str
    method: str
    category: IssueCategory
    issue_type: str
    severity: Severity
    expected: str = ""
    actual: str = ""
    evidence: str = ""
    explanation: str = ""
    suggestion: str = ""
    confidence: Optional[float] = None


class MatchStatus(str, Enum):
    EXACT = "Exact match"
    LIKELY = "Likely match"
    MISSING = "Missing endpoint"
    UNEXPECTED = "Unexpected documented endpoint"


class EndpointMatch(BaseModel):
    status: MatchStatus
    spec_method: Optional[str] = None
    spec_path: Optional[str] = None
    doc_method: Optional[str] = None
    doc_path: Optional[str] = None
    confidence: float = 0.0
    explanation: str = ""
    score_components: dict[str, float] = Field(default_factory=dict)
    doc_location: str = ""


class ComparisonRow(BaseModel):
    """One element compared side by side (parameter or schema field)."""

    endpoint: str
    method: str
    scope: str  # "parameter", "request body", "response 200"
    name: str
    expected_type: str = ""
    documented_type: str = ""
    expected_required: str = ""
    documented_required: str = ""
    expected_location: str = ""
    documented_location: str = ""
    documented_name: str = ""
    status: str = "OK"  # OK | Mismatch | Missing in documentation | Not in specification


class DescriptionComparison(BaseModel):
    endpoint: str
    method: str
    element: str  # "endpoint" or "parameter <name>"
    spec_text: str
    doc_text: str
    similarity: Optional[float] = None
    band: str  # High similarity | Moderate similarity | Potential inconsistency | Unrelated | Missing


class ScoreComponent(BaseModel):
    name: str
    weight: float
    score: float  # 0..1
    detail: str


class ValidationResult(BaseModel):
    session_id: str = ""
    session_name: str = ""
    created_at: str = ""
    documentation_file: str = ""
    specification_file: str = ""
    api_title: str = ""
    api_version: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    completeness_score: float = 0.0
    score_breakdown: list[ScoreComponent] = Field(default_factory=list)
    matches: list[EndpointMatch] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    comparisons: list[ComparisonRow] = Field(default_factory=list)
    descriptions: list[DescriptionComparison] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    semantic_model_available: bool = True

