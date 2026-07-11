import pandas as pd
import jdatetime
import re

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ENGLISH_DIGITS = "0123456789"
DIGIT_TRANSLATION = str.maketrans(PERSIAN_DIGITS, ENGLISH_DIGITS)

# الگوی ساعت در ابتدا یا انتهای تاریخ: "11:57:36 1404/10/15" یا "1404/10/15 11:57:36"
TIME_AT_START_RE = re.compile(r'^(\d{1,2}:\d{2}(:\d{2})?)\s+(\d{4}[-/]\d{1,2}[-/]\d{1,2})$')
TIME_AT_END_RE = re.compile(r'^(\d{4}[-/]\d{1,2}[-/]\d{1,2})\s+(\d{1,2}:\d{2}(:\d{2})?)$')


def normalize_digits(text: str) -> str:
    if not isinstance(text, str):
        return text
    return text.translate(DIGIT_TRANSLATION)


def parse_jalali_date(date_str):
    """تبدیل تاریخ شمسی رشته‌ای (مثل 1402/03/15) به تاریخ میلادی برای مرتب‌سازی دقیق."""
    if not date_str or not isinstance(date_str, str):
        return None
    normalized = normalize_digits(date_str)
    match = re.search(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", normalized)
    if not match:
        return None
    y, m, d = map(int, match.groups())
    try:
        return jdatetime.date(y, m, d).togregorian()
    except ValueError:
        return None


def normalize_datetime_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    نرمال‌سازی فیلدهای date/time.
    
    اگر فیلد date شامل ساعت هم باشد (مثلاً "11:57:36 1404/10/15"
    یا "1404/10/15 11:57:36")، ساعت جدا شده و به فیلد time منتقل می‌شود.
    """
    df = df.copy()
    for idx in df.index:
        date_val = str(df.at[idx, "date"]).strip() if pd.notna(df.at[idx, "date"]) else ""
        time_val = str(df.at[idx, "time"]).strip() if pd.notna(df.at[idx, "time"]) else ""

        if not date_val:
            continue

        # اگر time خالی است و date شامل ساعت است، جداسازی کن
        if not time_val:
            m = TIME_AT_START_RE.match(date_val)
            if m:
                df.at[idx, "time"] = m.group(1)
                df.at[idx, "date"] = m.group(3)
                continue
            m = TIME_AT_END_RE.match(date_val)
            if m:
                df.at[idx, "time"] = m.group(2)
                df.at[idx, "date"] = m.group(1)
                continue

    return df


def merge_results(page_results) -> pd.DataFrame:
    rows = []
    for pr in page_results:
        for t in pr.transactions:
            rows.append(t.model_dump())
    return pd.DataFrame(rows)


def extract_account_holder(page_results):
    for pr in page_results:
        if pr.account_holder_name:
            return pr.account_holder_name
    return None


def deduplicate(df: pd.DataFrame):
    """حذف تراکنش‌های تکراری (Exact Match روی ۶ فیلد کلیدی)."""
    key_cols = ["date", "time", "description", "deposit", "withdrawal", "balance"]
    before = len(df)
    df = df.drop_duplicates(subset=key_cols, keep="first").reset_index(drop=True)
    return df, before - len(df)


def deduplicate_by_financial_key(df: pd.DataFrame):
    """
    حذف تراکنش‌های تکراری بر اساس امضای مالی (date, deposit, withdrawal, balance).
    
    موارد کاربرد:
    - وقتی Camelot یک تراکنش را در دو صفحه مختلف با ستون‌بندی متفاوت
      استخراج کرده (مثلاً در یک صفحه date/time جدا و در صفحه دیگر چسبیده)
    - در این موارد فیلد description متفاوت است ولی مقادیر مالی یکی هستند
    
    از بین ردیف‌های تکراری، ردیفی که کیفیت بالاتری دارد نگه داشته می‌شود:
      ۱. time غیرخالی (ارجح بر time خالی)
      ۲. description بلندتر
      ۳. source_page کوچکتر (اولویت با صفحه اول)
    """
    key_cols = ["date", "deposit", "withdrawal", "balance"]
    before = len(df)

    # رتبه‌بندی کیفیت هر ردیف
    def _quality_score(row):
        score = 0
        if pd.notna(row.get("time")) and str(row.get("time", "")).strip():
            score += 100
        desc = str(row.get("description", ""))
        score += min(len(desc), 500)  # حداکثر ۵۰۰ امتیاز برای طول توضیحات
        score -= row.get("source_page", 0) * 0.001  # ترجیح صفحه کوچکتر
        return score

    df = df.copy()
    df["_quality"] = df.apply(_quality_score, axis=1)

    # برای هر گروه مالی، ردیف با بالاترین کیفیت را نگه دار
    df = df.loc[df.groupby(key_cols, dropna=False)["_quality"].idxmax()].reset_index(drop=True)
    df = df.drop(columns=["_quality"])

    removed = before - len(df)
    return df, removed


def sort_transactions(df: pd.DataFrame):
    df = df.copy()
    df["parsed_date"] = df["date"].apply(parse_jalali_date)
    unparsed_count = int(df["parsed_date"].isna().sum())

    df = df.sort_values(
        by=["parsed_date", "time", "source_page", "row_order"],
        na_position="last",
    ).reset_index(drop=True)

    return df, unparsed_count


def run_merge_pipeline(page_results):
    """
    قدم ۲ کامل: merge → normalize_datetime → dedup (exact) → dedup (financial) → sort
    به‌همراه متادیتای کیفیت.
    """
    df = merge_results(page_results)
    account_holder = extract_account_holder(page_results)

    metadata = {
        "account_holder_name": account_holder,
        "total_raw_rows": len(df),
    }

    if df.empty:
        metadata.update({
            "duplicates_removed": 0,
            "financial_dedup_removed": 0,
            "unparsed_dates": 0,
            "total_final_rows": 0,
        })
        return df, metadata

    # ۱. نرمال‌سازی date/time (جدا کردن ساعت از تاریخ چسبیده)
    df = normalize_datetime_fields(df)

    # ۲. Exact dedup روی ۶ فیلد
    df, duplicates_removed = deduplicate(df)

    # ۳. Dedup روی امضای مالی (برای ردیف‌های تکراری با فرمت متفاوت)
    df, financial_dedup_removed = deduplicate_by_financial_key(df)

    # ۴. مرتب‌سازی
    df, unparsed_dates = sort_transactions(df)

    metadata["duplicates_removed"] = duplicates_removed
    metadata["financial_dedup_removed"] = financial_dedup_removed
    metadata["unparsed_dates"] = unparsed_dates
    metadata["total_final_rows"] = len(df)

    return df, metadata