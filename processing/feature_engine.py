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


def compute_features(df: pd.DataFrame) -> dict:
    """قدم ۳: تمام فیچرها با کد deterministic محاسبه می‌شوند، نه مدل."""
    if df.empty:
        return {"error": "no_transactions_found"}

    df = df.copy()
    df["deposit"] = df["deposit"].fillna(0)
    df["withdrawal"] = df["withdrawal"].fillna(0)

    features = {}

    # --- آمار موجودی ---
    has_balance = "balance" in df.columns and df["balance"].notna().any()
    features["avg_balance"] = df["balance"].mean() if has_balance else None
    features["min_balance"] = df["balance"].min() if has_balance else None
    features["max_balance"] = df["balance"].max() if has_balance else None
    features["opening_balance"] = df["balance"].iloc[0] if has_balance else None
    features["closing_balance"] = df["balance"].iloc[-1] if has_balance else None

    # --- روزهای منفی‌شدن موجودی ---
    if has_balance:
        neg_rows = df[df["balance"] < 0]
        features["negative_balance_days_count"] = int(neg_rows["date"].nunique()) if not neg_rows.empty else 0
        features["negative_balance_max_magnitude"] = float(neg_rows["balance"].min()) if not neg_rows.empty else 0
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

    # --- تشخیص تراکنش‌های غیرعادی (outlier) با روش IQR ---
    amounts = df["deposit"] + df["withdrawal"]
    if amounts.notna().sum() >= 4:
        q1, q3 = amounts.quantile([0.25, 0.75])
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
        df["month"] = df["parsed_date"].apply(lambda d: d.strftime("%Y-%m") if pd.notna(d) else None)
        monthly = df.dropna(subset=["month"]).groupby("month").agg(
            total_deposit=("deposit", "sum"),
            total_withdrawal=("withdrawal", "sum"),
            avg_balance=("balance", "mean"),
        )
        features["monthly_breakdown"] = {
            month: {k: _to_native(v) for k, v in row.to_dict().items()}
            for month, row in monthly.iterrows()
        }

        if not salary_df.empty:
            salary_monthly = salary_df.groupby(
                salary_df["parsed_date"].apply(lambda d: d.strftime("%Y-%m"))
            )["deposit"].sum()
            features["avg_monthly_income"] = float(salary_monthly.mean())
        else:
            features["avg_monthly_income"] = None

        n_months = max(monthly.shape[0], 1)
        features["avg_monthly_expenses"] = float(total_withdrawal / n_months)
        features["net_monthly_surplus"] = (
            features["avg_monthly_income"] - features["avg_monthly_expenses"]
            if features["avg_monthly_income"] is not None else None
        )
    else:
        features["monthly_breakdown"] = {}
        features["avg_monthly_income"] = None
        features["avg_monthly_expenses"] = None
        features["net_monthly_surplus"] = None

    return {
        k: (_to_native(v) if not isinstance(v, (list, dict)) else v)
        for k, v in features.items()
    }