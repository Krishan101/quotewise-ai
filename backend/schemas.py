from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


# -------------------------------------------------------------------
# STATUS ENUMS
# -------------------------------------------------------------------

class LineStatus(str, Enum):
    READY_FOR_REVIEW     = "READY_FOR_REVIEW"
    NEEDS_CLARIFICATION  = "NEEDS_CLARIFICATION"
    NO_COMPATIBLE_MATCH  = "NO_COMPATIBLE_MATCH"
    PRICE_UNVERIFIED     = "PRICE_UNVERIFIED"
    COMPLIANCE_REVIEW    = "COMPLIANCE_REVIEW"
    PARSER_REVIEW        = "PARSER_REVIEW"


class InputType(str, Enum):
    TEXT  = "text"
    PDF   = "pdf"
    XLSX  = "xlsx"
    CSV   = "csv"
    EMAIL = "email"


class ComplianceStatus(str, Enum):
    PRESENT  = "PRESENT"
    MISSING  = "MISSING"
    UNKNOWN  = "UNKNOWN"


class MatchConfidence(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"
    NONE   = "NONE"


# -------------------------------------------------------------------
# PARSED RAW LINE (output of Stage 1: Parser)
# -------------------------------------------------------------------

class RawLineItem(BaseModel):
    line_number: int
    original_text: str                        # Never modified, always preserved
    source_page: Optional[int] = None         # PDF page number if applicable
    source_row: Optional[int] = None          # Spreadsheet row if applicable
    parse_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    parse_warnings: List[str] = []


# -------------------------------------------------------------------
# NORMALIZED LINE (output of Stage 2: Extractor + Normalizer)
# -------------------------------------------------------------------

class NormalizedLineItem(BaseModel):
    line_number: int
    original_text: str                        # Preserved from raw

    # Extracted fields — null means unknown, never guessed
    material: Optional[str] = None            # e.g. "Stainless Steel"
    grade: Optional[str] = None               # e.g. "304", "316L"
    form: Optional[str] = None                # e.g. "Sheet", "Plate", "Bar"
    thickness_in: Optional[float] = None      # inches
    width_in: Optional[float] = None          # inches
    length_in: Optional[float] = None         # inches
    gauge: Optional[str] = None               # e.g. "16ga"
    quantity: Optional[float] = None
    unit: Optional[str] = None                # e.g. "EA", "LB", "SQFT"
    standard: Optional[str] = None            # e.g. "ASTM A240"
    finish: Optional[str] = None              # e.g. "2B", "No.4"
    notes: Optional[str] = None

    # Unknown fields explicitly listed
    unknown_fields: List[str] = []            # e.g. ["standard", "finish"]

    # Extraction metadata
    extraction_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    extraction_warnings: List[str] = []


# -------------------------------------------------------------------
# VALIDATION RESULT (output of Stage 3: Validator)
# -------------------------------------------------------------------

class ValidationResult(BaseModel):
    line_number: int
    is_valid: bool
    missing_required_fields: List[str] = []   # Fields required but null
    contradictions: List[str] = []            # e.g. "Grade 304 conflicts with standard ASTM A276"
    dimension_warnings: List[str] = []        # e.g. "16ga = 0.060in, but 0.065in was specified"
    clarification_needed: bool = False
    clarification_question: Optional[str] = None  # Pre-drafted question to buyer


# -------------------------------------------------------------------
# CATALOG ITEM (loaded from catalog.csv)
# -------------------------------------------------------------------

class CatalogItem(BaseModel):
    sku: str
    material: str
    grade: str
    form: str
    thickness_in: Optional[float] = None
    width_in: Optional[float] = None
    length_in: Optional[float] = None
    gauge: Optional[str] = None
    finish: Optional[str] = None
    standard: Optional[str] = None
    unit: str
    stock_status: str                          # "IN_STOCK", "ORDER", "UNAVAILABLE"
    supplier: str
    notes: Optional[str] = None


# -------------------------------------------------------------------
# MATCH RESULT (output of Stage 4: Catalog Matcher)
# -------------------------------------------------------------------

class CatalogMatchResult(BaseModel):
    line_number: int
    matched: bool
    match_confidence: MatchConfidence = MatchConfidence.NONE
    matched_sku: Optional[str] = None
    matched_item: Optional[CatalogItem] = None
    hard_filter_passed: bool = False
    hard_filter_reason: Optional[str] = None  # Why it passed or failed
    fuzzy_score: Optional[float] = None        # 0-1 similarity score
    rejected_skus: List[str] = []             # SKUs that failed hard filter
    rejection_reasons: List[str] = []         # Why each was rejected


# -------------------------------------------------------------------
# PRICING RESULT (output of Stage 5: Pricing Engine)
# -------------------------------------------------------------------

class PricingResult(BaseModel):
    line_number: int
    priced: bool
    unit_price: Optional[float] = None
    total_price: Optional[float] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    margin_pct: Optional[float] = None
    benchmark_price: Optional[float] = None
    benchmark_source: Optional[str] = None    # Always labeled DEMO DATA or sourced
    benchmark_date: Optional[str] = None
    price_rationale: Optional[str] = None     # Human-readable explanation
    price_unverified: bool = False
    price_warnings: List[str] = []


# -------------------------------------------------------------------
# COMPLIANCE REQUIREMENT (output of Stage 6: Compliance Checker)
# -------------------------------------------------------------------

class ComplianceRequirement(BaseModel):
    requirement: str                           # e.g. "Mill Test Report (MTR)"
    required: bool
    status: ComplianceStatus
    evidence: Optional[str] = None            # What was found, if anything
    notes: Optional[str] = None


class ComplianceResult(BaseModel):
    line_number: int
    requirements: List[ComplianceRequirement] = []
    all_clear: bool = False                   # True only if all required docs present
    compliance_warnings: List[str] = []


# -------------------------------------------------------------------
# FINAL QUOTE LINE (output of Stage 7: Decision Engine)
# -------------------------------------------------------------------

class QuoteLine(BaseModel):
    line_number: int
    status: LineStatus

    # Preserved through pipeline
    original_text: str
    normalized: Optional[NormalizedLineItem] = None
    validation: Optional[ValidationResult] = None
    match: Optional[CatalogMatchResult] = None
    pricing: Optional[PricingResult] = None
    compliance: Optional[ComplianceResult] = None

    # Decision engine outputs
    status_reason: str = ""                   # Why this status was assigned
    clarification_question: Optional[str] = None
    ready_for_export: bool = False


# -------------------------------------------------------------------
# TOP-LEVEL REQUEST / RESPONSE
# -------------------------------------------------------------------

class RFQRequest(BaseModel):
    input_type: InputType
    raw_text: Optional[str] = None            # For text/email input
    filename: Optional[str] = None            # For file uploads


class RFQResponse(BaseModel):
    rfq_id: str
    input_type: InputType
    filename: Optional[str] = None
    total_lines: int
    lines: List[QuoteLine]
    summary: dict                             # Counts per status
    demo_data_notice: str = "DEMO DATA: All catalog items, prices, and benchmarks are synthetic and for demonstration purposes only."

