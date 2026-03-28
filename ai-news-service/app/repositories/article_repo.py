"""
app/repositories/article_repo.py — Compatibility re-export
===========================================================
The old ArticleRepository (backed by the articles table) has been replaced by
the two-stage pipeline:
  FilterArticleRepository     → filter_articles table
  PostProcessedArticleRepository → post_processed_articles table

This module re-exports PostProcessedArticleRepository under the legacy
ArticleRepository name so that existing imports in deps.py and routes_articles.py
continue to work without change.

To use the full pipeline API, import directly:
  from app.repositories.filter_article_repo import FilterArticleRepository
  from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
"""

from app.repositories.post_processed_article_repo import PostProcessedArticleRepository

# Legacy alias — used by deps.py → routes_articles.py
ArticleRepository = PostProcessedArticleRepository

__all__ = ["ArticleRepository"]
