"""
decision.py — Stage 7: Decision Engine

Assigns exactly one status per line, in strict priority order:

  1. PARSER_REVIEW        raw text could not be reliably parsed into a line item
  2. NEEDS_CLARIFICATION  missing / contradictory / ambiguous field that changes match or price
  3. NO_COMPATIBLE_MATCH  no catalog item passed hard filters
  4. PRICE_UNVERIFIED     match found but price cannot be verified against a benchmark
  5. COMPLIANCE_REVIEW    a required document has no evidence
  6. READY_FOR_REVIEW     everything checked; still needs human approval

READY_FOR_REVIEW is never "approved". Approval is a separate human action.
"""

from typing import Optional

from schemas import (
    CatalogMatchResult, ComplianceResult, LineStatus, NormalizedLineItem,
    PricingResult, QuoteLine, RawLineItem, ValidationResult
)

PARSE_CONFIDENCE_FLOOR = 0.5
SPEC_FIELDS = ("material", "grade", "form")


def _is_unparseable(raw: Optional[RawLineItem], item: NormalizedLineItem) -> Optional[str]:
    if raw is not None and raw.parse_confidence < PARSE_CONFIDENCE_FLOOR:
        return (f"Parse confidence {raw.parse_confidence:.2f} is below {PARSE_CONFIDENCE_FLOOR}. "
                f"{' '.join(raw.parse_warnings)}").strip()
    if item.is_line_item is False:
        return "LLM identified this text as a header, footer, or boilerplate rather than a line item."
    if all(getattr(item, f) is None for f in SPEC_FIELDS):
        return "No material, grade, or product form could be identified. This may not be a line item."
    return None


def _buyer_question(original_text: str, body: str) -> str:
    return (
        f"We received your request for: \"{original_text}\"\n\n"
        f"{body}\n\n"
        f"Please reply and we will update the quote promptly."
    )


def decide(
    item: NormalizedLineItem,
    validation: ValidationResult,
    match: CatalogMatchResult,
    pricing: PricingResult,
    compliance: ComplianceResult,
    raw: Optional[RawLineItem] = None,
) -> QuoteLine:
    base = dict(
        line_number=item.line_number,
        original_text=item.original_text,
        normalized=item,
        validation=validation,
        match=match,
        pricing=pricing,
        compliance=compliance,
    )

    # 1. PARSER_REVIEW — input guardrail first: never auto-quote a line carrying injected instructions
    if item.guardrail_flags:
        return QuoteLine(
            status=LineStatus.PARSER_REVIEW,
            status_reason="Held by input guardrail, human review required. " + " ".join(item.guardrail_flags),
            **base,
        )

    reason = _is_unparseable(raw, item)
    if reason:
        return QuoteLine(status=LineStatus.PARSER_REVIEW, status_reason=reason, **base)

    # 2. NEEDS_CLARIFICATION — validator issues
    if validation.clarification_needed:
        parts = []
        if validation.missing_required_fields:
            parts.append("missing " + ", ".join(validation.missing_required_fields))
        if validation.contradictions:
            parts.append(f"{len(validation.contradictions)} contradiction(s)")
        if validation.dimension_warnings:
            parts.append(f"{len(validation.dimension_warnings)} dimension warning(s)")
        return QuoteLine(
            status=LineStatus.NEEDS_CLARIFICATION,
            status_reason="Cannot quote without buyer input: " + "; ".join(parts) + ".",
            clarification_question=validation.clarification_question,
            **base,
        )

    # 2b. NEEDS_CLARIFICATION — extraction conflicts (e.g. gauge vs explicit thickness)
    conflicts = [w for w in item.extraction_warnings if "verify with buyer" in w.lower()]
    if conflicts:
        return QuoteLine(
            status=LineStatus.NEEDS_CLARIFICATION,
            status_reason="Conflicting values in the request: " + " ".join(conflicts),
            clarification_question=_buyer_question(
                item.original_text, "Please confirm: " + " ".join(conflicts)
            ),
            **base,
        )

    # 2c. NEEDS_CLARIFICATION — catalog ambiguity the buyer must resolve
    if match.ambiguity_question:
        return QuoteLine(
            status=LineStatus.NEEDS_CLARIFICATION,
            status_reason=f"{len(match.alternatives)} compatible SKUs differ on an attribute the buyer "
                          f"did not specify. Not choosing for the buyer.",
            clarification_question=_buyer_question(item.original_text, match.ambiguity_question),
            **base,
        )

    # 3. NO_COMPATIBLE_MATCH
    if not match.matched:
        near = [r for r in match.rejection_reasons if ":" in r][:3]
        return QuoteLine(
            status=LineStatus.NO_COMPATIBLE_MATCH,
            status_reason="No catalog item passed the hard filters. "
                          + (f"Closest rejected: {'; '.join(near)}." if near else "No similar items in catalog."),
            **base,
        )

    # 4. PRICE_UNVERIFIED
    if not pricing.priced or pricing.price_unverified:
        return QuoteLine(
            status=LineStatus.PRICE_UNVERIFIED,
            status_reason=pricing.price_rationale or "Price could not be verified.",
            **base,
        )

    # 5. COMPLIANCE_REVIEW
    if not compliance.all_clear:
        return QuoteLine(
            status=LineStatus.COMPLIANCE_REVIEW,
            status_reason=" ".join(compliance.compliance_warnings),
            **base,
        )

    # 6. READY_FOR_REVIEW
    notes = []
    if match.match_confidence.value != "HIGH":
        notes.append(f"Match confidence {match.match_confidence.value}; see assumptions.")
    if pricing.price_warnings:
        notes.append(f"{len(pricing.price_warnings)} pricing note(s).")
    return QuoteLine(
        status=LineStatus.READY_FOR_REVIEW,
        status_reason="All checks passed: fields complete, catalog match confirmed, price verified "
                      "against benchmark, compliance evidence present. Awaiting human approval."
                      + (" " + " ".join(notes) if notes else ""),
        ready_for_export=True,
        **base,
    )
