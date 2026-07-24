import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import init_db, _make_engine
from db import models

async def clean_db():
    engine = _make_engine()
    async with engine.begin() as conn:
        await conn.execute(models.Base.metadata.tables["transactions"].delete())
        await conn.execute(models.Base.metadata.tables["analysis_reports"].delete())
    await engine.dispose()
    print("✅ کش دیتابیس (جداول تراکنش‌ها و گزارش‌ها) با موفقیت پاک شد.")

if __name__ == "__main__":
    asyncio.run(clean_db())