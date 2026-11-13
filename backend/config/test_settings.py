"""Pytest settings that provide a non-production default secret key."""
import os

os.environ.setdefault("SECRET_KEY", "test-only-insecure-secret-key-not-for-production")

from .settings import *  # noqa: F403,E402

# Run indexing inline and tasks synchronously in tests to eliminate thread concurrency warnings
SYNC_INDEXING = True
CELERY_TASK_ALWAYS_EAGER = True
