"""
validator.py — Stage 3: Validator

Runs hard rule checks on each NormalizedLineItem.
Never guesses. Never fills missing fields.
Outputs a ValidationResult per line with:
  - missing required fields
  - dimension sanity checks per form factor
  - grade/standard contradiction checks
  - a pre-drafted clarification question when needed
"""

from typing import List, Optional
from schemas import NormalizedLineItem, ValidationResult


# -------------------------------------------------------------------
# REQUIRED FIELDS PER FORM FACTOR
# -------------------------------------------------------------------

# Fields that must be present for a line to be quotable
BASE_REQUIRED = ["material", "grade", "form", "quantity"]

# Additional required fields by form factor
FORM_REQUIRED_FIELDS = {
    "Sheet":      ["thickness_in", "width_in", "length_in"],
    "Plate":      ["thickness_in", "width_in", "length_in"],
    "Coil":       ["thickness_in", "width_in"],
    "Strip":      ["thickness_in", "width_in"],
    "Bar":        ["length_in"],
    "Flat Bar":   ["thickness_in", "width_in", "length_in"],
    "Square Bar": ["length_in"],
    "Hex Bar":    ["length_in"],
    "Tube":       ["length_in"],
    "Pipe":       ["length_in"],
    "Angle":      ["length_in"],
    "Channel":    ["length_in"],
    "Foil":       ["thickness_in", "width_in"],
}

# Dimension sanity bounds by form factor (inches)
DIMENSION_BOUNDS = {
    "Sheet": {
        "thickness_in": (0.005, 0.5),
        "width_in":     (6.0, 120.0),
        "length_in":    (6.0, 240.0),
    },
    "Plate": {
        "thickness_in": (0.1875, 6.0),
        "width_in":     (6.0, 120.0),
        "length_in":    (6.0, 480.0),
    },
    "Coil": {
        "thickness_in": (0.005, 0.25),
        "width_in":     (0.5, 72.0),
    },
    "Bar": {
        "length_in": (6.0, 480.0),
    },
    "Tube": {
        "length_in": (6.0, 480.0),
    },
    "Pipe": {
        "length_in": (6.0, 480.0),
    },
}

# -------------------------------------------------------------------
# GRADE / STANDARD COMPATIBILITY TABLE
# Grades known to be incompatible with certain standards
# -------------------------------------------------------------------

GRADE_STANDARD_RULES = [
    # Stainless grades must use stainless standards
    {
        "grades":     ["304", "304L", "316", "316L", "321", "347", "410", "430"],
        "blocked_standards": ["A36", "A572", "A514"],
        "reason":     "Stainless steel grades are not compatible with carbon steel standards."
    },
    # Carbon steel grades must not use stainless standards
    {
        "grades":     ["A36", "1018", "1020", "1045", "4130", "4140"],
        "blocked_standards": ["A240", "A276", "A312", "A554"],
        "reason":     "Carbon steel grades are not compatible with stainless steel standards."
    },
    # Aluminum grades must use aluminum standards
    {
        "grades":     ["6061", "6063", "7075", "5052", "3003", "2024"],
        "blocked_standards": ["A36", "A240", "A276", "A312"],
        "reason":     "Aluminum grades are not compatible with steel standards."
    },
]

# -------------------------------------------------------------------
# GRADE / MATERIAL COMPATIBILITY
# -------------------------------------------------------------------

MATERIAL_GRADE_MAP = {
    "Stainless Steel": ["304", "304L", "316", "316L", "321", "347", "410", "430", "2205", "2507", "17-4"],
    "Carbon Steel":    ["A36", "1018", "1020", "1045", "4130", "4140", "A572", "A514"],
    "Aluminum":        ["6061", "6063", "7075", "5052", "3003", "2024"],
    "Copper":          ["110", "101", "122"],
    "Brass":           ["260", "353", "464"],
    "Titanium":        ["Grade 2", "Grade 5", "6Al-4V"],
}


# -------------------------------------------------------------------
# CLARIFICATION QUESTION TEMPLATES
# -------------------------------------------------------------------

def build_clarification_question(
    original_text: str,
    missing_fields: List[str],
    contradictions: List[str],
    dimension_warnings: List[str]
) -> Optional[str]:
    """
    Build a specific, focused clarification question to send back to the buyer.
    Only asks about fields that materially affect match, price, or compliance.
    """
    questions = []

    field_questions = {
        "material":     "What material is required for this item?",
        "grade":        "What material grade is required (e.g. 304, 316L, A36)?",
        "form":         "What product form is required (e.g. Sheet, Plate, Bar, Tube)?",
        "quantity":     "What quantity is required, and in what unit (e.g. 10 EA, 50 LB)?",
        "thickness_in": "What thickness is required (e.g. 0.060\", 1/4\", 16 gauge)?",
        "width_in":     "What width is required (e.g. 48\")?",
        "length_in":    "What length is required (e.g. 96\", 20 ft)?",
        "unit":         "What unit of measure should be used for pricing (e.g. EA, LB, SQFT)?",
        "standard":     "Is a specific standard required (e.g. ASTM A240, ASTM A36)?",
    }

    for field in missing_fields:
        if field in field_questions:
            questions.append(field_questions[field])

    for contradiction in contradictions:
        questions.append(f"Please clarify: {contradiction}")

    for warning in dimension_warnings:
        questions.append(f"Please verify: {warning}")

    if not questions:
        return None

    question_list = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(questions))
    return (
        f"We received your request for: \"{original_text}\"\n\n"
        f"To prepare an accurate quote, we need the following clarification:\n"
        f"{question_list}\n\n"
        f"Please reply with the above details and we will respond promptly."
    )


# -------------------------------------------------------------------
# MAIN VALIDATOR
# -------------------------------------------------------------------

def validate_line(item: NormalizedLineItem) -> ValidationResult:
    """
    Run all hard rule checks on a single NormalizedLineItem.
    Returns a ValidationResult with all issues listed explicitly.
    """
    missing_required   = []
    contradictions     = []
    dimension_warnings = []

    # --- Check base required fields ---
    for field in BASE_REQUIRED:
        if getattr(item, field, None) is None:
            missing_required.append(field)

    # --- Check form-specific required fields ---
    if item.form:
        form_fields = FORM_REQUIRED_FIELDS.get(item.form, [])
        for field in form_fields:
            if getattr(item, field, None) is None:
                if field not in missing_required:
                    missing_required.append(field)

    # --- Dimension sanity checks ---
    if item.form and item.form in DIMENSION_BOUNDS:
        bounds = DIMENSION_BOUNDS[item.form]
        for field, (low, high) in bounds.items():
            val = getattr(item, field, None)
            if val is not None:
                if val < low or val > high:
                    dimension_warnings.append(
                        f"{field} value {val}\" is outside the expected range "
                        f"({low}\" - {high}\") for {item.form}. Please verify."
                    )

    # --- Sheet vs Plate boundary check ---
    if item.form == "Sheet" and item.thickness_in and item.thickness_in > 0.25:
        dimension_warnings.append(
            f"Thickness {item.thickness_in}\" exceeds typical sheet maximum (0.25\"). "
            f"Did you mean Plate?"
        )
    if item.form == "Plate" and item.thickness_in and item.thickness_in < 0.1875:
        dimension_warnings.append(
            f"Thickness {item.thickness_in}\" is below typical plate minimum (0.1875\"). "
            f"Did you mean Sheet?"
        )

    # --- Grade / Material contradiction check ---
    if item.material and item.grade:
        expected_grades = MATERIAL_GRADE_MAP.get(item.material, [])
        # Compare on the base alloy so tempers ("6061-T6") are accepted
        base_grade = item.grade if item.grade.startswith("17-") else item.grade.split("-")[0]
        if expected_grades and base_grade not in expected_grades:
            contradictions.append(
                f"Grade \"{item.grade}\" is not a known grade for {item.material}. "
                f"Known grades: {', '.join(expected_grades[:5])}."
            )

    # --- Grade / Standard contradiction check ---
    if item.grade and item.standard:
        for rule in GRADE_STANDARD_RULES:
            if item.grade in rule["grades"]:
                for blocked in rule["blocked_standards"]:
                    if blocked.upper() in item.standard.upper():
                        contradictions.append(
                            f"Grade \"{item.grade}\" with standard \"{item.standard}\": "
                            f"{rule['reason']}"
                        )

    # --- Determine if clarification is needed ---
    clarification_needed = bool(
        missing_required or contradictions or dimension_warnings
    )

    clarification_question = None
    if clarification_needed:
        clarification_question = build_clarification_question(
            original_text=item.original_text,
            missing_fields=missing_required,
            contradictions=contradictions,
            dimension_warnings=dimension_warnings
        )

    is_valid = not missing_required and not contradictions

    return ValidationResult(
        line_number=item.line_number,
        is_valid=is_valid,
        missing_required_fields=missing_required,
        contradictions=contradictions,
        dimension_warnings=dimension_warnings,
        clarification_needed=clarification_needed,
        clarification_question=clarification_question
    )


def validate_all(items: List[NormalizedLineItem]) -> List[ValidationResult]:
    """Run validation on all normalized line items."""
    return [validate_line(item) for item in items]
