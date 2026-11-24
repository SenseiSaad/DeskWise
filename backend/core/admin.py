"""Django admin: platform-level records only.

Platform/root admins are report-only for tenant data (see core.access). The
admin site therefore does NOT register tenant-content models (documents,
chunks, versions, grants, shares, chat, team chat, announcements, attendance
exemptions, ask logs, audit logs), and never renders secrets (LLM API keys,
TOTP seeds, password hashes). Security audit AUTHZ-12 / AI-03.
"""
from django.contrib import admin

from .models import Company, Department, Holiday, LLMConfig, Plan, User

admin.site.site_header = "Deskwise administration"
admin.site.site_title = "Deskwise admin"
admin.site.index_title = "Private knowledge platform management"


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price_usd", "billing_period", "max_members", "max_documents",
                    "storage_mb", "monthly_ask_limit", "is_default")
    search_fields = ("name",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "created_at")
    list_filter = ("company",)
    search_fields = ("name",)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "access_code", "slug", "plan", "created_at")
    list_filter = ("plan",)
    search_fields = ("name", "access_code", "slug")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "title", "role", "company", "department",
                    "is_platform_admin", "email_verified", "language", "is_staff", "is_active")
    list_filter = ("role", "is_platform_admin", "is_staff", "is_active", "company", "language")
    search_fields = ("email", "full_name")
    # Secrets are never rendered; privilege and tenancy fields are not editable here.
    exclude = ("password", "mfa_secret", "groups", "user_permissions")
    readonly_fields = (
        "email", "company", "department", "role", "clearance", "is_dept_admin",
        "is_platform_admin", "is_superuser", "is_staff", "token_version",
        "mfa_enabled", "google_sub", "last_login", "created_at",
    )


@admin.register(LLMConfig)
class LLMConfigAdmin(admin.ModelAdmin):
    list_display = ("company", "provider", "chat_model", "updated_at")
    exclude = ("api_key",)


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "company", "created_at")
    list_filter = ("company",)
