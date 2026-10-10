"""
agent.py — Stage 2b: LLM Gap-Filler (NicrronNinoo)

Runs AFTER extractor.py.
Only sends fields that rule-based extraction could not resolve to the LLM.
Never re-extracts fields already found by rules.

Trust hierarchy:
  1. extractor.py (rules)  — deterministic, auditable, always wins
  2. agent.py (LLM)        — fills only the gaps rules missed
"""

import json
import os
import re
import time
from typing import List, Optional

import prism

try:
    from openai import OpenAI
except ImportError:  # LLM gap-fill becomes unavailable; rules still run
    OpenAI = None
from schemas import RawLineItem, NormalizedLineItem


# -------------------------------------------------------------------
# NICRRON CLIENT
# -------------------------------------------------------------------

NICRRON_BASE_URL = os.getenv("NICRRON_BASE_URL", "https://api.nicrron.ai/v1")
NICRRON_MODEL = os.getenv("NICRRON_MODEL", "nicrron/auto")

# Fields the LLM may fill, and their types. Anything else it returns is ignored.
NUMERIC_FIELDS = {"thickness_in", "width_in", "length_in", "quantity"}
STRING_FIELDS = {"material", "grade", "form", "gauge", "unit", "standard", "finish"}


def llm_available() -> bool:
    return OpenAI is not None and bool(os.getenv("NICRRON_API_KEY"))


def get_nicrron_client():
    api_key = os.getenv("NICRRON_API_KEY")
    if OpenAI is None:
        raise ValueError("openai package not installed.")
    if not api_key:
        raise ValueError("NICRRON_API_KEY environment variable not set.")
    return OpenAI(
        base_url=NICRRON_BASE_URL,
        api_key=api_key
    )


# -------------------------------------------------------------------
# SYSTEM PROMPT
# -------------------------------------------------------------------

SYSTEM_PROMPT = """You are an industrial materials specification expert.

You are given RFQ (Request for Quotation) line items that have already been partially parsed by a rule-based system.
Your job is ONLY to fill in the fields that rules could not determine.

STRICT RULES:
1. Only fill fields listed in "fields_to_fill". Do not touch other fields.
2. If you cannot determine a field with confidence, return null for it. Never guess.
3. Do not re-interpret fields already extracted by rules.
4. unknown_fields in your response must list only fields you also could not determine.
5. extraction_warnings must note any ambiguities or assumptions.
6. is_line_item: set false only if the line is clearly a header, footer, or boilerplate.

OUTPUT FORMAT:
Return a JSON array, one object per input line, in the same order.
Each object must have exactly:
{
  "line_number": <integer>,
  "fields_filled": {
    "<field_name>": <value or null>,
    ...
  },
  "still_unknown": [<fields you also could not determine>],
  "extraction_confidence": <float 0.0-1.0>,
  "extraction_warnings": [<warning strings>],
  "is_line_item": <true|false>
}

Return ONLY the JSON array. No preamble, no markdown fences."""


# -------------------------------------------------------------------
# MAIN GAP-FILL FUNCTION
# -------------------------------------------------------------------

def llm_gap_fill(
    partially_extracted: List[NormalizedLineItem],
    session_id: Optional[str] = None,
) -> List[NormalizedLineItem]:
    """
    For each NormalizedLineItem, send only unknown fields to NicrronNinoo.
    Merges LLM-filled values back into the item, preserving rule-extracted values.
    Items with no unknown fields are returned as-is (no API call needed).
    """
    if not partially_extracted:
        return []

    # Split into: needs LLM vs already complete. Lines flagged by the input
    # guardrail never reach the model.
    needs_llm = [item for item in partially_extracted if item.unknown_fields and not item.guardrail_flags]
    already_complete = [item for item in partially_extracted if item not in needs_llm]

    if not needs_llm:
        return partially_extracted

    if not llm_available():
        for item in needs_llm:
            item.extraction_warnings.append(
                "LLM gap-fill skipped (NICRRON_API_KEY not set). Unknown fields remain unknown."
            )
        return partially_extracted

    # Build prompt payload
    lines_payload = []
    for item in needs_llm:
        lines_payload.append({
            "line_number": item.line_number,
            "original_text": item.original_text,
            "already_extracted": {
                "material":     item.material,
                "grade":        item.grade,
                "form":         item.form,
                "thickness_in": item.thickness_in,
                "width_in":     item.width_in,
                "length_in":    item.length_in,
                "gauge":        item.gauge,
                "quantity":     item.quantity,
                "unit":         item.unit,
                "standard":     item.standard,
                "finish":       item.finish,
            },
            "fields_to_fill": item.unknown_fields
        })

    user_message = f"""Fill only the unknown fields for these partially-parsed RFQ lines:

{json.dumps(lines_payload, indent=2)}"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message}
    ]
    try:
        client = get_nicrron_client()
        started = time.perf_counter()
        response = client.chat.completions.create(
            model=NICRRON_MODEL,
            max_tokens=4000,
            messages=messages
        )

        raw_response = response.choices[0].message.content.strip()

        # Trace to PRISM: the RFQ text in `messages` is what the dashboard Guardrail inspects
        usage = getattr(response, "usage", None)
        try:
            prism.trace_llm_call(
                model=getattr(response, "model", None) or NICRRON_MODEL,
                messages=messages,
                output=raw_response,
                latency_ms=int((time.perf_counter() - started) * 1000),
                tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                tokens_out=getattr(usage, "completion_tokens", 0) or 0,
                session_id=session_id,
                metadata={"lines": [i.line_number for i in needs_llm]},
            )
        except Exception as e:
            print(f"PRISM trace failed: {e}")

        # Strip markdown fences if present
        if raw_response.startswith("```"):
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]
        raw_response = raw_response.strip()

        llm_results = json.loads(raw_response)
        if isinstance(llm_results, dict):
            llm_results = [llm_results]
        llm_map = {r["line_number"]: r for r in llm_results if "line_number" in r}

        # Merge LLM results back into partially extracted items
        merged = []
        for item in needs_llm:
            llm_data = llm_map.get(item.line_number)
            if llm_data:
                merged.append(merge_llm_into_item(item, llm_data))
            else:
                # LLM did not return this line
                item.extraction_warnings.append(
                    "LLM did not return a result for this line. Unknown fields remain."
                )
                merged.append(item)

        # Combine and re-sort by line number
        all_items = merged + already_complete
        all_items.sort(key=lambda x: x.line_number)
        return all_items

    except json.JSONDecodeError as e:
        # LLM returned bad JSON — return partially extracted items as-is
        for item in needs_llm:
            item.extraction_warnings.append(
                f"LLM gap-fill returned invalid JSON: {str(e)}. Unknown fields remain."
            )
        all_items = needs_llm + already_complete
        all_items.sort(key=lambda x: x.line_number)
        return all_items

    except Exception as e:
        for item in needs_llm:
            item.extraction_warnings.append(
                f"LLM gap-fill API call failed: {str(e)}. Unknown fields remain."
            )
        all_items = needs_llm + already_complete
        all_items.sort(key=lambda x: x.line_number)
        return all_items


# -------------------------------------------------------------------
# MERGE LLM RESULT INTO ITEM
# -------------------------------------------------------------------

def merge_llm_into_item(
    item: NormalizedLineItem,
    llm_data: dict
) -> NormalizedLineItem:
    """
    Merge LLM-filled fields into a NormalizedLineItem.
    Rule-extracted fields are NEVER overwritten.
    Only fields in item.unknown_fields are eligible for LLM fill.
    """
    filled = llm_data.get("fields_filled", {})
    llm_warnings = llm_data.get("extraction_warnings", [])
    llm_confidence = float(llm_data.get("extraction_confidence", 0.5))

    # Apply only to fields that were unknown
    llm_filled = []
    for field in list(item.unknown_fields):
        if field in filled and filled[field] is not None:
            # Only set if currently None (rules win)
            if getattr(item, field, None) is not None:
                continue
            if field in NUMERIC_FIELDS:
                value = safe_float(filled[field])
            elif field in STRING_FIELDS:
                value = str(filled[field]).strip() or None
            else:
                value = None
            if value is None:
                continue

            # Grounding: an LLM value is only accepted with evidence
            if field in NUMERIC_FIELDS:
                if not _number_in_text(value, item.original_text):
                    item.extraction_warnings.append(
                        f"LLM value {field}={value} REJECTED: that number does not appear in the buyer's text."
                    )
                    continue
                evidence = "number appears in the buyer's text"
            elif field in prism.KB_GROUNDED_FIELDS:
                context = {"material": item.material, "grade": item.grade, "form": item.form}
                supported, evidence = prism.ground_field(field, value, context)
                if supported is False:
                    item.extraction_warnings.append(
                        f"LLM value {field}=\"{value}\" REJECTED by Knowledge Base grounding. {evidence}"
                    )
                    continue
                if supported is None:
                    evidence = f"UNGROUNDED ({evidence})"
            else:
                evidence = "not groundable"

            setattr(item, field, value)
            llm_filled.append(f"{field}={value} [{evidence}]")

    if llm_filled:
        item.extraction_warnings.append(
            "Filled by LLM (NicrronNinoo), not rules: " + "; ".join(llm_filled)
            + ". Verify against the original text."
        )

    if llm_data.get("is_line_item") is False:
        item.is_line_item = False

    # Unknown = whatever is still null (do not trust the LLM's own list blindly)
    item.unknown_fields = [
        f for f in item.unknown_fields if getattr(item, f, None) is None
    ]

    # Merge warnings
    item.extraction_warnings.extend(llm_warnings)

    # Blend confidence: rule confidence + LLM confidence weighted
    item.extraction_confidence = round(
        (item.extraction_confidence + llm_confidence) / 2, 2
    )

    return item


# -------------------------------------------------------------------
# HELPER
# -------------------------------------------------------------------

def _number_in_text(value: float, text: str) -> bool:
    """True if the number is written in the text (25 / 25.0 / 0.06 / .060 all count)."""
    for m in re.finditer(r"\d*\.?\d+", text):
        try:
            if abs(float(m.group(0)) - value) < 1e-9:
                return True
        except ValueError:
            pass
    return False


def safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
