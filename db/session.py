import config
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


def _make_engine():
    return create_async_engine(config.DATABASE_URL, echo=False)


def get_session():
    """Create a fresh async session (with its own engine) per call."""
    engine = _make_engine()
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return Session()


async def init_db():
    """Create all tables (for dev; use Alembic in production)."""
    engine = _make_engine()
    from db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
