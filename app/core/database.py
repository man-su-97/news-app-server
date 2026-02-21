"""
app/core/database.py — Database Engine and Session Factory
===========================================================
This file sets up the SQLAlchemy async database connection.
Two things are exported and used everywhere else:
  - engine:              the connection pool (created once at startup)
  - get_db():            an async generator that yields a DB session
                         per HTTP request (used via FastAPI's Depends system)

Architecture: We use SQLAlchemy's async engine with asyncpg (a fast Postgres driver).
"Async" means database calls use Python's async/await and don't block the event loop —
critical for a web server that handles many requests concurrently.

Connection pool:
  - pool_size=10:    keep 10 permanent connections open to the DB
  - max_overflow=20: allow up to 20 extra connections during traffic spikes
  Total max connections = 10 + 20 = 30 simultaneous DB connections.
  Adjust these based on your PostgreSQL server's max_connections setting.
"""

# create_async_engine: creates the connection pool using async IO
# async_sessionmaker: factory for creating individual database sessions
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings  # reads DATABASE_URL from .env


# Create the engine — this is the "connection pool manager".
# It is created ONCE when the module loads (not per request).
# echo=settings.DEBUG: when DEBUG=true in .env, every SQL query is printed.
#   This is very useful for debugging but noisy in production.
engine = create_async_engine(
    settings.DATABASE_URL,    # e.g. "postgresql+asyncpg://user:pass@host/dbname"
    echo=settings.DEBUG,      # print SQL to console if DEBUG=True
    pool_size=10,             # permanent connections kept alive
    max_overflow=20,          # extra connections allowed during peak load
)

# AsyncSessionLocal is a "session factory".
# Calling AsyncSessionLocal() creates a new database session.
# expire_on_commit=False: keeps ORM objects usable after commit.
#   Without this, accessing .id or .title after commit() would trigger
#   a new DB query because SQLAlchemy would assume they're "expired".
#   Since we use these objects to return JSON responses after commit, we need
#   them to stay loaded in memory.
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    """Async generator that yields one DB session per HTTP request.

    How FastAPI's Depends system uses this:
      async def my_endpoint(db: AsyncSession = Depends(get_db)):
          ...  # db is a fresh session just for this request

    The `async with` block handles session cleanup automatically:
      - On success: commits are done inside the repositories; session is closed here.
      - On error: the session is closed and any uncommitted changes are rolled back.

    Architecture decision: Using a generator (yield) instead of returning a session
    directly allows FastAPI to run the cleanup code (after yield) after the
    endpoint finishes, even if an exception occurred.
    """
    # Open a new session for this request
    async with AsyncSessionLocal() as session:
        yield session         # <-- hand the session to the endpoint/repository
        # session is automatically closed here when the request finishes
