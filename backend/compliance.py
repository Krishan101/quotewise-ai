"""
compliance.py — Stage 6: Compliance Checker

Finds compliance requirements in the buyer's text (rules in compliance_rules.csv),
then checks each one against evidence on the matched catalog record.

  PRESENT  — the catalog record explicitly shows the evidence
  MISSING  — the catalog record explicitly shows it is NOT available
  UNKNOWN  — no record either way

Never claims compliance without evidence. UNKNOWN is never treated as PRESENT.
"""

import csv
import os
import re
from typing import List, Optional

from schemas import (
    CatalogMatchResult, ComplianceRequirement, ComplianceResult,
    ComplianceStatus, NormalizedLineItem
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RULES_PATH = os.path.join(DATA_DIR, "compliance_rules.csv")

DOMESTIC_COUNTRIES = {"USA", "US", "UNITED STATES"}

_RULES_CACHE: Optional[List[dict]] = None


def get_rules() -> List[dict]:
    global _RULES_CACHE
    if _RULES_CACHE is None:
        with open(RULES_PATH, newline="", encoding="utf-8") as f:
            _RULES_CACHE = [
                {k: (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(f)
            ]
    return _RULES_CACHE


def _norm_std(s: str) -> str:
    return s.upper().replace(" ", "").replace("-", "")


def _rule_triggered(rule: dict, item: NormalizedLineItem, text: str) -> Optional[str]:
    """Returns the evidence of the trigger (what in the request caused it), or None."""
    ttype, tval = rule["trigger_type"], rule["trigger_value"]
    if ttype == "keyword":
        m = re.search(tval, text, re.IGNORECASE)
        return f"Buyer text contains \"{m.group(0)}\"" if m else None
    if ttype == "material":
        if item.material and item.material in tval.split("|"):
            return f"Material is {item.material}"
        return None
    if ttype == "standard":
        if item.standard and (tval == "*" or _norm_std(tval) == _norm_std(item.standard)):
            return f"Buyer specified {item.standard}"
        return None
    return None


def _check_evidence(rule: dict, item: NormalizedLineItem, match: CatalogMatchResult):
    """Returns (status, evidence, notes)."""
    field = rule["evidence_field"]
    cat = match.matched_item if match.matched else None

    if field == "none":
        return ComplianceStatus.UNKNOWN, None, "Not tracked in catalog data; confirm with supplier."

    if cat is None:
        return ComplianceStatus.UNKNOWN, None, "No confirmed catalog match, so no evidence can be checked."

    if field == "mtr_available":
        if cat.mtr_available is True:
            return ComplianceStatus.PRESENT, f"{cat.sku}: catalog record shows MTR available from {cat.supplier}.", None
        if cat.mtr_available is False:
            return ComplianceStatus.MISSING, f"{cat.sku}: catalog record shows MTR NOT available.", None
        return ComplianceStatus.UNKNOWN, None, f"{cat.sku}: MTR availability not on file."

    if field in ("country_of_origin", "country_of_origin_domestic"):
        coo = cat.country_of_origin
        if not coo:
            return ComplianceStatus.UNKNOWN, None, f"{cat.sku}: country of origin not on file."
        if field == "country_of_origin_domestic":
            if coo.upper() in DOMESTIC_COUNTRIES:
                return ComplianceStatus.PRESENT, f"{cat.sku}: catalog origin {coo}.", None
            return ComplianceStatus.MISSING, f"{cat.sku}: catalog origin is {coo}, not domestic.", None
        return ComplianceStatus.PRESENT, f"{cat.sku}: catalog origin {coo}.", None

    if field == "certifications":
        if rule["trigger_type"] == "standard" and item.standard:
            certs = [_norm_std(c) for c in cat.certifications]
            if _norm_std(item.standard) in certs:
                return ComplianceStatus.PRESENT, f"{cat.sku}: certified to {item.standard} per catalog record.", None
            return ComplianceStatus.MISSING, f"{cat.sku}: certifications on file: {', '.join(cat.certifications) or 'none'}.", None
        # Keyword-triggered cert (e.g. NACE): look for it in the cert list
        keyword = rule["requirement"].split()[0].upper()
        if any(keyword in c.upper() for c in cat.certifications):
            return ComplianceStatus.PRESENT, f"{cat.sku}: {keyword} listed in certifications.", None
        return ComplianceStatus.UNKNOWN, None, f"{cat.sku}: {keyword} not listed in catalog certifications."

    return ComplianceStatus.UNKNOWN, None, f"Unknown evidence field '{field}'."


def check_compliance(item: NormalizedLineItem, match: CatalogMatchResult) -> ComplianceResult:
    text = item.original_text
    if item.notes:
        text = f"{text} {item.notes}"

    requirements: List[ComplianceRequirement] = []
    warnings: List[str] = []
    seen = set()

    for rule in get_rules():
        trigger = _rule_triggered(rule, item, text)
        if not trigger:
            continue
        required = rule["required"].upper() == "Y"
        # An explicit request outranks the informational version of the same requirement
        if rule["requirement"] in seen:
            continue
        status, evidence, note = _check_evidence(rule, item, match)
        requirements.append(ComplianceRequirement(
            requirement=rule["requirement"],
            required=required,
            status=status,
            evidence=evidence,
            notes=f"{trigger}. {rule['description']}." + (f" {note}" if note else ""),
        ))
        seen.add(rule["requirement"])

    blocking = [r for r in requirements if r.required and r.status != ComplianceStatus.PRESENT]
    for r in blocking:
        warnings.append(f"{r.requirement}: {r.status.value}. Human review required before quoting.")

    return ComplianceResult(
        line_number=item.line_number,
        requirements=requirements,
        all_clear=not blocking,
        compliance_warnings=warnings,
    )
