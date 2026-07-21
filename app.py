import streamlit as st
import json
import asyncio

import config
from extractors.pdf_splitter import extract_page_data, split_pages_with_context, compute_file_hash
from extractors.llm_extractor import extract_all_pages
from processing.merger import run_merge_pipeline
from processing.validator import verify_balance_continuity
from processing.feature_engine import compute_features
from analysis.narrative_llm import generate_narrative
from analysis.account_router import route_and_analyze
from db.session import init_db, AsyncSessionLocal
from db import crud as db_crud
from storage import minio_client as storage_client
import faulthandler
faulthandler.enable()

# --- تنظیمات صفحه استریم‌لیت ---
st.set_page_config(page_title="تحلیل‌گر صورتحساب بانکی", page_icon="📊", layout="wide")

hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stAppDeployButton {display: none !important;}
    [data-testid="stStatusWidget"] {visibility: hidden;}
    .stAppViewerToolbar {display: none !important;}
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

st.markdown("""
    <style>
    .main .block-container { direction: rtl !important; text-align: right !important; }
    h1, h2, h3, h4, h5, h6, p, label, .stMarkdown, .stSelectbox, .stButton, div {
        font-family: 'Tahoma', 'Vazir', Arial, sans-serif !important;
        text-align: right !important;
    }
    .stExpander, .stAlert { direction: rtl !important; text-align: right !important; }
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
        text-align: right !important; direction: rtl !important;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📊 تحلیل‌گر هوشمند ریسک اعتباری و صورتحساب بانکی")
st.write("این نسخه با معماری Chunk-based Processing، صورتحساب‌های چند صفحه‌ای را صفحه‌به‌صفحه پردازش می‌کند تا هیچ تراکنشی از قلم نیفتد.")

# نمایش تنظیمات فعلی
print(f"\n⚙️ [config] EXTRACTION_MODEL = {config.EXTRACTION_MODEL}")
print(f"⚙️ [config] NARRATIVE_MODEL = {config.NARRATIVE_MODEL}")
print(f"⚙️ [config] PAGES_PER_CHUNK = {config.PAGES_PER_CHUNK}")
print(f"⚙️ [config] MAX_IMAGES_PER_REQUEST = {config.MAX_IMAGES_PER_REQUEST}")
print(f"⚙️ [config] MAX_OUTPUT_TOKENS = {config.MAX_OUTPUT_TOKENS}")

st.markdown("---")

col_space1, col_input, col_space2 = st.columns([1, 2, 1])
with col_input:
    uploaded_file = st.file_uploader("فایل صورتحساب بانکی خود را آپلود کنید (فرمت PDF)", type=["pdf"])
    submit_button = st.button("🚀 شروع تحلیل و پردازش", use_container_width=True)

if submit_button:
    if not config.OPENROUTER_API_KEY:
        st.error("⚠️ کلید API تنظیم نشده است! لطفاً فایل .env یا تنظیمات Secrets سرور را بررسی کنید.")
    elif not uploaded_file:
        st.warning("⚠️ لطفاً ابتدا یک فایل PDF آپلود کنید.")
    else:
        try:
            file_bytes = uploaded_file.getvalue()
            file_hash = compute_file_hash(file_bytes)

            # ─── Step 0 [NEW]: Upload PDF to MinIO + init DB ───
            with st.spinner("⏳ در حال آماده‌سازی زیرساخت ذخیره‌سازی..."):
                asyncio.run(init_db())
                storage_client.ensure_bucket()
                storage_client.upload_pdf(file_hash, file_bytes, uploaded_file.name)

            # ─── Check DB cache ───
            async def _check_db_cache():
                async with AsyncSessionLocal() as db:
                    return await db_crud.get_report_by_hash(db, file_hash)

            existing = asyncio.run(_check_db_cache())
            if existing and existing.status == "completed":
                st.success("✅ این فایل قبلاً تحلیل شده! نتایج قبلی نمایش داده می‌شود.")
                features = json.loads(existing.features_json) if existing.features_json else {}
                final_result = json.loads(existing.report_json) if existing.report_json else {}
                routing_result = {"account_type": existing.account_type}
                merge_metadata = {"account_holder_name": existing.account_holder_name}

            if existing and existing.status == "completed":
                pass  # skip analysis, jump to display
            else:
                # ---------- تفکیک صفحات ----------
                with st.spinner("⏳ در حال خواندن و تحلیل صفحات PDF..."):
                    pages_data = extract_page_data(file_bytes)
                    chunks = split_pages_with_context(pages_data, overlap_lines=config.OVERLAP_LINES)

                # نمایش تعداد صفحات و روش استخراج هر کدام
                method_counts = {}
                for p in pages_data:
                    m = p["method"]
                    method_counts[m] = method_counts.get(m, 0) + 1

                method_labels = {
                    "camelot": "📊 جدولی (Camelot)",
                    "llm_required": "📝 متنی (LLM)",
                    "image_required": "🖼️ تصویری (Vision LLM)",
                }
                parts = [f"{method_labels.get(k, k)}: {v}" for k, v in method_counts.items()]
                st.info(
                    f"📄 تعداد صفحات: {len(pages_data)} — "
                    f"تعداد chunks: {len(chunks)} (هر chunk شامل {config.PAGES_PER_CHUNK} صفحه) — "
                    f"روش‌ها: {', '.join(parts)}"
                )

                # ---------- قدم ۱: استخراج ساخت‌یافته per-page ----------
                progress_bar = st.progress(0, text="در حال استخراج تراکنش‌های هر صفحه...")

                def update_progress(completed, total, page_num):
                    progress_bar.progress(
                        completed / total,
                        text=f"صفحه {page_num} پردازش شد ({completed}/{total})",
                    )

                page_results = extract_all_pages(
                    chunks,
                    api_key=config.OPENROUTER_API_KEY,
                    file_hash=file_hash,
                    progress_callback=update_progress,
                )
                progress_bar.empty()

                ok_count = sum(1 for p in page_results if p.extraction_status == "ok")
                failed_count = sum(1 for p in page_results if p.extraction_status == "failed")
                skipped_count = sum(1 for p in page_results if p.extraction_status == "skipped_empty")

                st.success(f"✅ استخراج صفحات کامل شد: {ok_count} موفق، {failed_count} ناموفق، {skipped_count} خالی/رد شده")

                if failed_count > 0:
                    failed_pages = [p.page_number for p in page_results if p.extraction_status == "failed"]
                    st.warning(f"⚠️ استخراج صفحات زیر ناموفق بود؛ ممکن است برخی تراکنش‌ها از قلم افتاده باشند: {failed_pages}")

                # ---------- قدم ۲: یکپارچه‌سازی و اعتبارسنجی ----------
                with st.spinner("🔗 در حال یکپارچه‌سازی و اعتبارسنجی تراکنش‌ها..."):
                    df, merge_metadata = run_merge_pipeline(page_results)

                    if df.empty:
                        st.error("❌ هیچ تراکنشی از فایل استخراج نشد. لطفاً فایل را بررسی کنید.")
                        st.stop()

                    df, balance_report = verify_balance_continuity(df)

                quality_report = {**merge_metadata, **balance_report}

                with st.expander("🔍 گزارش کیفیت داده و اعتبارسنجی"):
                    st.json(quality_report)
                    if balance_report["mismatch_count"] > 0:
                        st.warning(
                            f"⚠️ در {balance_report['mismatch_count']} ردیف، پیوستگی موجودی برقرار نبود؛ "
                            "احتمالاً یک تراکنش جا افتاده یا خطای OCR/LLM رخ داده است."
                        )

                # ---------- قدم ۳: محاسبه فیچرها با کد ----------
                with st.spinner("🧮 در حال محاسبه فیچرهای مالی..."):
                    features = compute_features(df)

                with st.expander("📊 فیچرهای مالی محاسبه‌شده (deterministic)"):
                    st.json(features)

                # ---------- قدم ۴: Two-Step LLM Routing (دسته‌بندی + تحلیل تخصصی) ----------
                with st.spinner("🧠 در حال دسته‌بندی نوع حساب و تحلیل تخصصی توسط هوش مصنوعی..."):
                    routing_result = route_and_analyze(
                        features=features,
                        api_key=config.OPENROUTER_API_KEY,
                    )

                # ---------- قدم ۵: تحلیل کیفی نهایی (با استفاده از خروجی Routing) ----------
                with st.spinner("🧠 در حال تولید تحلیل روایت ریسک توسط هوش مصنوعی..."):
                    final_result = generate_narrative(
                        features=features,
                        quality_report=quality_report,
                        account_holder_name=merge_metadata.get("account_holder_name"),
                        api_key=config.OPENROUTER_API_KEY,
                        routing_result=routing_result,
                    )

                st.success("✅ تحلیل با موفقیت انجام شد!")

                # ─── Step 6 [NEW]: Save results to PostgreSQL ───
                async def _save_to_db():
                    async with AsyncSessionLocal() as db:
                        report = await db_crud.create_report(
                            db,
                            file_hash=file_hash,
                            original_filename=uploaded_file.name,
                            account_holder_name=merge_metadata.get("account_holder_name"),
                            account_type=routing_result.get("account_type") if routing_result else None,
                            features=features,
                            report=final_result,
                        )
                        txns = df.to_dict("records")
                        for t in txns:
                            t.pop("parsed_date", None)
                            t.pop("month", None)
                        await db_crud.save_transactions_bulk(db, report.id, txns)
                asyncio.run(_save_to_db())

            # ─── DISPLAY: Results (shared by fresh analysis and cache hit) ───

            # استخراج transactional_power_score از تحلیل تخصصی (فقط برای حساب تجاری)
            if routing_result:
                final_result["transactional_power_score"] = routing_result.get("analysis", {}).get("transactional_power_score", "-")

            st.markdown("### 📋 خلاصه وضعیت مالی گردش حساب")
            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("درآمد ماهیانه (تخمینی مستمر)", final_result.get("avg_monthly_income", "-"))
            m_col2.metric("مخارج ماهیانه (تخمینی)", final_result.get("avg_monthly_expenses", "-"))
            m_col3.metric("مازاد مالی (پس‌انداز واقعی)", final_result.get("net_monthly_surplus", "-"))

            st.write("")
            installments = final_result.get("recommended_max_installments", {})
            i_col1, i_col2, i_col3 = st.columns(3)
            i_col1.metric("اقسط پیشنهادی (ریسک پایین)", installments.get("low_risk_tier", "-"))
            i_col2.metric("اقسط پیشنهادی (ریسک متوسط)", installments.get("medium_risk_tier", "-"))
            i_col3.metric("اقسط پیشنهادی (ریسک بالا)", installments.get("high_risk_tier", "-"))

            st.write("")
            risk = final_result.get("final_assessed_risk", "Unknown")
            risk_color = "green" if risk == "Low" else "orange" if risk == "Medium" else "red"
            st.markdown(
                f"<div style='background-color:#f9f9f9; padding: 15px; border-radius: 5px; "
                f"border-right: 5px solid {risk_color};'><b>سطح ریسک اعتباری:</b> "
                f"<span style='color:{risk_color}; font-size:24px; font-weight:bold;'>{risk}</span></div>",
                unsafe_allow_html=True,
            )

            # نمایش امتیاز قدرت نقدینگی (فقط برای حساب تجاری)
            tps = final_result.get("transactional_power_score")
            if tps and tps != "-":
                st.write("")
                st.markdown(
                    f"<div style='background-color:#f0f7ff; padding: 15px; border-radius: 5px; "
                    f"border-right: 5px solid #1976d2;'><b>🏦 امتیاز قدرت نقدینگی (Transactional Power Score):</b> "
                    f"<span style='color:#1976d2; font-size:24px; font-weight:bold;'>{tps} / ۱۰</span>"
                    f"<br><small style='color:#666;'>بر اساس حجم حواله‌ها و خریدهای مستمر تجاری</small></div>",
                    unsafe_allow_html=True,
                )

            st.markdown("---")
            st.markdown("### 📝 گزارش تفصیلی هوش مصنوعی:")
            st.info(final_result.get("financial_analysis_fa", "تحلیلی یافت نشد."))

            st.markdown("---")
            st.markdown("### 📑 جدول کامل تراکنش‌های استخراج‌شده")

            # ستون‌های فارسی برای نمایش
            col_labels = {
                "date": "تاریخ",
                "time": "ساعت",
                "description": "شرح عملیات",
                "deposit": "واریز (ریال)",
                "withdrawal": "برداشت (ریال)",
                "balance": "مانده (ریال)",
                "source_page": "صفحه",
                "type": "نوع تراکنش",
            }

            # ساخت ستون نوع تراکنش
            df_display = df.copy()
            df_display["type"] = df_display.apply(
                lambda r: "واریز" if (r.get("deposit") and r["deposit"] > 0)
                else ("برداشت" if (r.get("withdrawal") and r["withdrawal"] > 0) else "—"),
                axis=1,
            )

            # جایگزینی 0 با None در ستون‌های مبلغ (حفظ نوع float برای PyArrow)
            for money_col in ["deposit", "withdrawal"]:
                if money_col in df_display.columns:
                    df_display[money_col] = df_display[money_col].apply(
                        lambda x: None if (x == 0 or x is None or (isinstance(x, float) and x == 0.0)) else x
                    )

            display_cols = ["date", "time", "type", "description", "deposit", "withdrawal", "balance", "source_page"]
            display_cols = [c for c in display_cols if c in df_display.columns]

            # تغییر نام ستون‌ها به فارسی
            df_final = df_display[display_cols].rename(columns=col_labels)

            st.dataframe(df_final, use_container_width=True)

            csv_data = df_final.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ دانلود جدول تراکنش‌ها (CSV)",
                data=csv_data,
                file_name="transactions.csv",
                mime="text/csv",
            )

            with st.expander("نمایش خروجی خام تحلیل نهایی (JSON)"):
                st.json(final_result)

        except json.JSONDecodeError:
            st.error("❌ خطایی در خواندن ساختار خروجی مدل رخ داد. لطفاً مجدداً تلاش کنید.")
        except Exception as e:
            error_msg = str(e).lower()
            if "403" in error_msg and ("limit" in error_msg or "forbidden" in error_msg):
                st.error("🚫 **محدودیت مصرف روزانه به پایان رسیده است!**")
                st.warning("اعتبار کلید ارتباطی با هوش مصنوعی (API) تمام شده است. لطفاً حساب کاربری خود را بررسی کرده و سقف مصرف را افزایش دهید.")
            elif "connection" in error_msg or "network" in error_msg:
                st.error("🌐 خطای ارتباط با شبکه رخ داد. لطفاً وضعیت اینترنت سرور را بررسی کنید.")
            else:
                st.error(f"❌ خطای سیستمی در حین پردازش: {e}")
