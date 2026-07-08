import re
import unicodedata
import camelot
import pandas as pd

print("در حال استخراج جداول از تمام صفحات... لطفا کمی صبر کنید.")
tables = camelot.read_pdf('bank_statement.pdf', pages='all', flavor='lattice')
print(f"مجموعاً {len(tables)} جدول پیدا شد.")

all_dfs = [table.df for table in tables]
combined_df = pd.concat(all_dfs, ignore_index=True)


def normalize_persian_chars(text):
    """
    تبدیل کاراکترهای Arabic Presentation Forms به حروف استاندارد فارسی/عربی
    و یکسان‌سازی ارقام عربی به فارسی
    """
    # نرمال‌سازی یونیکد -> حروف چسبیده/شکل‌های نمایشی را به فرم پایه تبدیل می‌کند
    text = unicodedata.normalize('NFKC', text)

    # نگاشت دستی چند کاراکتر رایج که NFKC به‌درستی تبدیل نمی‌کند
    manual_map = {
        '\u0640': '',       # تطویل (کشیدگی) - حذف شود
        'ك': 'ک',
        'ي': 'ی',
        'ى': 'ی',
        'ة': 'ه',
    }
    for old, new in manual_map.items():
        text = text.replace(old, new)

    # تبدیل ارقام عربی (Arabic-Indic) به فارسی
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    trans_table = str.maketrans(arabic_digits, persian_digits)
    text = text.translate(trans_table)

    return text


# بازه‌ی کامل کاراکترهای فارسی/عربی (شامل اشکال نمایشی)
PERSIAN_ARABIC_RANGE = r'\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF'
PERSIAN_CHAR_PATTERN = re.compile(f'[{PERSIAN_ARABIC_RANGE}]')

# الگوی تشخیص عدد/تاریخ/مبلغ (بعد از نرمال‌سازی، فقط ارقام فارسی داریم)
NUMBER_PATTERN = re.compile(r'^[۰-۹,\./\-\+:]+$')


def fix_persian_layout(text):
    if not isinstance(text, str) or text.strip() == "":
        return text

    # مرحله‌ی اول: نرمال‌سازی کاراکترها (حل مشکل «تشخیص نداده»)
    text = normalize_persian_chars(text)

    tokens = text.split()
    fixed_tokens = []

    for token in tokens:
        if PERSIAN_CHAR_PATTERN.search(token):
            if NUMBER_PATTERN.match(token):
                fixed_tokens.append(token)  # عدد/تاریخ را دست‌نخورده نگه دار
            else:
                fixed_tokens.append(token[::-1])  # کلمه فارسی را معکوس کن
        else:
            fixed_tokens.append(token)

    fixed_tokens.reverse()
    return ' '.join(fixed_tokens)


print("در حال اصلاح و مرتب‌سازی متن‌های فارسی...")
if hasattr(combined_df, 'map'):
    final_df = combined_df.map(fix_persian_layout)
else:
    final_df = combined_df.applymap(fix_persian_layout)

final_df.to_csv('all_pages_fixed.csv', index=False, encoding='utf-8-sig', header=False)

print("کار تمام شد! فایل یکپارچه و اصلاح‌شده در 'all_pages_fixed.csv' ذخیره شد.")