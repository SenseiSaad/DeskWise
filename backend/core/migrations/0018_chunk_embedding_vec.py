"""Add the pgvector KNN column for chunk embeddings.

Only touches PostgreSQL: on any other backend (SQLite dev) this is a no-op and
retrieval keeps using the capped in-Python scan. On Postgres it enables the
pgvector extension and adds a fixed-width `vector` column beside the existing
`embedding` bytea column, which stays the portable source of truth.

EMBED_DIM (settings) decides the column width; changing the embedding model
after data exists means a full re-embed — see the retrieval runbook.
"""
import logging

from django.conf import settings
from django.db import migrations, transaction

logger = logging.getLogger(__name__)

SKIP_MESSAGE = (
    "pgvector extension is not available on this PostgreSQL server; skipping "
    "core_chunk.embedding_vec. Retrieval will fall back to the in-Python scan. "
    "To enable it later, use the pgvector/pgvector:pg16 image (or install "
    "pgvector), then run in psql: CREATE EXTENSION vector; ALTER TABLE "
    "core_chunk ADD COLUMN embedding_vec vector(<EMBED_DIM>); CREATE INDEX "
    "core_chunk_embedding_vec_hnsw ON core_chunk USING hnsw "
    "(embedding_vec vector_cosine_ops); then `manage.py reindex_embeddings --all`."
)


def add_pgvector_column(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    dim = int(getattr(settings, "EMBED_DIM", 1024))
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        available = cursor.fetchone() is not None
    if not available:
        logger.warning(SKIP_MESSAGE)
        return
    try:
        # Savepoint so a permissions failure doesn't abort the whole migration.
        with transaction.atomic(using=connection.alias):
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    f"ALTER TABLE core_chunk ADD COLUMN IF NOT EXISTS embedding_vec vector({dim})"
                )
    except Exception as exc:  # e.g. insufficient privilege to CREATE EXTENSION
        logger.warning("%s (%s: %s)", SKIP_MESSAGE, type(exc).__name__, exc)


def remove_pgvector_column(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE core_chunk DROP COLUMN IF EXISTS embedding_vec")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_asklog_core_asklog_company_04f1aa_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(add_pgvector_column, remove_pgvector_column),
    ]
