import re
import unicodedata
import camelot
import pandas as pd

print("در حال استخراج جداول از تمام صفحات... لطفا کمی صبر کنید.")
tables = camelot.read_pdf('bank_statement.pdf', pages='all', flavor='lattice')
print(f"مجموعاً {len(tables)} جدول پیدا شد.")

# ---- ترکیب جداول + حذف هدرهای تکراری ----

def row_to_tuple(row):
    """تبدیل یک ردیف (Series) به تاپل رشته‌ای برای مقایسه‌ی امن"""
    return tuple(str(x) for x in row.tolist())


header_row = tables[0].df.iloc[0]
header_tuple = row_to_tuple(header_row)

all_dfs = []
for i, table in enumerate(tables):
    df = table.df.copy()

    if i == 0:
        all_dfs.append(df)
        continue

    # فقط اگر تعداد ستون‌ها برابر بود، مقایسه کن
    if df.shape[1] == len(header_tuple):
        first_row_tuple = row_to_tuple(df.iloc[0])
        if first_row_tuple == header_tuple:
            df = df.iloc[1:]

    all_dfs.append(df)

combined_df = pd.concat(all_dfs, ignore_index=True)


# ---- پاکسازی هر هدر تکراری باقی‌مانده در وسط جدول ----

def remove_duplicate_header_rows(df, header_tuple, keep_first=True):
    if df.shape[1] != len(header_tuple):
        return df

    mask_list = []
    for idx in range(len(df)):
        row_tuple = row_to_tuple(df.iloc[idx])
        mask_list.append(row_tuple == header_tuple)

    mask = pd.Series(mask_list, index=df.index)

    if keep_first and mask.any():
        first_idx = mask.idxmax()
        mask.loc[first_idx] = False

    return df[~mask].reset_index(drop=True)


combined_df = remove_duplicate_header_rows(combined_df, header_tuple, keep_first=True)
print(f"تعداد ردیف‌ها بعد از حذف هدرهای تکراری: {len(combined_df)}")


# ---- تابع اصلاح متن فارسی ----

def normalize_persian_chars(text):
    text = unicodedata.normalize('NFKC', text)
    manual_map = {
        '\u0640': '',
        'ك': 'ک',
        'ي': 'ی',
        'ى': 'ی',
        'ة': 'ه',
    }
    for old, new in manual_map.items():
        text = text.replace(old, new)
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    trans_table = str.maketrans(arabic_digits, persian_digits)
    text = text.translate(trans_table)
    return text


PERSIAN_ARABIC_RANGE = r'\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF'
PERSIAN_CHAR_PATTERN = re.compile(f'[{PERSIAN_ARABIC_RANGE}]')
NUMBER_PATTERN = re.compile(r'^[۰-۹,\./\-\+:]+$')


def fix_persian_layout(text):
    if not isinstance(text, str) or text.strip() == "":
        return text
    text = normalize_persian_chars(text)
    tokens = text.split()
    fixed_tokens = []
    for token in tokens:
        if PERSIAN_CHAR_PATTERN.search(token):
            if NUMBER_PATTERN.match(token):
                fixed_tokens.append(token)
            else:
                fixed_tokens.append(token[::-1])
        else:
            fixed_tokens.append(token)
    fixed_tokens.reverse()
    
    # تبدیل لیست توکن‌ها به متن نهایی
    fixed_text = ' '.join(fixed_tokens)
    
    # لغت‌نامه اصلاح خطاهای ناشی از جابجایی کلمات دارای "لا"
    # از replace به صورت زیررشته استفاده شده تا مشتقات کلمات (مثل کالاها یا اطلاعاتی) نیز اصلاح شوند.
    ligature_fixes = {
        "کاال": "کالا",
        "اصالح": "اصلاح",
        "اطالعات": "اطلاعات",
        "تسهیالت": "تسهیلات",
        "اعالم": "اعلام",
        "ابالع": "ابلاغ",
        "خالصه": "خلاصه",
        "عالمت": "علامت",
        "صالحیت": "صلاحیت",
        "انقالب": "انقلاب",
        "امالک": "املاک",
        "عالقه": "علاقه",
        "فالپی": "فلاپی",
        "مالحظه": "ملاحظه",
        "مالحظات": "ملاحظات",
        "باطال": "ابطال"
    }
    
    for wrong, right in ligature_fixes.items():
        fixed_text = fixed_text.replace(wrong, right)
        
    return fixed_text


print("در حال اصلاح و مرتب‌سازی متن‌های فارسی...")
if hasattr(combined_df, 'map'):
    final_df = combined_df.map(fix_persian_layout)
else:
    final_df = combined_df.applymap(fix_persian_layout)

final_df.to_csv('all_pages_fixed.csv', index=False, encoding='utf-8-sig', header=False)

print("کار تمام شد! فایل یکپارچه و اصلاح‌شده در 'all_pages_fixed.csv' ذخیره شد.")