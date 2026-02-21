"""
app/models/base.py — SQLAlchemy Declarative Base
=================================================
This file defines the "Base" class that every database model must inherit from.

Why is this a separate file?
  Architecture decision: All models import Base from here.
  This gives Alembic (the DB migration tool) a single place to find all models
  and auto-detect changes. If Base were defined in each model file, Alembic
  would struggle to discover them.

How it works:
  class Article(Base):     <- inherits from Base
      __tablename__ = "articles"
      id = mapped_column(...)

  SQLAlchemy uses this inheritance to:
    - Know that Article maps to the "articles" DB table
    - Generate SQL for CREATE TABLE, SELECT, INSERT, UPDATE, DELETE
    - Track changes for migration generation
"""

from sqlalchemy.orm import DeclarativeBase  # The SQLAlchemy ORM base class


class Base(DeclarativeBase):
    """The shared base class for all ORM models in this project.

    Every table in the database has a corresponding Python class that inherits
    from this Base. SQLAlchemy uses these classes to:
      - Map Python objects ↔ database rows
      - Generate SQL queries from Python code (no raw SQL needed)
      - Power Alembic migrations (it reads Base.metadata to see all tables)
    """
    pass   # No custom behaviour needed — DeclarativeBase provides everything
