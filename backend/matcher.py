"""
matcher.py — Stage 4: Catalog Matcher

Step A: Hard filters eliminate incompatible SKUs (material, form, grade,
        thickness, size, finish, standard, availability). A SKU that fails
        any hard filter is rejected with a recorded reason, no matter how
        similar its description looks.
Step B: Fuzzy text similarity ranks only the SKUs that passed Step A.
        Similarity never rescues a rejected SKU.
Step C: If nothing passes → no match. Never forces a nearest match.

If the passing SKUs differ in a way the buyer did not specify (e.g. finish),
the matcher does not pick one; it returns a clarification question instead.
"""

import csv
import os
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from schemas import (
    CatalogItem, CatalogMatchResult, MatchConfidence, NormalizedLineItem
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CATALOG_PATH = os.path.join(DATA_DIR, "catalog.csv")

# Tolerances (inches)
SHEET_THICKNESS_TOL = 0.004     # covers gauge vs decimal rounding (16ga = 0.0598 ~ 0.060)
PLATE_THICKNESS_TOL = 0.010
SIZE_TOL = 0.5


# -------------------------------------------------------------------
# CATALOG LOADING
# -------------------------------------------------------------------

def _opt_float(v: str) -> Optional[float]:
    v = (v or "").strip()
    return float(v) if v else None


def _opt_bool(v: str) -> Optional[bool]:
    v = (v or "").strip().upper()
    if v in ("Y", "YES", "TRUE"):
        return True
    if v in ("N", "NO", "FALSE"):
        return False
    return None  # blank = unknown, never assumed


def load_catalog(path: str = CATALOG_PATH) -> List[CatalogItem]:
    items = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            items.append(CatalogItem(
                sku=row["sku"].strip(),
                material=row["material"].strip(),
                grade=row["grade"].strip(),
                form=row["form"].strip(),
                thickness_in=_opt_float(row.get("thickness_in")),
                width_in=_opt_float(row.get("width_in")),
                length_in=_opt_float(row.get("length_in")),
                gauge=(row.get("gauge") or "").strip() or None,
                finish=(row.get("finish") or "").strip() or None,
                standard=(row.get("standard") or "").strip() or None,
                unit=row["unit"].strip(),
                stock_status=row["stock_status"].strip(),
                supplier=row["supplier"].strip(),
                cost_per_lb=_opt_float(row.get("cost_per_lb")),
                mtr_available=_opt_bool(row.get("mtr_available")),
                country_of_origin=(row.get("country_of_origin") or "").strip() or None,
                certifications=[c.strip() for c in (row.get("certifications") or "").split(";") if c.strip()],
                notes=(row.get("notes") or "").strip() or None,
            ))
    return items


_CATALOG_CACHE: Optional[List[CatalogItem]] = None


def get_catalog() -> List[CatalogItem]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        _CATALOG_CACHE = load_catalog()
    return _CATALOG_CACHE


# -------------------------------------------------------------------
# HARD FILTER HELPERS
# -------------------------------------------------------------------

def _norm_finish(f: Optional[str]) -> Optional[str]:
    if not f:
        return None
    return f.upper().replace(" ", "").replace("#", "NO.").replace("NO", "NO.").replace("..", ".")


def _norm_std(s: str) -> str:
    return s.upper().replace(" ", "").replace("-", "")


def _split_grade(grade: str) -> Tuple[str, Optional[str]]:
    """'6061-T6' → ('6061', 'T6'); '17-4' stays whole; '304L' → ('304L', None)."""
    if grade.startswith("17-"):
        return grade, None
    if "-" in grade:
        base, temper = grade.split("-", 1)
        return base, temper
    return grade, None


def grade_check(requested: str, catalog_grade: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Returns (passes, reason_if_failed, note_if_assumption).
    Dual-certified catalog grades ("304/304L") satisfy either grade.
    """
    req = requested.upper()
    cat_grades = [g.strip().upper() for g in catalog_grade.split("/")]
    if req in cat_grades:
        note = None
        if len(cat_grades) > 1:
            note = f"Catalog item is dual certified {catalog_grade}, which satisfies requested grade {requested}."
        return True, None, note

    req_base, req_temper = _split_grade(req)
    for cg in cat_grades:
        cat_base, cat_temper = _split_grade(cg)
        if req_base == cat_base:
            if req_temper and cat_temper and req_temper != cat_temper:
                return False, f"temper {cat_temper} does not match requested {req_temper}", None
            if not req_temper and cat_temper:
                return True, None, f"TEMPER_UNSPECIFIED:{cat_temper}"
            if req_temper and not cat_temper:
                return False, f"catalog temper unknown, requested {req_temper}", None
    return False, f"grade {catalog_grade} does not match requested {requested}", None


def _sizes_match(item: NormalizedLineItem, cat: CatalogItem) -> bool:
    if item.width_in is None or item.length_in is None:
        return True  # not required for this form; validator decides if it matters
    if cat.width_in is None or cat.length_in is None:
        return False
    a = (abs(item.width_in - cat.width_in) <= SIZE_TOL and abs(item.length_in - cat.length_in) <= SIZE_TOL)
    b = (abs(item.width_in - cat.length_in) <= SIZE_TOL and abs(item.length_in - cat.width_in) <= SIZE_TOL)
    return a or b


def hard_filter(item: NormalizedLineItem, cat: CatalogItem) -> Tuple[bool, str, List[str]]:
    """
    Apply every hard compatibility check. Returns (passed, reason, notes).
    A different material or form ends the check immediately (not a near miss);
    otherwise every failing filter is collected, so near misses can be ranked
    by how many filters they fail.
    """
    notes: List[str] = []
    failures: List[str] = []

    if item.material and item.material.lower() != cat.material.lower():
        return False, f"material {cat.material} vs requested {item.material}", notes

    if item.form and item.form.lower() != cat.form.lower():
        return False, f"form {cat.form} vs requested {item.form}", notes

    if item.grade:
        ok, reason, note = grade_check(item.grade, cat.grade)
        if not ok:
            failures.append(reason)
        elif note:
            notes.append(note)

    if item.thickness_in is not None:
        tol = PLATE_THICKNESS_TOL if cat.form == "Plate" else SHEET_THICKNESS_TOL
        if cat.thickness_in is None:
            failures.append("catalog thickness unknown")
        elif abs(item.thickness_in - cat.thickness_in) > tol:
            failures.append(f"thickness {cat.thickness_in}\" vs requested {item.thickness_in}\" (tolerance ±{tol}\")")
        else:
            notes.append(f"Thickness {cat.thickness_in}\" within ±{tol}\" of requested {item.thickness_in}\".")

    if not _sizes_match(item, cat):
        failures.append(f"size {cat.width_in:g}x{cat.length_in:g} vs requested {item.width_in:g}x{item.length_in:g}")
    elif item.width_in is not None:
        notes.append(f"Size {cat.width_in:g}\" x {cat.length_in:g}\" matches requested size.")

    if item.finish:
        if _norm_finish(item.finish) != _norm_finish(cat.finish):
            failures.append(f"finish {cat.finish} vs requested {item.finish}")
        else:
            notes.append(f"Finish {cat.finish} matches requested finish.")

    if item.standard:
        req = _norm_std(item.standard)
        cat_stds = [_norm_std(s) for s in ([cat.standard] if cat.standard else []) + cat.certifications]
        if req not in cat_stds:
            failures.append(f"not certified to requested {item.standard} (has: {', '.join(cat.certifications) or 'none'})")
        else:
            notes.append(f"Certified to requested standard {item.standard}.")

    if cat.stock_status == "UNAVAILABLE":
        failures.append("item marked UNAVAILABLE")

    if failures:
        return False, "; ".join(failures), notes
    return True, "passed all hard filters", notes


# -------------------------------------------------------------------
# FUZZY RANKING (ranking only — never decides compatibility)
# -------------------------------------------------------------------

def _descriptor(material, grade, form, thickness, width, length, finish) -> str:
    parts = [material, grade, form,
             f"{thickness:.3f}" if thickness else "",
             f"{width:g}x{length:g}" if width and length else "",
             finish or ""]
    return " ".join(p for p in parts if p).lower()


def fuzzy_score(item: NormalizedLineItem, cat: CatalogItem) -> float:
    a = _descriptor(item.material, item.grade, item.form, item.thickness_in,
                    item.width_in, item.length_in, item.finish)
    b = _descriptor(cat.material, cat.grade, cat.form, cat.thickness_in,
                    cat.width_in, cat.length_in, cat.finish)
    return round(SequenceMatcher(None, a, b).ratio(), 3)


# -------------------------------------------------------------------
# MAIN MATCHER
# -------------------------------------------------------------------

def match_line(
    item: NormalizedLineItem,
    can_match: bool = True,
    catalog: Optional[List[CatalogItem]] = None,
) -> CatalogMatchResult:
    """
    can_match=False means required fields are missing; matching on partial
    data would produce a guess, so it is not attempted.
    """
    catalog = catalog if catalog is not None else get_catalog()

    if not can_match:
        return CatalogMatchResult(
            line_number=item.line_number,
            matched=False,
            hard_filter_reason="Matching not attempted: required fields are missing or contradictory. "
                               "Clarification needed first.",
        )

    passed: List[Tuple[CatalogItem, List[str]]] = []
    near_misses: List[Tuple[int, str, str]] = []  # (failure count, sku, reason)
    other_family = 0

    for cat in catalog:
        ok, reason, notes = hard_filter(item, cat)
        if ok:
            passed.append((cat, notes))
        elif reason.startswith("material") or reason.startswith("form"):
            other_family += 1  # Not similar at all; counted, not listed
        else:
            near_misses.append((reason.count(";") + 1, cat.sku, reason))

    # Closest rejections first: the SKUs that failed the fewest hard filters
    near_misses.sort(key=lambda r: r[0])
    rejected_skus = [sku for _, sku, _ in near_misses]
    rejection_reasons = [f"{sku}: {reason}" for _, sku, reason in near_misses]

    if other_family:
        rejection_reasons.append(f"{other_family} other SKUs rejected: different material or product form.")

    if not passed:
        return CatalogMatchResult(
            line_number=item.line_number,
            matched=False,
            match_confidence=MatchConfidence.NONE,
            hard_filter_passed=False,
            hard_filter_reason="No catalog item passed the hard compatibility filters. "
                               "No substitute was chosen.",
            rejected_skus=rejected_skus,
            rejection_reasons=rejection_reasons,
            candidates_considered=len(catalog),
        )

    # Rank survivors: in stock first, then text similarity, then lower cost
    ranked = sorted(
        passed,
        key=lambda p: (p[0].stock_status != "IN_STOCK", -fuzzy_score(item, p[0]), p[0].cost_per_lb or 1e9),
    )
    best, best_notes = ranked[0]
    alternatives = [c.sku for c, _ in ranked[1:]]

    # --- Ambiguity: survivors differ on an attribute the buyer did not specify ---
    ambiguity_question = None
    match_notes = [n for n in best_notes if not n.startswith("TEMPER_UNSPECIFIED")]
    confidence = MatchConfidence.HIGH

    if not item.finish:
        finishes = sorted({c.finish for c, _ in passed if c.finish})
        if len(finishes) > 1:
            ambiguity_question = (
                f"We stock this item in more than one finish ({', '.join(finishes)}), and the "
                f"price differs. Which finish is required?"
            )
        elif finishes:
            match_notes.append(
                f"ASSUMPTION: finish not specified by buyer; the only catalog finish for this "
                f"size is {finishes[0]}."
            )
            confidence = MatchConfidence.MEDIUM

    tempers = sorted({n.split(":", 1)[1] for _, ns in passed for n in ns if n.startswith("TEMPER_UNSPECIFIED")})
    if len(tempers) > 1:
        q = f"Which temper is required ({', '.join(tempers)})?"
        ambiguity_question = f"{ambiguity_question} {q}" if ambiguity_question else q
    elif tempers:
        match_notes.append(f"ASSUMPTION: temper not specified by buyer; catalog item is {best.grade}.")
        confidence = MatchConfidence.MEDIUM

    if best.stock_status != "IN_STOCK":
        match_notes.append(f"Stock status: {best.stock_status} ({best.notes or 'lead time applies'}).")

    if ambiguity_question:
        return CatalogMatchResult(
            line_number=item.line_number,
            matched=False,
            match_confidence=MatchConfidence.LOW,
            hard_filter_passed=True,
            hard_filter_reason=f"{len(passed)} SKUs passed hard filters but differ on an unspecified "
                               f"attribute. Not choosing one for the buyer.",
            fuzzy_score=fuzzy_score(item, best),
            rejected_skus=rejected_skus,
            rejection_reasons=rejection_reasons,
            candidates_considered=len(catalog),
            alternatives=[c.sku for c, _ in ranked],
            match_notes=match_notes,
            ambiguity_question=ambiguity_question,
        )

    return CatalogMatchResult(
        line_number=item.line_number,
        matched=True,
        match_confidence=confidence,
        matched_sku=best.sku,
        matched_item=best,
        hard_filter_passed=True,
        hard_filter_reason=f"{best.sku} passed all hard filters "
                           f"(material, form, grade, thickness, size, finish, standard, availability).",
        fuzzy_score=fuzzy_score(item, best),
        rejected_skus=rejected_skus,
        rejection_reasons=rejection_reasons,
        candidates_considered=len(catalog),
        alternatives=alternatives,
        match_notes=match_notes,
    )
