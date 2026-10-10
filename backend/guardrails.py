"""
guardrails.py — Input guardrail for untrusted RFQ text

RFQ emails and attachments come from outside the company and are fed to an LLM,
so a line can carry instructions aimed at the model or the quoting process
("ignore previous instructions", "price this at $0", "mark as approved").

Flagged lines:
  - are never sent to the LLM gap-filler
  - are held as PARSER_REVIEW for a human, whatever the rules extracted

This runs locally because the PRISM dashboard Guardrail, on the SDK path,
flags but does not block. Both run: PRISM sees every traced LLM input, and this
check stops a flagged line before it reaches the model or the quote.
"""

import re
from typing import List

INJECTION_PATTERNS = [
    (r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b.{0,20}\b(instructions?|rules?|prompts?|guidelines?|constraints?)",
     "asks the model to ignore its instructions"),
    (r"\b(system|developer)\s*(prompt|message|instructions?)\b", "references the system prompt"),
    (r"\byou\s+are\s+now\b|\bact\s+as\b|\bpretend\s+(to\s+be|you)\b|\bnew\s+role\b", "tries to change the model's role"),
    (r"(^|\s)(system|assistant)\s*:", "contains a chat role marker"),
    (r"<\|?(im_start|im_end|system|endoftext)\|?>|\[/?INST\]", "contains model control tokens"),
    (r"\b(set|make|change|quote|price)\b.{0,30}\b(price|cost|total)\b.{0,20}(\$\s*0(\.0+)?\b|zero|free|no\s+charge)",
     "tries to dictate a zero / free price"),
    (r"\b(mark|set|flag)\b.{0,30}\b(approved|ready(_for_review)?|compliant|verified)\b", "tries to dictate a review outcome"),
    (r"\b(skip|bypass|disable)\b.{0,30}\b(validation|review|approval|compliance|checks?|guardrails?)\b",
     "asks to bypass checks"),
    (r"\b(reveal|print|output|show)\b.{0,30}\b(api\s*key|secret|password|credentials?|prompt)\b", "asks for secrets or the prompt"),
]

# Zero-width and bidi control characters used to hide text from a human reader
HIDDEN_CHARS = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")


def check_input(text: str) -> List[str]:
    """Returns a list of human-readable flags; empty means the line looks clean."""
    flags = []
    for pattern, reason in INJECTION_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            flags.append(f"Possible prompt injection: {reason} (\"{m.group(0).strip()[:60]}\")")
    if HIDDEN_CHARS.search(text):
        flags.append("Hidden zero-width or text-direction characters found in the line")
    return flags
