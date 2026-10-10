"""
prism_setup.py — One-time PRISM (Block Convey) setup check

    python prism_setup.py

1. Confirms PRISMTRACE_API_KEY / PRISMTRACE_PROJECT_ID are set
2. Uploads data/spec_reference.md to the PRISM Knowledge Base (skipped if already there)
3. Runs two grounding checks: one the KB should support, one it should reject

Then run the SDK's own credential check:
    python -m prismtrace.verify
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

import prism


def main() -> int:
    print(f"PRISM: {prism.status()}")
    if not prism.enabled():
        print("Set PRISMTRACE_API_KEY and PRISMTRACE_PROJECT_ID in backend/.env first.")
        return 2

    seeded = prism.seed_knowledge_base()
    print(f"Knowledge Base: {seeded['message']}")
    if not seeded["ok"]:
        return 1

    checks = [
        ("standard", "ASTM A240", {"material": "Stainless Steel", "grade": "316L", "form": "Sheet"}, True),
        ("standard", "ASTM A276", {"material": "Stainless Steel", "grade": "316L", "form": "Sheet"}, False),
    ]
    ok = True
    for field, value, ctx, expected in checks:
        supported, evidence = prism.ground_field(field, value, ctx)
        passed = supported is expected
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {field}={value} for {ctx['grade']} {ctx['form']}: "
              f"supported={supported} ({evidence})")
    if not ok:
        print("KB may still be processing the upload (chunking takes a moment). Re-run in a minute.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
