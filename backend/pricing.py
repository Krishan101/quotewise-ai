"""
pricing.py — Stage 5: Pricing Engine

Prices a matched line from:
  - supplier cost basis ($/lb, catalog.csv, DEMO DATA)
  - market benchmark range ($/lb, benchmarks.csv, DEMO DATA)
  - calculated piece weight (dimensions x density)

Every step of the math is recorded in calculation_steps.
If there is no benchmark, no cost, or the weight cannot be calculated,
the line is PRICE_UNVERIFIED. No price is ever invented.
"""

import csv
import os
from typing import Dict, Optional, Tuple

from schemas import CatalogMatchResult, NormalizedLineItem, PricingResult

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BENCHMARKS_PATH = os.path.join(DATA_DIR, "benchmarks.csv")

# Density in lb / cubic inch
DENSITY_LB_PER_IN3 = {
    "Stainless Steel": 0.289,
    "Carbon Steel":    0.2836,
    "Aluminum":        0.0975,
    "Copper":          0.323,
    "Brass":           0.307,
    "Titanium":        0.163,
}

TARGET_MARGIN = 0.18   # preferred margin over cost
MIN_MARGIN = 0.08      # floor; never quote below cost + this
KG_PER_LB = 0.45359237


# -------------------------------------------------------------------
# BENCHMARKS
# -------------------------------------------------------------------

_BENCH_CACHE: Optional[Dict[Tuple[str, str, str], dict]] = None


def load_benchmarks(path: str = BENCHMARKS_PATH) -> Dict[Tuple[str, str, str], dict]:
    table = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["material"].strip().lower(), row["grade"].strip().upper(), row["form"].strip().lower())
            table[key] = {
                "low": float(row["price_per_lb_low"]),
                "mid": float(row["price_per_lb_mid"]),
                "high": float(row["price_per_lb_high"]),
                "source": row["source"].strip(),
                "as_of_date": row["as_of_date"].strip(),
            }
    return table


def get_benchmarks() -> Dict[Tuple[str, str, str], dict]:
    global _BENCH_CACHE
    if _BENCH_CACHE is None:
        _BENCH_CACHE = load_benchmarks()
    return _BENCH_CACHE


def find_benchmark(material: str, catalog_grade: str, form: str) -> Optional[dict]:
    """
    Benchmarks are keyed on base alloy. '304/304L' tries 304/304L, 304, 304L;
    '6061-T6' tries 6061-T6, then 6061.
    """
    bench = get_benchmarks()
    candidates = [catalog_grade.upper()]
    for g in catalog_grade.upper().split("/"):
        candidates.append(g)
        if "-" in g and not g.startswith("17-"):
            candidates.append(g.split("-")[0])
        if g.endswith("L"):
            candidates.append(g[:-1])
    for g in candidates:
        hit = bench.get((material.lower(), g, form.lower()))
        if hit:
            return hit
    return None


# -------------------------------------------------------------------
# MAIN PRICER
# -------------------------------------------------------------------

def _unverified(line_number: int, item: NormalizedLineItem, reason: str, steps=None, **kw) -> PricingResult:
    return PricingResult(
        line_number=line_number,
        priced=False,
        quantity=item.quantity,
        unit=item.unit,
        price_unverified=True,
        price_rationale=f"PRICE_UNVERIFIED: {reason}",
        price_warnings=[reason],
        calculation_steps=steps or [],
        **kw,
    )


def price_line(item: NormalizedLineItem, match: CatalogMatchResult) -> PricingResult:
    if not match.matched or not match.matched_item:
        return PricingResult(
            line_number=item.line_number,
            priced=False,
            quantity=item.quantity,
            unit=item.unit,
            price_rationale="Not priced: no confirmed catalog match.",
        )

    cat = match.matched_item
    steps = []
    warnings = []

    # --- 1. Market benchmark ---
    bench = find_benchmark(cat.material, cat.grade, cat.form)
    if not bench:
        return _unverified(
            item.line_number, item,
            f"No market benchmark on file for {cat.material} {cat.grade} {cat.form}. "
            f"A human must verify the price before quoting.",
        )

    # --- 2. Cost basis ---
    if cat.cost_per_lb is None:
        return _unverified(
            item.line_number, item,
            f"No supplier cost on file for {cat.sku}.",
            benchmark_low=bench["low"], benchmark_price=bench["mid"], benchmark_high=bench["high"],
            benchmark_source=bench["source"], benchmark_date=bench["as_of_date"],
        )

    # --- 3. Piece weight ---
    density = DENSITY_LB_PER_IN3.get(cat.material)
    if density is None or None in (cat.thickness_in, cat.width_in, cat.length_in):
        return _unverified(item.line_number, item, f"Cannot calculate weight for {cat.sku} (density or dimensions unknown).")

    weight = cat.thickness_in * cat.width_in * cat.length_in * density
    steps.append(
        f"Piece weight = {cat.thickness_in}\" x {cat.width_in:g}\" x {cat.length_in:g}\" x "
        f"{density} lb/in³ ({cat.material}) = {weight:.2f} lb"
    )

    # --- 4. Price per lb: target margin, capped at market midpoint, floored at min margin ---
    target = cat.cost_per_lb * (1 + TARGET_MARGIN)
    floor = cat.cost_per_lb * (1 + MIN_MARGIN)
    steps.append(f"Cost basis = ${cat.cost_per_lb:.2f}/lb (catalog, DEMO DATA)")
    steps.append(f"Target price = cost x {1 + TARGET_MARGIN:.2f} = ${target:.3f}/lb")

    if target <= bench["mid"]:
        ppl = target
        steps.append(f"Target <= market midpoint ${bench['mid']:.2f}/lb -> use target")
    else:
        ppl = max(bench["mid"], floor)
        steps.append(
            f"Target above market midpoint ${bench['mid']:.2f}/lb -> reduce to "
            f"max(midpoint, cost x {1 + MIN_MARGIN:.2f} = ${floor:.3f}) = ${ppl:.3f}/lb"
        )
    ppl = round(ppl, 3)
    margin_pct = round((ppl - cat.cost_per_lb) / ppl * 100, 1)

    # --- 5. Competitiveness vs market ---
    mid = bench["mid"]
    diff_pct = (ppl - mid) / mid * 100
    if ppl < bench["low"]:
        position = f"{abs(diff_pct):.1f}% below market midpoint and below the market low (${bench['low']:.2f}/lb)"
        warnings.append("Price is below the market low. Verify cost basis before sending.")
    elif ppl <= mid:
        position = f"{abs(diff_pct):.1f}% below the market midpoint (${mid:.2f}/lb), within the market range"
    elif ppl <= bench["high"]:
        position = f"{diff_pct:.1f}% above the market midpoint but within the market range"
        warnings.append("Price is above market midpoint because cost basis is high; may not be competitive.")
    else:
        position = f"{diff_pct:.1f}% above the market high (${bench['high']:.2f}/lb)"
        warnings.append("Price is above the market range. Not competitive; human review required.")

    # --- 6. Unit of sale ---
    unit = item.unit
    qty = item.quantity
    if unit is None:
        unit = "EA"
        warnings.append("ASSUMPTION: unit of sale not stated; quantity priced as pieces (EA). Confirm with buyer.")

    if unit == "EA":
        unit_price = round(weight * ppl, 2)
        steps.append(f"Unit price = {weight:.2f} lb x ${ppl:.3f}/lb = ${unit_price:,.2f} per piece")
    elif unit == "LB":
        unit_price = round(ppl, 3)
        steps.append(f"Unit price = ${unit_price:.3f} per lb")
    elif unit == "KG":
        unit_price = round(ppl / KG_PER_LB, 3)
        steps.append(f"Unit price = ${ppl:.3f}/lb ÷ {KG_PER_LB} = ${unit_price:.3f} per kg")
    elif unit == "SQFT":
        sqft = cat.width_in * cat.length_in / 144
        unit_price = round(weight * ppl / sqft, 2)
        steps.append(f"Unit price = (${weight * ppl:,.2f} per piece) ÷ {sqft:.1f} sqft = ${unit_price:,.2f} per sqft")
    else:
        return _unverified(item.line_number, item, f"Unit of sale '{unit}' is not supported for {cat.form}.", steps)

    total = round(unit_price * qty, 2) if qty is not None else None
    if total is not None:
        steps.append(f"Line total = {qty:g} {unit} x ${unit_price:,.2f} = ${total:,.2f}")

    rationale = (
        f"${ppl:.3f}/lb is {position} for {cat.material} {cat.grade} {cat.form} "
        f"({bench['source']}, as of {bench['as_of_date']}). "
        f"Margin over cost: {margin_pct}%."
    )

    return PricingResult(
        line_number=item.line_number,
        priced=True,
        unit_price=unit_price,
        total_price=total,
        quantity=qty,
        unit=unit,
        margin_pct=margin_pct,
        weight_lb_each=round(weight, 2),
        price_per_lb=ppl,
        cost_per_lb=cat.cost_per_lb,
        benchmark_low=bench["low"],
        benchmark_price=mid,
        benchmark_high=bench["high"],
        benchmark_source=bench["source"],
        benchmark_date=bench["as_of_date"],
        price_rationale=rationale,
        price_unverified=False,
        price_warnings=warnings,
        calculation_steps=steps,
    )
