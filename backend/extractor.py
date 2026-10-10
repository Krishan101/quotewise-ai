"""
extractor.py — Stage 2a: Rule-Based Extractor

Runs before agent.py (LLM normalization).
Uses regex and lookup tables to extract obvious fields deterministically.
Only sends fields to the LLM that rules could not resolve.

Trust hierarchy:
  1. Rule-based extraction (this file) — deterministic, auditable
  2. LLM normalization (agent.py)      — fills gaps rules missed
"""

import re
from typing import List, Optional, Tuple
from schemas import RawLineItem, NormalizedLineItem


# -------------------------------------------------------------------
# LOOKUP TABLES
# -------------------------------------------------------------------

MATERIAL_ALIASES = {
    # Stainless Steel
    r"\b(ss|stainless|stainless[\s\-]?steel|s\.s\.)\b": "Stainless Steel",
    # Carbon Steel
    r"\b(cs|carbon[\s\-]?steel|mild[\s\-]?steel|hr|cr|hot[\s\-]?roll|cold[\s\-]?roll)\b": "Carbon Steel",
    # Aluminum
    r"\b(al|alum\.?|aluminum|aluminium)\b": "Aluminum",
    # Copper
    r"\b(cu|copper)\b": "Copper",
    # Brass
    r"\b(brass)\b": "Brass",
    # Titanium
    r"\b(ti|titanium)\b": "Titanium",
}

GRADE_PATTERNS = [
    # Stainless grades
    (r"\b(304L?|316L?|321|347|410|430|2205|2507|17[\-\s]?4)\b", lambda m: m.group(1).upper().replace(" ", "")),
    # Aluminum grades
    (r"\b(6061|6063|7075|5052|3003|2024)[\-\s]?(T6|T4|T3|T651|H32|H14|O)?\b",
     lambda m: (m.group(1) + ("-" + m.group(2) if m.group(2) else "")).strip("-")),
    # Carbon steel grades
    (r"\b(A36|A572|A514|1018|1020|1045|4130|4140)\b", lambda m: m.group(1).upper()),
    # Titanium grades ("Gr 2", "Grade 5", "CP2", "Ti-6Al-4V"); kept last so steel grades win
    (r"\b(?:gr(?:ade)?\.?\s*|cp\s*)(1|2|3|4|5|7|9|12|23)\b", lambda m: f"Grade {m.group(1)}"),
    (r"\b(?:ti[\-\s]?)?6al[\-\s]?4v\b", lambda m: "Grade 5"),
]

FORM_ALIASES = {
    r"\b(sheet|sht)\b":           "Sheet",
    r"\b(plate|plt)\b":           "Plate",
    r"\b(bar|rod|rnd)\b":         "Bar",
    r"\b(tube|tubing|tub)\b":     "Tube",
    r"\b(pipe|pip)\b":            "Pipe",
    r"\b(angle|ang)\b":           "Angle",
    r"\b(channel|chan)\b":        "Channel",
    r"\b(flat[\s\-]?bar)\b":      "Flat Bar",
    r"\b(square[\s\-]?bar)\b":    "Square Bar",
    r"\b(hex[\s\-]?bar)\b":       "Hex Bar",
    r"\b(coil)\b":                "Coil",
    r"\b(strip)\b":               "Strip",
    r"\b(foil)\b":                "Foil",
}

GAUGE_TO_INCHES = {
    "7":  0.179, "8":  0.164, "9":  0.150, "10": 0.135,
    "11": 0.120, "12": 0.105, "13": 0.090, "14": 0.075,
    "15": 0.067, "16": 0.060, "17": 0.054, "18": 0.048,
    "19": 0.042, "20": 0.036, "22": 0.030, "24": 0.024,
    "26": 0.018, "28": 0.015,
}

STANDARD_PATTERNS = [
    r"\b(ASTM\s?[A-Z]\d{1,4}(?:[\/\-][A-Z]?\d{1,4})?)\b",
    r"\b(ASME\s?SA[\-\s]?\d{1,4})\b",
    r"\b(ASME\s?[A-Z]{1,2}\d{1,4})\b",
    r"\b(AMS\s?\d{4}[A-Z]?)\b",
    r"\b(MIL[\-\s][A-Z]{1,5}[\-\s]\d+)\b",
    r"\b(ISO\s?\d{4,5})\b",
    r"\b(EN\s?\d{4,5})\b",
]

# Bare ASTM spec numbers written without the "ASTM" prefix (e.g. "per A240")
BARE_ASTM_SPECS = ["A240", "A276", "A312", "A479", "A480", "A554", "A666", "B209", "B221"]

FINISH_ALIASES = {
    r"\b(2[Bb]|2B)\b":            "2B",
    r"(?:\bno\.?\s?|#)([14])\b":  lambda m: "No." + m.group(1),
    r"\b(ba|bright[\s\-]?anneal)\b": "BA",
    r"\b(hr|hot[\s\-]?roll)\b":   "HR",
    r"\b(cr|cold[\s\-]?roll)\b":  "CR",
    r"\b(mirror|polished)\b":     "Mirror",
}

# Units of measure for QUANTITY. Dimension units (in, ft, mm) are deliberately
# excluded here: "0.060 in" is a thickness, not a unit of sale.
UNIT_PATTERNS = {
    r"(ea|each|pcs?|pieces?|sheets?|shts?|plates?|plts?|bars?|lengths?)": "EA",
    r"(lbs?|pounds?)":                                                    "LB",
    r"(kgs?|kilograms?)":                                                 "KG",
    r"(sqft|sq\.?\s?ft|square[\s\-]?feet)":                               "SQFT",
}

# Grade -> material, used only when the text names a grade but no material word.
# A grade like "304" or "A36" identifies exactly one material family, so this is a
# lookup, not a guess. The inference is recorded as a warning on the line.
GRADE_TO_MATERIAL = {
    "304": "Stainless Steel", "304L": "Stainless Steel", "316": "Stainless Steel",
    "316L": "Stainless Steel", "321": "Stainless Steel", "347": "Stainless Steel",
    "410": "Stainless Steel", "430": "Stainless Steel", "2205": "Stainless Steel",
    "2507": "Stainless Steel", "17-4": "Stainless Steel",
    "A36": "Carbon Steel", "A572": "Carbon Steel", "A514": "Carbon Steel",
    "1018": "Carbon Steel", "1020": "Carbon Steel", "1045": "Carbon Steel",
    "4130": "Carbon Steel", "4140": "Carbon Steel",
    "6061": "Aluminum", "6063": "Aluminum", "7075": "Aluminum",
    "5052": "Aluminum", "3003": "Aluminum", "2024": "Aluminum",
}

def _strip_spec_tokens(text: str) -> str:
    """Remove dimensions, grades, gauges and spec numbers so they are never read as a quantity."""
    text = re.sub(DIM_PAIR_RE + r"(?:\s*[xX×]\s*\d*\.?\d+\s*(?:in(?:ch(?:es)?)?|\"|ft|feet|')?)?", " ", text)
    for pattern, _ in GRADE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\d{1,2}\s*ga(?:uge)?", " ", text, flags=re.IGNORECASE)
    for pattern in STANDARD_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return text


# A W x L pair, used to keep dimensions out of thickness / quantity / unit extraction
DIM_PAIR_RE = r"\d*\.?\d+\s*(?:in(?:ch(?:es)?)?|\"|ft|feet|')?\s*[xX×]\s*\d*\.?\d+\s*(?:in(?:ch(?:es)?)?|\"|ft|feet|')?"


# -------------------------------------------------------------------
# INDIVIDUAL FIELD EXTRACTORS
# -------------------------------------------------------------------

def extract_material(text: str) -> Optional[str]:
    t = text.lower()
    for pattern, value in MATERIAL_ALIASES.items():
        if re.search(pattern, t, re.IGNORECASE):
            return value
    return None


def extract_grade(text: str) -> Optional[str]:
    for pattern, formatter in GRADE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return formatter(m)
    return None


def extract_form(text: str) -> Optional[str]:
    t = text.lower()
    for pattern, value in FORM_ALIASES.items():
        if re.search(pattern, t, re.IGNORECASE):
            return value
    return None


def extract_gauge(text: str) -> Tuple[Optional[str], Optional[float]]:
    """Returns (gauge_string, thickness_in)"""
    m = re.search(r"\b(\d{1,2})\s*ga(?:uge)?\b", text, re.IGNORECASE)
    if m:
        ga = m.group(1)
        thickness = GAUGE_TO_INCHES.get(ga)
        return f"{ga}ga", thickness
    return None, None


# A T x W x L triple; the thickness may be a fraction ("1/2\" x 96 x 240")
TRIPLE_RE = r"(?<![\d./])(\d+/\d+|\d*\.?\d+)\s*(?:\"|in)?\s*[xX×]\s*(\d+\.?\d*)\s*(?:\"|in)?\s*[xX×]"


def _to_inches(value: str) -> float:
    if "/" in value:
        num, den = value.split("/")
        return round(int(num) / int(den), 4) if int(den) else float("inf")
    return float(value)


def extract_thickness(text: str) -> Optional[float]:
    """
    Extract thickness in inches from patterns like:
    0.060 in, 0.060", 1/4", 1/4 in, .060, 6mm
    """
    # Remove W x L pairs (and a leading T in "T x W x L") so "48 x 96 in" is never a thickness
    triple = re.search(TRIPLE_RE, text)
    if triple and _to_inches(triple.group(1)) < 4:
        return _to_inches(triple.group(1))
    text = re.sub(DIM_PAIR_RE, " ", text)

    # Fractional inches: 1/4, 3/8, 1/2 (checked first so "1/4 in" is not read as "4 in")
    m = re.search(r"(?<![\d.])(\d+)/(\d+)\s*(?:in(?:ch(?:es)?)?(?![a-z])|\"|thk|thick)", text, re.IGNORECASE)
    if m and int(m.group(2)) != 0:
        return round(int(m.group(1)) / int(m.group(2)), 4)

    # Decimal inches: 0.060 in, .060", 0.25 thk
    for m in re.finditer(r"(?<![\d./])(\d*\.\d+|\d+)\s*(?:in(?:ch(?:es)?)?(?![a-z])|\"|thk|thick)", text, re.IGNORECASE):
        val = float(m.group(1))
        # Sanity check: thickness for sheet/plate is typically 0.005 to 4.0 inches
        if 0.005 <= val <= 4.0:
            return val

    # Bare leading-dot decimal (".060") is a common way to write thickness
    m = re.search(r"(?<![\d.])(\.\d{2,4})(?![\d.])", text)
    if m:
        return float(m.group(1))

    # Millimeters → convert to inches
    m = re.search(r"(?<![\d.])(\d*\.?\d+)\s*mm\b", text, re.IGNORECASE)
    if m:
        return round(float(m.group(1)) / 25.4, 4)

    return None


def extract_dimensions(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract width x length in inches from patterns like:
    4x8, 48x96, 4 x 8, 48 x 96 in, 4'x8'
    Returns (width_in, length_in)
    """
    # T x W x L triple (e.g. "0.060 x 48 x 96"): the first value is thickness, skip it
    triple = re.search(TRIPLE_RE, text)
    if triple and _to_inches(triple.group(1)) < 4:
        text = text[triple.start(2):]

    # Pattern: NxM or N x M (feet or inches), optional unit mark after each number
    m = re.search(
        r"(?<![\d.])(\d+\.?\d*)\s*(?:in(?:ch(?:es)?)?|\"|ft|feet|')?\s*[xX×]\s*(\d+\.?\d*)\s*(in(?:ch(?:es)?)?|\"|ft|feet|')?",
        text
    )
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        unit = (m.group(3) or "").lower()
        # A foot mark on the pair means both are in feet ("4' x 8'")
        if "'" in m.group(0) and '"' not in m.group(0):
            unit = "ft"

        if unit in ("ft", "feet"):
            return round(a * 12, 2), round(b * 12, 2)
        else:
            # If values look like feet (<=12), convert; else treat as inches
            if a <= 12 and b <= 12:
                return round(a * 12, 2), round(b * 12, 2)
            return a, b

    return None, None


def extract_quantity(text: str) -> Optional[float]:
    """
    Extract quantity from patterns like:
    qty 50, quantity: 20, 50 pcs, x50, (20)
    """
    text = _strip_spec_tokens(text)
    patterns = [
        r"\bqty[\s:\.\-]*(\d[\d,]*\.?\d*)",
        r"\bquantity[\s:\.\-]*(\d[\d,]*\.?\d*)",
        r"(?<![\d.])(\d[\d,]*\.?\d*)\s*(?:pcs?|pieces?|ea|each|sheets?|shts?|plates?|plts?|lbs?|pounds?|kgs?|sq\.?\s?ft)\b",
        r"\bx\s*(\d+)\b",
        r"\(\s*(\d+\.?\d*)\s*\)",
        r"^\s*(\d+)\s*(?:[\-–:]\s*|\s+)(?=[A-Za-z])",  # leading count: "10 - 304 SS sheet ..."
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def extract_unit(text: str) -> Optional[str]:
    """
    Unit of sale is only taken from a word attached to a quantity
    ("10 pcs", "500 lbs", "qty 10 ea"). Dimension units are never used.
    """
    text = _strip_spec_tokens(text)
    for pattern, value in UNIT_PATTERNS.items():
        if re.search(r"(?<![\d.])\d[\d,]*\.?\d*\s*" + pattern + r"(?![a-z])", text, re.IGNORECASE):
            return value
    return None


def extract_standard(text: str) -> Optional[str]:
    for pattern in STANDARD_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            std = re.sub(r"\s+", " ", m.group(1).upper())
            # Normalize "ASTMA240" -> "ASTM A240"
            return re.sub(r"^(ASTM|ASME|AMS|ISO|EN)(?=[A-Z0-9])", r"\1 ", std)
    for spec in BARE_ASTM_SPECS:
        if re.search(rf"\b{spec}\b", text, re.IGNORECASE):
            return f"ASTM {spec}"
    return None


def extract_finish(text: str) -> Optional[str]:
    for pattern, value in FINISH_ALIASES.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return value(m) if callable(value) else value
    return None


# -------------------------------------------------------------------
# MAIN EXTRACTION FUNCTION
# -------------------------------------------------------------------

def extract_fields(raw: RawLineItem) -> NormalizedLineItem:
    """
    Run all rule-based extractors on a single RawLineItem.
    Returns a NormalizedLineItem with as many fields filled as possible.
    Remaining null fields are passed to agent.py for LLM gap-filling.
    """
    text = raw.original_text
    warnings = list(raw.parse_warnings)
    unknown_fields = []

    # Run all extractors
    material  = extract_material(text)
    grade     = extract_grade(text)
    form      = extract_form(text)
    gauge_str, gauge_thickness = extract_gauge(text)
    thickness = gauge_thickness or extract_thickness(text)
    width_in, length_in = extract_dimensions(text)
    quantity  = extract_quantity(text)
    unit      = extract_unit(text)
    standard  = extract_standard(text)
    finish    = extract_finish(text)

    # A grade identifies the material family unambiguously; record that we inferred it
    if material is None and grade:
        inferred = GRADE_TO_MATERIAL.get(grade if grade == "17-4" else grade.split("-")[0])
        if inferred:
            material = inferred
            warnings.append(f"Material \"{inferred}\" inferred from grade {grade} (rule lookup, not LLM).")

    # Track what rules could not determine
    if material  is None: unknown_fields.append("material")
    if grade     is None: unknown_fields.append("grade")
    if form      is None: unknown_fields.append("form")
    if thickness is None: unknown_fields.append("thickness_in")
    if width_in  is None: unknown_fields.append("width_in")
    if length_in is None: unknown_fields.append("length_in")
    if quantity  is None: unknown_fields.append("quantity")
    if unit      is None: unknown_fields.append("unit")
    if standard  is None: unknown_fields.append("standard")

    # Dimension/gauge cross-check warning
    if gauge_str and thickness:
        # If text also has an explicit thickness, check consistency
        explicit_thickness = extract_thickness(
            re.sub(r"\b\d{1,2}\s*ga(?:uge)?\b", "", text, flags=re.IGNORECASE)
        )
        if explicit_thickness and abs(explicit_thickness - thickness) > 0.005:
            warnings.append(
                f"Gauge {gauge_str} implies {thickness}\" but explicit thickness "
                f"{explicit_thickness}\" also found. Verify with buyer."
            )

    # Confidence: proportion of required fields found by rules
    required = ["material", "grade", "form", "quantity"]
    found = sum(1 for f in required if f not in unknown_fields)
    confidence = round(found / len(required), 2)

    return NormalizedLineItem(
        line_number=raw.line_number,
        original_text=raw.original_text,
        material=material,
        grade=grade,
        form=form,
        thickness_in=thickness,
        width_in=width_in,
        length_in=length_in,
        gauge=gauge_str,
        quantity=quantity,
        unit=unit,
        standard=standard,
        finish=finish,
        unknown_fields=unknown_fields,
        extraction_confidence=confidence,
        extraction_warnings=warnings
    )


def extract_all(raw_lines: List[RawLineItem]) -> List[NormalizedLineItem]:
    """Run rule-based extraction on all raw lines."""
    return [extract_fields(raw) for raw in raw_lines]


# -------------------------------------------------------------------
# HELPER: which fields still need LLM gap-filling
# -------------------------------------------------------------------

def fields_needing_llm(item: NormalizedLineItem) -> list:
    """
    Returns list of field names that rules could not resolve.
    These are sent to agent.py for LLM gap-filling.
    """
    return item.unknown_fields
