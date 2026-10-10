"""
parser.py — Stage 1: Raw Input Parser

Supports:
  - Pasted text / email body
  - .eml file (extracts body + attachments)
  - Text-based PDF (pdfplumber)
  - Scanned PDF (pytesseract OCR, graceful fallback)
  - Screenshot / image (Claude Vision)
  - XLSX / CSV (pandas)

Output: List[RawLineItem] — original text always preserved, source tracked.
"""

import io
import re
import base64
import email
from email import policy as email_policy
from typing import List, Tuple
from schemas import RawLineItem

# Optional imports with graceful fallback
try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_SUPPORT = True
except ImportError:
    OCR_SUPPORT = False

try:
    import pandas as pd
    PANDAS_SUPPORT = True
except ImportError:
    PANDAS_SUPPORT = False

try:
    import anthropic
    VISION_SUPPORT = True
except ImportError:
    VISION_SUPPORT = False


# -------------------------------------------------------------------
# MAIN ENTRY POINT
# -------------------------------------------------------------------

def parse_input(
    content: bytes,
    input_type: str,
    filename: str = "",
    anthropic_api_key: str = ""
) -> List[RawLineItem]:
    """
    Route input to the correct parser based on input_type.
    Always returns List[RawLineItem], never raises silently.

    input_type: "text" | "pdf" | "image" | "xlsx" | "csv" | "eml"
    """
    raw_lines: List[Tuple[str, dict]] = []  # (text, metadata)

    if input_type == "text":
        raw_lines = parse_text(content.decode("utf-8", errors="replace"))

    elif input_type == "pdf":
        raw_lines = parse_pdf(content)

    elif input_type == "image":
        raw_lines = parse_image(content, filename, anthropic_api_key)

    elif input_type in ("xlsx", "csv"):
        raw_lines = parse_spreadsheet(content, input_type)

    elif input_type == "eml":
        raw_lines = parse_eml(content, anthropic_api_key)

    else:
        return [RawLineItem(
            line_number=1,
            original_text=f"Unsupported input type: {input_type}",
            parse_confidence=0.0,
            parse_warnings=[f"Input type '{input_type}' is not supported."]
        )]

    return build_raw_line_items(raw_lines)


# -------------------------------------------------------------------
# TEXT / EMAIL BODY PARSER
# -------------------------------------------------------------------

def parse_text(text: str) -> List[Tuple[str, dict]]:
    """
    Split plain text or email body into candidate line items.
    Filters out email headers, signatures, blank lines.
    """
    lines = text.splitlines()
    candidates = []

    # Patterns that indicate non-RFQ lines
    skip_patterns = [
        r"^from\s*:",
        r"^to\s*:",
        r"^cc\s*:",
        r"^subject\s*:",
        r"^date\s*:",
        r"^sent\s*:",
        r"^regards",
        r"^thanks",
        r"^sincerely",
        r"^best",
        r"^hi\s",
        r"^hello\s",
        r"^dear\s",
        r"^please\s(find|quote|see)",
        r"^attached",
        r"^note\s*:",
        r"^\-{3,}",       # divider lines
        r"^_{3,}",
        r"^={3,}",
    ]

    for line in lines:
        stripped = line.strip()

        # Skip blank or too short
        if len(stripped) < 5:
            continue

        # Skip email header/signature patterns
        if any(re.match(p, stripped, re.IGNORECASE) for p in skip_patterns):
            continue

        # Remove leading bullets or numbering
        cleaned = re.sub(r"^[\-\*\•\·]\s+", "", stripped)
        cleaned = re.sub(r"^\d+[\.\)]\s+", "", cleaned)

        if cleaned:
            candidates.append((cleaned, {"source": "text"}))

    return candidates


# -------------------------------------------------------------------
# PDF PARSER (text-based + scanned fallback)
# -------------------------------------------------------------------

def parse_pdf(content: bytes) -> List[Tuple[str, dict]]:
    """
    Extract lines from a PDF.
    Step 1: Try pdfplumber for text-based PDFs.
    Step 2: If no text found, fall back to OCR (pytesseract).
    Option A: extract both text and tables, merge all into one list.
    """
    if not PDF_SUPPORT:
        return [("PDF parsing unavailable: pdfplumber not installed.", {
            "parse_warning": True, "source": "pdf"
        })]

    candidates = []
    has_text = False

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):

            # --- Extract free text ---
            text = page.extract_text()
            if text:
                has_text = True
                for line in text.splitlines():
                    stripped = line.strip()
                    if len(stripped) > 4:
                        candidates.append((stripped, {
                            "source": "pdf_text",
                            "source_page": page_num
                        }))

            # --- Extract tables (Option A: merge with text) ---
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row:
                        continue
                    row_text = " | ".join(
                        str(cell).strip() for cell in row if cell and str(cell).strip()
                    )
                    if len(row_text) > 4:
                        candidates.append((row_text, {
                            "source": "pdf_table",
                            "source_page": page_num
                        }))

    # --- Scanned PDF fallback ---
    if not has_text:
        candidates.extend(parse_pdf_ocr(content))

    return candidates


def parse_pdf_ocr(content: bytes) -> List[Tuple[str, dict]]:
    """
    OCR fallback for scanned PDFs using pdf2image + pytesseract.
    Flags all lines as low confidence.
    """
    if not OCR_SUPPORT:
        return [("Scanned PDF detected but OCR is unavailable. Install pdf2image and pytesseract.", {
            "parse_warning": True,
            "source": "pdf_ocr",
            "ocr_confidence": 0.0
        })]

    candidates = []
    try:
        images = convert_from_bytes(content)
        for page_num, image in enumerate(images, start=1):
            ocr_data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT
            )
            # Reconstruct lines from word-level OCR output
            current_line = []
            current_line_num = -1
            for i, word in enumerate(ocr_data["text"]):
                word = word.strip()
                if not word:
                    continue
                conf = int(ocr_data["conf"][i])
                line_num = ocr_data["line_num"][i]

                if line_num != current_line_num:
                    if current_line:
                        line_text = " ".join(current_line)
                        if len(line_text) > 4:
                            candidates.append((line_text, {
                                "source": "pdf_ocr",
                                "source_page": page_num,
                                "ocr_confidence": conf / 100.0,
                                "parse_warning": conf < 60
                            }))
                    current_line = [word]
                    current_line_num = line_num
                else:
                    current_line.append(word)

            # Flush last line
            if current_line:
                line_text = " ".join(current_line)
                if len(line_text) > 4:
                    candidates.append((line_text, {
                        "source": "pdf_ocr",
                        "source_page": page_num,
                        "ocr_confidence": 0.5,
                        "parse_warning": True
                    }))

    except Exception as e:
        candidates.append((f"OCR failed: {str(e)}", {
            "parse_warning": True,
            "source": "pdf_ocr",
            "ocr_confidence": 0.0
        }))

    return candidates


# -------------------------------------------------------------------
# IMAGE PARSER (Claude Vision)
# -------------------------------------------------------------------

def parse_image(
    content: bytes,
    filename: str,
    anthropic_api_key: str
) -> List[Tuple[str, dict]]:
    """
    Use Claude Vision to extract RFQ line items from a screenshot or image.
    Returns one candidate per identified line item.
    """
    if not VISION_SUPPORT or not anthropic_api_key:
        return [("Image parsing unavailable: anthropic SDK not installed or API key missing.", {
            "parse_warning": True,
            "source": "image"
        })]

    # Detect media type
    media_type = "image/png"
    if filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
        media_type = "image/jpeg"
    elif filename.lower().endswith(".webp"):
        media_type = "image/webp"
    elif filename.lower().endswith(".gif"):
        media_type = "image/gif"

    image_b64 = base64.standard_b64encode(content).decode("utf-8")

    client = anthropic.Anthropic(api_key=anthropic_api_key)

    prompt = """You are parsing an image of an industrial RFQ (Request for Quotation).
Extract every line item you can see. Return ONLY a plain text list, one item per line.
Preserve the original wording exactly as it appears in the image.
Do not interpret, normalize, or add any information.
Do not include headers, totals, addresses, or email boilerplate.
If you cannot read a part clearly, include it with [UNCLEAR] marker."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64
                        }
                    },
                    {"type": "text", "text": prompt}
                ]
            }]
        )

        raw_text = response.content[0].text
        candidates = []
        for line in raw_text.splitlines():
            stripped = line.strip()
            if len(stripped) > 4:
                has_unclear = "[UNCLEAR]" in stripped
                candidates.append((stripped, {
                    "source": "image_vision",
                    "parse_warning": has_unclear,
                    "parse_confidence": 0.5 if has_unclear else 0.85
                }))
        return candidates

    except Exception as e:
        return [(f"Claude Vision failed: {str(e)}", {
            "parse_warning": True,
            "source": "image_vision",
            "parse_confidence": 0.0
        })]


# -------------------------------------------------------------------
# SPREADSHEET PARSER (XLSX / CSV)
# -------------------------------------------------------------------

def parse_spreadsheet(
    content: bytes,
    input_type: str
) -> List[Tuple[str, dict]]:
    """
    Parse XLSX or CSV into candidate line strings.
    Reads all sheets, skips blank rows, concatenates all columns per row.
    """
    if not PANDAS_SUPPORT:
        return [("Spreadsheet parsing unavailable: pandas not installed.", {
            "parse_warning": True,
            "source": input_type
        })]

    candidates = []

    try:
        if input_type == "csv":
            dfs = {"sheet1": pd.read_csv(io.BytesIO(content), dtype=str)}
        else:
            dfs = pd.read_excel(
                io.BytesIO(content),
                sheet_name=None,
                dtype=str
            )

        for sheet_name, df in dfs.items():
            # Drop fully empty rows
            df = df.dropna(how="all")

            for row_idx, row in df.iterrows():
                # Skip rows that look like headers repeated mid-sheet
                row_values = [str(v).strip() for v in row if pd.notna(v) and str(v).strip()]
                if not row_values:
                    continue

                row_text = " | ".join(row_values)
                if len(row_text) > 4:
                    candidates.append((row_text, {
                        "source": f"spreadsheet_{input_type}",
                        "source_row": int(row_idx) + 1,
                        "sheet_name": sheet_name
                    }))

    except Exception as e:
        candidates.append((f"Spreadsheet parsing failed: {str(e)}", {
            "parse_warning": True,
            "source": input_type,
            "parse_confidence": 0.0
        }))

    return candidates


# -------------------------------------------------------------------
# EML PARSER (email file with attachments)
# -------------------------------------------------------------------

def parse_eml(
    content: bytes,
    anthropic_api_key: str
) -> List[Tuple[str, dict]]:
    """
    Parse a .eml email file.
    Extracts the email body as text.
    Automatically extracts and parses any attached PDFs, images, or spreadsheets.
    """
    candidates = []

    try:
        msg = email.message_from_bytes(content, policy=email_policy.default)

        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            filename = part.get_filename() or ""

            # --- Email body (plain text) ---
            if content_type == "text/plain" and "attachment" not in disposition:
                body = part.get_content()
                if body:
                    body_lines = parse_text(body)
                    for line, meta in body_lines:
                        meta["source"] = "eml_body"
                        candidates.append((line, meta))

            # --- Attached PDF ---
            elif content_type == "application/pdf" or filename.lower().endswith(".pdf"):
                attachment = part.get_payload(decode=True)
                if attachment:
                    pdf_lines = parse_pdf(attachment)
                    for line, meta in pdf_lines:
                        meta["source"] = f"eml_attachment_pdf:{filename}"
                        candidates.append((line, meta))

            # --- Attached image ---
            elif content_type.startswith("image/") or any(
                filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp"]
            ):
                attachment = part.get_payload(decode=True)
                if attachment:
                    img_lines = parse_image(attachment, filename, anthropic_api_key)
                    for line, meta in img_lines:
                        meta["source"] = f"eml_attachment_image:{filename}"
                        candidates.append((line, meta))

            # --- Attached spreadsheet ---
            elif any(filename.lower().endswith(ext) for ext in [".xlsx", ".xls", ".csv"]):
                attachment = part.get_payload(decode=True)
                if attachment:
                    ext = "csv" if filename.lower().endswith(".csv") else "xlsx"
                    sheet_lines = parse_spreadsheet(attachment, ext)
                    for line, meta in sheet_lines:
                        meta["source"] = f"eml_attachment_spreadsheet:{filename}"
                        candidates.append((line, meta))

    except Exception as e:
        candidates.append((f"EML parsing failed: {str(e)}", {
            "parse_warning": True,
            "source": "eml",
            "parse_confidence": 0.0
        }))

    return candidates


# -------------------------------------------------------------------
# BUILD RawLineItem LIST
# -------------------------------------------------------------------

def build_raw_line_items(
    candidates: List[Tuple[str, dict]]
) -> List[RawLineItem]:
    """
    Convert raw (text, metadata) tuples into RawLineItem objects.
    """
    items = []
    for idx, (text, meta) in enumerate(candidates, start=1):
        warnings = []
        if meta.get("parse_warning"):
            if "ocr" in meta.get("source", ""):
                warnings.append("Line extracted via OCR — verify dimensions and grades carefully.")
            elif "UNCLEAR" in text:
                warnings.append("Claude Vision flagged part of this line as unclear.")
            elif "failed" in text.lower():
                warnings.append("Parser encountered an error on this line.")

        confidence = meta.get("parse_confidence", 1.0)
        if meta.get("ocr_confidence"):
            confidence = meta["ocr_confidence"]

        items.append(RawLineItem(
            line_number=idx,
            original_text=text,
            source_page=meta.get("source_page"),
            source_row=meta.get("source_row"),
            parse_confidence=confidence,
            parse_warnings=warnings
        ))

    return items
