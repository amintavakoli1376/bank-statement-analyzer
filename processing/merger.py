import pandas as pd
import jdatetime
import re

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ENGLISH_DIGITS = "0123456789"
DIGIT_TRANSLATION = str.maketrans(PERSIAN_DIGITS, ENGLISH_DIGITS)


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
    """حذف تراکنش‌های تکراری (مثلاً به‌خاطر overlap صفحات یا خطای مدل)."""
    key_cols = ["date", "time", "description", "deposit", "withdrawal", "balance"]
    before = len(df)
    df = df.drop_duplicates(subset=key_cols, keep="first").reset_index(drop=True)
    return df, before - len(df)


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
    """قدم ۲ کامل: merge → dedup → sort، به‌همراه متادیتای کیفیت."""
    df = merge_results(page_results)
    account_holder = extract_account_holder(page_results)

    metadata = {
        "account_holder_name": account_holder,
        "total_raw_rows": len(df),
    }

    if df.empty:
        metadata.update({"duplicates_removed": 0, "unparsed_dates": 0, "total_final_rows": 0})
        return df, metadata

    df, duplicates_removed = deduplicate(df)
    df, unparsed_dates = sort_transactions(df)

    metadata["duplicates_removed"] = duplicates_removed
    metadata["unparsed_dates"] = unparsed_dates
    metadata["total_final_rows"] = len(df)

    return df, metadata