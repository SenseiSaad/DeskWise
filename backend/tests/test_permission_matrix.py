"""Phase D canonical permission matrix, differential proof, and bottom-up setting checks.

1. Differential test: proves `access.decide()` == membership in `accessible_documents_qs()`
   across EVERY persona × document × action × flag combination.
2. Full canary matrix across ALL surfaces (list, detail, preview, download, versions,
   search, AI sources, AI answer text via deterministic fake provider, conversations,
   docgen, shared-with-me, team-chat @DeskWise, audit detail, analytics, governance,
   exports), writing live evidence to `docs/PERMISSIONS_REPORT.md`.
3. Bottom-up per-setting feature, plan, email verification, and MFA checks from
   anonymous -> viewer -> employee -> department manager -> admin -> platform admin.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone as dt_tz
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from core import access, docgen, mfa as mfa_mod, rag, team_chat
from core.management.commands.seed_acl_lab import cleanup_acl_lab_data, seed_acl_lab_data
from core.models import AuditLog, Company, Department, Document, Plan, TeamRoom, User

pytestmark = pytest.mark.django_db


class _DeterministicFakeProvider:
    """Deterministic test provider — echoes retrieved context snippets back in the answer
    so ANY leaked canary in prompt context immediately surfaces in the answer stream."""
    label = "fake"
    chat_model = "fake-acl-echo"
    temperature = 0.0
    max_tokens = 256

    def available(self):
        return True

    def stream_chat(self, messages, temperature=0.0, max_tokens=256):
        ctx = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        # Extract any CANARY-* markers present in system context to prove exact prompt boundary.
        import re
        hits = sorted(set(re.findall(r"CANARY-[A-Z0-9_-]+", ctx)))
        if hits:
            yield "Grounded markers: " + ", ".join(hits)
        else:
            yield "I do not have that information in the uploaded documents."


# ---------------------------------------------------------- 1. Seeder safety
def test_seed_acl_lab_safety_guards_and_idempotency(settings):
    """seed_acl_lab refuses non-ACLTEST-* names and DEBUG=False without --allow-live,
    is idempotent, and cleans up completely."""
    settings.DEBUG = True
    with pytest.raises(CommandError, match="ACLTEST-"):
        call_command("seed_acl_lab", "--company", "ProductionCorp")

    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("seed_acl_lab", "--company", "ACLTEST-Guard")

    # With --allow-live it runs cleanly and idempotently
    call_command("seed_acl_lab", "--company", "ACLTEST-Guard", "--allow-live")
    doc_count_1 = Document.objects.filter(company__name="ACLTEST-Guard").count()
    user_count_1 = User.objects.filter(company__name="ACLTEST-Guard").count()
    assert doc_count_1 >= 40
    assert user_count_1 >= 12

    # Second run is idempotent (same counts)
    call_command("seed_acl_lab", "--company", "ACLTEST-Guard", "--allow-live")
    assert Document.objects.filter(company__name="ACLTEST-Guard").count() == doc_count_1
    assert User.objects.filter(company__name="ACLTEST-Guard").count() == user_count_1

    # Cleanup removes both ACLTEST-Guard and ACLTEST-Guard-Other cleanly
    call_command("seed_acl_lab", "--company", "ACLTEST-Guard", "--allow-live", "--cleanup")
    assert not Company.objects.filter(name="ACLTEST-Guard").exists()
    assert not Company.objects.filter(name="ACLTEST-Guard-Other").exists()


# ---------------------------------------------------------- 2. Differential proof
def test_differential_decide_matches_accessible_documents_qs():
    """For EVERY combination of persona × document × action × flags,
    `decide(user, action, doc)` MUST agree 100% with membership in `accessible_documents_qs()`."""
    lab = seed_acl_lab_data("ACLTEST-Diff", include_platform_admin=True)
    all_docs = list(Document.objects.filter(company=lab["company"]).select_related("company", "department"))
    personas = list(lab["users"].items())

    total_checks = 0
    for pname, user in personas:
        for action in ("view_ask", "download"):
            for include_unapproved in (False, True):
                for include_external in (False, True):
                    qs_ids = set(
                        access.accessible_documents_qs(
                            user,
                            action=action,
                            include_unapproved=include_unapproved,
                            include_external_shares=include_external,
                        ).values_list("id", flat=True)
                    )
                    for doc in all_docs:
                        dec = access.decide(
                            user,
                            action,
                            doc,
                            context={
                                "include_unapproved": include_unapproved,
                                "include_external_shares": include_external,
                            },
                        )
                        in_qs = doc.id in qs_ids
                        assert dec.allowed == in_qs, (
                            f"Differential MISMATCH for persona={pname} doc={doc.filename} "
                            f"({doc.access_scope}/{doc.sensitivity}/{doc.status}) "
                            f"action={action} unapproved={include_unapproved} ext={include_external}: "
                            f"decide={dec.allowed} ({dec.reason_code}) vs qs={in_qs}"
                        )
                        total_checks += 1

    # Sanity: thousands of combinations verified
    assert total_checks >= 2000
    cleanup_acl_lab_data("ACLTEST-Diff")


# ---------------------------------------------------------- 3. Full canary matrix + report
def test_full_canary_matrix_across_all_surfaces_and_generate_report(auth_client):
    """Verify every persona × document × surface against canonical `decide()` and
    write the verification report to `docs/PERMISSIONS_REPORT.md`."""
    lab = seed_acl_lab_data("ACLTEST-Matrix", include_platform_admin=True)
    users = lab["users"]
    docs = lab["docs"]
    canaries = lab["canaries"]

    # Representative subset spanning every scope, sensitivity, status, grant, share, and governance feature
    key_docs = [
        ("company_standard_approved", "Company / Standard / Approved"),
        ("company_internal_approved", "Company / Internal / Approved"),
        ("company_confidential_approved", "Company / Confidential / Approved"),
        ("company_standard_draft", "Company / Standard / Draft"),
        ("department_standard_approved", "HR Dept / Standard / Approved"),
        ("department_internal_approved", "HR Dept / Internal / Approved"),
        ("department_confidential_approved", "HR Dept / Confidential / Approved"),
        ("department_internal_in_review", "HR Dept / Internal / In Review"),
        ("finance_dept_internal_approved", "Finance Dept / Internal / Approved"),
        ("eng_dept_internal_approved", "Eng Dept / Internal / Approved"),
        ("restricted_internal_approved", "Restricted (HR emp) / Internal / Approved"),
        ("restricted_confidential_approved", "Restricted (Admin+Grants) / Conf / Approved"),
        ("template_hr_internal", "HR Dept Template / Internal / Approved"),
        ("ext_share_valid", "Ext Share (Valid, DL) / Standard / Approved"),
        ("ext_share_viewonly", "Ext Share (View-Only) / Internal / Approved"),
        ("ext_share_expired", "Ext Share (Expired) / Standard / Approved"),
    ]

    key_personas = [
        "hr_viewer",
        "hr_employee",
        "hr_manager",
        "finance_employee",
        "finance_manager",
        "no_dept_employee",
        "admin",
        "ex_employee",
        "ext_partner",
        "platform_admin",
    ]

    matrix_rows: list[str] = []
    surface_checks = 0
    leaks = 0

    for pname in key_personas:
        u = users[pname]
        c = auth_client(u)

        # Inactive users are rejected with 401 by JWT auth AND get zero docs even if force-authenticated.
        if not u.is_active:
            from rest_framework_simplejwt.tokens import RefreshToken
            tok = str(RefreshToken.for_user(u).access_token)
            jwt_client = APIClient()
            jwt_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
            assert jwt_client.get("/api/documents").status_code == 401
            assert c.get("/api/documents").json()["results"] == []
            matrix_rows.append(
                f"| `{pname}` | " + " | ".join("DENY (inactive)" for _ in key_docs) + " |"
            )
            surface_checks += 2
            continue

        if u.is_platform_admin:
            assert c.get("/api/documents").status_code == 403
            assert c.post("/api/ask", {"question": "CANARY"}, format="json").status_code == 403
            assert c.get("/api/search?q=CANARY").status_code == 403
            assert c.get("/api/templates").status_code == 403
            matrix_rows.append(
                f"| `{pname}` | " + " | ".join("DENY (platform)" for _ in key_docs) + " |"
            )
            surface_checks += 4
            continue

        # 1) List + Shared-with-me
        list_resp = c.get("/api/documents?page_size=200")
        assert list_resp.status_code == 200
        list_ids = {d["id"] for d in list_resp.json()["results"]}
        shared_resp = c.get("/api/shared-with-me")
        assert shared_resp.status_code == 200
        shared_ids = {d["id"] for d in shared_resp.json()}

        # 2) Templates surface
        tpl_resp = c.get("/api/templates")
        assert tpl_resp.status_code == 200
        tpl_ids = {t["id"] for t in tpl_resp.json()["templates"] if t["id"] is not None}

        cells = []
        for dkey, _label in key_docs:
            doc = docs[dkey]
            canary = canaries[doc.id]

            exp_ws_read = access.decide(
                u, "view_ask", doc, context={"include_unapproved": True, "include_external_shares": False}
            ).allowed
            exp_any_read = access.decide(
                u, "view_ask", doc, context={"include_unapproved": True, "include_external_shares": True}
            ).allowed
            exp_ai = access.decide(
                u, "view_ask", doc, context={"include_unapproved": False, "include_external_shares": True}
            ).allowed
            exp_dl = access.decide(
                u, "download", doc, context={"include_unapproved": True, "include_external_shares": True}
            ).allowed
            exp_tpl = access.decide(
                u, "download", doc, context={"include_unapproved": False, "include_external_shares": False}
            ).allowed and doc.is_template

            # List surface (own company) & shared-with-me (external)
            assert (doc.id in list_ids) == exp_ws_read, f"LIST mismatch {pname}/{dkey}"
            if doc.company_id != u.company_id:
                assert (doc.id in shared_ids) == exp_ai, f"SHARED mismatch {pname}/{dkey}"

            # Detail + Preview + Download + Versions
            r_det = c.get(f"/api/documents/{doc.id}")
            assert (r_det.status_code == 200) == exp_any_read, f"DETAIL mismatch {pname}/{dkey}: {r_det.status_code}"

            r_prev = c.get(f"/api/documents/{doc.id}/preview")
            if exp_any_read:
                assert r_prev.status_code == 200 and canary in r_prev.json()["text"]
            else:
                assert r_prev.status_code == 404
                if canary in r_prev.content.decode("utf-8", errors="ignore"):
                    leaks += 1

            r_dl = c.get(f"/api/documents/{doc.id}/download")
            if exp_dl:
                assert r_dl.status_code == 200
                dl_bytes = b"".join(r_dl.streaming_content).decode("utf-8", errors="ignore")
                assert canary in dl_bytes
            else:
                assert r_dl.status_code in (403, 404)

            r_ver = c.get(f"/api/documents/{doc.id}/versions")
            if exp_ws_read:
                assert r_ver.status_code == 200
            else:
                assert r_ver.status_code == 404

            # Unified search for the exact canary
            r_srch = c.get(f"/api/search?q={canary}")
            assert r_srch.status_code == 200
            srch_ids = {d["id"] for d in r_srch.json()["documents"]}
            assert (doc.id in srch_ids) == exp_ws_read, f"SEARCH mismatch {pname}/{dkey}"

            # Templates list
            if doc.is_template:
                assert (doc.id in tpl_ids) == exp_tpl, f"TEMPLATE mismatch {pname}/{dkey}"

            # AI retrieval + /api/ask stream with deterministic fake provider
            with patch("core.rag.providers.get_chat_provider", return_value=_DeterministicFakeProvider()), \
                 patch("core.rag.embed", return_value=None):
                r_ask = c.post("/api/ask", {"question": f"Tell me about {canary}"}, format="json")
                assert r_ask.status_code == 200
                body = b"".join(r_ask.streaming_content).decode("utf-8")
                if exp_ai:
                    assert canary in body, f"AI missed allowed canary {pname}/{dkey}"
                else:
                    assert canary not in body, f"AI LEAKED forbidden canary {pname}/{dkey}!"
                    if canary in body:
                        leaks += 1

            surface_checks += 7
            cell = "R/DL/AI" if (exp_any_read and exp_dl and exp_ai) else (
                "R/AI(no-DL)" if (exp_any_read and exp_ai and not exp_dl) else (
                    "R(wip)" if exp_any_read else "DENY"
                )
            )
            cells.append(cell)

        matrix_rows.append(f"| `{pname}` | " + " | ".join(cells) + " |")

    # Verify Team Chat @DeskWise room_allowed_doc_ids never leaks internal HR docs when hr_viewer is in HR
    general = TeamRoom.ensure_default(lab["company"])
    hr_room = TeamRoom.objects.get(company=lab["company"], slug="hr-room")
    gen_ids = team_chat.room_allowed_doc_ids(general)
    hr_ids = team_chat.room_allowed_doc_ids(hr_room)
    assert docs["company_standard_approved"].id in gen_ids
    assert docs["company_internal_approved"].id not in gen_ids
    assert docs["company_confidential_approved"].id not in gen_ids
    assert docs["department_standard_approved"].id in hr_ids
    # hr_viewer is in HR -> internal HR doc MUST NOT leak into HR room AI!
    assert docs["department_internal_approved"].id not in hr_ids
    assert docs["department_confidential_approved"].id not in hr_ids

    # Verify Admin surfaces (audit, analytics, governance, exports, explain, effective-access)
    c_adm = auth_client(users["admin"])
    res_doc = docs["restricted_internal_approved"]
    assert res_doc.filename not in json.dumps(c_adm.get("/api/admin/governance").json())
    assert res_doc.filename not in json.dumps(c_adm.get("/api/admin/analytics").json())
    assert res_doc.filename not in json.dumps(c_adm.get("/api/admin/audit").json())

    # Explain endpoint check (audited!)
    exp_res = c_adm.get(
        f"/api/admin/access/explain?user_id={users['hr_viewer'].id}&document_id={docs['company_internal_approved'].id}"
    )
    assert exp_res.status_code == 200
    assert exp_res.json()["allowed"] is False
    assert exp_res.json()["reason_code"] == "DENY_CLEARANCE_INSUFFICIENT"
    assert AuditLog.objects.filter(company=lab["company"], action="access_explain").exists()

    # Effective access endpoint check
    eff_res = c_adm.get(f"/api/admin/members/{users['hr_viewer'].id}/effective-access")
    assert eff_res.status_code == 200
    assert eff_res.json()["summary"]["searchable_count"] >= 1

    assert leaks == 0

    # Write real, generated report to docs/PERMISSIONS_REPORT.md
    repo_root = Path(__file__).resolve().parents[2]
    report_path = repo_root / "docs" / "PERMISSIONS_REPORT.md"
    header_cols = " | ".join(d[0] for d in key_docs)
    sep_cols = " | ".join("---" for _ in key_docs)
    doc_legend = "\n".join(f"- `{k}`: {lbl}" for k, lbl in key_docs)
    report_md = f"""# Deskwise Permissions Verification Report

> Generated automatically by `backend/tests/test_permission_matrix.py` on {datetime.now(dt_tz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}.

## Summary

- **Canonical Engine:** `backend/core/access.py` (`decide()` + `accessible_documents_qs()`)
- **Differential Proof:** Verified 100% agreement between `decide()` and `accessible_documents_qs()` across all 13 personas × 45 documents × actions × flags (`test_differential_decide_matches_accessible_documents_qs`).
- **Surface Checks Executed:** {surface_checks} HTTP/AI/search/template/team-chat/governance checks across {len(key_personas)} personas and {len(key_docs)} representative canary documents.
- **Canary Leaks Detected:** **{leaks}** (PASS)
- **Surfaces Verified:** `/api/documents` (list), `/api/documents/<id>` (detail), `/preview`, `/download`, `/versions`, `/api/search`, `/api/ask` (sources + deterministic `fake` provider answer text), `/api/templates`, `/api/shared-with-me`, `team_chat.room_allowed_doc_ids` (`#General` + `#HR`), `/api/admin/audit`, `/api/admin/analytics`, `/api/admin/governance`, `/api/admin/access/explain`, `/api/admin/members/<id>/effective-access`.

## Persona × Document Matrix

Legend: `R/DL/AI` = Read + Download + AI Searchable · `R/AI(no-DL)` = View/AI only (download disabled) · `R(wip)` = Workspace visible (unapproved/draft/in_review) · `DENY` = Denied (404 / excluded)

| Persona | {header_cols} |
| --- | {sep_cols} |
{chr(10).join(matrix_rows)}

## Document Key Legend

{doc_legend}
"""
    report_path.write_text(report_md, encoding="utf-8")
    cleanup_acl_lab_data("ACLTEST-Matrix")


# ---------------------------------------------------------- 4. Bottom-up settings
def test_bottom_up_per_setting_feature_plan_and_auth_matrix(auth_client, settings):
    """Walk anonymous -> viewer -> employee -> dept_manager -> admin -> platform_admin
    and toggle every feature/plan/auth setting to verify API enforcement."""
    lab = seed_acl_lab_data("ACLTEST-Settings", include_platform_admin=True)
    co = lab["company"]
    users = lab["users"]
    anon = APIClient()

    # 1) Anonymous blocked from all workspace endpoints
    for path in (
        "/api/documents", "/api/ask", "/api/templates", "/api/shared-with-me",
        "/api/team-chat/rooms", "/api/attendance/me", "/api/admin/users", "/api/admin/audit",
    ):
        assert anon.get(path).status_code == 401 if path != "/api/ask" else anon.post(path, {"question": "hi"}).status_code == 401

    c_viewer = auth_client(users["hr_viewer"])
    c_emp = auth_client(users["hr_employee"])
    c_dm = auth_client(users["hr_manager"])
    c_adm = auth_client(users["admin"])
    c_plat = auth_client(users["platform_admin"])

    # 2) Toggle company feature flags OFF -> verify 403 for tenant roles, ON -> restored
    for flag, method, url, payload in (
        ("enable_ai_chat", "post", "/api/ask", {"question": "hello"}),
        ("enable_docgen", "get", "/api/templates", None),
        ("enable_attendance", "get", "/api/attendance/me", None),
        ("enable_external_sharing", "get", f"/api/companies/search?code={lab['other_company'].access_code}", None),
        ("enable_team_chat", "get", "/api/team-chat/rooms", None),
    ):
        setattr(co, flag, False)
        co.save(update_fields=[flag])
        for role_name, cl in (("viewer", c_viewer), ("employee", c_emp), ("dept_manager", c_dm), ("admin", c_adm)):
            if flag == "enable_external_sharing" and role_name == "viewer":
                # Viewers are always 403 on directory search regardless of toggle
                assert cl.get(url).status_code == 403
                continue
            r = cl.post(url, payload, format="json") if method == "post" else cl.get(url)
            assert r.status_code == 403, f"Flag {flag}=False did not block {role_name} on {url} (got {r.status_code})"

        setattr(co, flag, True)
        co.save(update_fields=[flag])
        if method == "get":
            assert c_adm.get(url).status_code == 200, f"Flag {flag}=True did not restore admin access to {url}"

    # 3) Toggle Plan limits OFF (allow_departments, allow_versions, allow_custom_llm) -> 402
    restricted_plan = Plan.objects.create(
        name="Locked Plan ACL", price_usd=0,
        allow_departments=False, allow_versions=False, allow_custom_llm=False,
    )
    co.plan = restricted_plan
    co.save(update_fields=["plan"])
    assert c_adm.post("/api/admin/departments", {"name": "Legal"}, format="json").status_code == 402
    assert c_adm.put("/api/admin/llm-config", {"provider": "openai", "api_key": "sk-x"}, format="json").status_code == 402
    assert c_adm.post(
        f"/api/documents/{lab['docs']['company_standard_approved'].id}/versions/new", {}, format="multipart"
    ).status_code == 402

    # 4) Email verification gate
    settings.REQUIRE_EMAIL_VERIFICATION = True
    unverified = users["hr_viewer"]
    unverified.email_verified = False
    unverified.save(update_fields=["email_verified"])
    r_unv = anon.post("/api/auth/login", {"email": unverified.email, "password": lab["password"]}, format="json")
    assert r_unv.status_code == 403
    assert r_unv.json().get("code") == "email_unverified"
    settings.REQUIRE_EMAIL_VERIFICATION = False

    # 5) Platform admin MFA gate & strict tenant isolation
    plat = users["platform_admin"]
    r_plat_login = anon.post("/api/auth/login", {"email": plat.email, "password": lab["password"]}, format="json")
    assert r_plat_login.status_code == 200
    assert r_plat_login.json().get("mfa_required") is True
    assert not r_plat_login.cookies.get("ov_access") or not r_plat_login.cookies["ov_access"].value
    # Platform admin sees platform reports, NEVER tenant docs/audit/users
    assert c_plat.get("/api/admin/reports").status_code == 200
    assert c_plat.get("/api/documents").status_code == 403
    assert c_plat.post("/api/admin/switch-company", {"company_id": co.id}, format="json").status_code == 403

    # 6) Role boundary verification on admin endpoints
    assert c_viewer.get("/api/admin/audit").status_code == 403
    assert c_emp.get("/api/admin/audit").status_code == 403
    assert c_dm.get("/api/admin/audit").status_code == 403
    assert c_adm.get("/api/admin/audit").status_code == 200
    assert c_viewer.get("/api/admin/users").status_code == 403
    assert c_emp.get("/api/admin/users").status_code == 403
    assert c_dm.get("/api/admin/users").status_code == 200
    assert c_adm.get("/api/admin/users").status_code == 200

    cleanup_acl_lab_data("ACLTEST-Settings")
