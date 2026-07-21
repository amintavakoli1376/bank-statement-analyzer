import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# می‌توانید برای استخراج (ارزان‌تر/سریع‌تر) و روایت‌نویسی (دقیق‌تر) مدل‌های متفاوت انتخاب کنید
EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", "google/gemini-3.5-flash")
NARRATIVE_MODEL = os.environ.get("NARRATIVE_MODEL", "google/gemini-3.1-pro-preview")

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", 5))
MAX_EXTRACTION_RETRIES = int(os.environ.get("MAX_EXTRACTION_RETRIES", 2))
OVERLAP_LINES = int(os.environ.get("OVERLAP_LINES", 2))
PAGES_PER_CHUNK = int(os.environ.get("PAGES_PER_CHUNK", 4))  # تعداد صفحات هر chunk
MIN_PAGE_TEXT_LENGTH = int(os.environ.get("MIN_PAGE_TEXT_LENGTH", 20))

BALANCE_TOLERANCE = float(os.environ.get("BALANCE_TOLERANCE", 1000))

# حداکثر توکن خروجی برای جلوگیری از تکرنکیت پاسخ LLM
# هر تراکنش ~100 توکن مصرف می‌کند.
# وقتی چندین صفحه در یک chunk پردازش می‌شوند (تا PAGES_PER_CHUNK صفحه)，
# خروجی می‌تواند بزرگ باشد: مثلاً 10 صفحه × 15 تراکنش × 100 توکن ≈ 15000 توکن
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", 16000))

MIN_TABLE_ROWS = int(os.environ.get("MIN_TABLE_ROWS", 2))
MIN_TEXT_LENGTH_FOR_IMAGE = int(os.environ.get("MIN_TEXT_LENGTH_FOR_IMAGE", 20))

# حداکثر تعداد تصاویر در هر درخواست LLM
# بیشتر مدل‌های vision از طریق OpenRouter محدودیت دارند.
# اگه 403 گرفتید، این عدد رو کم کنید (مثلاً 2 یا 3)
MAX_IMAGES_PER_REQUEST = int(os.environ.get("MAX_IMAGES_PER_REQUEST", 4))

# ─── تنظیمات Camelot ────────────────────────────────────────────────────────
USE_CAMELOT = os.environ.get("USE_CAMELOT", "false").lower() in ("true", "1", "yes")
MIN_CAMELOT_TABLE_ROWS = int(os.environ.get("MIN_CAMELOT_TABLE_ROWS", 2))

# ─── Database ────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/bank_analyzer",
)

# ─── MinIO ───────────────────────────────────────────────────────────────────
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "bank-statements")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() in ("true", "1", "yes")
