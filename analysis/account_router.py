"""Two-Step LLM Routing for bank account type classification and analysis.

Step 1 (Classifier): Sends features_dict to an LLM to classify the account type
                     as one of: BUSINESS, SALARIED, or PERSONAL.
Step 2 (Specialized Analyzer): Routes to the appropriate analysis function
                               based on the classifier output.
"""
import json
from typing import Optional

from utils.api_client import call_llm
import config


# ═══════════════════════════════════════════════════════════════════════
# ── PLACEHOLDER — متن پرامپت‌ها را خودت جایگزین کن ─────────────────
# ═══════════════════════════════════════════════════════════════════════

CLASSIFIER_SYSTEM_PROMPT = """
شما یک سیستم طبقه‌بندی حساب بانکی هستید.
بر اساس فیچرهای مالی زیر، نوع این حساب را تشخیص دهید:
{features_json}

قوانین تشخیص:
- اگر متغیر salary_deposits_detected دارای مقادیر بود -> خروجی: SALARIED
- اگر حقوقی یافت نشد اما monthly_avg_turnover بسیار بالا بود (مثلاً بالای ۵۰۰ میلیون ریال) و تراکنش‌های b2b_transfers_total زیاد بود -> خروجی: BUSINESS
- اگر حقوقی یافت نشد و گردش مالی هم پایین بود -> خروجی: PERSONAL

شما باید فقط و فقط یک کلمه خروجی دهید (بدون هیچ متن اضافه‌ای):
SALARIED یا BUSINESS یا PERSONAL
""".strip()

BUSINESS_ANALYSIS_PROMPT = """
شما یک تحلیل‌گر ارشد ریسک اعتباری برای کسب‌وکارهای خرد (SME) هستید.

قوانین جدید محاسبه توان بازپرداخت (بسیار مهم):
مدل‌های سنتی بانکی، توان بازپرداخت را فقط کسری از "سود خالص" می‌دانند؛ شما نباید این‌گونه عمل کنید. 
در کسب‌وکارهای تجاری، بخش بزرگی از "مخارج و حواله‌های خروجی" در واقع هزینه‌های مصرفی نیستند، بلکه جابه‌جایی نقدینگی و خرید موجودی کالا هستند. 
بنابراین، پتانسیل پرداخت مشتری باید ترکیبی از دو عامل زیر باشد:
۱. درصدی از سود تخمینی خالص
۲. به علاوه "ظرفیت پنهان تراکنشی": یعنی درصدی از میانگین خروجی‌ها/مخارج ماهانه (مثلاً ۵ تا ۱۵ درصد از کل خروجی‌ها می‌تواند به راحتی به سمت پرداخت قسط هدایت شود).
بر این اساس، در حساب‌های پرگردش، مبلغ قسط پیشنهادی (به ویژه در سناریوی جسورانه) می‌تواند حتی با کل سود خالص برابر یا از آن بیشتر باشد، زیرا از محل چرخش نقدینگی تامین می‌شود نه فقط سود.

قوانین نگارش خروجی متنی (financial_analysis_fa):
- اکیداً ممنوع: استفاده از هرگونه کلماتی مانند "درصد"، "تخصیص"، "ضریب" و اشاره به نحوه محاسبه ریاضی در متن.
- در این فیلد فقط مبالغ نهایی را اعلام کنید و دلیل بالا بودن این مبالغ را "حجم بالای گردش مالی"، "رسوب پول" و "پویایی و تکرار حواله‌ها/خریدها" توجیه کنید.

فیچرهای مالی:
{features_json}

خروجی را فقط به صورت JSON زیر برگردانید:
{{
  "_reasoning_and_math": "فضای تفکر تحلیلی شما. ابتدا در اینجا محاسبه کنید که چگونه درصدی از 'کل مخارج/خروجی‌ها' را به عنوان ظرفیت پنهان در نظر گرفتید و با سود ترکیب کردید تا به اعداد بالاتری برای اقساط برسید.",
  "account_type": "Business",
  "avg_monthly_turnover": "میانگین گردش مالی ماهیانه به ریال",
  "estimated_monthly_profit": "سود خالص تخمینی ماهیانه به ریال",
  "transactional_power_score": "امتیاز از ۱ تا ۱۰",
  "recommended_max_installments": {{
    "low_risk_tier": "قسط پیشنهادی (ترکیب سود + سهم کوچکی از گردش خروجی)",
    "medium_risk_tier": "قسط متعادل",
    "high_risk_tier": "قسط جسورانه (متکی بر بالاترین ظرفیت جابه‌جایی نقدینگی)"
  }},
  "final_assessed_risk": "Low یا Medium یا High",
  "financial_analysis_fa": "متن نهایی، روان و حرفه‌ای. بدون هیچ‌گونه عدد درصدی و فرمول ریاضی (طبق قوانین نگارش)."
}}
""".strip()

SALARIED_ANALYSIS_PROMPT = """
شما یک تحلیل‌گر ارشد ریسک اعتباری برای اشخاص حقیقی هستید.
این یک حساب "حقوق‌بگیر" است. در این حساب‌ها، نظم واریز حقوق و میزان "مازاد درآمد بر مخارج (Surplus)" مهم‌ترین معیار برای تعیین توان بازپرداخت اقساط است.

فیچرهای مالی:
{features_json}

خروجی را فقط به صورت JSON زیر برگردانید:
{{
    "account_type": "Salaried",
    "avg_monthly_salary": "میانگین حقوق ماهیانه به ریال",
    "net_monthly_surplus": "میانگین مازاد ماهیانه به ریال",
    "salary_regularity_status": "وضعیت منظم بودن حقوق",
    "transactional_power_score": "امتیاز از ۱ تا ۱۰",
    "recommended_max_installments": {{
        "low_risk_tier": "قسط پیشنهادی محافظه‌کارانه (حداکثر 30 درصد حقوق) به ریال",
        "medium_risk_tier": "قسط پیشنهادی متعادل (حداکثر 50 درصد حقوق) به ریال",
        "high_risk_tier": "قسط پیشنهادی جسورانه (حداکثر 70 درصد حقوق) به ریال"
    }},
    "final_assessed_risk": "Low یا Medium یا High",
    "financial_analysis_fa": "تحلیل فارسی شامل بررسی نظم حقوق، میزان مازاد حساب و توانایی فرد در پرداخت اقساط بدون فشار مالی."
}}
""".strip()

PERSONAL_ANALYSIS_PROMPT = """
شما یک تحلیل‌گر ارشد ریسک اعتباری برای اشخاص حقیقی هستید.
این یک حساب "شخصی" است. در این حساب‌ها، میزان درآمد، مخارج و مازاد حساب مهم‌ترین معیار برای تعیین توان بازپرداخت اقساط است.

فیچرهای مالی:
{features_json}

خروجی را فقط به صورت JSON زیر برگردانید:
{{
    "account_type": "Personal",
    "avg_monthly_income": "میانگین درآمد ماهیانه به ریال",
    "avg_monthly_expenses": "میانگین مخارج ماهیانه به ریال",
    "net_monthly_surplus": "میانگین مازاد ماهیانه به ریال",
    "transactional_power_score": "امتیاز از ۱ تا ۱۰",
    "recommended_max_installments": {{
        "low_risk_tier": "قسط پیشنهادی محافظه‌کارانه (ریال)",
        "medium_risk_tier": "قسط پیشنهادی متعادل (ریال)",
        "high_risk_tier": "قسط پیشنهادی جسورانه (ریال)"
    }},
    "final_assessed_risk": "Low یا Medium یا High",
    "financial_analysis_fa": "تحلیل فارسی شامل بررسی الگوی درآمدی، ثبات مالی و توان بازپرداخت اقساط."
}}
""".strip()


# ═══════════════════════════════════════════════════════════════════════
# ── گام اول: Classifier ──────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════

def classify_account(
    features: dict,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.0,
) -> str:
    """گام اول: نوع حساب را با LLM به BUSINESS / SALARIED / PERSONAL طبقه‌بندی کن.

    Args:
        features: دیکشنری فیچرهای مالی (خروجی compute_features).
        api_key: API key OpenRouter (پیش‌فرض از config).
        model: نام مدل (پیش‌فرض از config.NARRATIVE_MODEL).
        temperature: دمای مدل (پیش‌فرض 0.0 برای پاسخ deterministic).

    Returns:
        یکی از سه رشته: "BUSINESS", "SALARIED", "PERSONAL".
        در صورت خطا مقدار پیش‌فرض "PERSONAL" برمی‌گرداند.
    """
    api_key = api_key or config.OPENROUTER_API_KEY
    model = model or config.NARRATIVE_MODEL

    print(f"🔍 [router] classify_account: مدل={model}")

    prompt = CLASSIFIER_SYSTEM_PROMPT.format(
        features_json=json.dumps(features, ensure_ascii=False, indent=2, default=str),
    )

    try:
        raw = call_llm(prompt=prompt, api_key=api_key, model=model, temperature=temperature)
        raw = raw.strip().upper()

        # استخراج کلمه کلیدی از پاسخ مدل
        for keyword in ("BUSINESS", "SALARIED", "PERSONAL"):
            if keyword in raw:
                return keyword

        # fallback: اگر مدل چیزی خارج از سه کلمه برگرداند
        return "PERSONAL"

    except Exception:
        return "PERSONAL"


# ═══════════════════════════════════════════════════════════════════════
# ── توابع تحلیل تخصصی هر نوع حساب ────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════

def analyze_business_account(
    features: dict,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """تحلیل حساب تجاری (BUSINESS)."""
    api_key = api_key or config.OPENROUTER_API_KEY
    model = model or config.NARRATIVE_MODEL

    print(f"🧠 [router] analyze_business_account: مدل={model}")
    prompt = BUSINESS_ANALYSIS_PROMPT.format(
        features_json=json.dumps(features, ensure_ascii=False, indent=2, default=str),
    )

    raw = call_llm(prompt=prompt, api_key=api_key, model=model, temperature=0.3)
    return _parse_llm_response(raw)


def analyze_salaried_account(
    features: dict,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """تحلیل حساب کارمندی (SALARIED)."""
    api_key = api_key or config.OPENROUTER_API_KEY
    model = model or config.NARRATIVE_MODEL

    print(f"🧠 [router] analyze_salaried_account: مدل={model}")
    prompt = SALARIED_ANALYSIS_PROMPT.format(
        features_json=json.dumps(features, ensure_ascii=False, indent=2, default=str),
    )

    raw = call_llm(prompt=prompt, api_key=api_key, model=model, temperature=0.3)
    return _parse_llm_response(raw)


def analyze_personal_account(
    features: dict,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """تحلیل حساب شخصی (PERSONAL)."""
    api_key = api_key or config.OPENROUTER_API_KEY
    model = model or config.NARRATIVE_MODEL

    print(f"🧠 [router] analyze_personal_account: مدل={model}")
    prompt = PERSONAL_ANALYSIS_PROMPT.format(
        features_json=json.dumps(features, ensure_ascii=False, indent=2, default=str),
    )

    raw = call_llm(prompt=prompt, api_key=api_key, model=model, temperature=0.3)
    return _parse_llm_response(raw)


# ═══════════════════════════════════════════════════════════════════════
# ── گام دوم: Specialized Router ──────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════

ACCOUNT_TYPE_ANALYZERS = {
    "BUSINESS": analyze_business_account,
    "SALARIED": analyze_salaried_account,
    "PERSONAL": analyze_personal_account,
}


def route_and_analyze(
    features: dict,
    api_key: Optional[str] = None,
    classifier_model: Optional[str] = None,
    analyzer_model: Optional[str] = None,
    temperature: float = 0.0,
) -> dict:
    """گام دوم: بر اساس خروجی Classifier، به تحلیلگر تخصصی هدایت کن.

    Args:
        features: دیکشنری فیچرهای مالی.
        api_key: API Key OpenRouter.
        classifier_model: مدل مرحله Classification.
        analyzer_model: مدل مرحله تحلیل تخصصی.
        temperature: دمای مدل در مرحله Classification (پیش‌فرض 0.0).

    Returns:
        dict شامل:
          - account_type:  BUSINESS / SALARIED / PERSONAL
          - analysis: خروجی تحلیل تخصصی (dict)
    """
    account_type = classify_account(
        features=features,
        api_key=api_key,
        model=classifier_model,
        temperature=temperature,
    )

    analyzer = ACCOUNT_TYPE_ANALYZERS.get(account_type, analyze_personal_account)
    analysis = analyzer(features=features, api_key=api_key, model=analyzer_model)

    return {
        "account_type": account_type,
        "analysis": analysis,
    }


# ═══════════════════════════════════════════════════════════════════════
# ── Helper ────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════

def _parse_llm_response(raw_text: str) -> dict:
    """تبدیل متن پاسخ LLM به دیکشنری، با پشتیبانی از Markdown code block."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_response": text, "parse_error": "JSON decoding failed"}