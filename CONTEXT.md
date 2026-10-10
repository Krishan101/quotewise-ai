# QuoteWise AI — Full Session Context

## Hackathon Brief

**Event:** Columbia Hackathon
**Track:** 2 — RudCo RFQ to Quote
**Theme:** AI You Can Trust

Industrial buyers send requests for quotes (RFQs) as messy emails, PDFs and spreadsheets. The same item gets written five different ways ("304 SS sheet 16ga 4x8", "Stainless 304, 0.060 in, 48 x 96"), and each one needs a material grade, a spec standard, certifications and a competitive price. Today a person decodes every line by hand.

**Build:** An agent that takes a messy RFQ and turns it into a ready-to-send quote. It should:
- Parse each line into a standard spec (material, grade, dimensions, quantity, standard such as ASTM)
- Match each line to items in a supplier catalog
- Price each line against market benchmarks and explain why the price is competitive
- Flag compliance requirements (mill test reports, country of origin, spec certifications)
- Send any ambiguous line back to the buyer with a clarifying question instead of guessing

**Requirements:**
- Be built during the event
- Show how it handles uncertainty
- Using NicrronNinoo and Block Convey is a must

---

## What We're Building

**QuoteWise AI** — a traceable RFQ preparation assistant.
- Never invents fields, always shows evidence
- Human approval required before anything is sent
- Every line gets one of 6 explicit statuses
- Demo data labeled SYNTHETIC throughout

---

## Team Setup

- 3-4 people
- React frontend
- Under 6 hours remaining at start

**Team split:**
| Person | Owns |
|---|---|
| P1 | Backend pipeline |
| P2 | React frontend |
| P3 | Data and rules |
| P4 | Integrations and Devpost |

---

## Tech Stack

| Layer | Tool |
|---|---|
| Frontend | React + Tailwind |
| Backend | FastAPI (Python) |
| LLM | NicrronNinoo API (OpenAI-compatible, base_url: https://api.nicrron.ai/v1, model: nicrron/auto) |
| Data validation | Pydantic |
| Catalog + pricing | Local CSV files (labeled synthetic) |
| PDF parsing | pdfplumber |
| OCR fallback | pytesseract + pdf2image |
| Image parsing | Claude Vision (for screenshots) |
| CSV/XLSX parsing | pandas |
| Email parsing | Python email library (.eml files) |
| Export | ReportLab / JSON |

---

## NicrronNinoo Integration

- OpenAI-compatible SDK
- base_url: https://api.nicrron.ai/v1
- API key in environment variable: NICRRON_API_KEY
- Model: nicrron/auto (auto-picks best model)
- Used in: agent.py (LLM gap-filler only)
- Promo code: COLUMBIA26 ($260 credits per participant)

```python
from openai import OpenAI
client = OpenAI(base_url="https://api.nicrron.ai/v1", api_key=os.getenv("NICRRON_API_KEY"))
```

---

## Block Convey

- Still to be integrated (P4 owns this)
- Likely at document parsing or audit trail layer
- No API docs received yet — stub for now

---

## GitHub Repo

**URL:** https://github.com/Krishan101/quotewise-ai
**Owner:** Krishan101
**Visibility:** Public

**Working rules:**
- README updated after every push
- README checked before every push to avoid conflicts
- Every file shown to team before pushing
- Design decisions flagged and confirmed before implementing

---

## Pipeline Architecture

```
Raw RFQ Input
     |
     v
[1. PARSER]               parser.py           DONE
Extracts raw line items from:
  - Pasted text / email body
  - Text-based PDF (pdfplumber)
  - Scanned PDF (pytesseract OCR, graceful fallback)
  - Screenshot / image (Claude Vision)
  - XLSX / CSV (pandas, all sheets)
  - .eml email file (body + auto-extracts attachments)
Output: List[RawLineItem], original_text always preserved
     |
     v
[2a. EXTRACTOR]           extractor.py        DONE
Rule-based regex + lookup tables
Fills: material, grade, form, gauge, thickness, dimensions,
       quantity, unit, standard, finish
Deterministic, auditable, no LLM
Tracks unknown_fields explicitly
     |
     v
[2b. LLM GAP-FILLER]      agent.py            DONE
NicrronNinoo API (nicrron/auto)
Only fills fields in unknown_fields
Never overwrites rule-extracted fields
Graceful fallback if API fails
     |
     v
[3. VALIDATOR]            validator.py        DONE
Hard rule checks:
  - Required fields: material, grade, form, quantity
  - Form-specific required fields (Sheet needs thickness+width+length)
  - Dimension sanity bounds per form factor
  - Sheet vs Plate boundary detection
  - Grade/material contradiction check
  - Grade/standard contradiction check
  - Generates pre-drafted clarification question if needed
     |
     v
[4. CATALOG MATCHER]      matcher.py          PENDING
Step A: Hard filters — eliminate incompatible SKUs by material+grade+form
Step B: Fuzzy rank remaining candidates by dimension closeness
Step C: If no candidate passes → NO_COMPATIBLE_MATCH
Never forces a nearest match
     |
     v
[5. PRICING ENGINE]       pricing.py          PENDING
Benchmark lookup from benchmarks.csv (labeled DEMO DATA)
Calculates unit price, total, margin
Shows data source, date, rationale
If benchmark missing → PRICE_UNVERIFIED
     |
     v
[6. COMPLIANCE CHECKER]   compliance.py       PENDING
Checks compliance_rules.csv
MTR, COO, certs marked PRESENT/MISSING/UNKNOWN
Never claims compliance without evidence
     |
     v
[7. DECISION ENGINE]      decision.py         PENDING
Assigns one status per line:
  READY_FOR_REVIEW
  NEEDS_CLARIFICATION
  NO_COMPATIBLE_MATCH
  PRICE_UNVERIFIED
  COMPLIANCE_REVIEW
  PARSER_REVIEW
     |
     v
[8. REACT UI]             frontend/           PENDING
Upload zone, quote table, line detail drawer,
clarification panel, export button
     |
     v
[9. DRAFT EXPORT]                             PENDING
PDF or JSON, DRAFT watermark, all assumptions visible
```

---

## Line Statuses

| Status | Meaning |
|---|---|
| READY_FOR_REVIEW | All fields present, match found, price verified, compliance checked |
| NEEDS_CLARIFICATION | Missing or ambiguous field that would change match or price |
| NO_COMPATIBLE_MATCH | No catalog item passed hard filters |
| PRICE_UNVERIFIED | Match found but no benchmark data available |
| COMPLIANCE_REVIEW | Required document (MTR, COO, cert) has no evidence |
| PARSER_REVIEW | Raw text could not be reliably parsed into a line item |

---

## File Structure

```
quotewise-ai/
  backend/
    schemas.py            DONE — Pydantic models, all status enums
    parser.py             DONE — All input format handlers
    extractor.py          DONE — Rule-based field extraction
    agent.py              DONE — NicrronNinoo LLM gap-filler
    validator.py          DONE — Hard rule checks + clarification questions
    matcher.py            PENDING
    pricing.py            PENDING
    compliance.py         PENDING
    decision.py           PENDING
    main.py               PENDING
    data/
      catalog.csv         PENDING — ~20 synthetic SS SKUs
      benchmarks.csv      PENDING — Synthetic price benchmarks
      compliance_rules.csv PENDING
    requirements.txt      PENDING
    .env.example          PENDING
  frontend/               PENDING
  README.md               DONE
```

---

## Key Design Decisions Made

| Decision | Choice | Reason |
|---|---|---|
| PDF with text + tables | Extract both, merge (Option A) | Safer, loses nothing |
| Screenshot parsing | Claude Vision | Better accuracy than pytesseract on mixed layouts |
| Scanned PDF | pytesseract with graceful fallback | Full support, no crash if Tesseract missing |
| Email input | .eml file upload (primary), paste text (fallback) | No OAuth complexity, handles attachments automatically |
| Gmail/Outlook connector | Skipped for now | Too risky under time constraint |
| Extraction approach | Rules first (extractor.py), LLM gap-fill second (agent.py) | More trustworthy, auditable, cheaper |
| LLM provider | NicrronNinoo (nicrron/auto) | Required by hackathon, OpenAI-compatible |
| Anthropic API | Not used | Per team decision |

---

## Input Formats Supported

| Format | Handler | Notes |
|---|---|---|
| Pasted text | parse_text() | Strips headers, signatures, bullets |
| Text PDF | parse_pdf() | pdfplumber, extracts text + tables |
| Scanned PDF | parse_pdf_ocr() | pytesseract fallback, flags low confidence |
| Screenshot/image | parse_image() | Claude Vision, flags [UNCLEAR] |
| XLSX | parse_spreadsheet() | pandas, all sheets |
| CSV | parse_spreadsheet() | pandas |
| .eml email | parse_eml() | Body + auto-extracts attached PDF/image/sheet |

---

## Pending Decisions

- Block Convey integration: no docs yet, P4 to research
- NicrronNinoo model: using nicrron/auto, may want to switch to specific model
- Frontend framework details: React + Tailwind confirmed, component breakdown TBD

---

## Devpost Checklist

- [ ] Project name and one-line description
- [ ] Track: Track 2 - RudCo RFQ to Quote
- [ ] What we built and why
- [ ] How the solution handles accuracy and uncertainty
- [ ] Tools and technologies (NicrronNinoo + Block Convey required)
- [ ] Team member names and roles
- [ ] Video demo link
- [ ] GitHub repo link

---

## Demo Script (3-4 minutes)

1. Paste RFQ with 3 lines: one clean, one ambiguous, one wrong grade
2. Show original text next to normalized fields
3. Open clean line: hard filter passing, price math, MTR flag
4. Open wrong-grade line: rejected despite looking similar
5. Open ambiguous line: exact clarification question shown
6. Answer question, reprocess, watch status move to READY_FOR_REVIEW
7. Export draft quote, show totals, show DRAFT watermark
8. Close: "It automates the routine work, shows every step, and stops when it isn't sure."

---

## Next Up

**Stage 4:** matcher.py + catalog.csv
- catalog.csv: ~20 synthetic SS sheet/plate SKUs
- matcher.py: hard filter (material+grade+form exact match) then fuzzy dimension ranking
