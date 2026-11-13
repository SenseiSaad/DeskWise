"""pgvector retrieval path, exercised against a REAL PostgreSQL + pgvector.

Skipped automatically on SQLite or on a Postgres server without pgvector. Run:

    docker run -d -p 55432:5432 -e POSTGRES_USER=openvault -e POSTGRES_PASSWORD=pw \
        -e POSTGRES_DB=openvault pgvector/pgvector:pg16
    DATABASE_URL=postgres://openvault:pw@localhost:55432/openvault pytest tests/test_pgvector.py
"""
import pytest
from django.conf import settings
from django.db import connection

from core import rag
from core.models import Chunk, Document

pytestmark = pytest.mark.django_db


def _pgvector_installed() -> bool:
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'core_chunk' AND column_name = 'embedding_vec'"
        )
        return cur.fetchone() is not None


@pytest.fixture(autouse=True)
def _require_pgvector(db):
    if not _pgvector_installed():
        pytest.skip("requires PostgreSQL with pgvector (core_chunk.embedding_vec)")
    rag._PGVECTOR_STATE.update(checked=False, ok=False)
    yield
    rag._PGVECTOR_STATE.update(checked=False, ok=False)


def _vec(axis: int, dim: int | None = None, scale: float = 1.0) -> list:
    """Unit-ish vector pointing along one axis (cosine-distinct per axis)."""
    dim = dim or settings.EMBED_DIM
    v = [0.0] * dim
    v[axis] = scale
    return v


def _doc(company, name="d.md", user=None):
    return Document.objects.create(company=company, filename=name, stored_path="s",
                                   uploaded_by=user)


def _chunk(doc, ord_, text, axis):
    c = Chunk.objects.create(document=doc, company=doc.company, ord=ord_, text=text,
                             embedding=rag._to_bytes(_vec(axis)))
    rag.persist_chunk_vectors([(c.pk, _vec(axis))])
    return c


def _stored_vec_dims(chunk_id):
    with connection.cursor() as cur:
        cur.execute("SELECT vector_dims(embedding_vec) FROM core_chunk WHERE id = %s",
                    [chunk_id])
        row = cur.fetchone()
    return row[0] if row else None


# ------------------------------------------------------------------ readiness
def test_pgvector_ready_true_with_extension_and_column():
    assert rag._pgvector_ready() is True
    assert rag._PGVECTOR_STATE == {"checked": True, "ok": True}


def test_hnsw_cosine_index_exists():
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'core_chunk' AND indexname = 'core_chunk_embedding_vec_hnsw'")
        row = cur.fetchone()
    assert row is not None, "HNSW index missing (migration 0025)"
    assert "USING hnsw" in row[0] and "vector_cosine_ops" in row[0]


# -------------------------------------------------------------- writing vectors
def test_persist_chunk_vectors_writes_column(make_company):
    company = make_company()
    doc = _doc(company)
    c = Chunk.objects.create(document=doc, company=company, ord=0, text="x", embedding=None)
    assert _stored_vec_dims(c.pk) is None  # NULL before the write

    written = rag.persist_chunk_vectors([(c.pk, _vec(3))])

    assert written == 1
    assert _stored_vec_dims(c.pk) == settings.EMBED_DIM


def test_persist_chunk_vectors_skips_none_and_empty(make_company):
    assert rag.persist_chunk_vectors([]) == 0
    assert rag.persist_chunk_vectors([(1, None)]) == 0


def test_persist_accepts_numpy_vectors(make_company):
    np = pytest.importorskip("numpy")
    company = make_company()
    c = Chunk.objects.create(document=_doc(company), company=company, ord=0, text="x")
    assert rag.persist_chunk_vectors([(c.pk, np.array(_vec(1), dtype=np.float32))]) == 1
    assert _stored_vec_dims(c.pk) == settings.EMBED_DIM


# ------------------------------------------------------------------ KNN shortlist
def test_shortlist_orders_by_cosine_distance(make_company):
    company = make_company()
    doc = _doc(company)
    near = _chunk(doc, 0, "near", axis=0)
    far = _chunk(doc, 1, "far", axis=1)

    result = rag._pg_shortlist({doc.id}, _vec(0), limit=10)

    assert list(result) == [near.id, far.id]
    assert result[near.id] == pytest.approx(0.0, abs=1e-6)
    assert result[far.id] == pytest.approx(1.0, abs=1e-6)  # orthogonal => distance 1


def test_shortlist_restricted_to_callers_document_set(make_company):
    company = make_company()
    allowed = _doc(company, "allowed.md")
    other = _doc(company, "other.md")  # same tenant, NOT in the caller's set
    a = _chunk(allowed, 0, "a", axis=0)
    o = _chunk(other, 0, "o-identical-vector", axis=0)  # would be a perfect match

    result = rag._pg_shortlist({allowed.id}, _vec(0), limit=10)

    assert set(result) == {a.id}
    assert o.id not in result


def test_shortlist_respects_limit_and_ignores_null_vectors(make_company):
    company = make_company()
    doc = _doc(company)
    for i in range(4):
        _chunk(doc, i, f"c{i}", axis=i)
    Chunk.objects.create(document=doc, company=company, ord=9, text="no vec", embedding=None)

    assert len(rag._pg_shortlist({doc.id}, _vec(0), limit=2)) == 2
    assert len(rag._pg_shortlist({doc.id}, _vec(0), limit=50)) == 4  # NULL row excluded


def test_shortlist_empty_inputs_return_empty(make_company):
    doc = _doc(make_company())
    assert rag._pg_shortlist(set(), _vec(0), 5) == {}
    assert rag._pg_shortlist({doc.id}, None, 5) == {}


# ------------------------------------------------------------ dimension mismatch
def test_shortlist_dimension_mismatch_returns_empty(make_company):
    doc = _doc(make_company())
    _chunk(doc, 0, "a", axis=0)
    wrong = _vec(0, dim=settings.EMBED_DIM + 1)
    assert rag._pg_shortlist({doc.id}, wrong, 5) == {}
    assert rag._pg_shortlist({doc.id}, wrong[:8], 5) == {}


def test_shortlist_dimension_mismatch_numpy_returns_empty(make_company):
    np = pytest.importorskip("numpy")
    doc = _doc(make_company())
    _chunk(doc, 0, "a", axis=0)
    assert rag._pg_shortlist({doc.id}, np.ones(7, dtype=np.float32), 5) == {}


def test_retrieve_falls_back_to_python_scan_on_dimension_mismatch(make_company, make_user,
                                                                  monkeypatch):
    company = make_company()
    user = make_user(company, role="admin")
    doc = _doc(company, user=user)
    Chunk.objects.create(document=doc, company=company, ord=0, embedding=None,
                         text="The pay cycle pays salaries on the 25th of each month.")
    # Query vector has the wrong width -> pgvector path declines -> Python scan + BM25.
    monkeypatch.setattr(rag, "embed", lambda texts: [_vec(0, dim=settings.EMBED_DIM + 5)])

    chunks = rag.retrieve(user, "pay cycle salaries")

    assert [c.text for c in chunks] == ["The pay cycle pays salaries on the 25th of each month."]


# --------------------------------------------------------------- cross-tenant
def test_shortlist_never_returns_other_tenants_chunks(make_company):
    a_co, b_co = make_company("Tenant A"), make_company("Tenant B")
    a_doc, b_doc = _doc(a_co, "a.md"), _doc(b_co, "b.md")
    a_chunk = _chunk(a_doc, 0, "a secret", axis=5)
    b_chunk = _chunk(b_doc, 0, "b secret", axis=0)  # exact match for the query

    result = rag._pg_shortlist({a_doc.id}, _vec(0), limit=10)

    assert set(result) == {a_chunk.id}
    assert b_chunk.id not in result


def test_retrieve_end_to_end_isolates_tenants(make_company, make_user, monkeypatch):
    a_co, b_co = make_company("Tenant A"), make_company("Tenant B")
    a_user = make_user(a_co, role="admin")
    b_user = make_user(b_co, role="admin")
    a_doc, b_doc = _doc(a_co, "a.md", a_user), _doc(b_co, "b.md", b_user)
    a_chunk = _chunk(a_doc, 0, "alpha handbook leave policy", axis=5)
    b_chunk = _chunk(b_doc, 0, "beta confidential leave policy", axis=0)
    # The query embeds to B's vector, so a leaky KNN would surface B's chunk for A.
    monkeypatch.setattr(rag, "embed", lambda texts: [_vec(0)])

    a_results = rag.retrieve(a_user, "leave policy")
    b_results = rag.retrieve(b_user, "leave policy")

    assert {c.id for c in a_results} == {a_chunk.id}
    assert {c.id for c in b_results} == {b_chunk.id}
