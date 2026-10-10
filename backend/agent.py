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
from typing import List, Optional
from openai import OpenAI
from schemas import RawLineItem, NormalizedLineItem


# -------------------------------------------------------------------
# NICRRON CLIENT
# -------------------------------------------------------------------

def get_nicrron_client() -> OpenAI:
    api_key = os.getenv("NICRRON_API_KEY")
    if not api_key:
        raise ValueError("NICRRON_API_KEY environment variable not set.")
    return OpenAI(
        base_url="https://api.nicrron.ai/v1",
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
    partially_extracted: List[NormalizedLineItem]
) -> List[NormalizedLineItem]:
    """
    For each NormalizedLineItem, send only unknown fields to NicrronNinoo.
    Merges LLM-filled values back into the item, preserving rule-extracted values.
    Items with no unknown fields are returned as-is (no API call needed).
    """
    if not partially_extracted:
        return []

    # Split into: needs LLM vs already complete
    needs_llm = [item for item in partially_extracted if item.unknown_fields]
    already_complete = [item for item in partially_extracted if not item.unknown_fields]

    if not needs_llm:
        return partially_extracted

    client = get_nicrron_client()

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

    try:
        response = client.chat.completions.create(
            model="nicrron/auto",
            max_tokens=4000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message}
            ]
        )

        raw_response = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        if raw_response.startswith("```"):
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]
        raw_response = raw_response.strip()

        llm_results = json.loads(raw_response)
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
    still_unknown = llm_data.get("still_unknown", [])
    llm_warnings = llm_data.get("extraction_warnings", [])
    llm_confidence = float(llm_data.get("extraction_confidence", 0.5))

    # Apply only to fields that were unknown
    for field in list(item.unknown_fields):
        if field in filled and filled[field] is not None:
            # Only set if currently None (rules win)
            current_val = getattr(item, field, None)
            if current_val is None:
                try:
                    setattr(item, field, filled[field])
                except Exception:
                    pass

    # Update unknown fields to what LLM also couldn't resolve
    item.unknown_fields = still_unknown

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

def safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
