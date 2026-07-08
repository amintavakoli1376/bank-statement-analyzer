import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from extractors.schemas import PageExtractionResult
from extractors.pdf_splitter import mask_sensitive_info
from utils.api_client import call_llm
import config

# ─── پرامپت استخراج متنی ─────────────────────────────────────────────────────

EXTRACTION_SCHEMA_EXAMPLE = """
{
  "account_holder_name": "نام صاحب حساب یا null",
  "transactions": [
    {
      "date": "1402/03/15",
      "time": "14:22",
      "description": "متن توضیحات ردیف",
      "deposit": 1500000,
      "withdrawal": 0,
      "balance": 24500000
    }
  ]
}
"""

EXTRACTION_PROMPT_TEMPLATE = """
شما فقط یک استخراج‌کننده جدول تراکنش‌های بانکی هستید. تحلیل، محاسبه، جمع‌بندی یا نتیجه‌گیری مالی انجام ندهید.

قوانین سخت‌گیرانه:
1. تمام ردیف‌های تراکنش از تمام صفحات ارسالی را استخراج کن.
2. اگر مقدار ستونی نامشخص یا خالی بود، null بگذار؛ هرگز حدس نزن یا مقدار جعل نکن.
3. اعداد را بدون کاما، بدون واحد پول و به‌صورت عدد خام برگردان.
4. اگر نام صاحب حساب در متن دیده شد استخراجش کن، وگرنه null بگذار.
5. اگر هیچ ردیف تراکنشی وجود نداشت، آرایه transactions را خالی برگردان.
6. خروجی را دقیقاً و فقط به‌صورت یک JSON معتبر مطابق نمونه‌ی زیر برگردان، بدون Markdown و بدون توضیح اضافه.

نمونه فرمت خروجی:
{schema}

محتوای صفحات:
{chunk_text}
"""

# ─── پرامپت استخراج تصویری (vision) ──────────────────────────────────────────

IMAGE_EXTRACTION_PROMPT_TEMPLATE = """
شما فقط یک استخراج‌کننده جدول تراکنش‌های بانکی هستید. تصویر زیر یک یا چند صفحه از صورتحساب بانکی است.

قوانین سخت‌گیرانه:
1. تمام ردیف‌های تراکنش قابل مشاهده در تصویر را استخراج کن.
2. اگر مقدار ستونی نامشخص یا خوانا نبود، null بگذار؛ هرگز حدس نزن.
3. اعداد را بدون کاما، بدون واحد پول و به‌صورت عدد خام برگردان.
4. اگر نام صاحب حساب در تصویر دیده شد استخراجش کن، وگرنه null بگذار.
5. خروجی را دقیقاً و فقط به‌صورت یک JSON معتبر برگردان، بدون Markdown و بدون توضیح اضافه.

نمونه فرمت خروجی:
{schema}

صفحات {page_range}:
{chunk_text}
"""

# ─── توابع کمکی ──────────────────────────────────────────────────────────────


def _clean_json_response(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _cache_path(file_hash: str, page_number: int) -> str:
    cache_dir = os.path.join(config.CACHE_DIR, file_hash)
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"page_{page_number}.json")


def _build_page_result(page_number, data):
    """ساخت PageExtractionResult از دیکشنری JSON خروجی مدل."""
    transactions = []
    for i, row in enumerate(data.get("transactions", [])):
        row["source_page"] = page_number
        row["row_order"] = i
        transactions.append(row)

    return PageExtractionResult(
        page_number=page_number,
        account_holder_name=data.get("account_holder_name"),
        transactions=transactions,
        extraction_status="ok",
    )


def _call_llm_extraction(page_number, prompt, api_key, file_hash):
    """فراخوانی LLM و ساخت PageExtractionResult."""
    cache_file = _cache_path(file_hash, page_number) if file_hash else None
    if cache_file and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return PageExtractionResult(**json.load(f))
        except Exception:
            pass

    last_error = None
    for attempt in range(config.MAX_EXTRACTION_RETRIES):
        try:
            raw_response = call_llm(
                prompt=prompt,
                api_key=api_key,
                model=config.EXTRACTION_MODEL,
                temperature=0.0,
            )
            data = json.loads(_clean_json_response(raw_response))
            result = _build_page_result(page_number, data)

            if cache_file:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

            return result

        except Exception as e:
            last_error = e
            continue

    return PageExtractionResult(
        page_number=page_number,
        transactions=[],
        extraction_status="failed",
        notes=f"خطا پس از {config.MAX_EXTRACTION_RETRIES} تلاش: {last_error}",
    )


# ─── توابع استخراج ───────────────────────────────────────────────────────────


def _extract_with_llm_text(chunk, api_key, file_hash):
    """استخراج متنی از chunk (ممکن است شامل چند صفحه باشد)."""
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        schema=EXTRACTION_SCHEMA_EXAMPLE,
        chunk_text=chunk["text"],
    )
    result = _call_llm_extraction(chunk["page_number"], prompt, api_key, file_hash)
    if result:
        page_range = chunk.get("page_range", str(chunk["page_number"]))
        result.notes = f"استخراج متنی از صفحات {page_range}"
    return result


def _extract_with_llm_image(chunk, api_key, file_hash):
    """استخراج تصویری با vision model."""
    image_b64 = chunk.get("image_b64")
    if not image_b64:
        return None

    page_range = chunk.get("page_range", str(chunk["page_number"]))
    prompt = IMAGE_EXTRACTION_PROMPT_TEMPLATE.format(
        schema=EXTRACTION_SCHEMA_EXAMPLE,
        page_range=page_range,
        chunk_text=chunk.get("text", ""),
    )

    page_number = chunk["page_number"]

    cache_file = _cache_path(file_hash, page_number) if file_hash else None
    if cache_file and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return PageExtractionResult(**json.load(f))
        except Exception:
            pass

    last_error = None
    for attempt in range(config.MAX_EXTRACTION_RETRIES):
        try:
            raw_response = call_llm(
                prompt=prompt,
                api_key=api_key,
                model=config.EXTRACTION_MODEL,
                temperature=0.0,
                image_b64=image_b64,
            )
            data = json.loads(_clean_json_response(raw_response))
            result = _build_page_result(page_number, data)
            result.notes = f"استخراج تصویری از صفحات {page_range}"

            if cache_file:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

            return result

        except Exception as e:
            last_error = e
            continue

    return PageExtractionResult(
        page_number=page_number,
        transactions=[],
        extraction_status="failed",
        notes=f"خطا در استخراج تصویری پس از {config.MAX_EXTRACTION_RETRIES} تلاش: {last_error}",
    )


# ─── تابع اصلی استخراج یک chunk ──────────────────────────────────────────────


def extract_single_page(chunk, api_key: str, file_hash: str = None) -> PageExtractionResult:
    """
    استخراج تراکنش‌های یک chunk (ممکن است شامل چند صفحه باشد).

    دو حالت:
      1. "llm_required"     — متن → LLM
      2. "image_required"   — تصویر → vision LLM
    """
    method = chunk.get("method", "llm_required")

    # حالت متنی
    if method == "llm_required":
        return _extract_with_llm_text(chunk, api_key, file_hash)

    # حالت تصویری
    if method == "image_required":
        return _extract_with_llm_image(chunk, api_key, file_hash)

    # پیش‌فرض: متنی
    return _extract_with_llm_text(chunk, api_key, file_hash)


# ─── استخراج موازی تمام chunks ────────────────────────────────────────────────


def extract_all_pages(chunks, api_key: str, file_hash: str = None,
                       max_workers: int = None, progress_callback=None):
    """اجرای موازی استخراج چون chunks کاملاً مستقل از هم هستند."""
    max_workers = max_workers or config.MAX_WORKERS
    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_single_page, c, api_key, file_hash): c["page_number"]
            for c in chunks
        }
        completed = 0
        total = len(futures)
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                results[page_num] = future.result()
            except Exception as e:
                results[page_num] = PageExtractionResult(
                    page_number=page_num,
                    transactions=[],
                    extraction_status="failed",
                    notes=str(e),
                )
            completed += 1
            if progress_callback:
                progress_callback(completed, total, page_num)

    return [results[k] for k in sorted(results)]
