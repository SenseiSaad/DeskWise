"""Unit tests for Stripe Billing, Checkout, Customer Portal, and Webhooks."""
from unittest.mock import patch, MagicMock

import pytest
from rest_framework.test import APIClient

from core import billing
from core.models import Company, Plan, User

pytestmark = pytest.mark.django_db


def test_billing_status_requires_auth(client):
    resp = client.get("/api/billing/status")
    assert resp.status_code == 401


def test_billing_status_authenticated(auth_client, make_company, make_user):
    company = make_company()
    user = make_user(company, email="user@acme.test", role="admin")
    client = auth_client(user)

    resp = client.get("/api/billing/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "has_stripe" in data
    assert "is_subscribed" in data
    assert data["is_subscribed"] is False


def test_billing_checkout_requires_admin(auth_client, make_company, make_user):
    company = make_company()
    member = make_user(company, email="member@acme.test", role="member")
    client = auth_client(member)

    resp = client.post("/api/billing/checkout", {"plan_id": 1}, format="json")
    assert resp.status_code == 403


def test_billing_checkout_requires_plan_id(auth_client, make_company, make_user):
    company = make_company()
    admin = make_user(company, email="admin@acme.test", role="admin")
    client = auth_client(admin)

    resp = client.post("/api/billing/checkout", {}, format="json")
    assert resp.status_code == 400
    assert "plan_id is required" in resp.json()["detail"]


def test_billing_checkout_free_tier_rejected(auth_client, make_company, make_user):
    company = make_company()
    admin = make_user(company, email="admin@acme.test", role="admin")
    client = auth_client(admin)
    free_plan = Plan.objects.get_or_create(name="Free", defaults={"price_usd": 0, "is_default": True})[0]

    with patch.object(billing, "is_stripe_configured", return_value=True):
        with patch.object(billing, "_init_stripe"):
            resp = client.post("/api/billing/checkout", {"plan_id": free_plan.id}, format="json")
            assert resp.status_code == 400
            assert "Free tier does not require checkout" in resp.json()["detail"]


def test_billing_checkout_creates_session_success(auth_client, make_company, make_user):
    company = make_company()
    admin = make_user(company, email="admin@acme.test", role="admin")
    client = auth_client(admin)
    paid_plan = Plan.objects.get_or_create(name="Starter", defaults={"price_usd": 15})[0]

    mock_session = MagicMock()
    mock_session.id = "cs_test_12345"
    mock_session.url = "https://checkout.stripe.com/pay/cs_test_12345"

    mock_customer = MagicMock()
    mock_customer.id = "cus_test_999"

    with patch.object(billing, "is_stripe_configured", return_value=True):
        with patch.object(billing, "_init_stripe"):
            with patch("stripe.Customer.create", return_value=mock_customer):
                with patch("stripe.checkout.Session.create", return_value=mock_session):
                    resp = client.post("/api/billing/checkout", {"plan_id": paid_plan.id}, format="json")
                    assert resp.status_code == 201
                    data = resp.json()
                    assert data["session_id"] == "cs_test_12345"
                    assert "checkout.stripe.com" in data["url"]


def test_billing_portal_session_success(auth_client, make_company, make_user):
    company = make_company()
    company.stripe_customer_id = "cus_existing_123"
    company.save()
    admin = make_user(company, email="admin@acme.test", role="admin")
    client = auth_client(admin)

    mock_portal = MagicMock()
    mock_portal.url = "https://billing.stripe.com/p/session/test"

    with patch.object(billing, "is_stripe_configured", return_value=True):
        with patch.object(billing, "_init_stripe"):
            with patch("stripe.billing_portal.Session.create", return_value=mock_portal):
                resp = client.post("/api/billing/portal", {}, format="json")
                assert resp.status_code == 200
                assert resp.json()["url"] == "https://billing.stripe.com/p/session/test"


def test_billing_webhook_checkout_completed(client, make_company, make_user):
    company = make_company()
    free_plan = Plan.objects.get_or_create(name="Free", defaults={"price_usd": 0, "is_default": True})[0]
    business_plan = Plan.objects.get_or_create(name="Business", defaults={"price_usd": 49})[0]
    company.plan = free_plan
    company.save()

    payload = {
        "id": "evt_test_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_abc",
                "customer": "cus_test_123",
                "subscription": "sub_test_456",
                "metadata": {
                    "company_id": str(company.id),
                    "plan_id": str(business_plan.id),
                },
            }
        },
    }

    with patch.object(billing, "_init_stripe"):
        with patch("stripe.Webhook.construct_event", return_value=payload):
            resp = client.post(
                "/api/billing/webhook",
                payload,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="t=123,v1=fake",
            )
            assert resp.status_code == 200

    company.refresh_from_db()
    assert company.plan.id == business_plan.id
    assert company.stripe_customer_id == "cus_test_123"
    assert company.stripe_subscription_id == "sub_test_456"


def test_billing_webhook_subscription_deleted(client, make_company):
    company = make_company()
    free_plan = Plan.objects.get_or_create(name="Free", defaults={"price_usd": 0, "is_default": True})[0]
    business_plan = Plan.objects.get_or_create(name="Business", defaults={"price_usd": 49})[0]
    company.plan = business_plan
    company.stripe_customer_id = "cus_cancel_1"
    company.stripe_subscription_id = "sub_cancel_1"
    company.save()

    payload = {
        "id": "evt_test_2",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_cancel_1",
                "customer": "cus_cancel_1",
                "metadata": {
                    "company_id": str(company.id),
                },
            }
        },
    }

    with patch.object(billing, "_init_stripe"):
        with patch("stripe.Webhook.construct_event", return_value=payload):
            resp = client.post(
                "/api/billing/webhook",
                payload,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="t=123,v1=fake",
            )
            assert resp.status_code == 200

    company.refresh_from_db()
    assert company.plan.name == "Free"
    assert company.stripe_subscription_id == ""


def test_plans_endpoint_never_fails(client):
    # Public plans endpoint returns 200 even on fresh/empty database
    resp = client.get("/api/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
