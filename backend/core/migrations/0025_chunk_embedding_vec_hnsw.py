"""HNSW cosine index on core_chunk.embedding_vec (PostgreSQL + pgvector only).

No-op on SQLite and on PostgreSQL servers where migration 0018 skipped the
pgvector column. The KNN query in core.rag orders by `<=>` (cosine distance),
so the index uses vector_cosine_ops.
"""
import logging

from django.db import migrations, transaction

logger = logging.getLogger(__name__)

INDEX_NAME = "core_chunk_embedding_vec_hnsw"


def _has_vec_column(cursor) -> bool:
    cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    if not cursor.fetchone():
        return False
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'core_chunk' "
        "AND column_name = 'embedding_vec'"
    )
    return cursor.fetchone() is not None


def create_hnsw_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        if not _has_vec_column(cursor):
            logger.warning(
                "core_chunk.embedding_vec not present (pgvector unavailable); "
                "skipping HNSW index. Retrieval uses the in-Python scan."
            )
            return
    try:
        with transaction.atomic(using=schema_editor.connection.alias):
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
                    "ON core_chunk USING hnsw (embedding_vec vector_cosine_ops)"
                )
    except Exception as exc:
        logger.warning(
            "Skipping HNSW index on core_chunk.embedding_vec (%s: %s). "
            "Exact pgvector / in-Python search will still work.",
            type(exc).__name__,
            exc,
        )


def drop_hnsw_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_company_attendance_auto_freeze_and_more"),
    ]

    operations = [
        migrations.RunPython(create_hnsw_index, drop_hnsw_index),
    ]
