"""
استخراج‌کننده جدول از PDF با استفاده از Camelot.

وقتی PDF شامل جدول ساختاریافته (با خطوط/حاشیه) باشد،
camelot داده‌ها را مستقیماً بدون نیاز به LLM استخراج می‌کند.
"""

import re
import unicodedata
import io
import tempfile
import os

import pandas as pd

from extractors.schemas import PageExtractionResult, Transaction
import config

# ─── بررسی دسترسی به camelot ──────────────────────────────────────────────────

try:
    import camelot
    HAS_CAMELOT = True
except ImportError:
    HAS_CAMELOT = False

# ─── الگوهای شناسایی ستون‌ها از هدر ──────────────────────────────────────────

HEADER_PATTERNS = {
    "date": re.compile(r'(تاریخ|تارخ|date)', re.IGNORECASE),
    "time": re.compile(r'(ساعت|زمان|time|hour)', re.IGNORECASE),
    "description": re.compile(r'(شرح|توضیحات|عملیات|بابت|operation|desc|description)', re.IGNORECASE),
    "deposit": re.compile(r'(واریز|بستانکار|بست|ورود|مبلغ\s*بستانکار|بدار|deposit|credit|بیعانه)', re.IGNORECASE),
    "withdrawal": re.compile(r'(برداشت|بدهکار|بد|خروج|مبلغ\s*بدهکار|withdrawal|debit)', re.IGNORECASE),
    "balance": re.compile(r'(مانده|باقی[\s-]*مانده|موجودی|موجود|balance|remaining)', re.IGNORECASE),
    "reference": re.compile(r'(شماره|مرجع|سند|پیگیری|کد|ref|reference)', re.IGNORECASE),
}


def detect_columns_from_header(header_row):
    """
    شناسایی نوع هر ستون از نام هدر.

    خروجی: دیکشنری {index: column_type}
    مثال: {0: 'date', 1: 'description', 2: 'deposit', 3: 'withdrawal', 4: 'balance'}
    """
    mapping = {}
    for idx, cell in enumerate(header_row):
        cell_str = str(cell).strip()
        for col_type, pattern in HEADER_PATTERNS.items():
            if pattern.search(cell_str):
                mapping[idx] = col_type
                break
    return mapping


def row_to_tuple(row):
    """تبدیل یک ردیف (Series) به تاپل رشته‌ای برای مقایسه."""
    return tuple(str(x).strip() for x in row.tolist())


def remove_duplicate_headers(dfs, min_rows=1):
    """
    حذف هدرهای تکراری بین صفحات.
    هدر اول جدول به‌عنوان مرجع در نظر گرفته می‌شود
    و ردیف‌های تکراری در صفحات بعدی حذف می‌شوند.
    """
    if not dfs:
        return []

    first_df = dfs[0]
    if first_df.empty:
        return dfs

    header_tuple = row_to_tuple(first_df.iloc[0])
    result = [first_df]

    for df in dfs[1:]:
        df = df.copy()
        if df.shape[1] == len(header_tuple) and not df.empty:
            first_row = row_to_tuple(df.iloc[0])
            if first_row == header_tuple:
                df = df.iloc[1:]
        result.append(df)

    return result


def combine_tables(dfs):
    """
    ترکیب چند جدول و حذف هدرهای تکراری باقی‌مانده.
    """
    if not dfs:
        return pd.DataFrame()

    cleaned = remove_duplicate_headers(dfs)

    # حذف هدرهای تکراری باقی‌مانده در وسط جدول
    first_df = cleaned[0]
    if first_df.empty:
        return pd.DataFrame()

    header_tuple = row_to_tuple(first_df.iloc[0])
    combined = pd.concat(cleaned, ignore_index=True)

    if combined.empty:
        return combined

    # پیدا و حذف ردیف‌هایی که دقیقاً مثل هدر هستند (به‌جز اولی)
    mask = []
    for idx in range(len(combined)):
        if idx == 0:
            mask.append(False)
        else:
            mask.append(row_to_tuple(combined.iloc[idx]) == header_tuple)

    combined = combined[~pd.Series(mask, index=combined.index)].reset_index(drop=True)
    return combined


# ─── توابع اصلاح متن فارسی ──────────────────────────────────────────────────

def normalize_persian_chars(text):
    """نرمال‌سازی کاراکترهای فارسی/عربی."""
    if not isinstance(text, str) or text.strip() == "":
        return text
    text = unicodedata.normalize('NFKC', text)
    manual_map = {
        '\u0640': '',       # tatweel
        'ك': 'ک',           # Arabic Kaf → Persian Kaf
        'ي': 'ی',           # Arabic Ya → Persian Ya
        'ى': 'ی',
        'ة': 'ه',
    }
    for old, new in manual_map.items():
        text = text.replace(old, new)
    # ارقام عربی → فارسی
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    text = text.translate(str.maketrans(arabic_digits, persian_digits))
    return text


PERSIAN_ARABIC_RANGE = r'\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF'
PERSIAN_CHAR_PATTERN = re.compile(f'[{PERSIAN_ARABIC_RANGE}]')
NUMBER_PATTERN = re.compile(r'^[۰-۹,\./\-\+:]+$')

LIGATURE_FIXES = {
    "کاال": "کالا",
    "اصالح": "اصلاح",
    "اطالعات": "اطلاعات",
    "تسهیالت": "تسهیلات",
    "اعالم": "اعلام",
    "ابالع": "ابلاغ",
    "خالصه": "خلاصه",
    "عالمت": "علامت",
    "صالحیت": "صلاحیت",
    "انقالب": "انقلاب",
    "امالک": "املاک",
    "عالقه": "علاقه",
    "فالپی": "فلاپی",
    "مالحظه": "ملاحظه",
    "مالحظات": "ملاحظات",
    "باطال": "ابطال",
}


def fix_persian_layout(text):
    """
    اصلاح چیدمان متن فارسی استخراج‌شده از PDF.
    Camelot متن‌های RTL را معمولاً برعکس استخراج می‌کند.
    """
    if not isinstance(text, str) or text.strip() == "":
        return text
    text = normalize_persian_chars(text)
    tokens = text.split()
    fixed_tokens = []
    for token in tokens:
        if PERSIAN_CHAR_PATTERN.search(token):
            if NUMBER_PATTERN.match(token):
                fixed_tokens.append(token)
            else:
                fixed_tokens.append(token[::-1])
        else:
            fixed_tokens.append(token)
    fixed_tokens.reverse()
    fixed_text = ' '.join(fixed_tokens)

    for wrong, right in LIGATURE_FIXES.items():
        fixed_text = fixed_text.replace(wrong, right)

    return fixed_text


def clean_number(value):
    """تبدیل رشته عددی به float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("٬", "").replace(" ", "").strip()
        if cleaned in ("", "-", "null", "None", "NaN", "*"):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def apply_persian_fixes(df):
    """اعمال اصلاحات فارسی روی تمام سلول‌های DataFrame."""
    try:
        return df.map(fix_persian_layout)
    except AttributeError:
        return df.applymap(fix_persian_layout)


# ─── تابع اصلی استخراج جدول از یک صفحه ────────────────────────────────────────


def try_extract_tables(file_bytes, page_idx):
    """
    تلاش برای استخراج جدول از یک صفحه PDF با Camelot.

    Args:
        file_bytes: محتوای فایل PDF (bytes)
        page_idx: شماره صفحه (0-based)

    Returns:
        list[pd.DataFrame]: لیست جداول استخراج‌شده (می‌تواند خالی باشد)
    """
    if not HAS_CAMELOT or not config.USE_CAMELOT:
        return []

    try:
        # Camelot نیاز به مسیر فایل دارد، بنابراین از فایل موقت استفاده می‌کنیم
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            tables = camelot.read_pdf(
                tmp_path,
                pages=str(page_idx + 1),  # camelot صفحه‌ها را 1-based می‌شمارد
                flavor='lattice',
            )

            if len(tables) == 0:
                return []

            result_dfs = []
            for table in tables:
                df = table.df.copy()
                # بررسی حداقل تعداد ردیف (به‌جز هدر)
                if len(df) > config.MIN_CAMELOT_TABLE_ROWS:
                    result_dfs.append(df)

            return result_dfs

        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except Exception:
        # هر خطایی (Ghostscript نصب نیست، PDF خراب، و ...) → بازگشت خالی
        return []


def parse_camelot_to_page_result(page_number, dataframes):
    """
    تبدیل جداول استخراج‌شده توسط Camelot به PageExtractionResult.

    Args:
        page_number: شماره صفحه (1-based)
        dataframes: لیست DataFrame های Camelot

    Returns:
        PageExtractionResult
    """
    if not dataframes:
        return PageExtractionResult(
            page_number=page_number,
            transactions=[],
            extraction_status="ok",
            notes="camelot: جدولی یافت نشد",
        )

    # ترکیب جداول
    combined = combine_tables(dataframes)

    if combined.empty:
        return PageExtractionResult(
            page_number=page_number,
            transactions=[],
            extraction_status="ok",
            notes="camelot: جدول خالی پس از ترکیب",
        )

    # شناسایی ستون‌ها از هدر اصلی 
    header = combined.iloc[0].tolist()
    
    # تست هدر خام
    col_mapping_raw = detect_columns_from_header(header)
    
    # تست هدر اصلاح شده (برای مواقعی که Camelot کلمات را برعکس استخراج کرده)
    header_fixed = [fix_persian_layout(str(c)) for c in header]
    col_mapping_fixed = detect_columns_from_header(header_fixed)
    
    # انتخاب نگاشتی که بیشترین ستون را پیدا کرده است
    if len(col_mapping_fixed) > len(col_mapping_raw):
        col_mapping = col_mapping_fixed
    else:
        col_mapping = col_mapping_raw

    # اگر نتوانست ستون‌ها را شناسایی کند، سعی می‌کنم با ترتیب پیش‌فرض
    if len(col_mapping) < 3:
        col_mapping = _fallback_column_mapping(len(header), col_mapping)

    # اصلاح متن فارسی روی ردیف‌های داده (نه هدر)
    combined = apply_persian_fixes(combined)

    # حذف ردیف هدر و تبدیل به تراکنش‌ها
    data_rows = combined.iloc[1:]
    transactions = []

    for row_idx, row in data_rows.iterrows():
        txn = _row_to_transaction(row, col_mapping, page_number, row_idx)
        if txn:
            transactions.append(txn)

    return PageExtractionResult(
        page_number=page_number,
        transactions=transactions,
        extraction_status="ok",
        notes=f"camelot: {len(transactions)} تراکنش استخراج شد",
    )


def _fallback_column_mapping(num_cols, existing_mapping):
    """
    ترتیب پیش‌فرض ستون‌ها برای صورتحساب‌های بانکی ایرانی.
    معمولاً: [ردیف, تاریخ, شرح, واریز, برداشت, مانده]
    یا: [تاریخ, شرح, واریز, برداشت, مانده]
    یا: [تاریخ, ساعت, شرح, واریز, برداشت, مانده]
    یا: [ردیف, تاریخ, ساعت, شرح, واریز, برداشت, مانده]
    """
    mapping = dict(existing_mapping)

    if num_cols == 5:
        # فرض: تاریخ، شرح، واریز، برداشت، مانده
        defaults = {0: "date", 1: "description", 2: "deposit", 3: "withdrawal", 4: "balance"}
    elif num_cols == 6:
        # اولویت ۱: تاریخ، ساعت، شرح، واریز، برداشت، مانده
        # اولویت ۲: ردیف، تاریخ، شرح، واریز، برداشت، مانده
        if "time" not in mapping.values() and "date" not in mapping.values():
            # اگر هیچ ستون time/date شناسایی نشده، فرض می‌کنیم ستون اول تاریخ و دوم ساعت است
            defaults = {0: "date", 1: "time", 2: "description", 3: "deposit", 4: "withdrawal", 5: "balance"}
        else:
            defaults = {1: "date", 2: "description", 3: "deposit", 4: "withdrawal", 5: "balance"}
    elif num_cols == 7:
        # فرض: ردیف، تاریخ، ساعت، شرح، واریز، برداشت، مانده
        defaults = {1: "date", 2: "time", 3: "description", 4: "deposit", 5: "withdrawal", 6: "balance"}
    elif num_cols == 4:
        # فرض: تاریخ، شرح، برداشت/واریز، مانده
        defaults = {0: "date", 1: "description", 2: "withdrawal", 3: "balance"}
    else:
        # حدس: آخرین ستون = مانده، یکی مانده آخر = برداشت، دو مانده آخر = واریز
        defaults = {}
        if num_cols >= 2:
            defaults[num_cols - 1] = "balance"
        if num_cols >= 3:
            defaults[num_cols - 2] = "withdrawal"
        if num_cols >= 4:
            defaults[num_cols - 3] = "deposit"

    # فقط ستون‌هایی که قبلاً شناسایی نشده‌اند را اضافه کن
    for idx, col_type in defaults.items():
        if idx not in mapping and idx < num_cols:
            mapping[idx] = col_type

    return mapping


TIME_AT_START_PATTERN = re.compile(r'^(\d{1,2}:\d{2}(:\d{2})?)\s+(\d{4}[-/]\d{1,2}[-/]\d{1,2})$')
TIME_AT_END_PATTERN = re.compile(r'^(\d{4}[-/]\d{1,2}[-/]\d{1,2})\s+(\d{1,2}:\d{2}(:\d{2})?)$')


def _extract_time_from_date(date_val, time_val):
    """
    اگر time خالی بود و date شامل ساعت در ابتدا یا انتها بود،
    ساعت را از date جدا کن.
    
    حالات پشتیبانی شده:
    - "11:57:36 1404/10/15" ← time="11:57:36", date="1404/10/15"
    - "1404/10/15 11:57:36" ← time="11:57:36", date="1404/10/15"
    """
    if not date_val:
        return date_val, time_val

    if not time_val or not time_val.strip():
        # بررسی الگوی "HH:MM:SS YYYY/MM/DD"
        m = TIME_AT_START_PATTERN.match(date_val)
        if m:
            return m.group(3).strip(), m.group(1)

        # بررسی الگوی "YYYY/MM/DD HH:MM:SS"
        m = TIME_AT_END_PATTERN.match(date_val)
        if m:
            return m.group(1).strip(), m.group(2)

    return date_val, time_val


def _row_to_transaction(row, col_mapping, page_number, row_idx):
    """
    تبدیل یک ردیف جدول به Transaction.
    """
    # استخراج مقادیر بر اساس نگاشت ستون‌ها
    date_val = ""
    time_val = None
    description_val = ""
    deposit_val = 0.0
    withdrawal_val = 0.0
    balance_val = None

    for idx, col_type in col_mapping.items():
        if idx >= len(row):
            continue
        cell = str(row.iloc[idx]).strip()

        if col_type == "date":
            date_val = cell
        elif col_type == "time":
            time_val = cell if cell else None
        elif col_type == "description":
            description_val = cell
        elif col_type == "deposit":
            deposit_val = clean_number(cell) or 0.0
        elif col_type == "withdrawal":
            withdrawal_val = clean_number(cell) or 0.0
        elif col_type == "balance":
            balance_val = clean_number(cell)

    # نرمال‌سازی: اگر time خالی است ولی date شامل ساعت است، آن را جدا کن
    date_val, time_val = _extract_time_from_date(date_val, time_val)

    # ردیف‌های خالی یا نامعتبر را نادیده بگیر
    if not date_val and not description_val:
        return None
    if deposit_val == 0 and withdrawal_val == 0 and balance_val is None:
        return None

    return Transaction(
        date=date_val,
        time=time_val,
        description=description_val,
        deposit=deposit_val,
        withdrawal=withdrawal_val,
        balance=balance_val,
        source_page=page_number,
        row_order=row_idx,
    )
