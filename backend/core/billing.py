"""Stripe billing and subscription integration.

Supports Stripe Sandbox (test mode) and Live mode.
Provides:
- Self-serve Stripe Checkout sessions for subscription upgrades.
- Stripe Customer Portal for managing/cancelling cards and subscriptions.
- Webhook handler for automated plan synchronization on payment/cancellation.
- Graceful offline fallback (bank transfer / manual admin approval) when
  Stripe keys are not configured.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import stripe
from django.conf import settings
from django.db import transaction

from .models import AuditLog, Company, Plan, User

logger = logging.getLogger(__name__)


def is_stripe_configured() -> bool:
    """Return True if a Stripe secret key is present."""
    return bool(getattr(settings, "STRIPE_SECRET_KEY", "").strip())


def _init_stripe() -> None:
    """Initialize Stripe API client with secret key."""
    key = getattr(settings, "STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise ValueError(
            "Stripe is not configured. Set STRIPE_SECRET_KEY in your environment or .env file."
        )
    stripe.api_key = key


def create_checkout_session(
    user: User,
    plan_id: int,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for upgrading a company's subscription.

    Args:
        user: The authenticated company admin.
        plan_id: ID of the Plan model to subscribe to.
        success_url: Redirect URL on payment completion.
        cancel_url: Redirect URL on checkout cancellation.

    Returns:
        dict with "url" (Stripe hosted checkout URL) and "session_id".
    """
    _init_stripe()

    company = getattr(user, "company", None)
    if not company:
        raise ValueError("User must belong to a company to manage subscriptions.")

    plan = Plan.objects.filter(pk=plan_id, is_active=True).first()
    if not plan:
        raise ValueError("Plan not found or inactive.")

    if plan.price_usd == 0:
        raise ValueError("Free tier does not require checkout. It is already attached.")

    # Prevent subscribing to the exact same plan if already active
    if company.plan and company.plan.id == plan.id and company.stripe_subscription_id:
        raise ValueError(
            f"Already subscribed to {plan.name}. Use the Customer Portal to manage or cancel."
        )

    # Validate redirect URLs BEFORE making any outbound Stripe API calls.
    base_url = (getattr(settings, "PUBLIC_BASE_URL", "") or "http://localhost:3000").rstrip("/")
    default_success = f"{base_url}/workspace/usage?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    default_cancel = f"{base_url}/workspace/usage?checkout=cancelled"
    success_url = _validate_redirect_url(success_url, default_success)
    cancel_url = _validate_redirect_url(cancel_url, default_cancel)

    # 1. Retrieve or create Stripe customer with concurrency lock to prevent duplicates
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=company.id)
        customer_id = (company.stripe_customer_id or "").strip()
        if not customer_id:
            try:
                # Query Stripe to prevent duplicate customer creation on rapid clicks
                existing = stripe.Customer.search(
                    query=f"metadata['company_id']:'{company.id}'",
                    limit=1,
                )
                if existing and existing.data:
                    customer_id = existing.data[0].id
            except Exception:
                pass

            if not customer_id:
                customer = stripe.Customer.create(
                    email=user.email,
                    name=company.name,
                    metadata={
                        "company_id": str(company.id),
                        "created_by_user": str(user.id),
                    },
                )
                customer_id = customer.id

            company.stripe_customer_id = customer_id
            company.save(update_fields=["stripe_customer_id"])

    # 2. Build line items
    # If plan has an explicit stripe_price_id, use it; otherwise generate dynamic price_data.
    stripe_price_id = getattr(plan, "stripe_price_id", "").strip()
    if stripe_price_id:
        line_items = [{"price": stripe_price_id, "quantity": 1}]
    else:
        line_items = [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Deskwise {plan.name} Plan",
                        "description": (
                            f"Subscription to {plan.name} tier: "
                            f"{plan.max_members or 'Unlimited'} members, "
                            f"{plan.max_documents or 'Unlimited'} docs, "
                            f"{plan.monthly_ask_limit or 'Unlimited'} queries/month."
                        ),
                    },
                    "unit_amount": plan.price_usd * 100,  # cents
                    "recurring": {
                        "interval": "month" if plan.billing_period == "month" else "year"
                    },
                },
                "quantity": 1,
            }
        ]

    # 3. Success and cancel redirects (strictly validated against trusted origins)
    base_url = (getattr(settings, "PUBLIC_BASE_URL", "") or "http://localhost:3000").rstrip("/")
    default_success = f"{base_url}/workspace/usage?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    default_cancel = f"{base_url}/workspace/usage?checkout=cancelled"
    success_url = _validate_redirect_url(success_url, default_success)
    cancel_url = _validate_redirect_url(cancel_url, default_cancel)

    # 4. Create Checkout Session (dynamic payment methods managed by Stripe dashboard)
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(company.id),
        metadata={
            "company_id": str(company.id),
            "plan_id": str(plan.id),
            "user_id": str(user.id),
        },
        subscription_data={
            "metadata": {
                "company_id": str(company.id),
                "plan_id": str(plan.id),
            }
        },
    )

    return {"url": session.url, "session_id": session.id}


def _validate_redirect_url(url: str | None, fallback: str) -> str:
    """Ensure checkout/portal redirect URLs match our trusted PUBLIC_BASE_URL origin."""
    if not url:
        return fallback
    from urllib.parse import urlparse
    parsed = urlparse(url)
    base = urlparse((getattr(settings, "PUBLIC_BASE_URL", "") or "http://localhost:3000").rstrip("/"))
    allowed_hosts = {base.netloc.lower()} if base.netloc else set()
    for origin in getattr(settings, "CORS_ALLOWED_ORIGINS", []) or []:
        o = urlparse(origin)
        if o.netloc:
            allowed_hosts.add(o.netloc.lower())
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in allowed_hosts:
        raise ValueError("Redirect URL must match a trusted application origin.")
    return url


def _is_paid_checkout(session: dict[str, Any]) -> bool:
    ps = session.get("payment_status")
    return ps is None or ps in ("paid", "no_payment_required")


def create_portal_session(user: User, return_url: str | None = None) -> dict[str, str]:
    """Create a Stripe Customer Portal session so customers can manage cards & subscriptions."""
    _init_stripe()

    company = getattr(user, "company", None)
    if not company:
        raise ValueError("User must belong to a company to access billing portal.")

    customer_id = (company.stripe_customer_id or "").strip()
    if not customer_id:
        raise ValueError("Company does not have a linked Stripe customer. Subscribe first.")

    base_url = (getattr(settings, "PUBLIC_BASE_URL", "") or "http://localhost:3000").rstrip("/")
    return_url = _validate_redirect_url(return_url, f"{base_url}/workspace/usage")

    portal_session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return {"url": portal_session.url}


def handle_webhook(payload: bytes, sig_header: str | None) -> dict[str, Any]:
    """Verify and process incoming Stripe webhook events.

    Updates company plan and subscription state automatically.
    """
    _init_stripe()
    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "").strip()
    is_prod = getattr(settings, "IS_PRODUCTION", False)

    if is_prod and not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET must be configured in production.")
        raise ValueError("Webhook secret is not configured on the server.")

    if not sig_header:
        raise ValueError("Missing Stripe-Signature header.")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        raise ValueError(f"Invalid webhook signature: {exc}")

    event_type = event.get("type", "")
    data_object = event.get("data", {}).get("object", {})
    logger.info("Received Stripe webhook event: %s", event_type)

    if event_type == "checkout.session.completed":
        if not _is_paid_checkout(data_object):
            logger.warning("Ignoring unpaid checkout.session.completed status=%s", data_object.get("payment_status"))
            return {"status": "ignored", "event": event_type}
        _handle_checkout_completed(data_object)
    elif event_type in ("customer.subscription.deleted", "customer.subscription.cancelled"):
        _handle_subscription_deleted(data_object)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data_object)

    return {"status": "success", "event": event_type}


def _handle_checkout_completed(session: dict[str, Any]) -> None:
    """Handle successful checkout by linking subscription and upgrading plan."""
    metadata = session.get("metadata") or {}
    company_id = metadata.get("company_id")
    plan_id = metadata.get("plan_id")
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    if not company_id:
        logger.warning("checkout.session.completed missing company_id metadata")
        return

    with transaction.atomic():
        company = Company.objects.filter(pk=company_id).select_for_update().first()
        if not company:
            logger.error("Company %s not found for completed checkout session", company_id)
            return

        if plan_id:
            plan = Plan.objects.filter(pk=plan_id, is_active=True).first()
            if plan:
                company.plan = plan

        if customer_id:
            company.stripe_customer_id = str(customer_id)
        if subscription_id:
            company.stripe_subscription_id = str(subscription_id)

        company.save(update_fields=["plan", "stripe_customer_id", "stripe_subscription_id"])

        AuditLog.objects.create(
            company=company,
            action="stripe_checkout_completed",
            detail=f"Subscribed to {company.plan.name if company.plan else 'Plan'} (sub: {subscription_id})",
            ip="stripe-webhook",
        )
        logger.info("Upgraded company %s to plan %s via Stripe checkout", company.name, company.plan)


def _handle_subscription_deleted(subscription: dict[str, Any]) -> None:
    """Revert company to default Free plan when subscription is canceled or lapses."""
    sub_id = subscription.get("id")
    customer_id = subscription.get("customer")
    metadata = subscription.get("metadata") or {}
    company_id = metadata.get("company_id")

    company = None
    if company_id:
        company = Company.objects.filter(pk=company_id).first()
    if not company and sub_id:
        company = Company.objects.filter(stripe_subscription_id=sub_id).first()
    if not company and customer_id:
        company = Company.objects.filter(stripe_customer_id=customer_id).first()

    if not company:
        logger.warning("Could not find company for deleted subscription %s", sub_id)
        return

    with transaction.atomic():
        default_plan = Plan.default()
        company.plan = default_plan
        company.stripe_subscription_id = ""
        company.save(update_fields=["plan", "stripe_subscription_id"])

        AuditLog.objects.create(
            company=company,
            action="stripe_subscription_cancelled",
            detail=f"Subscription {sub_id} deleted. Reverted to {default_plan.name} plan.",
            ip="stripe-webhook",
        )
        logger.info("Reverted company %s to %s plan after Stripe cancellation", company.name, default_plan)


def _handle_subscription_updated(subscription: dict[str, Any]) -> None:
    """Track status updates (e.g. past_due, active, trialing)."""
    sub_id = subscription.get("id")
    status = subscription.get("status", "")
    customer_id = subscription.get("customer")

    company = Company.objects.filter(stripe_subscription_id=sub_id).first()
    if not company and customer_id:
        company = Company.objects.filter(stripe_customer_id=customer_id).first()

    if company:
        AuditLog.objects.create(
            company=company,
            action="stripe_subscription_status",
            detail=f"Subscription {sub_id} status changed to {status}",
            ip="stripe-webhook",
        )
        logger.info("Company %s subscription %s status: %s", company.name, sub_id, status)
