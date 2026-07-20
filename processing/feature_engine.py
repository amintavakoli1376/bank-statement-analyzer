import pandas as pd
import numpy as np


def _to_native(value):
    """تبدیل انواع numpy به انواع پایتون خالص برای سریالایز شدن صحیح در JSON."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value) if not np.isnan(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def compute_regularity(salary_df: pd.DataFrame) -> str:
    """چک منظم بودن واریزی‌های حقوق (فاصله ماهانه ~۳۰ روز)."""
    if salary_df.empty or "parsed_date" not in salary_df.columns:
        return "insufficient_data"
    valid_dates = salary_df["parsed_date"].dropna().sort_values()
    if len(valid_dates) < 2:
        return "insufficient_data"
    diffs = valid_dates.diff().dropna().apply(lambda x: x.days)
    if diffs.empty:
        return "insufficient_data"
    return "regular" if diffs.between(25, 35).all() else "irregular"


def compute_features(df: pd.DataFrame, business_margin_rate: float = 0.10) -> dict:
    """قدم ۳: تمام فیچرها با کد deterministic محاسبه می‌شوند، نه مدل.

    Args:
        df: دیتافریم تراکنش‌ها.
        business_margin_rate: نرخ حاشیه سود تجاری (پیش‌فرض ۱۰٪) برای تخمین سود کسب‌وکار.
    """
    if df.empty:
        return {"error": "no_transactions_found"}

    df = df.copy()

    # --- مرتب‌سازی بر اساس تاریخ (FIX 2) ---
    # اگر parsed_date وجود داشته باشه، دیتافریم رو صعودی sort می‌کنیم تا
    # opening_balance، closing_balance و محاسبات مبتنی بر ترتیب درست باشن.
    if "parsed_date" in df.columns:
        df = df.sort_values("parsed_date", ascending=True).reset_index(drop=True)

    # --- تبدیل امن به numeric (FIX 7) ---
    # اگر ستون‌های مالی به صورت رشته با جداکننده‌ی هزارگان باشن (مثل "1,000,000")،
    # جمع اشتباه محاسبه می‌شه. ابتدا کاما رو حذف می‌کنیم، سپس با pd.to_numeric و
    # errors="coerce" امن سازی می‌کنیم.
    for col in ["deposit", "withdrawal"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
    if "balance" in df.columns:
        df["balance"] = pd.to_numeric(
            df["balance"].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )

    df["deposit"] = df["deposit"].fillna(0)
    df["withdrawal"] = df["withdrawal"].fillna(0)

    features = {}

    # --- آمار موجودی ---
    has_balance = "balance" in df.columns and df["balance"].notna().any()
    features["avg_balance"] = df["balance"].mean() if has_balance else None
    features["min_balance"] = df["balance"].min() if has_balance else None
    features["max_balance"] = df["balance"].max() if has_balance else None
    # opening_balance و closing_balance حالا روی دیتافریم مرتب‌شده درست کار می‌کنن.
    features["opening_balance"] = df["balance"].iloc[0] if has_balance else None
    features["closing_balance"] = df["balance"].iloc[-1] if has_balance else None

    # --- روزهای منفی‌شدن موجودی ---
    if has_balance:
        neg_rows = df[df["balance"] < 0]
        if not neg_rows.empty:
            # FIX 4: به‌جای date (رشته)، از parsed_date.dt.date استفاده می‌کنیم تا
            # صرف‌نظر از فرمت رشته‌ای، روزهای یکتا به درستی شمارش بشن. اگر
            # parsed_date موجود نباشه، به date فال‌بک می‌کنیم.
            if "parsed_date" in neg_rows.columns:
                features["negative_balance_days_count"] = int(
                    neg_rows["parsed_date"].dt.date.nunique()
                )
            else:
                features["negative_balance_days_count"] = int(neg_rows["date"].nunique())
            # FIX 3: magnitude باید قدر مطلق منفی‌ترین موجودی باشه، نه خود عدد منفی.
            features["negative_balance_max_magnitude"] = float(
                abs(neg_rows["balance"].min())
            )
        else:
            features["negative_balance_days_count"] = 0
            features["negative_balance_max_magnitude"] = 0
    else:
        features["negative_balance_days_count"] = 0
        features["negative_balance_max_magnitude"] = 0

    # --- جمع واریز/برداشت و نسبت ---
    total_deposit = float(df["deposit"].sum())
    total_withdrawal = float(df["withdrawal"].sum())
    features["total_deposits"] = total_deposit
    features["total_withdrawals"] = total_withdrawal
    features["deposit_to_withdrawal_ratio"] = (
        round(total_deposit / total_withdrawal, 3) if total_withdrawal else None
    )

    # --- تشخیص واریزی حقوق ---
    salary_mask = df["description"].astype(str).str.contains("حقوق|salary", case=False, na=False, regex=True)
    salary_df = df[salary_mask]
    features["salary_deposits_detected"] = [float(x) for x in salary_df["deposit"].tolist()]
    features["avg_salary"] = float(salary_df["deposit"].mean()) if not salary_df.empty else None
    features["salary_regularity"] = compute_regularity(salary_df)

    # --- تشخیص تراکنش‌های غیرعادی (outlier) با روش IQR (FIX 6) ---
    amounts = df["deposit"] + df["withdrawal"]
    # تراکنش‌های صفر-صفر رو از محاسبه‌ی IQR خارج می‌کنیم تا توزیع منحرف نشه.
    nonzero_mask = ~((df["deposit"] == 0) & (df["withdrawal"] == 0))
    valid_amounts = amounts[nonzero_mask]
    if valid_amounts.notna().sum() >= 4:
        q1, q3 = valid_amounts.quantile([0.25, 0.75])
        iqr = q3 - q1
        lower_bound, upper_bound = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outlier_mask = (amounts < lower_bound) | (amounts > upper_bound)
        features["outlier_transactions"] = df[outlier_mask][
            ["date", "description", "deposit", "withdrawal"]
        ].to_dict("records")
        features["outlier_count"] = int(outlier_mask.sum())
    else:
        features["outlier_transactions"] = []
        features["outlier_count"] = 0

    # --- تفکیک ماهانه و درآمد/مخارج ---
    if "parsed_date" in df.columns and df["parsed_date"].notna().any():
        valid_dates = df["parsed_date"].dropna()

        df["month"] = valid_dates.apply(lambda d: d.strftime("%Y-%m") if pd.notna(d) else None)
        monthly = df.dropna(subset=["month"]).groupby("month").agg(
            total_deposit=("deposit", "sum"),
            total_withdrawal=("withdrawal", "sum"),
            avg_balance=("balance", "mean"),
        )
        features["monthly_breakdown"] = {
            month: {k: _to_native(v) for k, v in row.to_dict().items()}
            for month, row in monthly.iterrows()
        }

        # FIX 5: n_months بر اساس مدت زمان واقعی داده (داینامیک).
        # به‌جای تعداد ماه‌های تقویمی، تعداد روزهای واقعی داده رو محاسبه می‌کنیم
        # و بر 30.44 (میانگین روز در یک ماه) تقسیم می‌کنیم.
        # مثال: داده 23 خرداد تا 16 تیر = 23 روز ≈ 0.76 ماه
        min_date = valid_dates.min()
        max_date = valid_dates.max()
        date_range_days = (max_date - min_date).days + 1
        # 30.44 = میانگین روز در یک ماه تقویمی (365.25/12)
        n_months = max(date_range_days / 30.44, 1)
        features["date_range_days"] = int(date_range_days)
        features["n_months_used"] = round(n_months, 2)

        if not salary_df.empty:
            salary_monthly = salary_df.groupby(
                salary_df["parsed_date"].apply(lambda d: d.strftime("%Y-%m"))
            )["deposit"].sum()
            # FIX 1: avg_monthly_income حالا با همون مبنای n_months محاسبه می‌شه که
            # avg_monthly_expenses. مجموع حقوق‌ها / تعداد کل ماه‌ها، نه میانگین
            # ماه‌هایی که حقوق واریز شده. این باعث می‌شه net_monthly_surplus معنی‌دار باشه.
            features["avg_monthly_income"] = float(salary_monthly.sum() / n_months)
        else:
            features["avg_monthly_income"] = None

        features["avg_monthly_expenses"] = float(total_withdrawal / n_months)
        features["net_monthly_surplus"] = (
            features["avg_monthly_income"] - features["avg_monthly_expenses"]
            if features["avg_monthly_income"] is not None else None
        )

        # --- فیچرهای جدید ---
        pos_keywords = "پایانه فروش|خرید|POS|درگاه"
        pos_mask = df["description"].astype(str).str.contains(pos_keywords, case=False, na=False, regex=True)
        features["pos_purchases_total"] = float(df.loc[pos_mask, "withdrawal"].sum())

        b2b_keywords = "پایا|ساتنا|پل|شبا"
        b2b_mask = df["description"].astype(str).str.contains(b2b_keywords, case=False, na=False, regex=True)
        features["b2b_transfers_total"] = float(df.loc[b2b_mask, "withdrawal"].sum())

        # --- monthly_avg_turnover ---
        features["monthly_avg_turnover"] = round(total_deposit / n_months, 3) if n_months else None

        # --- estimated_business_profit (کاملاً داینامیک) ---
        if salary_df.empty:
            features["estimated_business_profit"] = round(
                features["monthly_avg_turnover"] * business_margin_rate, 3
            ) if features["monthly_avg_turnover"] is not None else None
        else:
            features["estimated_business_profit"] = None

    else:
        features["monthly_breakdown"] = {}
        features["avg_monthly_income"] = None
        features["avg_monthly_expenses"] = None
        features["net_monthly_surplus"] = None
        features["pos_purchases_total"] = 0.0
        features["b2b_transfers_total"] = 0.0
        features["monthly_avg_turnover"] = None
        features["estimated_business_profit"] = None

    return {
        k: (_to_native(v) if not isinstance(v, (list, dict)) else v)
        for k, v in features.items()
    }
