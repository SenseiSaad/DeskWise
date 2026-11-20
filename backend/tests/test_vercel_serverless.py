"""Verification tests for serverless (Vercel) deployment adaptations."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth import _cookie_kwargs
from core.models import Company, TeamRoom, User
from core.providers import GeminiProvider, get_expected_dim


class VercelServerlessTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_cron_maintenance_requires_secret(self):
        with patch.dict("os.environ", {"CRON_SECRET": ""}, clear=False):
            r = self.client.get("/api/cron/maintenance")
            self.assertEqual(r.status_code, 503)

        with patch.dict("os.environ", {"CRON_SECRET": "top-secret-123"}, clear=False):
            r_bad = self.client.get(
                "/api/cron/maintenance", HTTP_AUTHORIZATION="Bearer wrong"
            )
            self.assertEqual(r_bad.status_code, 401)

            r_ok = self.client.get(
                "/api/cron/maintenance", HTTP_AUTHORIZATION="Bearer top-secret-123"
            )
            self.assertEqual(r_ok.status_code, 200)
            self.assertTrue(r_ok.json()["ok"])

    @override_settings(EMBED_DIM=1024)
    def test_gemini_embed_uses_configured_output_dimensionality(self):
        self.assertEqual(get_expected_dim("gemini", "gemini-embedding-001"), 1024)
        prov = GeminiProvider("fake-key", "gemini-2.5-flash", "gemini-embedding-001")
        captured = {}

        def fake_json(url, payload=None, headers=None, timeout=30.0):
            captured["url"] = url
            captured["payload"] = payload
            return {"embeddings": [{"values": [0.1] * 1024}]}

        with patch("core.providers._json", side_effect=fake_json):
            vecs = prov.embed(["hello world"])
        self.assertIsNotNone(vecs)
        self.assertEqual(len(vecs), 1)
        self.assertEqual(captured["payload"]["requests"][0]["outputDimensionality"], 1024)

    @override_settings(SESSION_COOKIE_SECURE=False, COOKIE_SAMESITE="None", COOKIE_DOMAIN=".saadops.site")
    def test_cookie_kwargs_guards_samesite_none_without_secure(self):
        kw = _cookie_kwargs(300)
        self.assertEqual(kw["samesite"], "Lax")
        self.assertEqual(kw["domain"], ".saadops.site")

    @override_settings(SESSION_COOKIE_SECURE=True, COOKIE_SAMESITE="None", COOKIE_DOMAIN=None)
    def test_cookie_kwargs_allows_samesite_none_when_secure(self):
        kw = _cookie_kwargs(300)
        self.assertEqual(kw["samesite"], "None")
        self.assertTrue(kw["secure"])
        self.assertNotIn("domain", kw)

    @override_settings(SYNC_INDEXING=True, RATELIMIT_ENABLED=False)
    def test_team_chat_sync_returns_inline_deskwise_message(self):
        company = Company.objects.create(name="Vercel Co", slug="vercel-co")
        user = User.objects.create_user(
            username="alice",
            email="alice@vercel.test",
            password="Password123!",
            company=company,
            role="admin",
            full_name="Alice",
        )
        room = TeamRoom.objects.create(
            company=company, name="General", slug="general", scope="company", is_default=True
        )
        self.client.force_authenticate(user=user)
        with patch("core.team_chat.providers.get_chat_provider") as mock_prov:
            mock_prov.return_value.label = "gemini"
            mock_prov.return_value.chat_model = "gemini-2.5-flash"
            mock_prov.return_value.last_usage = {}
            mock_prov.return_value.available.return_value = True
            mock_prov.return_value.stream_chat.return_value = iter(["Hello from DeskWise!"])
            r = self.client.post(
                f"/api/team-chat/rooms/{room.id}/messages",
                {"content": "@DeskWise quick hello"},
                format="json",
            )
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertTrue(data["deskwise_triggered"])
        self.assertIsNotNone(data["deskwise_message"])
        self.assertEqual(data["deskwise_message"]["sender_type"], "deskwise")

    @override_settings(
        AWS_STORAGE_BUCKET_NAME="deskwise-docs",
        AWS_S3_ENDPOINT_URL="https://br-test.storage.c-1.us-east-2.aws.neon.tech",
        AWS_S3_REGION_NAME="us-east-2",
        AWS_ACCESS_KEY_ID="nak_test",
        AWS_SECRET_ACCESS_KEY="nsk_test",
    )
    def test_s3_client_uses_path_style_and_sigv4_for_custom_endpoints(self):
        from core.storage import _s3_client

        client = _s3_client()
        self.assertEqual(client._client_config.signature_version, "s3v4")
        self.assertEqual(client._client_config.s3.get("addressing_style"), "path")

    def test_gemini_3x_omits_thinking_budget_and_uses_live_fallback(self):
        import io
        import urllib.error

        seen_calls = []

        class _FakeSSE:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def __iter__(self):
                return iter([b'data: {"candidates":[{"content":{"parts":[{"text":"OK"}]}}]}\n'])

        def fake_open(url, payload=None, headers=None, method=None, timeout=30.0):
            seen_calls.append((url, payload))
            if "gemini-3.8-flash" in url:
                raise urllib.error.HTTPError(url, 503, "Unavailable", {}, io.BytesIO(b'{"error":{"message":"busy"}}'))
            return _FakeSSE()

        prov = GeminiProvider("fake-key", "gemini-3.8-flash")
        with patch("core.providers._open", side_effect=fake_open), patch("core.providers.time.sleep"):
            out = "".join(prov.stream_chat([{"role": "user", "content": "hi"}]))

        self.assertEqual(out, "OK")
        self.assertNotIn("thinkingConfig", seen_calls[0][1]["generationConfig"])
        self.assertTrue(any("gemini-3.5-flash-lite" in u for u, _ in seen_calls))
        self.assertFalse(any("gemini-2.5-flash-lite" in u for u, _ in seen_calls))

    @override_settings(IS_VERCEL=True, AWS_STORAGE_BUCKET_NAME="", SYNC_INDEXING=True, RATELIMIT_ENABLED=False)
    def test_vercel_upload_returns_ephemeral_notice_and_cron_prunes_old_uploads(self):
        import tempfile
        from datetime import timedelta
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone
        from core.models import Document

        with tempfile.TemporaryDirectory() as tmpdir, override_settings(DATA_DIR=tmpdir):
            company = Company.objects.create(name="Beta Co", slug="beta-co")
            user = User.objects.create_user(
                username="betaadmin",
                email="beta@vercel.test",
                password="Password123!",
                company=company,
                role="admin",
                full_name="Beta Admin",
            )
            self.client.force_authenticate(user=user)
            f = SimpleUploadedFile("temp_note.txt", b"temporary test file content", content_type="text/plain")
            resp = self.client.post("/api/documents/upload", {"file": f}, format="multipart")
            self.assertEqual(resp.status_code, 201)
            data = resp.json()
            self.assertIn("24 hours", data.get("ephemeral_notice", ""))

            # Create a protected default demo doc and backdate both past 24 hours
            demo_doc = Document.objects.create(
                company=company, filename="Default.md", stored_path="demo/Default.md",
                size=10, uploaded_by=user, indexing_status="ready",
            )
            old_ts = timezone.now() - timedelta(hours=30)
            Document.objects.filter(pk__in=[data["id"], demo_doc.pk]).update(created_at=old_ts)

            with patch.dict("os.environ", {"CRON_SECRET": "cron-test-key"}, clear=False):
                r = self.client.get("/api/cron/maintenance", HTTP_AUTHORIZATION="Bearer cron-test-key")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["pruned_ephemeral_docs"], 1)
            self.assertFalse(Document.objects.filter(pk=data["id"]).exists())
            self.assertTrue(Document.objects.filter(pk=demo_doc.pk).exists())


