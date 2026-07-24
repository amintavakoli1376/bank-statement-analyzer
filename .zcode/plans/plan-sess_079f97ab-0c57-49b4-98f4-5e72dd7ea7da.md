## طرح رفع باگ‌ها

### P0 — ریشه اصلی: تکرنکیت JSON و شکست همه chunks

**مشکل:** MAX_OUTPUT_TOKENS=16000 برای ۴ صفحه کافی نیست. مدل ۱۵۹۹۶ توکن تولید می‌کند و JSON ناقص می‌ماند. ۲ retry هم همان نتیجه → همه chunks fail.

**تغییرات:**

1. **`config.py`**: `MAX_OUTPUT_TOKENS` = 16000 → 32000

2. **`utils/api_client.py`**:
   - رفع merge conflict → انتخاب URL پروکسی Worker
   - `finish_reason == "length"` دیگر فقط warning نیست: RuntimeError("TruncatedResponse") raise می‌کند
   - timeout پیش‌فرض = 120 → 180

3. **`extractors/llm_extractor.py`**:
   - تابع جدید `_repair_truncated_json(raw_text)`:
     - شمارش `{`/`}` و `[`/`]` باز و بسته → بستن براکت‌های باز
     - حذف trailing comma قبل از `]` یا `}`
     - Salvage: `json.JSONDecoder.raw_decode` برای استخراج prefix معتبر
   - در retry loop `_extract_with_llm_image`: اگر `TruncatedResponseException` گرفت، prompt ساده‌تر با درخواست "فقط نیمه اول" بفرستد
   - `_repair_truncated_json` قبل از `json.loads` اعمال شود

### P1 — Fixهای جانبی

4. **`extractors/pdf_splitter.py`**: رفع ۴ conflict block → نسخه PyMuPDF (fitz) برای ساخت عکس

5. **`app.py`**:
   - خط ۷۱: رفع indent — `try:` الآن بیرون `else:` است، باید داخل آن باشد
   - خط ۶۳: `st.button(..., use_container_width=True)` → `st.button(..., width="stretch")`
   - خط ۲۹۳: `st.dataframe(..., use_container_width=True)` → `st.dataframe(..., width="stretch")`

6. **`processing/validator.py`**: FutureWarning رفع شود
   - خط ۱۷-۱۸: قبل از `.fillna(0)`، تبدیل به عددی با `pd.to_numeric(..., errors="coerce")`

### فایل‌های تغییر‌یافته
- `config.py` (۱ تغییر)
- `utils/api_client.py` (۳ تغییر)
- `extractors/llm_extractor.py` (~۴۰ خط جدید + تغییر retry logic)
- `extractors/pdf_splitter.py` (۴ conflict resolution)
- `app.py` (۳ تغییر)
- `processing/validator.py` (۲ تغییر)