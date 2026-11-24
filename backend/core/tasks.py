"""Celery tasks for background document work.

Indexing moves off the request path: upload → queue → worker. Everything here
is idempotent and re-entrancy safe (index_document deletes and rebuilds the
document's chunks), so a requeue can never double-index.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

log = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def index_document_task(self, document_id: int):
    """Extract, chunk and embed one document; flips indexing_status."""
    from . import rag, storage
    from .uploads import index_error_message
    from .models import Document

    try:
        doc = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        log.warning("index_document_task: document %s vanished", document_id)
        return None
    try:
        raw = storage.read_bytes(doc.stored_path, base_dir=settings.DATA_DIR)
        n = rag.index_document(doc, raw)
        doc.indexing_status = "ready" if n >= 0 else "failed"
        doc.index_error = ""
    except Exception as exc:
        doc.indexing_status = "failed"
        doc.index_error = index_error_message(exc)
    finally:
        doc.save(update_fields=["indexing_status", "index_error"])
    return doc.indexing_status


@shared_task
def requeue_stuck_documents(max_age_minutes: int = 30) -> int:
    """Re-dispatch documents stuck in 'pending' (worker died mid-index).

    Returns the number of requeued documents; beat runs this every 15 minutes.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .models import Document

    cutoff = timezone.now() - timedelta(minutes=max_age_minutes)
    stuck = list(
        Document.objects.filter(indexing_status="pending", updated_at__lt=cutoff)
        .values_list("id", flat=True)
    )
    for document_id in stuck:
        index_document_task.delay(document_id)
    if stuck:
        log.warning("requeued %d stuck pending document(s)", len(stuck))
    return len(stuck)


@shared_task
def prune_asklogs_task(days: int = 90) -> int:
    """Nightly retention for AskLog rows (wraps the management command)."""
    from django.core.management import call_command

    from io import StringIO
    out = StringIO()
    call_command("prune_asklogs", days=days, stdout=out)
    log.info(out.getvalue().strip())
    return 1


@shared_task
def purge_expired_pending_uploads(limit: int = 500, max_batches: int = 5) -> int:
    """AI-04 / S7-06: delete bucket objects for presigned uploads that were
    never confirmed. A PendingUpload outlives its 5-minute PUT URL (15 minutes),
    and confirm refuses expired rows, so these objects can never become
    documents.

    The pending row is the only record that the object exists, so it is removed
    ONLY after the object is confirmed gone. A failed deletion leaves the row in
    place (it stays expired, so it can't be confirmed) and the next run retries.
    Rows are walked by primary key in batches, so rows that keep failing can't
    starve the ones behind them.

    Runs hourly from beat and on every /api/cron/maintenance call."""
    from django.utils import timezone

    from . import storage
    from .models import Document, PendingUpload

    if not storage.is_s3_enabled():
        return 0
    now = timezone.now()
    purged = failed = 0
    last_pk = 0
    for _ in range(max(1, max_batches)):
        batch = list(
            PendingUpload.objects.filter(consumed=False, expires_at__lt=now, pk__gt=last_pk)
            .order_by("pk")[:limit]
        )
        if not batch:
            break
        for pending in batch:
            last_pk = pending.pk
            if Document.objects.filter(stored_path=pending.key).exists():
                pending.delete()  # the object belongs to a document; keep it
                continue
            if storage.delete_checked(pending.key):
                pending.delete()
                purged += 1
            else:
                failed += 1
        if len(batch) < limit:
            break
    if purged:
        log.info("purged %d expired unconfirmed upload(s)", purged)
    if failed:
        log.warning("%d expired upload object(s) could not be deleted; will retry", failed)
    return purged
