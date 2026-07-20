import json
from utils.api_client import call_llm
import config

NARRATIVE_PROMPT_TEMPLATE = """
شما یک تحلیل‌گر ارشد ریسک اعتباری بانکی هستید.
بر اساس داده‌های ساخت‌یافته و فیچرهای از پیش محاسبه‌شده‌ی زیر (با کد قطعی از روی صورتحساب واقعی
استخراج شده‌اند، نه حدس مدل)، یک تحلیل ریسک/نکول بنویسید.

نام صاحب حساب: {account_holder_name}

نوع حساب شناسایی‌شده: {account_type}
تحلیل تخصصی اولیه: {specialized_analysis_json}

فیچرهای مالی محاسبه‌شده:
{features_json}

گزارش کیفیت داده (فقط برای آگاهی از محدودیت‌های احتمالی؛ در متن تحلیل فقط در صورت مهم بودن اشاره کنید):
{quality_report_json}

خروجی را دقیقاً و فقط به‌صورت یک JSON معتبر با ساختار زیر برگردانید، بدون Markdown و بدون توضیح اضافه:

{{
    "avg_monthly_income": "میانگین درآمد ماهانه به ریال (رشته با کاما)",
    "avg_monthly_expenses": "میانگین مخارج ماهانه به ریال (رشته با کاما)",
    "net_monthly_surplus": "میانگین مازاد ماهانه به ریال (رشته با کاما)",
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

    # اگر پاسخ شامل بک‌تیک بود، محتوای بین اون‌ها رو استخراج کن
    if "```" in text:
        # پیدا کردن اولین بک‌تیک و بعدی
        first = text.index("```")
        after_first = text[first + 3:]
        # حذف کلمه json یا ... از ابتدای محتوا
        if after_first.lower().startswith("json"):
            after_first = after_first[4:].lstrip("\n")
        second = after_first.find("```")
        if second != -1:
            text = after_first[:second].strip()
        else:
            # اگر بک‌تیک بسته‌نشده، محتوا تا انتهای متن
            text = after_first.strip()

    return text.strip()


def generate_narrative(
    features: dict,
    quality_report: dict,
    account_holder_name: str,
    api_key: str,
    routing_result: dict | None = None,
) -> dict:
    """قدم ۵: تحلیل کیفی نهایی با استفاده از خروجی Two-Step Routing.

    Args:
        features: دیکشنری فیچرهای مالی.
        quality_report: گزارش کیفیت داده.
        account_holder_name: نام صاحب حساب.
        api_key: API Key OpenRouter.
        routing_result: خروجی route_and_analyze شامل account_type و analysis تخصصی.
    """
    if routing_result:
        specialized_analysis_json = json.dumps(
            routing_result.get("analysis", {}), ensure_ascii=False, indent=2, default=str,
        )
        account_type_label = {
            "BUSINESS": "تجاری (Business)",
            "SALARIED": "حقوق‌بگیر (Salaried)",
            "PERSONAL": "شخصی (Personal)",
        }.get(routing_result.get("account_type", ""), "نامشخص")
    else:
        specialized_analysis_json = "در دسترس نیست"
        account_type_label = "تشخیص‌داده‌نشده"

    prompt = NARRATIVE_PROMPT_TEMPLATE.format(
        account_holder_name=account_holder_name or "نامشخص",
        account_type=account_type_label,
        specialized_analysis_json=specialized_analysis_json,
        features_json=json.dumps(features, ensure_ascii=False, indent=2, default=str),
        quality_report_json=json.dumps(quality_report, ensure_ascii=False, indent=2, default=str),
    )

    print(f"📝 [narrative] تولید تحلیل نهایی: مدل={config.NARRATIVE_MODEL}")

    raw_response = call_llm(
        prompt=prompt,
        api_key=api_key,
        model=config.NARRATIVE_MODEL,
        temperature=0.2,
    )

    return json.loads(_clean_json_response(raw_response))