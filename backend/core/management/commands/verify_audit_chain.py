"""Verify the tamper-evident SHA-256 hash chain for company AuditLog tables.

Usage:
    python manage.py verify_audit_chain --all
    python manage.py verify_audit_chain --company acme-corp
"""
from django.core.management.base import BaseCommand, CommandError

from core.models import AuditLog, Company


class Command(BaseCommand):
    help = "Verify SHA-256 hash chain integrity across company audit logs."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Verify every registered company.")
        parser.add_argument("--company", type=str, default="", help="Verify a single company by slug.")

    def handle(self, *args, **options):
        run_all = options["all"]
        slug = (options["company"] or "").strip()
        if not run_all and not slug:
            raise CommandError("Specify either --all or --company <slug>.")

        qs = Company.objects.all().order_by("id")
        if slug:
            qs = qs.filter(slug=slug)
            if not qs.exists():
                raise CommandError(f"Company with slug '{slug}' not found.")

        failures = []
        total_checked = 0
        for company in qs.iterator():
            report = AuditLog.verify_chain_report(company)
            total_checked += report["checked"]
            head = (report["head_hash"] or "none")[:16]
            if report["valid"]:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"OK    {company.slug}: {report['checked']} entries verified (head={head})"
                    )
                )
            else:
                failures.append((company.slug, report["broken_id"]))
                self.stderr.write(
                    self.style.ERROR(
                        f"FAIL  {company.slug}: chain broken at AuditLog id={report['broken_id']} "
                        f"after {report['checked']} entries"
                    )
                )

        if failures:
            summary = ", ".join(f"{s} (id={bid})" for s, bid in failures)
            raise CommandError(f"Audit chain verification FAILED for: {summary}")
        self.stdout.write(
            self.style.SUCCESS(f"All audit chains valid ({total_checked} total entries checked).")
        )
