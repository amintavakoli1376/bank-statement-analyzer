import pdfplumber

with pdfplumber.open("bank_statement.pdf") as pdf:
    page = pdf.pages[0]
    tables = page.extract_tables()
    print(f"تعداد جدول‌های تشخیص داده‌شده: {len(tables)}")
    if tables:
        print(tables[0][:3])  # سه ردیف اول