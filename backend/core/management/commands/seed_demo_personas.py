"""Idempotent local demo company seeder with multi-persona permission story.

Seeds `Deskwise Demo` with 4 personas (Admin, Finance Manager, General Employee, Viewer)
and 3 permission-tiered documents:
  1. `company_handbook.txt` (Company-wide / Standard) — visible to everyone
  2. `finance_contract.txt` (Finance Dept / Internal) — visible to Finance & Admin, DENIED to Eng Employee & Viewer
  3. `exec_board_notes.txt` (Restricted / Confidential, uploaded by Finance Manager) — requires audited Break-Glass for Admin
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from core import storage
from core.models import Chunk, Company, Department, Document, DocumentAccess, Plan, User


class Command(BaseCommand):
    help = "Seed local Deskwise Demo company with multi-persona permission fixtures."

    def add_arguments(self, parser):
        parser.add_argument("--password", type=str, required=True, help="Demo password for all demo personas.")
        parser.add_argument("--company", type=str, default="Deskwise Demo", help="Demo company name.")

    def handle(self, *args, **options):
        password = options["password"]
        company_name = options["company"]

        plan, _ = Plan.objects.get_or_create(
            name="Plus",
            defaults={
                "price_usd": 49,
                "max_members": 50,
                "max_documents": 1000,
                "storage_mb": 25600,
                "monthly_ask_limit": 6000,
                "allow_versions": True,
                "allow_departments": True,
                "allow_custom_llm": True,
                "is_default": False,
            },
        )
        company, _ = Company.objects.update_or_create(
            slug="deskwise-demo",
            defaults={
                "name": company_name,
                "plan": plan,
                "enable_ai_chat": True,
                "enable_docgen": True,
                "enable_external_sharing": True,
                "enable_team_chat": False,
                "enable_attendance": False,
            },
        )

        fin_dept, _ = Department.objects.get_or_create(company=company, name="Finance")
        eng_dept, _ = Department.objects.get_or_create(company=company, name="Engineering")
        hr_dept, _ = Department.objects.get_or_create(company=company, name="HR")

        personas = [
            ("admin@demo.deskwise.local", "Amina Admin", "CTO", "admin", False, None, "confidential"),
            ("finance@demo.deskwise.local", "Farah Finance", "CFO", "employee", True, fin_dept, "internal"),
            ("employee@demo.deskwise.local", "Bilal Engineer", "Engineer", "employee", False, eng_dept, "internal"),
            ("viewer@demo.deskwise.local", "Sara Viewer", "Analyst", "viewer", False, hr_dept, "standard"),
        ]
        created_users = {}
        for email, full_name, title, role, is_dm, dept, clr in personas:
            u = User.objects.filter(email=email).first()
            if u is None:
                u = User.objects.create_user(
                    email=email,
                    password=password,
                    full_name=full_name,
                    title=title,
                    role=role,
                    is_dept_admin=is_dm,
                    clearance=clr,
                    company=company,
                    department=dept,
                    email_verified=True,
                )
            else:
                u.full_name = full_name
                u.title = title
                u.role = role
                u.is_dept_admin = is_dm
                u.clearance = clr
                u.company = company
                u.department = dept
                u.is_active = True
                u.email_verified = True
                u.set_password(password)
                u.save()
            created_users[email] = u

        fixtures = [
            (
                "company_handbook.txt",
                "Company Handbook: Full-time employees receive 20 paid annual leave days and 10 sick days per year.",
                "HR",
                "company",
                "standard",
                None,
                created_users["admin@demo.deskwise.local"],
            ),
            (
                "finance_contract.txt",
                "CONFIDENTIAL FINANCE VENDOR CONTRACT (Q4-2026): Master Services Agreement with Northstar Cloud — Annual Cap $240,000 USD, Net-30 payment terms. Reference: DEMO-FINANCE-CONTRACT-2026.",
                "Finance",
                "department",
                "internal",
                fin_dept,
                created_users["finance@demo.deskwise.local"],
            ),
            (
                "exec_board_notes.txt",
                "Restricted Board Prep Notes (Q4-2026): Potential Series A valuation scenarios and headcount freeze draft. Reference: DEMO-RESTRICTED-BOARD-2026.",
                "Executive",
                "restricted",
                "internal",
                None,
                created_users["finance@demo.deskwise.local"],
            ),
        ]

        for filename, body, category, scope, sens, dept, uploader in fixtures:
            rel_key = f"{company.slug}/demo_{filename}"
            stored = storage.save_bytes(rel_key, body.encode("utf-8"), base_dir=settings.DATA_DIR)
            doc, _ = Document.objects.update_or_create(
                company=company,
                filename=filename,
                defaults={
                    "stored_path": stored,
                    "content_type": "text/plain",
                    "size": len(body.encode("utf-8")),
                    "category": category,
                    "description": f"Demo fixture ({scope} / {sens})",
                    "tags": f"demo,{scope},{sens}",
                    "access_scope": scope,
                    "department": dept,
                    "sensitivity": sens,
                    "status": "approved",
                    "uploaded_by": uploader,
                    "indexing_status": "ready",
                    "num_chunks": 1,
                    "preview_text": body,
                },
            )
            Chunk.objects.filter(document=doc).delete()
            Chunk.objects.create(company=company, document=doc, ord=0, text=body)
            DocumentAccess.objects.get_or_create(document=doc, user=uploader)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded '{company.name}' with 4 demo personas (Admin, Finance Manager, Employee, Viewer) and 3 tiered documents."
            )
        )
