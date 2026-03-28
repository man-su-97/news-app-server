from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings  # reads DATABASE_URL from .env

# Engine → manages connections
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
)

# AsyncSessionLocal is a session factory which on call generate session
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# get_db → creates session per request + auto cleanup


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Transaction starts
#         ↓
#    Changes happen
#         ↓
#     ┌───────────┐
#     │           │
#  COMMIT      ROLLBACK
#     │           │
# Permanent    Discarded
