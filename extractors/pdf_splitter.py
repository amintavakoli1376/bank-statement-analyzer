import pdfplumber
import re
import hashlib
import io
import base64

try:
    import fitz  # PyMuPDF — متن‌خوان تقویتی
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

import config

CARD_NUMBER_PATTERN = re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b')

# ─── توابع کمکی ──────────────────────────────────────────────────────────────


def mask_sensitive_info(text: str) -> str:
    """ماسک کردن شماره کارت‌ها."""
    if not text:
        return text
    return CARD_NUMBER_PATTERN.sub('*-****-****-****', text)


def compute_file_hash(file_bytes: bytes) -> str:
    """هش فایل برای کش کردن نتایج استخراج هر صفحه."""
    return hashlib.md5(file_bytes).hexdigest()[:16]


# ─── تبدیل صفحه به عکس ──────────────────────────────────────────────────────


def page_to_image_b64(page) -> str:
    """تبدیل صفحه pdfplumber به PNG base64 برای ارسال به مدل vision."""
    img = page.to_image(resolution=150)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ─── متن‌خوانی تقویتی با PyMuPDF ────────────────────────────────────────────


def _extract_text_with_fitz(file_bytes: bytes, page_idx: int) -> str:
    """
    خواندن متن صفحه با PyMuPDF (fitz).
    برای PDFهایی که pdfplumber متن کافی برنمی‌گرداند.
    """
    if not HAS_FITZ:
        return ""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page = doc[page_idx]
        text = page.get_text("text")
        doc.close()
        return text.strip()
    except Exception:
        return ""


# ─── استخراج متن/تصویر هر صفحه ─────────────────────────────────────────────


def extract_page_data(file_bytes: bytes):
    """
    استخراج متن یا تصویر هر صفحه PDF.
    فقط دو حالت:
      1. "llm_required"     — متن کافی موجود است
      2. "image_required"   — صفحه تصویری/اسکن (نیاز به vision LLM)

    جدول‌ها توسط LLM پردازش می‌شوند، نه pdfplumber.
    """
    pages_data = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1

            # استخراج متن با pdfplumber
            text = page.extract_text() or ""
            text_stripped = text.strip()

            # تلاش برای متن بهتر با PyMuPDF
            fitz_text = _extract_text_with_fitz(file_bytes, page_idx)
            effective_text = fitz_text if (fitz_text and len(fitz_text) > len(text_stripped)) else text_stripped

            # تصمیم‌گیری: متنی یا تصویری
            if len(effective_text) >= config.MIN_TEXT_LENGTH_FOR_IMAGE:
                pages_data.append({
                    "method": "llm_required",
                    "page_number": page_num,
                    "raw_text": effective_text,
                })
            else:
                image_b64 = page_to_image_b64(page)
                pages_data.append({
                    "method": "image_required",
                    "page_number": page_num,
                    "image_b64": image_b64,
                    "raw_text": effective_text,
                })

    return pages_data


# ─── ساخت chunk از چند صفحه ──────────────────────────────────────────────────


def split_pages_with_context(pages_data, overlap_lines: int = 2):
    """
    گروه‌بندی چند صفحه در یک chunk برای ارسال به LLM.

    هر chunk شامل PAGES_PER_CHUNK صفحه متوالی است.
    متن صفحات با جداکننده مشخص ترکیب می‌شود.
    """
    pages_per_chunk = config.PAGES_PER_CHUNK
    chunks = []

    for start_idx in range(0, len(pages_data), pages_per_chunk):
        group = pages_data[start_idx : start_idx + pages_per_chunk]
        start_page = group[0]["page_number"]
        end_page = group[-1]["page_number"]

        # آیا همه صفحات متنی هستند یا تصویری؟
        has_image = any(p["method"] == "image_required" for p in group)
        image_b64 = None
        if has_image:
            # اولین صفحه تصویری
            for p in group:
                if p["method"] == "image_required":
                    image_b64 = p.get("image_b64")
                    break

        # ترکیب متن صفحات
        text_parts = []
        for p in group:
            raw_text = p.get("raw_text", "")
            masked_text = mask_sensitive_info(raw_text)
            text_parts.append(
                f"--- صفحه {p['page_number']} ---\n{masked_text}"
            )

        chunk_text = "\n\n".join(text_parts)

        chunk = {
            "page_number": start_page,  # صفحه شروع
            "page_range": f"{start_page}-{end_page}",
            "method": "image_required" if has_image else "llm_required",
            "text": chunk_text,
            "raw_length": len(chunk_text),
            "page_count": len(group),
        }

        if image_b64:
            chunk["image_b64"] = image_b64

        chunks.append(chunk)

    return chunks
