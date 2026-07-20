import pandas as pd
import config


def verify_balance_continuity(df: pd.DataFrame, tolerance: float = None):
    """
    چک deterministic پیوستگی موجودی:
    balance[i] باید تقریباً برابر balance[i-1] + deposit[i] - withdrawal[i] باشد.
    اگر نبود => یا تراکنش جا افتاده یا OCR/LLM خطا کرده.
    """
    tolerance = tolerance if tolerance is not None else config.BALANCE_TOLERANCE

    if df.empty or "balance" not in df.columns:
        return df, {"total_rows": 0, "mismatch_count": 0, "mismatch_rows": []}

    df = df.copy()
    df["deposit"] = df["deposit"].fillna(0)
    df["withdrawal"] = df["withdrawal"].fillna(0)

    # ── دیباگ: نمایش اطلاعات پایه ──
    print("\n" + "=" * 80)
    print("🔍 دیباگ اعتبارسنجی موجودی")
    print(f"  تعداد کل ردیف‌ها: {len(df)}")
    print(f"  تلرانس: {tolerance:,} ریال")
    print(f"  تعداد ردیف‌هایی که balance دارند: {df['balance'].notna().sum()}")
    print(f"  تعداد ردیف‌هایی که deposit > 0: {(df['deposit'] > 0).sum()}")
    print(f"  تعداد ردیف‌هایی که withdrawal > 0: {(df['withdrawal'] > 0).sum()}")
    print(f"  تعداد ردیف‌هایی که deposit=0 و withdrawal=0: {((df['deposit'] == 0) & (df['withdrawal'] == 0)).sum()}")

    df["expected_balance"] = df["balance"].shift(1) + df["deposit"] - df["withdrawal"]
    df["balance_diff"] = (df["expected_balance"] - df["balance"]).abs()
    df["balance_mismatch"] = df["balance_diff"] > tolerance

    if len(df) > 0:
        df.loc[df.index[0], "balance_mismatch"] = False  # سطر اول مبنای مقایسه است

    # اگر داده ناقص است (نه اشتباه)، mismatch محسوب نشود
    df.loc[df["balance"].isna() | df["expected_balance"].isna(), "balance_mismatch"] = False

    mismatches = df[df["balance_mismatch"]]

    # ── دیباگ: نمایش نمونه ردیف‌ها ──
    print(f"\n  📊 ۵ ردیف اول:")
    print(df[["date", "deposit", "withdrawal", "balance"]].head(5).to_string())

    print(f"\n  📊 ۵ ردیف آخر:")
    print(df[["date", "deposit", "withdrawal", "balance"]].tail(5).to_string())

    if len(mismatches) > 0:
        print(f"\n  ❌ تعداد mismatch: {len(mismatches)} از {len(df)}")
        print(f"\n  📊 ۵ ردیف اول mismatch:")
        print(mismatches[["date", "deposit", "withdrawal", "balance", "expected_balance", "balance_diff"]].head(5).to_string())

        # بررسی آیا همه mismatch ها به یک دلیل هستند
        avg_diff = mismatches["balance_diff"].mean()
        max_diff = mismatches["balance_diff"].max()
        print(f"\n  📈 میانگین تفاوت: {avg_diff:,.0f} ریال")
        print(f"  📈 حداکثر تفاوت: {max_diff:,.0f} ریال")

        # بررسی الگو: آیا تفاوت همیشه مثبت یا منفی است؟
        positive_diffs = (mismatches["balance_diff"] > 0).sum()
        print(f"  📈 تفاوت مثبت: {positive_diffs} / {len(mismatches)}")
    print("=" * 80 + "\n")

    report = {
        "total_rows": len(df),
        "mismatch_count": int(len(mismatches)),
        "mismatch_rows": mismatches[
            ["date", "time", "description", "source_page", "balance", "expected_balance"]
        ].to_dict("records"),
    }

    return df, report
