"""
prism.py — PRISM by Block Convey integration (prismtrace-sdk)

Three uses, all keyed to one agent identity (PRISM_AGENT_NAME / PRISM_AGENT_ID):

  1. Tracing + Guardrail input   Every NicrronNinoo call is traced with the raw RFQ
                                  text as input, so the dashboard Guardrail
                                  (prompt-injection check) runs on it.
  2. Evaluator output            Each line's pipeline run (extract → LLM fill →
                                  validate → match → price → compliance → status)
                                  is submitted as a trajectory. The Evaluator
                                  attached in the Evaluators Hub scores the status
                                  decision; the verdict is read back per line.
  3. Knowledge Base grounding    Values the LLM fills in (grade, standard,
                                  material, form, finish) are checked against the
                                  spec reference in the PRISM Knowledge Base. A
                                  value the KB does not support is rejected.

When PRISMTRACE_API_KEY / PRISMTRACE_PROJECT_ID are not set, or the SDK is not
installed, every function here is a no-op that reports "disabled". The pipeline
never depends on PRISM being reachable.
"""

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

try:
    from prismtrace import PRISMtrace
except ImportError:
    PRISMtrace = None

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SPEC_REFERENCE_PATH = os.path.join(DATA_DIR, "spec_reference.md")
SPEC_REFERENCE_NAME = "quotewise_spec_reference.md"

AGENT_NAME = os.getenv("PRISM_AGENT_NAME", "quotewise-rfq-agent")
AGENT_ID = os.getenv("PRISM_AGENT_ID", AGENT_NAME)

# Fields the LLM may fill that the Knowledge Base can confirm
KB_GROUNDED_FIELDS = ("material", "grade", "form", "standard", "finish")

_client = None
_client_lock = threading.Lock()
# Trajectory submits are synchronous HTTP calls (up to 30 s on a cold backend),
# so they run off the request thread
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="prism")


def enabled() -> bool:
    return (PRISMtrace is not None
            and bool(os.getenv("PRISMTRACE_API_KEY"))
            and bool(os.getenv("PRISMTRACE_PROJECT_ID")))


def status() -> str:
    if PRISMtrace is None:
        return "disabled (prismtrace-sdk not installed)"
    if not enabled():
        return "disabled (PRISMTRACE_API_KEY / PRISMTRACE_PROJECT_ID not set)"
    return f"enabled (agent {AGENT_NAME})"


def client():
    global _client
    if not enabled():
        return None
    with _client_lock:
        if _client is None:
            # host resolves from PRISMTRACE_HOST, else the SDK's production default
            _client = PRISMtrace(
                api_key=os.environ["PRISMTRACE_API_KEY"],
                host=os.getenv("PRISMTRACE_HOST", "https://api.prism.blockconvey.com"),
                project_id=os.environ["PRISMTRACE_PROJECT_ID"],
            )
        return _client


# -------------------------------------------------------------------
# 1. TRACING (Guardrail input)
# -------------------------------------------------------------------

def trace_llm_call(
    model: str,
    messages: List[dict],
    output: str,
    latency_ms: int,
    tokens_in: int = 0,
    tokens_out: int = 0,
    session_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    c = client()
    if c is None:
        return
    c.trace_llm(
        model=model,
        input_messages=messages,
        output=output,
        latency_ms=latency_ms,
        token_count_input=tokens_in,
        token_count_output=tokens_out,
        agent_id=AGENT_ID,
        agent_name=AGENT_NAME,
        session_id=session_id,
        metadata={"stage": "llm_gap_fill", **(metadata or {})},
    )


# -------------------------------------------------------------------
# 2. TRAJECTORIES (Evaluator output)
# -------------------------------------------------------------------

def _summ(v: Any, limit: int = 400) -> str:
    s = v if isinstance(v, str) else repr(v)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def build_line_steps(line) -> List[dict]:
    """Ordered steps for one QuoteLine, in the shape submit_trajectory expects."""
    n, v, m, p, c = line.normalized, line.validation, line.match, line.pricing, line.compliance
    steps = []
    if n:
        fields = {f: getattr(n, f) for f in ("material", "grade", "form", "thickness_in", "width_in",
                                             "length_in", "quantity", "unit", "standard", "finish")
                  if getattr(n, f) is not None}
        steps.append({
            "step_type": "tool_call", "tool_name": "rule_extractor", "label": "Extract fields",
            "input_summary": _summ(line.original_text), "output_summary": _summ(fields),
        })
        llm_notes = [w for w in n.extraction_warnings if "LLM" in w or "Knowledge Base" in w]
        if llm_notes:
            steps.append({
                "step_type": "tool_call", "tool_name": "llm_gap_fill_kb_grounded", "label": "LLM gap-fill + KB grounding",
                "input_summary": _summ(n.unknown_fields), "output_summary": _summ(" | ".join(llm_notes)),
            })
        if n.guardrail_flags:
            steps.append({
                "step_type": "tool_call", "tool_name": "input_guardrail", "label": "Input guardrail",
                "input_summary": _summ(line.original_text), "output_summary": _summ(n.guardrail_flags),
                "status": "error",
            })
    if v:
        steps.append({
            "step_type": "tool_call", "tool_name": "validator", "label": "Validate",
            "output_summary": _summ({"missing": v.missing_required_fields, "contradictions": v.contradictions,
                                     "dimension_warnings": v.dimension_warnings}),
        })
    if m:
        steps.append({
            "step_type": "tool_call", "tool_name": "catalog_matcher", "label": "Match catalog (hard filters)",
            "output_summary": _summ({"matched_sku": m.matched_sku, "reason": m.hard_filter_reason,
                                     "closest_rejections": m.rejection_reasons[:3],
                                     "ambiguity": m.ambiguity_question}),
        })
    if p:
        steps.append({
            "step_type": "tool_call", "tool_name": "pricing_engine", "label": "Price vs benchmark",
            "output_summary": _summ(p.price_rationale or "not priced"),
        })
    if c:
        steps.append({
            "step_type": "tool_call", "tool_name": "compliance_checker", "label": "Check compliance evidence",
            "output_summary": _summ({r.requirement: r.status.value for r in c.requirements}),
        })
    steps.append({
        "step_type": "final_answer", "label": f"Status: {line.status.value}",
        "output_summary": _summ(f"{line.status.value}: {line.status_reason}"
                                + (f" | Question to buyer: {line.clarification_question}" if line.clarification_question else "")),
    })
    return steps


def submit_line_trajectories(rfq_id: str, lines: list) -> None:
    """
    Fire-and-forget: submits one trajectory per line and stores the returned
    trajectory id on the line object, so the evaluation can be read later.
    """
    c = client()
    if c is None:
        return

    def work():
        for line in list(lines):
            try:
                resp = c.submit_trajectory(
                    build_line_steps(line),
                    agent_name=AGENT_NAME,
                    agent_id=AGENT_ID,
                    conversation_id=rfq_id,
                    request_id=f"{rfq_id}-L{line.line_number}-{len(line.clarification_history)}",
                    model=os.getenv("NICRRON_MODEL", "nicrron/auto"),
                    final_status="success",
                )
                if resp and resp.get("id"):
                    line.prism_trajectory_id = str(resp["id"])
            except Exception as e:  # never break the app over telemetry
                line.prism_trajectory_id = None
                print(f"PRISM trajectory submit failed for line {line.line_number}: {e}")

    _executor.submit(work)


def get_evaluation(trajectory_id: str) -> Optional[dict]:
    c = client()
    if c is None:
        return None
    return c.get_trajectory_evaluation(trajectory_id)


# -------------------------------------------------------------------
# 3. KNOWLEDGE BASE GROUNDING
# -------------------------------------------------------------------

def seed_knowledge_base(force: bool = False) -> Dict[str, Any]:
    """Upload the spec reference once. Re-uploading creates duplicates, so it checks first."""
    c = client()
    if c is None:
        return {"ok": False, "message": status()}
    existing = [d for d in c.kb_list_documents(agent_id=AGENT_ID)
                if d.get("name") == SPEC_REFERENCE_NAME or d.get("filename") == SPEC_REFERENCE_NAME]
    if existing and not force:
        return {"ok": True, "message": "spec reference already in Knowledge Base", "documents": existing}
    with open(SPEC_REFERENCE_PATH, encoding="utf-8") as f:
        content = f.read()
    resp = c.kb_upload(
        SPEC_REFERENCE_NAME, content, agent_id=AGENT_ID, content_type="text/markdown",
        description="QuoteWise AI spec reference: grades, ASTM specs, forms, gauges, finishes (DEMO REFERENCE)",
    )
    return {"ok": bool(resp), "message": "uploaded" if resp else "upload failed", "document": resp}


def _chunk_text(chunk: dict) -> str:
    for key in ("content", "text", "chunk_text", "chunk", "page_content"):
        if isinstance(chunk.get(key), str):
            return chunk[key]
    return str(chunk)


def _mentions(text: str, value: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


# Which already-known fields a KB sentence must also mention to confirm each field.
# A standard is only confirmed for the product form actually requested.
GROUNDING_ANCHORS = {
    "material": ("grade",),
    "grade":    ("material",),
    "form":     ("material", "grade"),
    "standard": ("material", "grade", "form"),
    "finish":   ("material",),
}

NEGATION = re.compile(r"\b(not|never|no longer|excludes?)\b", re.IGNORECASE)


def ground_field(field: str, value: str, context: Dict[str, Optional[str]]) -> Tuple[Optional[bool], str]:
    """
    Check one LLM-filled value against the Knowledge Base.

    Returns (supported, evidence):
      True   one KB sentence states this value together with the line's known
             context (e.g. "ASTM A240 covers Stainless Steel grade 316L sheet")
      False  the KB was searched and no sentence supports it -> caller rejects the value
      None   the KB could not be consulted                  -> caller keeps the value,
                                                               marked ungrounded
    Negated sentences ("ASTM A276 does not cover sheet") never count as support.
    """
    c = client()
    if c is None:
        return None, "PRISM Knowledge Base not configured"

    value = str(value).strip()
    anchors = [context[k] for k in GROUNDING_ANCHORS.get(field, ()) if context.get(k)]
    query = " ".join([field, value] + anchors)

    try:
        results = c.kb_search(query, agent_id=AGENT_ID, limit=5)
    except Exception as e:
        return None, f"Knowledge Base search failed: {type(e).__name__}"
    if not results:
        return False, f"Knowledge Base returned no passage for \"{query}\""

    lookup_value = value
    if field == "grade" and not value.startswith("17-"):
        lookup_value = value.split("-")[0]  # tempers: confirm the base alloy
    if field == "finish":
        lookup_value = value.replace("#", "No.")

    for chunk in results:
        for sentence in re.split(r"(?<=\.)\s+|\n+", _chunk_text(chunk)):
            if NEGATION.search(sentence):
                continue
            if _mentions(sentence, lookup_value) and all(_mentions(sentence, a.split("/")[0]) for a in anchors):
                return True, f"KB: \"{sentence.strip(' -')[:220]}\""
    return False, f"No Knowledge Base passage states {field} \"{value}\"" + (
        f" for {' '.join(anchors)}" if anchors else "")
