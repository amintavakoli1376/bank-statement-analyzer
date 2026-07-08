import json
from utils.api_client import call_llm
import config

NARRATIVE_PROMPT_TEMPLATE = """
شما یک تحلیل‌گر ارشد ریسک اعتباری بانکی هستید.
بر اساس داده‌های ساخت‌یافته و فیچرهای از پیش محاسبه‌شده‌ی زیر (که با کد قطعی از روی صورتحساب واقعی
استخراج شده‌اند، نه حدس مدل)، یک تحلیل ریسک/نکول بنویسید.

نام صاحب حساب: {account_holder_name}

فیچرهای مالی محاسبه‌شده:
{features_json}

گزارش کیفیت داده (فقط برای آگاهی از محدودیت‌های احتمالی؛ در متن تحلیل فقط در صورت مهم بودن اشاره کنید):
{quality_report_json}

خروجی را دقیقاً و فقط به‌صورت یک JSON معتبر با ساختار زیر برگردانید، بدون Markdown و بدون توضیح اضافه:

{{
    "avg_monthly_income": "میانگین درآمد ماهیانه به ریال (رشته با کاما)",
    "avg_monthly_expenses": "میانگین مخارج ماهیانه به ریال (رشته با کاما)",
    "net_monthly_surplus": "میانگین مازاد ماهیانه به ریال (رشته با کاما)",
    "recommended_max_installments": {{
        "low_risk_tier": "حداکثر قسط پیشنهادی با فرض آستانه ریسک پایین (محافظه‌کارانه) به ریال (رشته با کاما)",
        "medium_risk_tier": "حداکثر قسط پیشنهادی با فرض آستانه ریسک متوسط (متعادل) به ریال (رشته با کاما)",
        "high_risk_tier": "حداکثر قسط پیشنهادی با فرض آستانه ریسک بالا (جسورانه) به ریال (رشته با کاما)"
    }},
    "final_assessed_risk": "سطح ریسک نهایی ارزیابی‌شده برای این شخص بر اساس رفتار مالی فعلی (Low یا Medium یا High)",
    "financial_analysis_fa": "تحلیل تفصیلی فارسی شامل نام صاحب حساب، روند موجودی، منظم بودن واریزی حقوق، تراکنش‌های غیرعادی و منطق محاسباتی پشت ارقام پیشنهادی برای هر سه سطح ریسک"
}}
"""


def _clean_json_response(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def generate_narrative(features: dict, quality_report: dict, account_holder_name: str, api_key: str) -> dict:
    """قدم ۴: تحلیل کیفی نهایی، فقط با ورودی فشرده (نه متن خام PDF)."""
    prompt = NARRATIVE_PROMPT_TEMPLATE.format(
        account_holder_name=account_holder_name or "نامشخص",
        features_json=json.dumps(features, ensure_ascii=False, indent=2, default=str),
        quality_report_json=json.dumps(quality_report, ensure_ascii=False, indent=2, default=str),
    )

    raw_response = call_llm(
        prompt=prompt,
        api_key=api_key,
        model=config.NARRATIVE_MODEL,
        temperature=0.0,
    )

    return json.loads(_clean_json_response(raw_response))