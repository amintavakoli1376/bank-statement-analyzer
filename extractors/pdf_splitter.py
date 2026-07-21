import pdfplumber
import re
import hashlib
import io
import base64

try:
    import fitz  # PyMuPDF — متن‌خوان تقویتی
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

import config
from extractors.camelot_extractor import try_extract_tables

CARD_NUMBER_PATTERN = re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b')

# ─── توابع کمکی ──────────────────────────────────────────────────────────────


def mask_sensitive_info(text: str) -> str:
    """ماسک کردن شماره کارت‌ها."""
    if not text:
        return text
    return CARD_NUMBER_PATTERN.sub('*-****-****-****', text)


def compute_file_hash(file_bytes: bytes) -> str:
    """هش فایل برای کش کردن نتایج استخراج هر صفحه."""
    return hashlib.md5(file_bytes).hexdigest()[:16]


# ─── تبدیل صفحه به عکس ──────────────────────────────────────────────────────


<<<<<<< HEAD
def page_to_image_b64(page) -> str:
    """تبدیل صفحه pdfplumber به PNG base64 برای ارسال به مدل vision."""
    img = page.to_image(resolution=150)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
=======
# def page_to_image_b64(page) -> str:
#     """تبدیل صفحه pdfplumber به PNG base64 برای ارسال به مدل vision."""
#     img = page.to_image(resolution=150)
#     buf = io.BytesIO()
#     img.save(buf, format="PNG")
#     return base64.b64encode(buf.getvalue()).decode("utf-8")

def page_to_image_b64_fitz(fitz_page) -> str:
    """
    تبدیل صفحه به PNG با استفاده از موتور PyMuPDF.
    بسیار سریع‌تر و پایدارتر از pdfplumber و بدون خطر Segfault.
    """
    # 150 DPI (~ رزولوشن 150)
    zoom_mat = fitz.Matrix(150 / 72, 150 / 72)
    pix = fitz_page.get_pixmap(matrix=zoom_mat, alpha=False)
    
    # خروجی گرفتن به صورت بایت‌های PNG
    img_bytes = pix.tobytes("png")
    return base64.b64encode(img_bytes).decode("utf-8")
>>>>>>> a084173664107afb8cda54b75206cedbdb0a73de


# ─── متن‌خوانی تقویتی با PyMuPDF ────────────────────────────────────────────


def _extract_text_with_fitz(file_bytes: bytes, page_idx: int) -> str:
    """
    خواندن متن صفحه با PyMuPDF (fitz).
    برای PDFهایی که pdfplumber متن کافی برنمی‌گرداند.
    """
    if not HAS_FITZ:
        return ""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page = doc[page_idx]
        text = page.get_text("text")
        doc.close()
        return text.strip()
    except Exception:
        return ""


# ─── استخراج متن/تصویر هر صفحه ─────────────────────────────────────────────


<<<<<<< HEAD
def extract_page_data(file_bytes: bytes):
    """
    استخراج متن، تصویر یا جدول هر صفحه PDF.

    دو حالت:
      1. "camelot"          — جدول ساختاریافته قابل استخراج با Camelot
      2. "image_required"   — صفحه تصویری/اسکن (نیاز به vision LLM)
    """
    pages_data = []
=======
# def extract_page_data(file_bytes: bytes):
#     """
#     استخراج متن، تصویر یا جدول هر صفحه PDF.

#     دو حالت:
#       1. "camelot"          — جدول ساختاریافته قابل استخراج با Camelot
#       2. "image_required"   — صفحه تصویری/اسکن (نیاز به vision LLM)
#     """
#     pages_data = []
#     with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
#         total_pages = len(pdf.pages)
#         print(f"\n📖 [splitter] شروع استخراج از PDF با {total_pages} صفحه")

#         for page_idx, page in enumerate(pdf.pages):
#             page_num = page_idx + 1

#             # استخراج متن با pdfplumber
#             text = page.extract_text() or ""
#             text_stripped = text.strip()

#             # تلاش برای متن بهتر با PyMuPDF
#             fitz_text = _extract_text_with_fitz(file_bytes, page_idx)
#             effective_text = fitz_text if (fitz_text and len(fitz_text) > len(text_stripped)) else text_stripped

#             # ─── اولویت اول: تلاش برای استخراج جدول با Camelot ───
#             if config.USE_CAMELOT:
#                 camelot_dfs = try_extract_tables(file_bytes, page_idx)
#                 if camelot_dfs:
#                     pages_data.append({
#                         "method": "camelot",
#                         "page_number": page_num,
#                         "tables_data": camelot_dfs,
#                         "raw_text": effective_text,  # برای استخراج نام صاحب حساب
#                     })
#                     continue

#             # ─── اولویت دوم: فقط تصویر (حالت متنی حذف شد) ───
#             image_b64 = page_to_image_b64(page)
#             pages_data.append({
#                 "method": "image_required",
#                 "page_number": page_num,
#                 "image_b64": image_b64,
#                 "raw_text": effective_text,
#             })

#     # لاگ خلاصه‌ی روش استخراج هر صفحه
#     print(f"📖 [splitter] استخراج کامل شد:")
#     labels = {"camelot": "📊 جدولی", "image_required": "🖼️ تصویری"}
#     for p in pages_data:
#         len_text = len(p.get("raw_text", ""))
#         label = labels.get(p["method"], p["method"])
#         print(f"   صفحه {p['page_number']}: {label} (متن: {len_text} کاراکتر)")

#     return pages_data

def extract_page_data(file_bytes: bytes):
    pages_data = []
    
    # 1. باز کردن داکیومنت PyMuPDF فقط یک بار برای کل فایل (جلوگیری از مموری لیک)
    fitz_doc = None
    if HAS_FITZ:
        try:
            fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception:
            pass

>>>>>>> a084173664107afb8cda54b75206cedbdb0a73de
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        total_pages = len(pdf.pages)
        print(f"\n📖 [splitter] شروع استخراج از PDF با {total_pages} صفحه")

        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1

            # استخراج متن با pdfplumber
            text = page.extract_text() or ""
            text_stripped = text.strip()

<<<<<<< HEAD
            # تلاش برای متن بهتر با PyMuPDF
            fitz_text = _extract_text_with_fitz(file_bytes, page_idx)
=======
            # تلاش برای متن بهتر با PyMuPDF (استفاده از داکیومنت باز شده)
            fitz_text = ""
            if fitz_doc and page_idx < len(fitz_doc):
                fitz_text = fitz_doc[page_idx].get_text("text").strip()
            
>>>>>>> a084173664107afb8cda54b75206cedbdb0a73de
            effective_text = fitz_text if (fitz_text and len(fitz_text) > len(text_stripped)) else text_stripped

            # ─── اولویت اول: تلاش برای استخراج جدول با Camelot ───
            if config.USE_CAMELOT:
                camelot_dfs = try_extract_tables(file_bytes, page_idx)
                if camelot_dfs:
                    pages_data.append({
                        "method": "camelot",
                        "page_number": page_num,
                        "tables_data": camelot_dfs,
<<<<<<< HEAD
                        "raw_text": effective_text,  # برای استخراج نام صاحب حساب
                    })
                    continue

            # ─── اولویت دوم: فقط تصویر (حالت متنی حذف شد) ───
            image_b64 = page_to_image_b64(page)
=======
                        "raw_text": effective_text,
                    })
                    continue

            # ─── اولویت دوم: فقط تصویر ───
            # اگر fitz داریم، عکس را با آن می‌سازیم. در غیر این صورت به عنوان پشتیبان از pdfplumber استفاده می‌کنیم
            if fitz_doc and page_idx < len(fitz_doc):
                image_b64 = page_to_image_b64_fitz(fitz_doc[page_idx])
            else:
                # این خط فقط در صورتی اجرا می‌شود که PyMuPDF نصب نباشد (احتمال کرش در اینجا وجود دارد)
                img = page.to_image(resolution=150)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

>>>>>>> a084173664107afb8cda54b75206cedbdb0a73de
            pages_data.append({
                "method": "image_required",
                "page_number": page_num,
                "image_b64": image_b64,
                "raw_text": effective_text,
            })

<<<<<<< HEAD
    # لاگ خلاصه‌ی روش استخراج هر صفحه
=======
    # بستن داکیومنت PyMuPDF
    if fitz_doc:
        fitz_doc.close()

>>>>>>> a084173664107afb8cda54b75206cedbdb0a73de
    print(f"📖 [splitter] استخراج کامل شد:")
    labels = {"camelot": "📊 جدولی", "image_required": "🖼️ تصویری"}
    for p in pages_data:
        len_text = len(p.get("raw_text", ""))
        label = labels.get(p["method"], p["method"])
        print(f"   صفحه {p['page_number']}: {label} (متن: {len_text} کاراکتر)")

    return pages_data

<<<<<<< HEAD

=======
>>>>>>> a084173664107afb8cda54b75206cedbdb0a73de
# ─── ساخت chunk از چند صفحه ──────────────────────────────────────────────────


def split_pages_with_context(pages_data, overlap_lines: int = 2):
    """
    گروه‌بندی صفحات در chunk برای پردازش.

    استراتژی:
    - صفحات غیر-camelot (متنی + تصویری): در گروه‌های PAGES_PER_CHUNK صفحه batch می‌شوند.
      همه‌ی تصاویر هر گروه در یک درخواست multimodal به LLM ارسال می‌شوند
      (هیچ تصویری drop نمی‌شود).
    - صفحات جدولی (camelot): هر کدام یک chunk مستقل (بدون نیاز به LLM).
    """
    pages_per_chunk = config.PAGES_PER_CHUNK
    chunks = []

    # لاگ خلاصه‌ی صفحات ورودی
    method_summary = {}
    for p in pages_data:
        m = p["method"]
        method_summary[m] = method_summary.get(m, 0) + 1
    print(f"\n📄 [splitter] صفحات ورودی: {len(pages_data)} صفحه | روش‌ها: {method_summary}")

    # ─── قدم ۱: صفحات camelot → chunk مستقل (بدون LLM) ────────────────────────
    non_camelot_pages = []
    for p in pages_data:
        if p["method"] == "camelot":
            chunks.append({
                "page_number": p["page_number"],
                "page_range": str(p["page_number"]),
                "method": "camelot",
                "tables_data": p.get("tables_data"),
                "raw_text": p.get("raw_text", ""),
                "page_count": 1,
            })
        else:
            non_camelot_pages.append(p)

    # ─── قدم ۲: صفحات متنی + تصویری → batch در گروه‌های PAGES_PER_CHUNK ───────
    max_images = config.MAX_IMAGES_PER_REQUEST

    for start_idx in range(0, len(non_camelot_pages), pages_per_chunk):
        group = non_camelot_pages[start_idx : start_idx + pages_per_chunk]

        # جمع‌آوری همه‌ی تصاویر گروه
        images_b64 = []
        for p in group:
            if p["method"] == "image_required" and p.get("image_b64"):
                images_b64.append({
                    "page_number": p["page_number"],
                    "image_b64": p["image_b64"],
                })

        # ترکیب متن صفحات با جداکننده
        text_parts = []
        for p in group:
            raw_text = p.get("raw_text", "")
            if raw_text:
                masked_text = mask_sensitive_info(raw_text)
                text_parts.append(
                    f"--- صفحه {p['page_number']} ---\n{masked_text}"
                )
        chunk_text = "\n\n".join(text_parts)

        # اگر تعداد تصاویر از محدودیت بیشتر است، بشکون به زیر-chunks
        if images_b64 and len(images_b64) > max_images:
            img_idx = 0
            while img_idx < len(images_b64):
                sub_imgs = images_b64[img_idx : img_idx + max_images]
                sub_start_page = sub_imgs[0]["page_number"]
                sub_end_page = sub_imgs[-1]["page_number"]

                # متن فقط صفحات این زیر-chunk
                sub_pages = set(im["page_number"] for im in sub_imgs)
                sub_text_parts = []
                for p in group:
                    if p["page_number"] in sub_pages and p.get("raw_text"):
                        sub_text_parts.append(
                            f"--- صفحه {p['page_number']} ---\n{mask_sensitive_info(p['raw_text'])}"
                        )
                # اگر متن اضافی هم از صفحات غیر-تصویری داریم، بذاریم
                for p in group:
                    if p["method"] != "image_required" and p.get("raw_text"):
                        sub_text_parts.append(
                            f"--- صفحه {p['page_number']} ---\n{mask_sensitive_info(p['raw_text'])}"
                        )
                sub_text = "\n\n".join(sub_text_parts)

                chunks.append({
                    "page_number": sub_start_page,
                    "page_range": f"{sub_start_page}-{sub_end_page}",
                    "method": "image_required",
                    "text": sub_text,
                    "raw_length": len(sub_text),
                    "page_count": len(sub_imgs),
                    "images_b64": sub_imgs,
                })
                img_idx += max_images
        else:
            start_page = group[0]["page_number"]
            end_page = group[-1]["page_number"]
            chunk = {
                "page_number": start_page,
                "page_range": f"{start_page}-{end_page}",
                "method": "image_required",
                "text": chunk_text,
                "raw_length": len(chunk_text),
                "page_count": len(group),
                "images_b64": images_b64,
            }
            chunks.append(chunk)

    # مرتب‌سازی chunks بر اساس page_number اولین صفحه
    chunks.sort(key=lambda c: c["page_number"])

    # ─── لاگ خلاصه‌ی chunks ساخته‌شده ──────────────────────────────────────────
    print(f"📦 [splitter] تعداد chunks ساخته‌شده: {len(chunks)}")
    for c in chunks:
        if c["method"] == "image_required":
            n_imgs = len(c.get("images_b64", []))
            print(f"   chunk صفحات {c['page_range']}: 🖼️ {n_imgs} تصویر + متن ({c.get('raw_length', 0)} کاراکتر)")
        else:
            print(f"   chunk صفحه {c['page_number']}: 📊 جدولی (camelot)")
    print()

    return chunks
