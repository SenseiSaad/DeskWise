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
