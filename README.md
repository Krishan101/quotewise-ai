# QuoteWise AI

**Hackathon:** RudCo RFQ-to-Quote | **Track:** 2 | **Theme:** AI You Can Trust

---

## Hackathon Brief

**Theme:** AI You Can Trust
Counselors, pharmacists and investors make high-stakes decisions from messy data every day. They don't need another chatbot that sounds confident. They need AI that's grounded in real data, honest about what it doesn't know, and clear about how it got its answer.

**What the judges are looking for:** Working prototypes that solve a real problem for a real company, built by engineers who care about getting it right.

**What they are not looking for:** Slide decks with no product behind them, thin wrappers that pass a prompt to a model and print the result, or pre-built projects.

---

## Track 2 | RudCo | RFQ to Quote

Industrial buyers send requests for quotes (RFQs) as messy emails, PDFs and spreadsheets. The same item gets written five different ways ("304 SS sheet 16ga 4x8", "Stainless 304, 0.060 in, 48 x 96"), and each one needs a material grade, a spec standard, certifications and a competitive price. Today a person decodes every line by hand.

**Build:** An agent that takes a messy RFQ and turns it into a ready-to-send quote. It should:
- Parse each line into a standard spec (material, grade, dimensions, quantity, standard such as ASTM)
- Match each line to items in a supplier catalog
- Price each line against market benchmarks and explain why the price is competitive
- Flag compliance requirements (mill test reports, country of origin, spec certifications)
- Send any ambiguous line back to the buyer with a clarifying question instead of guessing

**Requirements:**
- Be built during the event
- Show how it handles uncertainty: what it does when it isn't sure
- Using NicrronNinoo and Block Convey is a must in your project

---

## What We Built

An AI-assisted RFQ preparation tool. Converts messy industrial requests for quotation (emails, PDFs, spreadsheets) into reviewable draft quotes. Every decision is traceable. Human approval required before anything is sent.

---

## Core Promise

- Never invent a material grade, dimension, standard, certification, price, or country of origin
- Keep the buyer's original wording alongside every normalized field
- Separate hard compatibility checks from fuzzy text similarity
- Label all synthetic/demo data explicitly
- Show the evidence and calculation behind every match and price
- Ask a clarifying question when uncertainty could change the product, compliance, or price
- Generate a DRAFT quote only; require human approval before sending

---

## Pipeline

```
Raw RFQ Input
     |
     v
[1. PARSER]          parser.py
Extracts raw line items from email text / PDF / CSV / XLSX
Keeps original wording alongside everything it extracts
     |
     v
[2a. EXTRACTOR]               extractor.py
Rule-based regex + lookup tables, deterministic
     |
     v
[2b. LLM GAP-FILLER]          agent.py
Claude reads each raw line and outputs structured JSON
Unknown fields are explicitly null, never guessed
     |
     v
[3. VALIDATOR]       validator.py
Hard rule checks: required fields, dimension sanity, contradictions
     |
     v
[4. CATALOG MATCHER] matcher.py
Hard filters first, fuzzy ranking second
Never forces a nearest match
     |
     v
[5. PRICING ENGINE]  pricing.py
Benchmark lookup + price math
Missing benchmark → PRICE_UNVERIFIED
     |
     v
[6. COMPLIANCE CHECKER]  compliance.py
MTR, COO, certs checked against rule table
Never claims compliance without evidence
     |
     v
[7. DECISION ENGINE] decision.py
Assigns one of 6 statuses per line
     |
     v
[8. REACT UI]        frontend/
Upload, quote table, line detail, clarification panel
     |
     v
[9. DRAFT EXPORT]
PDF or JSON, watermarked DRAFT, assumptions visible
```

---

## Line Statuses

| Status | Meaning |
|---|---|
| `READY_FOR_REVIEW` | All fields present, match found, price verified, compliance checked |
| `NEEDS_CLARIFICATION` | Missing or ambiguous field that would change match or price |
| `NO_COMPATIBLE_MATCH` | No catalog item passed hard filters |
| `PRICE_UNVERIFIED` | Match found but no benchmark data available |
| `COMPLIANCE_REVIEW` | Required document (MTR, COO, cert) has no evidence |
| `PARSER_REVIEW` | Raw text could not be reliably parsed into a line item |

---

## Tech Stack

| Layer | Tool |
|---|---|
| Frontend | React + Tailwind |
| Backend | FastAPI (Python) |
| AI parsing | Claude API (claude-sonnet-4-6) |
| Data validation | Pydantic |
| Catalog + pricing | Local CSV files (labeled synthetic) |
| PDF parsing | pdfplumber |
| CSV/XLSX parsing | pandas |
| Export | ReportLab / JSON |

---

## Project Structure

```
quotewise-ai/
  backend/
    schemas.py            # Pydantic models and status enums (DONE)
    parser.py             # PDF, CSV, XLSX, EML, image ingestion (DONE)
    extractor.py          # Rule-based field extraction - regex + lookups (DONE)
    agent.py              # NicrronNinoo LLM gap-filler for unknown fields (DONE)
    validator.py          # Hard rule checks (PENDING)
    matcher.py            # Catalog matching (PENDING)
    pricing.py            # Benchmark pricing (PENDING)
    compliance.py         # Compliance checker (PENDING)
    decision.py           # Status assignment (PENDING)
    main.py               # FastAPI app (PENDING)
    data/
      catalog.csv         # Synthetic supplier catalog (PENDING)
      benchmarks.csv      # Synthetic price benchmarks (PENDING)
      compliance_rules.csv # Compliance rule table (PENDING)
    requirements.txt      # Python dependencies (PENDING)
    .env.example          # Environment variable template (PENDING)
  frontend/               # React app (PENDING)
  README.md
```

---

## Input Methods

| Method | Format | Notes |
|---|---|---|
| Paste text | Plain text / email body | Splits by newline or bullet |
| Upload PDF | .pdf | pdfplumber extracts text and tables |
| Upload spreadsheet | .xlsx / .csv | pandas reads rows into line strings |

---

## Data Notice

> **DEMO DATA:** All catalog items, prices, and benchmarks are synthetic and for demonstration purposes only. No real supplier pricing or inventory data is used.

---

## Devpost Submission Checklist

- [ ] Project name and one-line description
- [ ] Track: Track 2 - RudCo RFQ to Quote
- [ ] What we built and why
- [ ] How the solution handles accuracy and uncertainty
- [ ] Tools and technologies used (NicrronNinoo and Block Convey included)
- [ ] Team member names and roles
- [ ] Link to video demo
- [ ] Link to GitHub repository

---

## Team

| Name | Role |
|---|---|
| TBD | Backend pipeline |
| TBD | React frontend |
| TBD | Data and rules |
| TBD | Integrations and Devpost |

---

## Build Status

| Component | Status |
|---|---|
| schemas.py | DONE |
| parser.py | DONE |
| extractor.py | DONE |
| agent.py | DONE |
| validator.py | PENDING |
| matcher.py | PENDING |
| pricing.py | PENDING |
| compliance.py | PENDING |
| decision.py | PENDING |
| main.py | PENDING |
| catalog.csv | PENDING |
| benchmarks.csv | PENDING |
| compliance_rules.csv | PENDING |
| requirements.txt | PENDING |
| Frontend | PENDING |
