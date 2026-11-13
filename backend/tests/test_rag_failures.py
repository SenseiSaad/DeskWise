"""Failure path and boundary condition tests for core/rag.py:
extraction edge cases, corrupt files, context truncation, and retrieval fallbacks."""
import io
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings

from core import rag
from core.models import Chunk, Company, Document, User

pytestmark = pytest.mark.django_db


def test_extract_text_plain_text():
    raw = b"This is a simple plain text document with company policies."
    txt = rag.extract_text(raw, "policy.txt", "text/plain")
    assert "company policies" in txt


def test_extract_text_markdown():
    raw = b"# Heading 1\n\n- Item 1\n- Item 2"
    txt = rag.extract_text(raw, "notes.md", "text/markdown")
    assert "Heading 1" in txt


def test_index_document_empty_bytes():
    company = Company.objects.create(name="Empty Co", slug="empty-co")
    doc = Document.objects.create(company=company, filename="empty.txt", stored_path="empty.txt")
    count = rag.index_document(doc, b"")
    assert count == 0
    assert doc.indexing_status == "ready"
    assert Chunk.objects.filter(document=doc).count() == 0


def test_index_document_corrupt_raw_sets_status():
    company = Company.objects.create(name="Fail Co", slug="fail-co")
    doc = Document.objects.create(company=company, filename="fail.pdf", stored_path="fail.pdf")

    # When extraction or chunking raises an unexpected exception
    with patch("core.rag.extract_text", side_effect=RuntimeError("Extraction crashed")):
        with pytest.raises(RuntimeError):
            rag.index_document(doc, b"fake-pdf-content")


def test_retrieve_empty_query_returns_empty():
    company = Company.objects.create(name="Ret Co", slug="ret-co")
    user = User.objects.create(email="ret@test.com", company=company, role="employee")
    res = rag.retrieve(user, "")
    assert res == []


def test_retrieve_no_chunks_returns_empty():
    company = Company.objects.create(name="No Chunks Co", slug="no-chunks-co")
    user = User.objects.create(email="nochunks@test.com", company=company, role="employee")
    res = rag.retrieve(user, "what is the remote work policy?")
    assert res == []


def test_build_messages_truncates_giant_context(settings):
    settings.RAG_MAX_CONTEXT_CHARS = 3000
    company = Company.objects.create(name="Trunc Co", slug="trunc-co")
    doc = Document.objects.create(company=company, filename="huge.txt", stored_path="huge.txt")

    # Create several large chunks
    chunks = [
        Chunk(document=doc, company=company, ord=i, text=f"Chunk {i}: " + ("data " * 1000))
        for i in range(10)
    ]

    messages = rag.build_messages(chunks, "test question")
    assert len(messages) >= 2
    user_content = messages[-1]["content"]
    assert "Chunk 0" in user_content
    # Subsequent chunks were truncated and excluded from the context
    assert "Chunk 1" not in user_content
    assert "Chunk 9" not in user_content
