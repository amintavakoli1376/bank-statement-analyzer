import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from extractors.schemas import PageExtractionResult
from extractors.pdf_splitter import mask_sensitive_info
from extractors.camelot_extractor import parse_camelot_to_page_result
from utils.api_client import call_llm
import config

# ─── پرامپت استخراج متنی ─────────────────────────────────────────────────────

EXTRACTION_SCHEMA_EXAMPLE = """
{
  "account_holder_name": "نام صاحب حساب یا null",
  "transactions": [
    {
      "source_page": 1,
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
2. برای هر تراکنش، شماره صفحه‌ای که از آن استخراج شده را در فیلد source_page قرار بده. شماره صفحات در متن با عبارت «--- صفحه X ---» مشخص شده است.
3. اگر مقدار ستونی نامشخص یا خالی بود، null بگذار؛ هرگز حدس نزن یا مقدار جعل نکن.
4. اعداد را بدون کاما، بدون واحد پول و به‌صورت عدد خام برگردان.
5. اگر نام صاحب حساب در متن دیده شد استخراجش کن، وگرنه null بگذار.
6. اگر هیچ ردیف تراکنشی وجود نداشت، آرایه transactions را خالی برگردان.
7. خروجی را دقیقاً و فقط به‌صورت یک JSON معتبر مطابق نمونه‌ی زیر برگردان، بدون Markdown و بدون توضیح اضافه.

نمونه فرمت خروجی:
{schema}

محتوای صفحات:
{chunk_text}
"""

# ─── پرامپت استخراج تصویری (vision) ──────────────────────────────────────────

IMAGE_EXTRACTION_PROMPT_TEMPLATE = """
شما فقط یک استخراج‌کننده جدول تراکنش‌های بانکی هستید. تصاویر زیر مربوط به صفحات {page_range} صورتحساب بانکی است.
تصاویر به ترتیب ارسال شده‌اند: تصویر اول = کوچک‌ترین شماره صفحه.

قوانین سخت‌گیرانه:
1. تمام ردیف‌های تراکنش قابل مشاهده در تمام تصاویر را استخراج کن. هیچ تصویری را رد نکن.
2. برای هر تراکنش، شماره صفحه‌ی تصویر مبدا را در فیلد source_page قرار بده.
   ترتیب تصاویر و شماره صفحات: {page_mapping}
3. اگر مقدار ستونی نامشخص یا خوانا نبود، null بگذار؛ هرگز حدس نزن.
4. اعداد را بدون کاما، بدون واحد پول و به‌صورت عدد خام برگردان.
5. اگر نام صاحب حساب در تصویر دیده شد استخراجش کن، وگرنه null بگذار.
6. خروجی را دقیقاً و فقط به‌صورت یک JSON معتبر برگردان، بدون Markdown و بدون توضیح اضافه.

نمونه فرمت خروجی:
{schema}

متن کمکی صفحات (ممکن است خالی یا ناقص باشد):
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
        # اگر مدل source_page برگردانده از آن استفاده کن، وگرنه page_number chunk
        row["source_page"] = row.get("source_page") or page_number
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
                cached = PageExtractionResult(**json.load(f))
                print(f"💾 [extractor] صفحه {page_number}: از cache خوانده شد ({len(cached.transactions)} تراکنش)")
                return cached
        except Exception:
            pass

    last_error = None
    for attempt in range(config.MAX_EXTRACTION_RETRIES):
        try:
            print(f"🤖 [extractor] صفحه {page_number}: فراخوانی LLM (تلاش {attempt + 1}/{config.MAX_EXTRACTION_RETRIES})، طول prompt: {len(prompt)}")
            raw_response = call_llm(
                prompt=prompt,
                api_key=api_key,
                model=config.EXTRACTION_MODEL,
                temperature=0.0,
            )

            # هشدار اگر پاسخ خیلی کوتاه است (احتمال تکرنکیت یا خروجی ناقص)
            if len(raw_response) < 100:
                print(f"⚠️ [extractor] صفحه {page_number}: پاسخ LLM خیلی کوتاه است ({len(raw_response)} کاراکتر)! احتمالاً خروجی ناقص یا تکرنکیت شده.")

            cleaned = _clean_json_response(raw_response)
            data = json.loads(cleaned)
            result = _build_page_result(page_number, data)

            print(f"✅ [extractor] صفحه {page_number}: {len(result.transactions)} تراکنش استخراج شد (پاسخ: {len(raw_response)} کاراکتر)")

            if cache_file:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

            return result

        except json.JSONDecodeError as e:
            preview = raw_response[:200] if raw_response else "(خالی)"
            print(f"❌ [extractor] صفحه {page_number}: خطای parse JSON — {e}")
            print(f"   پیش‌نمایش پاسخ: {preview!r}")
            last_error = e
            continue
        except Exception as e:
            print(f"❌ [extractor] صفحه {page_number}: خطا — {e}")
            last_error = e
            continue

    print(f"💥 [extractor] صفحه {page_number}: شکست پس از {config.MAX_EXTRACTION_RETRIES} تلاش")
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
    """استخراج تصویری با vision model — می‌تواند چندین تصویر در یک درخواست باشد."""
    images_b64 = chunk.get("images_b64", [])
    # پشتیبانی از فرمت قدیمی (تک تصویر)
    if not images_b64 and chunk.get("image_b64"):
        images_b64 = [{"page_number": chunk["page_number"], "image_b64": chunk["image_b64"]}]
    if not images_b64:
        print(f"⚠️ [extractor] chunk {chunk['page_number']}: بدون تصویر!")
        return None

    page_range = chunk.get("page_range", str(chunk["page_number"]))
    page_number = chunk["page_number"]

    # نقشه‌ی ترتیب تصاویر → شماره صفحه (برای پرامپت)
    page_mapping_parts = []
    for i, img in enumerate(images_b64, start=1):
        page_mapping_parts.append(f"تصویر {i} = صفحه {img['page_number']}")
    page_mapping = "، ".join(page_mapping_parts)

    prompt = IMAGE_EXTRACTION_PROMPT_TEMPLATE.format(
        schema=EXTRACTION_SCHEMA_EXAMPLE,
        page_range=page_range,
        page_mapping=page_mapping,
        chunk_text=chunk.get("text", ""),
    )

    cache_file = _cache_path(file_hash, page_number) if file_hash else None
    if cache_file and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = PageExtractionResult(**json.load(f))
                print(f"💾 [extractor] صفحات {page_range} (تصویری): از cache خوانده شد ({len(cached.transactions)} تراکنش)")
                return cached
        except Exception:
            pass

    # لیست base64 برای ارسال
    b64_list = [img["image_b64"] for img in images_b64]

    last_error = None
    for attempt in range(config.MAX_EXTRACTION_RETRIES):
        try:
            print(f"🤖 [extractor] صفحات {page_range} (تصویری): فراخوانی vision LLM (تلاش {attempt + 1}/{config.MAX_EXTRACTION_RETRIES})، "
                  f"تعداد تصاویر: {len(b64_list)}، طول prompt: {len(prompt)}")
            raw_response = call_llm(
                prompt=prompt,
                api_key=api_key,
                model=config.EXTRACTION_MODEL,
                temperature=0.0,
                images_b64=b64_list,
            )

            if len(raw_response) < 100:
                print(f"⚠️ [extractor] صفحات {page_range} (تصویری): پاسخ LLM خیلی کوتاه است ({len(raw_response)} کاراکتر)! احتمالاً خروجی ناقص یا تکرنکیت شده.")

            cleaned = _clean_json_response(raw_response)
            data = json.loads(cleaned)
            result = _build_page_result(page_number, data)
            result.notes = f"استخراج تصویری از صفحات {page_range} ({len(b64_list)} تصویر)"

            print(f"✅ [extractor] صفحات {page_range} (تصویری): {len(result.transactions)} تراکنش استخراج شد (پاسخ: {len(raw_response)} کاراکتر)")

            if cache_file:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

            return result

        except json.JSONDecodeError as e:
            preview = raw_response[:200] if raw_response else "(خالی)"
            print(f"❌ [extractor] صفحات {page_range} (تصویری): خطای parse JSON — {e}")
            print(f"   پیش‌نمایش پاسخ: {preview!r}")
            last_error = e
            continue
        except Exception as e:
            print(f"❌ [extractor] صفحات {page_range} (تصویری): خطا — {e}")
            last_error = e
            continue

    print(f"💥 [extractor] صفحات {page_range} (تصویری): شکست پس از {config.MAX_EXTRACTION_RETRIES} تلاش")
    return PageExtractionResult(
        page_number=page_number,
        transactions=[],
        extraction_status="failed",
        notes=f"خطا در استخراج تصویری پس از {config.MAX_EXTRACTION_RETRIES} تلاش: {last_error}",
    )


# ─── استخراج با Camelot (بدون LLM) ───────────────────────────────────────────


def _extract_with_camelot(chunk, api_key: str, file_hash: str = None):
    """استخراج جدول با Camelot — بدون فراخوانی LLM."""
    page_number = chunk["page_number"]
    tables_data = chunk.get("tables_data", [])

    cache_file = _cache_path(file_hash, page_number) if file_hash else None
    if cache_file and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return PageExtractionResult(**json.load(f))
        except Exception:
            pass

    result = parse_camelot_to_page_result(page_number, tables_data)

    if cache_file:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

    return result


# ─── تابع اصلی استخراج یک chunk ──────────────────────────────────────────────


def extract_single_page(chunk, api_key: str, file_hash: str = None) -> PageExtractionResult:
    """
    استخراج تراکنش‌های یک chunk (ممکن است شامل چند صفحه باشد).

    سه حالت:
      1. "camelot"          — جدول → پردازش مستقیم (بدون LLM)
      2. "llm_required"     — متن → LLM
      3. "image_required"   — تصویر → vision LLM
    """
    method = chunk.get("method", "llm_required")

    # حالت جدول Camelot — بدون نیاز به LLM
    if method == "camelot":
        return _extract_with_camelot(chunk, api_key, file_hash)

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

    print(f"\n🚀 [extractor] شروع استخراج {len(chunks)} chunk با {max_workers} worker موازی")
    print(f"   مدل: {config.EXTRACTION_MODEL} | max_output_tokens: {config.MAX_OUTPUT_TOKENS}")

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

    final_results = [results[k] for k in sorted(results)]

    # ─── لاگ خلاصه‌ی نهایی ────────────────────────────────────────────────────
    total_txns = sum(len(r.transactions) for r in final_results)
    ok = sum(1 for r in final_results if r.extraction_status == "ok")
    failed = sum(1 for r in final_results if r.extraction_status == "failed")
    print(f"\n📊 [extractor] خلاصه‌ی نهایی استخراج:")
    print(f"   chunks: {len(final_results)} | موفق: {ok} | ناموفق: {failed} | مجموع تراکنش‌ها: {total_txns}")
    if failed > 0:
        failed_pages = [r.page_number for r in final_results if r.extraction_status == "failed"]
        print(f"   ⚠️ صفحات ناموفق: {failed_pages}")
    print()

    return final_results
