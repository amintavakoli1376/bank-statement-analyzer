import streamlit as st
import pdfplumber
import re
import json
from google import genai
import os
from dotenv import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# PROXY_URL = "http://127.0.0.1:10808"

# os.environ['HTTP_PROXY'] = PROXY_URL
# os.environ['HTTPS_PROXY'] = PROXY_URL


# --- تنظیمات صفحه استریم‌لیت ---
st.set_page_config(page_title="تحلیل‌گر صورتحساب بانکی", page_icon="📊", layout="wide")
hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    # /* مخفی کردن دکمه‌ها و منوی شناور پایین سمت راست */
    .stAppDeployButton {display: none !important;}
    [data-testid="stStatusWidget"] {visibility: hidden;}
    .stAppViewerToolbar {display: none !important;}
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# استایل برای راست‌چین کردن متن‌های فارسی
# استایل جامع برای راست‌چین کردن کامل و کنترل طول کامپوننت‌ها
st.markdown("""
    <style>
    /* راست‌چین کردن کل بدنه اپلیکیشن */
    .main .block-container {
        direction: rtl !important;
        text-align: right !important;
    }
    
    /* استایل فونت فارسی و چینش متن */
    h1, h2, h3, h4, h5, h6, p, label, .stMarkdown, .stSelectbox, .stButton, div {
        font-family: 'Tahoma', 'Vazir', Arial, sans-serif !important;
        text-align: right !important;
    }
    
    /* اصلاح جهت فلش‌ها و متن متون در پاپ‌آپ‌ها و اکسپندرها */
    .stExpander, .stAlert {
        direction: rtl !important;
        text-align: right !important;
    }
    
    /* راست‌چین کردن باکس‌های متصدی اطلاعات مالی (Metrics) */
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
        text-align: right !important;
        direction: rtl !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- توابع پردازشی ---
def extract_and_clean_pdf(pdf_file):
    """استخراج متن از PDF آپلود شده و ماسک کردن اطلاعات حساس"""
    full_text = ""
    # استریم‌لیت فایل آپلود شده را به صورت یک شیء فایل‌مانند برمی‌گرداند که pdfplumber می‌تواند آن را بخواند
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    # ماسک کردن شماره کارت‌ها
    cleaned_text = re.sub(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b', '*-****-****-****', full_text)
    return cleaned_text

def analyze_bank_statement(statement_text, api_key):
    """ارسال متن به هوش مصنوعی و دریافت خروجی"""
    client = genai.Client(api_key=api_key)

    prompt = f"""
    You are an expert financial risk analyst. Analyze this 3-month bank statement written in Persian/English.
    Calculate the user's financial health and determine how much monthly loan installment (قسط ماهانه) they can safely afford.

    CRITICAL ALGORITHM FOR CHRONOLOGY & VALUES:
    1. DETIMATE ACCOUNT HOLDER:
    - Identify the real account holder's name from the document header and use it in the final analysis. Do NOT reuse names from your training or previous prompts.
    2. DETERMINE THE SORTING DIRECTION:
    - Read the first 3 rows and the last 3 rows of the transaction ledger. Determine if the dates are in Ascending (oldest to newest) or Descending (newest to oldest) order.
    3. DYNAMIC OPENING BALANCE & START DATE:
    - If the statement is Descending (newest at the top): Go to the ABSOLUTE LAST row of the transaction table (the very bottom of the last page). Extract the exact date, time, and the remaining 'Balance' (مانده) of that specific last row. This is your strictly verified "opening_balance" and start date.
    - If the statement is Ascending (oldest at the top): Extract the date, time, and 'Balance' of the VERY FIRST row of the transaction table.
    4. DYNAMIC CLOSING BALANCE & END DATE:
    - Locate the most recent transaction row chronologically. Extract its exact date and the 'Balance' (مانده) value. This is your "closing_balance".
    - Do NOT just hallucinate or guess these numbers. They must match the exact cell values of the ultimate start/end rows.

    IN-DEPTH INCOME ANALYSIS:
    - Scan the entire description ("توضیحات") column. Find all rows containing the word "حقوق" or "Salary" or clear monthly corporate deposits.
    - For the final "avg_monthly_income", calculate the exact mathematical average of ONLY these verified salary items. If a month has no salary, factor it into the 3-month average accurately.

    You MUST return the response ONLY as a valid JSON object in the following format. Do not include any markdown formatting like ```json or text outside the JSON. All numbers inside the values must be clean strings with commas for readability.

    {{
        "total_deposits_3_months": "مجموع واریزی‌های سه ماه موجود در هدر یا جمع ردیف‌ها به ریال",
        "total_withdrawals_3_months": "مجموع برداشت‌های سه ماه موجود در هدر یا جمع ردیف‌ها به ریال",
        "opening_balance": "مانده دقیق ردیف آغازین دوره بر اساس الگوریتم بالا به ریال",
        "closing_balance": "مانده دقیق ردیف پایانی دوره بر اساس الگوریتم بالا به ریال",
        "avg_monthly_income": "میانگین ریاضی درآمد ماهیانه فقط از روی واریزی‌های مستمر و حقوق واقعی این فایل به ریال",
        "avg_monthly_expenses": "میانگین مخارج ماهیانه واقعی این فایل به ریال",
        "net_monthly_surplus": "میانگین پس‌انداز یا مازاد مالی واقعی در هر ماه به ریال",
        "recommended_max_installment": "حداکثر مبلغ قسط پیشنهادی بر اساس تحلیل این فایل به ریال",
        "risk_score": "سطح ریسک اعتباری: Low یا Medium یا High",
        "financial_analysis_fa": "تحلیل دقیق وضعیت گردش حساب جدید با ذکر نام صاحب حساب فعلی، توالی زمانی دقیق (تاریخ اولین تراکنش فایل جدید تا تاریخ آخرین تراکنش آن و تغییر مانده از ابتدا تا انتها)، ذکر مبالغ واریزی‌های مستمر پیدا شده در این فایل و علت تعیین این مبلغ قسط به زبان فارسی"
    }}

    Bank Statement Content:
    {statement_text}
    """

    response = client.models.generate_content(
        model="gemini-3.5-flash", 
        contents=prompt
    )
    
    return response.text

# --- رابط کاربری (UI) ---
st.title("📊 تحلیل‌گر هوشمند ریسک اعتباری و صورتحساب بانکی")
st.write("این برنامه با استفاده از هوش مصنوعی گوگل، صورتحساب بانکی شما را تحلیل کرده و توانایی پرداخت قسط را می‌سنجد")

st.markdown("---")

# کنترل طول کامپوننت آپلود با استفاده از ستون‌بندی (قرارگیری در مرکز صفحه با عرض مناسب)
col_space1, col_input, col_space2 = st.columns([1, 2, 1])

with col_input:
    uploaded_file = st.file_uploader("فایل صورتحساب بانکی خود را آپلود کنید (فرمت PDF)", type=["pdf"])
    
    # دکمه اجرای تحلیل با سایز کنترل‌شده و هماهنگ
    submit_button = st.button("🚀 شروع تحلیل و پردازش ", use_container_width=True)

# بخش پردازش پس از فشردن دکمه
if submit_button:
    if not GEMINI_API_KEY:
        st.error("⚠️ کلید API تنظیم نشده است! لطفاً فایل .env یا تنظیمات Secrets سرور را بررسی کنید.")
    elif not uploaded_file:
        st.warning("⚠️ لطفاً ابتدا یک فایل PDF آپلود کنید.")
    else:
        try:
            with st.spinner("⏳ در حال استخراج متن از PDF..."):
                extracted_text = extract_and_clean_pdf(uploaded_file)
            
            with st.spinner("🧠 در حال تحلیل مالی توسط هوش مصنوعی..."):
                result_str = analyze_bank_statement(extracted_text, GEMINI_API_KEY)
                
                clean_json_str = result_str.strip()
                if clean_json_str.startswith("```json"):
                    clean_json_str = clean_json_str[7:]
                if clean_json_str.endswith("```"):
                    clean_json_str = clean_json_str[:-3]
                
                final_result = json.loads(clean_json_str)
            
            st.success("✅ تحلیل با موفقیت انجام شد!")
            
            st.markdown("### 📋 خلاصه وضعیت مالی گردش حساب")
            
            # نمایش کارت‌های شاخص مالی در جهت راست به چپ
            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("درآمد ماهیانه (تخمینی مستمر)", final_result.get("avg_monthly_income", "-"))
            m_col2.metric("مخارج ماهیانه (تخمینی)", final_result.get("avg_monthly_expenses", "-"))
            m_col3.metric("مازاد مالی (پس‌انداز واقعی)", final_result.get("net_monthly_surplus", "-"))
            
            st.write("") # فاصله مجازی
            
            m_col4, m_col5 = st.columns(2)
            m_col4.metric("حداکثر قسط پیشنهادی قابل پرداخت", final_result.get("recommended_max_installment", "-"))
            
            risk = final_result.get("risk_score", "Unknown")
            risk_color = "green" if risk == "Low" else "orange" if risk == "Medium" else "red"
            m_col5.markdown(f"<div style='background-color:#f9f9f9; padding: 15px; border-radius: 5px; border-right: 5px solid {risk_color};'><b>سطح ریسک اعتباری:</b> <span style='color:{risk_color}; font-size:24px; font-weight:bold;'>{risk}</span></div>", unsafe_allow_html=True)
            
            st.markdown("---")
            st.markdown("### 📝 گزارش تفصیلی هوش مصنوعی:")
            
            # نمایش متن تحلیل فارسی به صورت کاملاً RTL در یک باکس متناسب
            analysis_text = final_result.get("financial_analysis_fa", "تحلیلی یافت نشد.")
            st.info(analysis_text)
            
            with st.expander("نمایش داده‌های خام استخراج‌شده (JSON)"):
                st.json(final_result)
                
        except json.JSONDecodeError:
            st.error("❌ خطایی در خواندن ساختار خروجی مدل رخ داد. لطفاً مجدداً تلاش کنید.")
        except Exception as e:
            st.error(f"❌ خطای سیستمی: {e}")