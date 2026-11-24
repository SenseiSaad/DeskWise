"""Database tables. Every tenant-owned row carries `company` — that FK is the
backbone of multi-tenant isolation (one company can never see another's data)."""
import hashlib
import json
import os
import secrets
import string
import threading
from datetime import timedelta, timezone as dt_timezone

from django.contrib.auth.models import (
    AbstractBaseUser, BaseUserManager, PermissionsMixin,
)
from django.db import IntegrityError, connection, models, transaction
from django.db.models import Q
from django.utils import timezone

from .crypto import decrypt_secret, encrypt_secret


class _EncryptedFieldMixin:
    """Transparently encrypt field values at rest; legacy plaintext rows still read."""

    def from_db_value(self, value, expression, connection):
        return decrypt_secret(value)

    def get_prep_value(self, value):
        return encrypt_secret(super().get_prep_value(value))


class EncryptedCharField(_EncryptedFieldMixin, models.CharField):
    """CharField whose value is encrypted at rest, transparently."""


class EncryptedTextField(_EncryptedFieldMixin, models.TextField):
    """TextField whose value is encrypted at rest, transparently."""


_COMPANY_CODE_ALPHABET = string.ascii_uppercase + string.digits


def generate_company_code():
    """Return a short, human-shareable identifier unique to one company.

    Eight characters (36^8 ≈ 2.8 trillion) keeps the directory endpoints
    un-enumerable while staying typeable by hand.
    """
    return "".join(secrets.choice(_COMPANY_CODE_ALPHABET) for _ in range(8))


class Company(models.Model):
    """One tenant. Every document, chunk, user and audit row hangs off a company,
    and queries always filter by it, so tenants stay fully isolated."""
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    # "Type of company" for platform-level subscription reporting only.
    industry = models.CharField(max_length=80, blank=True, default="")
    # Short identifier shown to admins and used for cross-company lookup.
    # It is intentionally not derived from the company name, so it is safe to
    # share without exposing a predictable tenant URL. 8 chars since the
    # directory hardening; older 5-char codes keep working.
    access_code = models.CharField(max_length=8, unique=True, null=True, blank=True)
    # --- optional company profile (collected at registration, shown in the workspace) ---
    website = models.CharField(max_length=200, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    # Company-level fields used when filling document templates. Only non-empty
    # values are ever injected into a prompt or a generated document.
    hr_email = models.EmailField(blank=True, default="")
    signature = models.TextField(blank=True, default="")
    tone = models.CharField(max_length=80, blank=True, default="")
    # Seat limit for member accounts. NULL means unlimited; when set, admins can't
    # add more members than this (enforced in the users() view, never crashes).
    max_employees = models.PositiveIntegerField(null=True, blank=True)
    # Subscription tier. Governed by Plan limits; every new company starts on
    # the default (Free) plan. Platform admins can move a company between plans.
    plan = models.ForeignKey(
        "Plan", on_delete=models.PROTECT, related_name="companies", null=True, blank=True,
    )
    # Stripe linkage (blank when billing is handled offline / not configured).
    stripe_customer_id = models.CharField(max_length=120, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=120, blank=True, default="")
    subscription_status = models.CharField(max_length=30, blank=True, default="")
    # Feature flags
    enable_attendance = models.BooleanField(default=True)
    attendance_auto_freeze = models.BooleanField(default=False)  # warn-only by default (False = no auto-deactivation)
    enable_docgen = models.BooleanField(default=True)
    enable_ai_chat = models.BooleanField(default=True)
    enable_team_chat = models.BooleanField(default=True)
    enable_external_sharing = models.BooleanField(default=True)
    require_doc_approval = models.BooleanField(default=False)
    redact_pii_for_llm = models.BooleanField(default=True)
    doc_retention_days = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.access_code:
            # The collision loop also covers the very small chance of a code
            # collision during imports or local demo seeding.
            while True:
                code = generate_company_code()
                if not type(self).objects.filter(access_code=code).exclude(pk=self.pk).exists():
                    self.access_code = code
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    """Custom manager: users are keyed by email (there is no separate username field
    for enterprise accounts) and passwords are always hashed via set_password."""
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        cleaned = self.normalize_email(email).strip().lower()
        user = self.model(email=cleaned, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", "admin")
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """An enterprise account. `role` is the security level and `title` is a
    display job label used when selecting document recipients."""
    ROLES = [
        ("admin", "admin"),
        ("employee", "employee"),
        ("viewer", "viewer"),
    ]

    # Reply-language preference for the AI assistant (global defaults + opt-in languages).
    LANGUAGES = [
        ("en", "English"),
        ("es", "Spanish"),
        ("fr", "French"),
        ("de", "German"),
        ("ar", "Arabic"),
        ("pt", "Portuguese"),
        ("ur", "Roman Urdu"),
    ]

    email = models.EmailField(unique=True)
    # Retained nullable for compatibility with pre-existing database rows; all
    # current enterprise authentication uses email.
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=200, blank=True, default="")
    # Display job title only (CEO, CTO, HR, ...). This is a label, NOT a permission:
    # what a user can actually do is decided by `role` below.
    title = models.CharField(max_length=120, blank=True, default="")
    # one employee belongs to exactly ONE company and cannot log into another
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="users", null=True, blank=True
    )
    department = models.ForeignKey(
        "Department", on_delete=models.SET_NULL, related_name="members",
        null=True, blank=True,
    )
    role = models.CharField(max_length=20, choices=ROLES, default="employee")
    CLEARANCE_LEVELS = [
        ("standard", "Standard"),
        ("internal", "Internal"),
        ("confidential", "Confidential"),
    ]
    # Explicit sensitivity clearance. Blank derives from role:
    # viewer -> standard, employee -> internal, admin -> confidential.
    clearance = models.CharField(max_length=20, choices=CLEARANCE_LEVELS, blank=True, default="")
    # Delegated department sub-admin (can manage/approve docs & members inside own department only).
    is_dept_admin = models.BooleanField(default=False)
    # Bumped on password reset, deactivation, role/dept changes, or logout-all to invalidate active JWTs.
    token_version = models.PositiveIntegerField(default=1)
    # Platform root admin: complete authority over every tenant, the platform
    # LLM default, plans and company plan assignment. Granted via the
    # `create_platform_admin` management command — never hardcoded to an email.
    is_platform_admin = models.BooleanField(default=False)
    # Profile fields used for template filling (all optional; only non-empty
    # values are injected). role/department stay admin-controlled because they
    # are permission boundaries, not display labels.
    manager = models.CharField(max_length=200, blank=True, default="")
    employee_id = models.CharField(max_length=60, blank=True, default="")
    join_date = models.DateField(null=True, blank=True)
    # TOTP two-factor secrets (RFC 6238). Required for platform-admin sign-ins;
    # see core.mfa. The secret is encrypted at rest like LLMConfig.api_key.
    mfa_secret = EncryptedCharField(max_length=64, blank=True, default="")
    mfa_enabled = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    # Google account identity (the ID token's `sub`), bound on first Google
    # sign-in. Emails can be reassigned; `sub` never is (AUTHN-01).
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True)
    language = models.CharField(max_length=2, choices=LANGUAGES, default="en")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    @property
    def effective_clearance(self) -> str:
        if self.clearance in ("standard", "internal", "confidential"):
            return self.clearance
        if self.role == "admin":
            return "confidential"
        if self.role == "viewer":
            return "standard"
        return "internal"

    def __str__(self):
        return self.email


class Department(models.Model):
    """A team inside one company. Documents can be scoped to a department so
    only its members (plus explicit grantees) can read them."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("company", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.company.name} / {self.name}"


class Plan(models.Model):
    """A subscription tier. Limits are enforced server-side (seats on member
    creation, document count + storage on upload, monthly asks on /api/ask).
    Prices are in USD per month; the Free plan is auto-attached to every new
    company. Local payment methods and a PKR equivalent are handled at
    checkout, not in this table."""
    name = models.CharField(max_length=60, unique=True)
    price_usd = models.PositiveIntegerField(default=0)
    billing_period = models.CharField(max_length=20, default="month")
    max_members = models.PositiveIntegerField(null=True, blank=True)      # None = unlimited
    max_documents = models.PositiveIntegerField(null=True, blank=True)
    storage_mb = models.PositiveIntegerField(null=True, blank=True)
    monthly_ask_limit = models.PositiveIntegerField(null=True, blank=True)
    # Extra capabilities a plan unlocks (checked in views, not just shown).
    allow_versions = models.BooleanField(default=False)
    allow_departments = models.BooleanField(default=False)
    allow_custom_llm = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @classmethod
    def default(cls):
        """The default (Free) plan. Auto-provisions it on fresh installs so a
        missing seed command can never block company registration."""
        plan = cls.objects.filter(is_default=True, is_active=True).first()
        if plan is None:
            plan = cls.objects.filter(name="Free").first()
        if plan is None:
            plan = cls.objects.create(
                name="Free", price_usd=0, billing_period="month",
                max_members=3, max_documents=20, storage_mb=512, monthly_ask_limit=50,
                is_default=True,
            )
        return plan


class OneTimeToken(models.Model):
    """Single-purpose, expiring, hashed token for email verification and
    password resets. The raw token only ever exists in the emailed link."""
    # "invite" is also issued/consumed for 7-day email-bound member invitations.
    PURPOSES = [("verify_email", "verify_email"), ("password_reset", "password_reset")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="one_time_tokens")
    purpose = models.CharField(max_length=20, choices=PURPOSES)
    token_hash = models.CharField(max_length=64, unique=True)  # sha256 hex of the raw token
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        from django.utils import timezone
        return self.used_at is None and self.expires_at > timezone.now()

    @classmethod
    def issue(cls, user, purpose, minutes=60):
        import hashlib
        from django.utils import timezone
        raw = secrets.token_urlsafe(32)
        obj = cls.objects.create(
            user=user, purpose=purpose, token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=minutes),
        )
        return obj, raw

    @classmethod
    def peek(cls, raw, purpose):
        """The token row when it is currently valid, without consuming it."""
        import hashlib
        h = hashlib.sha256((raw or "").encode()).hexdigest()
        obj = cls.objects.select_related("user").filter(token_hash=h, purpose=purpose).first()
        return obj if obj and obj.is_valid() else None

    @classmethod
    def consume(cls, raw, purpose):
        """Return the token row when valid, marking it used. None otherwise.

        The write is a conditional UPDATE (used_at IS NULL, not expired), so two
        concurrent requests can never both consume one token."""
        import hashlib
        from django.utils import timezone
        h = hashlib.sha256((raw or "").encode()).hexdigest()
        obj = cls.objects.filter(token_hash=h, purpose=purpose).first()
        if not obj or not obj.is_valid():
            return None
        now = timezone.now()
        claimed = cls.objects.filter(
            pk=obj.pk, used_at__isnull=True, expires_at__gt=now,
        ).update(used_at=now)
        if claimed != 1:
            return None
        obj.used_at = now
        return obj


class Document(models.Model):
    """An uploaded file owned by one company. Access is company-wide or
    explicitly restricted to named users; `is_okf` marks a trusted AI note."""
    # 30 subject genres for the public knowledge library, plus the legacy
    # business categories (kept so enterprise uploads still have those options).
    CATEGORIES = [
        # --- knowledge-library subject genres ---
        ("Technology", "Technology"),
        ("Artificial Intelligence", "Artificial Intelligence"),
        ("Cybersecurity", "Cybersecurity"),
        ("Software Engineering", "Software Engineering"),
        ("Data Science", "Data Science"),
        ("Biology", "Biology"),
        ("Biotechnology", "Biotechnology"),
        ("Medicine", "Medicine"),
        ("Neuroscience", "Neuroscience"),
        ("Genetics", "Genetics"),
        ("Agriculture", "Agriculture"),
        ("Environmental Science", "Environmental Science"),
        ("Climate", "Climate"),
        ("Energy", "Energy"),
        ("Physics", "Physics"),
        ("Chemistry", "Chemistry"),
        ("Mathematics", "Mathematics"),
        ("Astronomy", "Astronomy"),
        ("Economics", "Economics"),
        ("Finance", "Finance"),
        ("Business", "Business"),
        ("Law", "Law"),
        ("Education", "Education"),
        ("Psychology", "Psychology"),
        ("Sociology", "Sociology"),
        ("History", "History"),
        ("Philosophy", "Philosophy"),
        ("Arts & Design", "Arts & Design"),
        ("Literature", "Literature"),
        ("Engineering", "Engineering"),
        # --- legacy business categories (enterprise workspace) ---
        ("Legal", "Legal"), ("HR", "HR"), ("Marketing", "Marketing"),
        ("Research", "Research"), ("Operations", "Operations"),
        ("Other", "Other"),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="documents")
    filename = models.CharField(max_length=300)
    stored_path = models.CharField(max_length=500)
    content_type = models.CharField(max_length=100, blank=True, default="")
    size = models.IntegerField(default=0)
    category = models.CharField(max_length=50, choices=CATEGORIES, default="Other")
    description = models.TextField(blank=True, default="")
    downloads = models.IntegerField(default=0)
    is_okf = models.BooleanField(default=False)     # curated OKF note, always in context
    # Templates are returned WHOLE (not chunked) when a user asks for a filled
    # form/email/policy document. Editing these flags is admin-only.
    TEMPLATE_TYPES = [
        ("email", "Email"), ("form", "Form"),
        ("policy", "Policy"), ("other", "Other"),
    ]
    is_template = models.BooleanField(default=False)
    template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPES,
                                     blank=True, default="")
    uploaded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    num_chunks = models.IntegerField(default=0)
    # `company` keeps the existing tenant-wide behaviour. `restricted` means
    # only the uploader and explicitly granted users may read/search/download.
    # `department` limits visibility to members of document.department.
    ACCESS_SCOPES = [
        ("company", "Entire company"),
        ("restricted", "Selected people"),
        ("department", "My department"),
    ]
    SENSITIVITY_LEVELS = [
        ("standard", "Standard"),
        ("internal", "Internal (Employees+)"),
        ("confidential", "Confidential (Admin Only)"),
    ]
    APPROVAL_STATES = [
        ("draft", "Draft"),
        ("in_review", "In Review"),
        ("approved", "Approved"),
        ("archived", "Archived"),
    ]
    access_scope = models.CharField(max_length=20, choices=ACCESS_SCOPES, default="company")
    sensitivity = models.CharField(max_length=20, choices=SENSITIVITY_LEVELS, default="standard")
    status = models.CharField(max_length=20, choices=APPROVAL_STATES, default="approved")
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_documents",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=300, blank=True, default="")
    contains_pii = models.BooleanField(default=False)
    legal_hold = models.BooleanField(default=False)
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, related_name="documents", null=True, blank=True,
    )
    # Comma-separated free-form tags (searchable/filterable in the workspace).
    tags = models.CharField(max_length=300, blank=True, default="")
    # Background indexing lifecycle: upload returns immediately (pending) and a
    # worker thread flips this to ready (or failed) once chunks exist.
    INDEXING_STATES = [("pending", "pending"), ("ready", "ready"), ("failed", "failed")]
    indexing_status = models.CharField(max_length=10, choices=INDEXING_STATES, default="ready")
    index_error = models.CharField(max_length=300, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    # Which embedding model produced this document's vectors. Mixing models
    # silently breaks cosine retrieval (dimension/geometry mismatch), so the
    # name is recorded at index time and surfaced by check_embeddings.
    embed_model = models.CharField(max_length=120, blank=True, default="")
    # Extracted text cached at index time so /documents/<id>/preview does not
    # re-parse the file on every view. Cleared on new-version upload; encrypted at rest.
    preview_text = EncryptedTextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DocumentVersion(models.Model):
    """A frozen copy of a document's file as of a version upload. The current
    file lives on Document; older ones are archived here (plan-gated)."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    stored_path = models.CharField(max_length=500)
    filename = models.CharField(max_length=300)
    size = models.IntegerField(default=0)
    uploaded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("document", "version_number")
        ordering = ["-version_number"]


class ChatConversation(models.Model):
    """A named chat thread for one user in one company. Messages persist so the
    assistant keeps context across turns and users can revisit old answers."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="conversations")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Chat {self.pk}"


class ChatMessage(models.Model):
    """One persisted turn inside a ChatConversation. Assistant rows keep their
    grounded source names and a thumbs up/down rating for quality analytics."""
    conversation = models.ForeignKey(
        ChatConversation, on_delete=models.CASCADE, related_name="messages",
    )
    role = models.CharField(max_length=10)  # "user" | "assistant"
    content = models.TextField()
    sources = models.TextField(blank=True, default="")  # JSON list of filenames
    source_document_ids = models.TextField(blank=True, default="")  # JSON list of doc IDs for revocation masking
    # null = unrated; 1 = thumbs up; -1 = thumbs down
    rating = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class AskLog(models.Model):
    """One row per /api/ask call. Powers usage analytics: questions per user or
    department, unanswered questions (zero chunks retrieved), flagged asks and
    plan quota accounting."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="ask_logs")
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="ask_logs")
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="ask_logs",
    )
    question = models.TextField()
    mode = models.CharField(max_length=10, blank=True, default="")
    provider = models.CharField(max_length=20, blank=True, default="")
    chunks_found = models.IntegerField(default=0)
    answered = models.BooleanField(default=False)
    flagged = models.BooleanField(default=False)
    latency_ms = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Monthly quota checks and analytics always filter company + time.
        indexes = [models.Index(fields=["company", "created_at"])]


class Announcement(models.Model):
    """A company-wide broadcast from an admin, shown in the workspace."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="announcements")
    title = models.CharField(max_length=200)
    body = models.TextField()
    require_ack = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AnnouncementAck(models.Model):
    """Employee read-acknowledgement receipt for a mandatory announcement/policy."""
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="acks")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="announcement_acks")
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("announcement", "user")


class DocumentAccess(models.Model):
    """An explicit per-user grant for a restricted or department document.

    A grant widens the document audience only; it NEVER silently raises
    sensitivity clearance unless an admin sets `override_clearance=True` with a
    mandatory `grant_reason` (audited).
    """
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="access_grants")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="document_access")
    can_download = models.BooleanField(default=True)
    override_clearance = models.BooleanField(default=False)
    grant_reason = models.CharField(max_length=300, blank=True, default="")
    granted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="grants_issued",
    )
    is_break_glass = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("document", "user")


class PendingUpload(models.Model):
    """Server-side binding for presigned S3 PUT uploads so callers can only
    confirm keys that were issued to their own user and company."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="pending_uploads")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pending_uploads")
    key = models.CharField(max_length=500, unique=True)
    filename = models.CharField(max_length=300)
    size = models.IntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class Chunk(models.Model):
    """A slice of a document's text plus its embedding, used for RAG retrieval.
    Carries `company` too so retrieval can filter by tenant without a join; text is encrypted at rest."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="chunks")
    ord = models.IntegerField(default=0)
    text = EncryptedTextField()
    # numpy float32 vector as raw bytes; NULL when embeddings unavailable
    embedding = models.BinaryField(null=True, blank=True)


_AUDIT_LOCK_GUARD = threading.Lock()
_AUDIT_COMPANY_LOCKS: dict[int, threading.Lock] = {}


def _audit_lock_for(company_id: int) -> threading.Lock:
    with _AUDIT_LOCK_GUARD:
        lock = _AUDIT_COMPANY_LOCKS.get(company_id)
        if lock is None:
            lock = threading.Lock()
            _AUDIT_COMPANY_LOCKS[company_id] = lock
        return lock


class AuditPurgeRecord(models.Model):
    """Explicit, permanent record of every whole-company audit purge.

    Also acts as the transaction-scoped allow flag for the SQLite BEFORE DELETE
    trigger during `AuditLog.purge_for_company()` so no ad-hoc delete can bypass
    the append-only guard.
    """
    company_id_snapshot = models.IntegerField()
    company_slug = models.CharField(max_length=120)
    actor_email = models.CharField(max_length=254, blank=True, default="")
    reason = models.CharField(max_length=300)
    purged_count = models.IntegerField(default=0)
    head_hash = models.CharField(max_length=64, blank=True, default="")
    in_progress = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditLogQuerySet(models.QuerySet):
    """Enforce append-only semantics on ORM bulk operations."""

    def update(self, **kwargs):
        raise PermissionError("AuditLog is tamper-evident and append-only; updates are forbidden.")

    def delete(self):
        raise PermissionError(
            "AuditLog is tamper-evident and append-only; use AuditLog.purge_for_company() for explicit company purge."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise PermissionError("AuditLog is tamper-evident and append-only; bulk updates are forbidden.")


class AuditLogManager(models.Manager):
    def get_queryset(self):
        return AuditLogQuerySet(self.model, using=self._db)


class AuditLog(models.Model):
    """Tamper-evident, append-only hash-chained activity trail per company."""
    OUTCOMES = [("allowed", "Allowed"), ("denied", "Denied")]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="audit")
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    # Immutable actor snapshot preserved in the hash even if the User row is later deleted.
    actor_id = models.IntegerField(null=True, blank=True)
    actor_email = models.CharField(max_length=254, blank=True, default="")
    action = models.CharField(max_length=50)
    outcome = models.CharField(max_length=20, choices=OUTCOMES, blank=True, default="allowed")
    target_type = models.CharField(max_length=40, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    detail = models.CharField(max_length=300, blank=True, default="")
    ip = models.CharField(max_length=64, blank=True, default="")
    hash_version = models.PositiveSmallIntegerField(default=2)
    prev_hash = models.CharField(max_length=64, blank=True, default="")
    entry_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    objects = AuditLogManager()

    class Meta:
        # The audit page paginates newest-first within one company.
        indexes = [models.Index(fields=["company", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "prev_hash"],
                condition=~Q(prev_hash=""),
                name="uniq_auditlog_company_prev_hash",
            ),
        ]

    def compute_hash(self, prev_hash: str) -> str:
        ts = self.created_at
        if timezone.is_naive(ts):
            ts = timezone.make_aware(ts, dt_timezone.utc)
        ts_str = ts.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if int(self.hash_version or 1) == 1:
            payload = f"{self.company_id}|{self.action}|{self.detail}|{self.ip}|{ts_str}|{prev_hash}"
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()
        # hash_version >= 2: canonical JSON array prevents delimiter ambiguity and binds actor/outcome/target.
        fields = [
            int(self.hash_version or 2),
            self.company_id,
            self.actor_id,
            self.actor_email or "",
            self.action or "",
            self.outcome or "allowed",
            self.target_type or "",
            str(self.target_id or ""),
            self.detail or "",
            self.ip or "",
            ts_str,
            prev_hash,
        ]
        payload = json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("AuditLog is tamper-evident and append-only; updates are forbidden.")
        if not self.created_at:
            self.created_at = timezone.now()
        if self.user_id and self.actor_id is None:
            self.actor_id = self.user_id
        if self.user_id and not self.actor_email:
            email = getattr(self.user, "email", "") if self.user else ""
            if not email:
                email = User.objects.filter(pk=self.user_id).values_list("email", flat=True).first() or ""
            self.actor_email = email
        if not self.outcome:
            self.outcome = "allowed"
        if not self.hash_version:
            self.hash_version = 2
        if self.company_id and not self.entry_hash:
            lock = _audit_lock_for(self.company_id)
            with lock:
                for attempt in range(5):
                    try:
                        with transaction.atomic():
                            # Lock the company row on PostgreSQL so even the first audit row
                            # for a tenant cannot race on prev_hash = "0"*64.
                            if connection.vendor == "postgresql":
                                Company.objects.select_for_update().filter(pk=self.company_id).first()
                            last = (
                                type(self).objects
                                .filter(company_id=self.company_id)
                                .exclude(entry_hash="")
                                .order_by("-id")
                                .values_list("entry_hash", flat=True)
                                .first()
                            )
                            self.prev_hash = last or ("0" * 64)
                            self.entry_hash = self.compute_hash(self.prev_hash)
                            return super().save(*args, **kwargs)
                    except IntegrityError:
                        self.prev_hash = ""
                        self.entry_hash = ""
                        if attempt == 4:
                            raise
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(
            "AuditLog is tamper-evident and append-only; use AuditLog.purge_for_company() for explicit company purge."
        )

    @classmethod
    def purge_for_company(cls, company, *, actor=None, reason: str = "") -> AuditPurgeRecord:
        """The ONLY permitted delete path for AuditLog rows (whole-company purge).

        Records an AuditPurgeRecord with count and final head hash before removing rows.
        """
        clean_reason = (reason or "").strip()
        if len(clean_reason) < 5:
            raise ValueError("AuditLog.purge_for_company requires an explicit reason (at least 5 characters).")
        company_id = company.pk if hasattr(company, "pk") else int(company)
        company_slug = getattr(company, "slug", f"company-{company_id}")
        actor_email = getattr(actor, "email", "") if actor is not None else ""
        with transaction.atomic():
            head = (
                cls.objects.filter(company_id=company_id)
                .exclude(entry_hash="")
                .order_by("-id")
                .values_list("entry_hash", flat=True)
                .first()
                or ""
            )
            count = cls.objects.filter(company_id=company_id).count()
            rec = AuditPurgeRecord.objects.create(
                company_id_snapshot=company_id,
                company_slug=company_slug,
                actor_email=actor_email,
                reason=clean_reason[:300],
                purged_count=count,
                head_hash=head,
                in_progress=True,
            )
            with connection.cursor() as cur:
                if connection.vendor == "postgresql":
                    cur.execute("SET LOCAL openvault.allow_audit_purge = '1'")
                cur.execute("DELETE FROM core_auditlog WHERE company_id = %s", [company_id])
            rec.in_progress = False
            rec.save(update_fields=["in_progress"])
            return rec

    @classmethod
    def verify_chain_report(cls, company) -> dict:
        """Verify hash chain integrity for `company` without buffering the whole table in RAM."""
        expected_prev = "0" * 64
        checked = 0
        seen_hashed = False
        head_hash = ""
        for row in cls.objects.filter(company=company).order_by("id").iterator(chunk_size=1000):
            if not row.entry_hash:
                if seen_hashed:
                    return {
                        "valid": False,
                        "checked": checked,
                        "broken_id": row.id,
                        "head_hash": head_hash,
                        "verified_at": timezone.now().isoformat(),
                    }
                continue
            seen_hashed = True
            checked += 1
            if row.prev_hash != expected_prev or row.entry_hash != row.compute_hash(expected_prev):
                return {
                    "valid": False,
                    "checked": checked,
                    "broken_id": row.id,
                    "head_hash": head_hash,
                    "verified_at": timezone.now().isoformat(),
                }
            expected_prev = row.entry_hash
            head_hash = row.entry_hash
        return {
            "valid": True,
            "checked": checked,
            "broken_id": None,
            "head_hash": head_hash,
            "verified_at": timezone.now().isoformat(),
        }

    @classmethod
    def verify_chain(cls, company) -> tuple[bool, int, int | None]:
        """Verify hash chain integrity for `company`. Returns (valid, checked_count, broken_id)."""
        rep = cls.verify_chain_report(company)
        return rep["valid"], rep["checked"], rep["broken_id"]


class DocumentShare(models.Model):
    """Granular cross-company collaboration.

    Isolation stays the default: a user only sees their OWN company's rows.
    A DocumentShare is an explicit exception — it grants ONE named user (who may
    belong to another company) access to ONE specific document. So Company A's
    HR person can be given exactly one Company C file, and nothing else.
    """
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="shares")
    shared_with_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="shared_documents"
    )
    # who granted it (their company owns the document)
    shared_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="shares_created"
    )
    can_download = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("document", "shared_with_user")

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())


class LLMConfig(models.Model):
    """Runtime-editable LLM settings.

    Two levels: the platform-wide row (company NULL, pk arbitrary) and optional
    per-company overrides (a company's own provider/model/key). Resolution in
    providers._resolve(): company row -> platform row -> .env, except that the
    Render BEDROCK_API_KEY/BEDROCK_MODEL win over a stale platform row so every
    ordinary user shares the platform key. The api_key is encrypted at rest
    (core.crypto) and never returned by the API.
    """
    PROVIDERS = [("ollama", "ollama"), ("openai", "openai"),
                 ("anthropic", "anthropic"), ("gemini", "gemini"),
                 ("bedrock", "bedrock"),
                 # Load-test/demo provider: settable via platform env only,
                 # never through the tenant-facing API (serializer blocks it).
                 ("fake", "fake")]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="llm_configs",
        null=True, blank=True,
    )
    provider = models.CharField(max_length=20, choices=PROVIDERS, default="ollama")
    chat_model = models.CharField(max_length=120, blank=True, default="")
    api_key = EncryptedCharField(max_length=1000, blank=True, default="")
    base_url = models.CharField(max_length=300, blank=True, default="")
    temperature = models.FloatField(default=0.2)
    max_tokens = models.IntegerField(default=512)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company"], condition=models.Q(company__isnull=False),
                name="uniq_llmconfig_per_company",
            )
        ]

    @classmethod
    def load(cls):
        """The platform-wide row when one exists; otherwise an UNSAVED default
        derived from the environment. Never auto-creates a row, so `.env` stays
        the source of truth until a platform admin explicitly saves settings."""
        obj = cls.objects.filter(company=None).first()
        if obj is not None:
            return obj
        provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
        if provider not in dict(cls.PROVIDERS):
            provider = "ollama"
        model_env = "LLM_MODEL" if provider == "ollama" else f"{provider.upper()}_MODEL"
        return cls(provider=provider, chat_model=os.getenv(model_env, "").strip())

    @classmethod
    def for_company(cls, company):
        """The company's own override row, or None when it uses the platform default."""
        if company is None:
            return None
        return cls.objects.filter(company=company).first()


class AttendanceRecord(models.Model):
    """One attendance mark for one user on one calendar day (Feature 5).

    Created when an employee scans the company QR code from an authenticated web
    session. `company` keeps the row tenant-scoped like every other table, and
    the (user, date) pair is unique so a day can only be marked once."""
    STATUSES = [("Present", "Present"), ("Absent", "Absent")]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="attendance")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    scanned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="Present")

    class Meta:
        unique_together = ("user", "date")
        ordering = ["-date", "-scanned_at"]

    def __str__(self):
        return f"{self.user} {self.date} {self.status}"


class GeneratedArtifact(models.Model):
    """A finished, copy/paste-ready document produced from a template.

    Deterministic filler output — no model call, no invented facts. Owned by
    the user who requested it; download/GET endpoints enforce that ownership
    and the company boundary.
    """
    KINDS = [("email", "Email"), ("form", "Form"), ("policy", "Policy"),
             ("table", "Table"), ("text", "Text")]

    company = models.ForeignKey(Company, on_delete=models.CASCADE,
                                related_name="artifacts")
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name="artifacts")
    kind = models.CharField(max_length=20, choices=KINDS, default="text")
    title = models.CharField(max_length=200, blank=True, default="")
    subject = models.CharField(max_length=300, blank=True, default="")
    content_md = models.TextField(blank=True, default="")
    structured = models.TextField(blank=True, default="{}")
    missing_fields = models.TextField(blank=True, default="[]")
    source_template_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind}: {self.title or self.pk}"


class UserStrike(models.Model):
    """Rolling attendance-discipline counter for one user (Feature 5).

    The monthly evaluation utility refreshes `absent_count`, and when a month
    crosses the absence limit it increments `strikes`. Once `strikes` reaches the
    cap the account is frozen (and deactivated by the evaluator). `last_evaluated_period`
    guards against double-counting if the evaluation runs twice in the same month."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="strike_record")
    absent_count = models.IntegerField(default=0)
    strikes = models.IntegerField(default=0)
    is_frozen = models.BooleanField(default=False)
    # "YYYY-MM" of the last month already counted toward strikes.
    last_evaluated_period = models.CharField(max_length=7, blank=True, default="")
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user}: {self.strikes} strike(s), {self.absent_count} absence(s)"


class Holiday(models.Model):
    """A non-working day that must never count as an absence.

    company=NULL means a platform-wide holiday (e.g. national days); otherwise
    the holiday belongs to one company's calendar (Eid dates differ per
    tenant's region/policy).
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="holidays",
        null=True, blank=True)
    date = models.DateField()
    name = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date"]
        unique_together = ("company", "date")

    def __str__(self):
        return f"{self.date} {self.name or 'Holiday'}"


class AttendanceExemption(models.Model):
    """An approved absence window (leave, business travel, WFH exception).

    Business days inside [start_date, end_date] are not counted as absences by
    the monthly evaluation, so approved leave can no longer generate strikes.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendance_exemptions")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="exemptions_granted",
        null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.user}: {self.start_date}..{self.end_date} {self.reason}"


class TeamRoom(models.Model):
    """Real-time employee chatroom scoped to one company.

    Every company starts with one default room (`is_default=True`, slug='general')
    open to all company members; admins can create extra rooms if needed.
    """
    SCOPES = [
        ("company", "Entire company"),
        ("department", "Department"),
        ("private", "Selected members"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="team_rooms")
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80)
    description = models.CharField(max_length=240, blank=True, default="")
    scope = models.CharField(max_length=20, choices=SCOPES, default="company")
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="team_rooms",
    )
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_team_rooms",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("company", "slug")
        ordering = ["-is_default", "name", "id"]

    @classmethod
    def ensure_default(cls, company):
        """Return the company's default all-employee chatroom, creating it once."""
        existing = cls.objects.filter(company=company, is_default=True).first()
        if existing is not None:
            return existing
        try:
            with transaction.atomic():
                room, _created = cls.objects.get_or_create(
                    company=company,
                    slug="general",
                    defaults={
                        "name": "General",
                        "description": "Company-wide employee chatroom. Mention @DeskWise anytime for work.",
                        "scope": "company",
                        "is_default": True,
                    },
                )
                if not room.is_default:
                    room.is_default = True
                    room.scope = "company"
                    room.save(update_fields=["is_default", "scope"])
                return room
        except IntegrityError:
            return cls.objects.filter(company=company, slug="general").first()

    def __str__(self):
        return f"{self.company.name} / {self.name}"


class TeamRoomMember(models.Model):
    """Explicit membership row for `private` TeamRooms."""
    room = models.ForeignKey(TeamRoom, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_room_memberships")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("room", "user")


class TeamRoomReadState(models.Model):
    """Per-user last-seen message id in a room for unread count badges."""
    room = models.ForeignKey(TeamRoom, on_delete=models.CASCADE, related_name="read_states")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_room_read_states")
    last_read_message_id = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("room", "user")


class TeamMessage(models.Model):
    """A message inside an employee TeamRoom (human or @DeskWise AI)."""
    SENDER_TYPES = [
        ("user", "User"),
        ("deskwise", "DeskWise AI"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="team_messages")
    room = models.ForeignKey(TeamRoom, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="team_messages",
    )
    sender_type = models.CharField(max_length=16, choices=SENDER_TYPES, default="user")
    content = models.TextField()
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="replies",
    )
    referenced_document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="team_chat_references",
    )
    sources = models.TextField(blank=True, default="")   # JSON list of source dicts/filenames
    metadata = models.TextField(blank=True, default="{}")  # JSON dict (flag, mode, stream info)
    is_pinned = models.BooleanField(default=False)
    pinned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pinned_team_messages",
    )
    pinned_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["room", "created_at", "id"]),
            models.Index(fields=["room", "is_pinned"]),
        ]

    def __str__(self):
        author = "DeskWise" if self.sender_type == "deskwise" else (self.sender.email if self.sender_id else "Deleted")
        return f"[{self.room.slug}] {author}: {self.content[:40]}"


class TeamMessageReaction(models.Model):
    """Emoji reaction toggle on a TeamMessage."""
    message = models.ForeignKey(TeamMessage, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_message_reactions")
    emoji = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user", "emoji")
