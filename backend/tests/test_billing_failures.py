"""Failure path and edge case tests for core/billing.py."""
import json
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings

from core import billing
from core.models import Company, Plan, User

pytestmark = pytest.mark.django_db


def test_init_stripe_raises_when_no_key(settings):
    settings.STRIPE_SECRET_KEY = ""
    with pytest.raises(ValueError, match="Stripe is not configured"):
        billing._init_stripe()


def test_create_checkout_session_no_company(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    user = User.objects.create(email="nocompany@test.com", role="admin")
    with pytest.raises(ValueError, match="User must belong to a company"):
        billing.create_checkout_session(user, plan_id=1)


def test_create_checkout_session_invalid_plan(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    company = Company.objects.create(name="Test Co", slug="test-co")
    user = User.objects.create(email="admin@test.com", company=company, role="admin")
    with pytest.raises(ValueError, match="Plan not found or inactive"):
        billing.create_checkout_session(user, plan_id=99999)


def test_create_checkout_session_already_subscribed(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    plan = Plan.objects.create(name="Pro", price_usd=29, is_active=True)
    company = Company.objects.create(name="Test Co", slug="test-co-sub", plan=plan, stripe_subscription_id="sub_active_123")
    user = User.objects.create(email="admin@sub.com", company=company, role="admin")

    with pytest.raises(ValueError, match="Already subscribed to Pro"):
        billing.create_checkout_session(user, plan_id=plan.id)


def test_create_checkout_session_reuses_existing_customer(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    plan = Plan.objects.create(name="Scale", price_usd=99, billing_period="year", is_active=True)
    plan.stripe_price_id = "price_scale_123"
    company = Company.objects.create(name="Search Co", slug="search-co")
    user = User.objects.create(email="admin@search.com", company=company, role="admin")

    mock_search = MagicMock()
    mock_cust = MagicMock()
    mock_cust.id = "cus_found_search"
    mock_search.data = [mock_cust]

    mock_session = MagicMock()
    mock_session.id = "cs_search_1"
    mock_session.url = "https://checkout.stripe.com/search"

    with patch("stripe.Customer.search", return_value=mock_search):
        with patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create_sess:
            res = billing.create_checkout_session(user, plan_id=plan.id)
            assert res["session_id"] == "cs_search_1"
            company.refresh_from_db()
            assert company.stripe_customer_id == "cus_found_search"
            mock_create_sess.assert_called_once()
            call_kwargs = mock_create_sess.call_args[1]
            assert call_kwargs["line_items"][0]["price_data"]["unit_amount"] == 9900
            assert call_kwargs["line_items"][0]["price_data"]["recurring"]["interval"] == "year"


def test_create_portal_session_raises_when_no_customer(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    company = Company.objects.create(name="No Cust Co", slug="no-cust-co")
    user = User.objects.create(email="nocust@test.com", company=company, role="admin")
    with pytest.raises(ValueError, match="does not have a linked Stripe customer"):
        billing.create_portal_session(user)


def test_handle_webhook_missing_sig_when_secret_configured(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    with pytest.raises(ValueError, match="Missing Stripe-Signature header"):
        billing.handle_webhook(b'{"test": 1}', sig_header=None)


def test_handle_webhook_invalid_signature(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    with patch("stripe.Webhook.construct_event", side_effect=Exception("Bad signature")):
        with pytest.raises(ValueError, match="Invalid webhook signature"):
            billing.handle_webhook(b'{"test": 1}', sig_header="t=123,v1=bad")


def test_handle_webhook_dev_json_parse(settings):
    # Decision D-12 / F-15: unsigned webhooks are ALWAYS rejected even without STRIPE_WEBHOOK_SECRET.
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    settings.STRIPE_WEBHOOK_SECRET = ""

    with pytest.raises(ValueError, match="Missing Stripe-Signature header"):
        billing.handle_webhook(b"not-json", sig_header=None)

    # Signed subscription updated event succeeds
    company = Company.objects.create(name="Sub Update Co", slug="sub-update-co", stripe_subscription_id="sub_live_999")
    payload = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_live_999",
                "status": "past_due",
                "customer": "cus_999",
            }
        },
    }
    with patch("stripe.Webhook.construct_event", return_value=payload):
        res = billing.handle_webhook(json.dumps(payload).encode("utf-8"), sig_header="t=1,v1=ok")
    assert res["status"] == "success"
    assert res["event"] == "customer.subscription.updated"


def test_handle_webhook_missing_company(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    payload = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_missing",
                "metadata": {"company_id": "99999"},
            }
        },
    }
    with patch("stripe.Webhook.construct_event", return_value=payload):
        res = billing.handle_webhook(json.dumps(payload).encode("utf-8"), sig_header="t=1,v1=ok")
    assert res["status"] == "success"
