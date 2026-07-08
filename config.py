import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# می‌توانید برای استخراج (ارزان‌تر/سریع‌تر) و روایت‌نویسی (دقیق‌تر) مدل‌های متفاوت انتخاب کنید
EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", "google/gemini-3.5-flash")
NARRATIVE_MODEL = os.environ.get("NARRATIVE_MODEL", "google/gemini-3.5-flash")

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", 5))
MAX_EXTRACTION_RETRIES = int(os.environ.get("MAX_EXTRACTION_RETRIES", 2))
OVERLAP_LINES = int(os.environ.get("OVERLAP_LINES", 2))
PAGES_PER_CHUNK = int(os.environ.get("PAGES_PER_CHUNK", 10))  # تعداد صفحات هر chunk
MIN_PAGE_TEXT_LENGTH = int(os.environ.get("MIN_PAGE_TEXT_LENGTH", 20))

BALANCE_TOLERANCE = float(os.environ.get("BALANCE_TOLERANCE", 1000))

MIN_TABLE_ROWS = int(os.environ.get("MIN_TABLE_ROWS", 2))
MIN_TEXT_LENGTH_FOR_IMAGE = int(os.environ.get("MIN_TEXT_LENGTH_FOR_IMAGE", 20))

CACHE_DIR = os.environ.get("CACHE_DIR", "cache")