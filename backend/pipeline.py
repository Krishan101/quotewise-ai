"""
pipeline.py — Runs stages 2-7 on parsed lines and handles clarification answers.

  raw lines → extractor → (LLM gap-fill) → validator → matcher → pricing
            → compliance → decision → QuoteLine
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from agent import llm_available, llm_gap_fill
import prism
from audit import AuditLog
from compliance import check_compliance
from decision import decide
from extractor import extract_all, extract_fields
from guardrails import check_input
from matcher import match_line
from pricing import price_line
from schemas import LineStatus, NormalizedLineItem, QuoteLine, RawLineItem
from validator import validate_line

EXTRACTED_FIELDS = ("material", "grade", "form", "thickness_in", "width_in", "length_in",
                    "gauge", "quantity", "unit", "standard", "finish")


def _evaluate(item: NormalizedLineItem, raw: Optional[RawLineItem], audit: AuditLog) -> QuoteLine:
    """Stages 3-7 for one normalized line."""
    validation = validate_line(item)
    audit.record("validated", item.line_number,
                 is_valid=validation.is_valid,
                 missing=validation.missing_required_fields,
                 contradictions=validation.contradictions,
                 dimension_warnings=validation.dimension_warnings)

    match = match_line(item, can_match=validation.is_valid and not validation.dimension_warnings)
    audit.record("matched", item.line_number,
                 matched=match.matched, sku=match.matched_sku,
                 confidence=match.match_confidence.value,
                 rejected=len(match.rejected_skus),
                 ambiguity=match.ambiguity_question)

    pricing = price_line(item, match)
    audit.record("priced", item.line_number,
                 priced=pricing.priced, unit_price=pricing.unit_price,
                 total=pricing.total_price, benchmark_mid=pricing.benchmark_price,
                 source=pricing.benchmark_source)

    compliance = check_compliance(item, match)
    audit.record("compliance_checked", item.line_number,
                 all_clear=compliance.all_clear,
                 requirements={r.requirement: r.status.value for r in compliance.requirements})

    line = decide(item, validation, match, pricing, compliance, raw)
    audit.record("status_assigned", item.line_number, status=line.status.value, reason=line.status_reason)
    return line


def run_pipeline(
    raw_lines: List[RawLineItem],
    audit: AuditLog,
    use_llm: bool = True,
) -> Tuple[List[QuoteLine], bool, List[str]]:
    """Returns (quote_lines, llm_used, pipeline_warnings)."""
    warnings: List[str] = []
    audit.record("parsed", None, lines=len(raw_lines))

    normalized = extract_all(raw_lines)
    for n in normalized:
        n.guardrail_flags = check_input(n.original_text)
        if n.guardrail_flags:
            audit.record("guardrail_flagged", n.line_number, flags=n.guardrail_flags)
        audit.record("rules_extracted", n.line_number,
                     fields={f: getattr(n, f) for f in EXTRACTED_FIELDS if getattr(n, f) is not None},
                     unknown=n.unknown_fields)

    llm_used = False
    if use_llm and llm_available():
        normalized = llm_gap_fill(normalized, session_id=audit.rfq_id)
        llm_used = True
        for n in normalized:
            llm_notes = [w for w in n.extraction_warnings if "LLM" in w or "Knowledge Base" in w]
            if llm_notes:
                audit.record("llm_gap_fill", n.line_number, notes=llm_notes)
    elif use_llm:
        warnings.append("LLM gap-fill unavailable (NICRRON_API_KEY not set). Rule-based extraction only; "
                        "anything rules could not read is sent back for clarification.")

    raw_by_line = {r.line_number: r for r in raw_lines}
    lines = [_evaluate(n, raw_by_line.get(n.line_number), audit) for n in normalized]
    prism.submit_line_trajectories(audit.rfq_id, lines)
    return lines, llm_used, warnings


def apply_clarification(line: QuoteLine, answer: str, audit: AuditLog, actor: str = "reviewer") -> QuoteLine:
    """
    Re-run a line with the buyer's answer.
    Fields stated in the answer override the original; everything else comes
    from the original text. The original wording is never modified.
    """
    previous = line.normalized
    from_answer = extract_fields(RawLineItem(line_number=line.line_number, original_text=answer))
    from_original = extract_fields(RawLineItem(line_number=line.line_number, original_text=line.original_text))

    merged = from_original.model_copy(deep=True)
    changed = {}
    for f in EXTRACTED_FIELDS:
        v = getattr(from_answer, f)
        if v is not None:
            if getattr(merged, f) != v:
                changed[f] = {"from": getattr(merged, f), "to": v}
            setattr(merged, f, v)
        elif previous is not None and getattr(merged, f) is None and getattr(previous, f) is not None:
            # Keep values from the earlier pass (e.g. a prior clarification or LLM fill)
            setattr(merged, f, getattr(previous, f))
    if from_answer.thickness_in is not None and from_answer.gauge is None:
        merged.gauge = None  # an explicit thickness in the answer supersedes the original gauge
    # A thickness in the answer resolves any gauge-vs-thickness conflict in the original
    conflict_resolved = from_answer.thickness_in is not None
    merged.extraction_warnings = [
        w for w in from_original.extraction_warnings
        if not (conflict_resolved and "verify with buyer" in w.lower())
    ] + from_answer.extraction_warnings
    merged.unknown_fields = [f for f in from_original.unknown_fields if getattr(merged, f, None) is None]
    # The buyer's answer is untrusted input too
    merged.guardrail_flags = check_input(line.original_text) + check_input(answer)

    history = list(line.clarification_history)
    history.append({
        "question": line.clarification_question,
        "answer": answer,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fields_changed": changed,
    })
    merged.notes = " | ".join(f"Buyer clarification: {h['answer']}" for h in history)

    audit.record("clarification_applied", line.line_number, actor=actor, answer=answer, fields_changed=changed)

    # raw=None: the buyer has now confirmed the line, so the original parse confidence no longer applies
    new_line = _evaluate(merged, None, audit)
    new_line.clarification_history = history
    prism.submit_line_trajectories(audit.rfq_id, [new_line])
    return new_line


def summarize(lines: List[QuoteLine]) -> dict:
    counts = {s.value: 0 for s in LineStatus}
    for l in lines:
        counts[l.status.value] += 1
    ready = [l for l in lines if l.status == LineStatus.READY_FOR_REVIEW]
    return {
        "counts": counts,
        "ready_lines": len(ready),
        "approved_lines": sum(1 for l in lines if l.approved),
        "quotable_total": round(sum((l.pricing.total_price or 0) for l in ready if l.pricing), 2),
        "approved_total": round(sum((l.pricing.total_price or 0) for l in ready if l.pricing and l.approved), 2),
    }
