import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from extractors.schemas import PageExtractionResult
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


def _repair_truncated_json(raw_text: str) -> str:
    """تلاش برای ترمیم JSON ناقص ناشی از تکرنکیت max_tokens.

    استراتژی (به ترتیب):
    1. بستن براکت‌ها / آکولاد‌های بازمانده
    2. حذف trailing comma قبل از ] یا }
    3. Salvage: استخراج prefix معتبر با json.JSONDecoder.raw_decode
    """
    text = raw_text.strip()

    # ── شمارش براکت‌های باز و بسته ──
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")

    # بستن براکت‌های بازمانده از آخر به اول (اول آرایه، بعد آبجکت)
    if open_brackets > 0:
        text += "]" * open_brackets
    if open_braces > 0:
        text += "}" * open_braces

    # حذف trailing comma قبل از ] یا }
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    # ── تلاش Salvage: اگر JSON همچنان شکست، prefix معتبر را استخراج کن ──
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # raw_decode: بزرگترین prefix معتبر JSON را استخراج کن
    try:
        decoder = json.JSONDecoder()
        obj, end_idx = decoder.raw_decode(text)
        # فقط prefix معتبر را برگردان و transactions آرایه را salvage کن
        if isinstance(obj, dict) and "transactions" in obj:
            salvaged = json.dumps(obj, ensure_ascii=False)
            print(f"🔧 [repair] JSON salvage: {len(obj.get('transactions', []))} تراکنش از prefix معتبر استخراج شد "
                  f"(اندیس {end_idx} از {len(text)} کاراکتر)")
            return salvaged
    except json.JSONDecodeError:
        pass

    # آخرین تلاش: فقط transactions آرایه را salvage کن
    # دنبال آخرین "transactions": [ بگرد و آرایه رو ببند
    tx_start = text.rfind('"transactions":')
    if tx_start >= 0:
        bracket_start = text.find("[", tx_start)
        if bracket_start >= 0:
            prefix = text[:bracket_start + 1]
            # پیدا کردن آخرین آبجکت کامل در آرایه (با } بسته شده)
            # از انتها برگرد و ببین کجا {} متوازن می‌شود
            depth = 0
            last_good = bracket_start
            for i in range(bracket_start + 1, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        last_good = i
            if last_good > bracket_start:
                salvaged_text = text[:last_good + 1] + "] }"
                try:
                    obj = json.loads(salvaged_text)
                    print(f"🔧 [repair] JSON salvage (روش آرایه): "
                          f"{len(obj.get('transactions', []))} تراکنش استخراج شد")
                    return json.dumps(obj, ensure_ascii=False)
                except json.JSONDecodeError:
                    pass

    return text  # نتوانستیم repair کنیم — برگردان همان متن برای خطای بعدی


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
            # تلاش اول: parse مستقیم، در صورت شکست → repair JSON ناقص
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                repaired = _repair_truncated_json(cleaned)
                data = json.loads(repaired)
            result = _build_page_result(page_number, data)

            print(f"✅ [extractor] صفحه {page_number}: {len(result.transactions)} تراکنش استخراج شد (پاسخ: {len(raw_response)} کاراکتر)")

            return result

        except RuntimeError as e:
            msg = str(e)
            print(f"⚠️ [extractor] صفحه {page_number}: تکرنکیت API — {msg}")
            if "TruncatedResponse" in msg and attempt < config.MAX_EXTRACTION_RETRIES - 1:
                print(f"   🔄 تلاش مجدد با درخواست خروجی خلاصه‌تر...")
            last_error = e
            continue
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


def _merge_page_results(result1, result2, page_number, page_range):
    if result1 is None:
        result1 = PageExtractionResult(page_number=page_number, transactions=[], extraction_status="failed")
    if result2 is None:
        result2 = PageExtractionResult(page_number=page_number, transactions=[], extraction_status="failed")

    merged = PageExtractionResult(
        page_number=page_number,
        transactions=(result1.transactions or []) + (result2.transactions or []),
        extraction_status="success" if (result1.extraction_status == "success" and result2.extraction_status == "success") else "partial",
        notes=f"ادغام نتایج تقسیم‌شده صفحات {page_range}",
    )
    return merged


def _extract_with_llm_image(chunk, api_key, file_hash):
    """استخراج تصویری با vision model — می‌تواند چندین تصویر در یک درخواست باشد."""
    images_b64 = chunk.get("images_b64", [])
    if not images_b64 and chunk.get("image_b64"):
        images_b64 = [{"page_number": chunk["page_number"], "image_b64": chunk["image_b64"]}]
    if not images_b64:
        print(f"⚠️ [extractor] chunk {chunk['page_number']}: بدون تصویر!")
        return None

    page_range = chunk.get("page_range", str(chunk["page_number"]))
    page_number = chunk["page_number"]

    page_mapping = "، ".join(
        f"تصویر {i} = صفحه {img['page_number']}" for i, img in enumerate(images_b64, start=1)
    )
    prompt = IMAGE_EXTRACTION_PROMPT_TEMPLATE.format(
        schema=EXTRACTION_SCHEMA_EXAMPLE,
        page_range=page_range,
        page_mapping=page_mapping,
        chunk_text=chunk.get("text", ""),
    )
    b64_list = [img["image_b64"] for img in images_b64]

    last_error = None
    temperature = 0.0

    for attempt in range(config.MAX_EXTRACTION_RETRIES):
        try:
            print(f"🤖 [extractor] صفحات {page_range} (تصویری): تلاش {attempt+1}/{config.MAX_EXTRACTION_RETRIES}، "
                  f"تصاویر: {len(b64_list)}، temperature={temperature}")
            raw_response = call_llm(
                prompt=prompt,
                api_key=api_key,
                model=config.EXTRACTION_MODEL,
                temperature=temperature,
                images_b64=b64_list,
            )

            cleaned = _clean_json_response(raw_response)
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                data = json.loads(_repair_truncated_json(cleaned))

            result = _build_page_result(page_number, data)
            result.notes = f"استخراج تصویری از صفحات {page_range} ({len(b64_list)} تصویر)"
            print(f"✅ [extractor] صفحات {page_range}: {len(result.transactions)} تراکنش")
            return result

        except RuntimeError as e:
            msg = str(e)
            last_error = e
            print(f"⚠️ [extractor] صفحات {page_range}: خطای API — {msg}")

            if "TruncatedResponse" in msg:
                # اگر بیش از یک تصویر داریم → chunk را نصف کن و جداگانه پردازش کن
                if len(images_b64) > 1:
                    print("   ✂️ تقسیم chunk به دو نیمه به‌دلیل truncation...")
                    mid = len(images_b64) // 2
                    first_half = images_b64[:mid]
                    second_half = images_b64[mid:]

                    chunk1 = {**chunk, "images_b64": first_half,
                              "page_range": f"{first_half[0]['page_number']}-{first_half[-1]['page_number']}"}
                    chunk2 = {**chunk, "images_b64": second_half,
                              "page_range": f"{second_half[0]['page_number']}-{second_half[-1]['page_number']}",
                              "page_number": second_half[0]["page_number"]}

                    result1 = _extract_with_llm_image(chunk1, api_key, file_hash)
                    result2 = _extract_with_llm_image(chunk2, api_key, file_hash)
                    return _merge_page_results(result1, result2, page_number, page_range)
                else:
                    # فقط یک تصویر بود ولی باز هم truncate شد → temperature را کمی بالا ببر
                    temperature = min(temperature + 0.3, 0.7)
                    print(f"   🔄 تلاش مجدد با temperature={temperature} (چون تک‌تصویری بود)...")
            continue

        except json.JSONDecodeError as e:
            preview = raw_response[:200] if raw_response else "(خالی)"
            print(f"❌ [extractor] صفحات {page_range}: خطای parse JSON — {e}")
            print(f"   پیش‌نمایش: {preview!r}")
            last_error = e
            continue

        except Exception as e:
            print(f"❌ [extractor] صفحات {page_range}: خطا — {type(e).__name__}: {e}")
            last_error = e
            continue

    print(f"💥 [extractor] صفحات {page_range}: شکست پس از {config.MAX_EXTRACTION_RETRIES} تلاش. خطای نهایی: {last_error}")
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
    return parse_camelot_to_page_result(page_number, tables_data)


# ─── تابع اصلی استخراج یک chunk ──────────────────────────────────────────────


def extract_single_page(chunk, api_key: str, file_hash: str = None) -> PageExtractionResult:
    """
    استخراج تراکنش‌های یک chunk (ممکن است شامل چند صفحه باشد).

    دو حالت:
      1. "camelot"          — جدول → پردازش مستقیم (بدون LLM)
      2. "image_required"   — تصویر → vision LLM
    """
    method = chunk.get("method", "image_required")

    # حالت جدول Camelot — بدون نیاز به LLM
    if method == "camelot":
        return _extract_with_camelot(chunk, api_key, file_hash)

    # حالت تصویری
    if method == "image_required":
        return _extract_with_llm_image(chunk, api_key, file_hash)

    # پیش‌فرض: تصویری
    return _extract_with_llm_image(chunk, api_key, file_hash)


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
