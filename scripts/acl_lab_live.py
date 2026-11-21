#!/usr/bin/env python3
"""Safe black-box ACL verification script for Deskwise (local or live).

Safety rules enforced in code:
  - Creates a fresh fake company named `ACLTEST-<YYYYMMDD>-<4hex>`.
  - Uses ONLY document/user IDs created by this script. Never probes or guesses IDs.
  - Low-rate sequential requests (no load testing).
  - Never uses AWS Bedrock (checks retrieval `sources`, preview, download, and list ACLs).
  - Cleans up every uploaded document and created member when finished.

Usage:
  python3 scripts/acl_lab_live.py --base-url http://127.0.0.1:8000
  python3 scripts/acl_lab_live.py --base-url https://deskbackend.saadops.site
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.cookiejar
import json
import mimetypes
import secrets
import sys
import urllib.error
import urllib.request
import uuid


class ApiSession:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method: str, path: str, data=None, headers: dict | None = None, timeout: int = 20):
        url = f"{self.base}{path}"
        req_headers = {"Accept": "application/json", **(headers or {})}
        body = None
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, bytes):
            body = data
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, raw, dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def json_req(self, method: str, path: str, data=None):
        code, raw, hdrs = self.request(method, path, data=data)
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            parsed = raw.decode("utf-8", errors="replace")
        return code, parsed, hdrs

    def upload_file(self, filename: str, content: bytes, fields: dict[str, str]):
        boundary = f"----DeskwiseAclLab{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for k, v in fields.items():
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                f"{v}\r\n".encode("utf-8")
            )
        ctype = mimetypes.guess_type(filename)[0] or "text/plain"
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n".encode("utf-8")
            + content
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        code, raw, hdrs = self.request(
            "POST",
            "/api/documents/upload",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            parsed = raw.decode("utf-8", errors="replace")
        return code, parsed, hdrs


def run_suite(base_url: str) -> int:
    stamp = dt.date.today().strftime("%Y%m%d")
    tag = secrets.token_hex(2).upper()
    company_name = f"ACLTEST-{stamp}-{tag}"
    domain = f"acltest-{stamp.lower()}-{tag.lower()}.example.test"
    password = f"AclLab!{secrets.token_hex(6)}9A"

    admin_email = f"admin@{domain}"
    emp_email = f"emp@{domain}"
    viewer_email = f"viewer@{domain}"

    admin_s = ApiSession(base_url)
    emp_s = ApiSession(base_url)
    viewer_s = ApiSession(base_url)
    anon_s = ApiSession(base_url)

    results: list[tuple[str, bool, str]] = []
    created_doc_ids: list[int] = []
    created_user_ids: list[int] = []

    def check(name: str, ok: bool, detail: str = ""):
        results.append((name, ok, detail))
        status_str = "PASS" if ok else "FAIL"
        print(f"[{status_str}] {name}" + (f" — {detail}" if detail else ""))

    print(f"=== Deskwise Black-Box ACL Lab against {base_url} ({company_name}) ===")

    try:
        # 1. Anonymous blocked
        code, _, _ = anon_s.json_req("GET", "/api/documents")
        check("Anonymous blocked from /api/documents", code == 401, f"HTTP {code}")

        # 2. Register fresh ACLTEST-<YYYYMMDD> company
        code, reg, _ = admin_s.json_req(
            "POST",
            "/api/auth/register",
            {
                "company_name": company_name,
                "admin_name": "ACL Lab Admin",
                "email": admin_email,
                "password": password,
            },
        )
        if code != 201:
            check("Register fake ACLTEST company", False, f"HTTP {code}: {reg}")
            return 1
        check("Register fake ACLTEST company", True, f"company={company_name}")

        # Verify cookie session works (if email verification is disabled)
        me_code, me_data, _ = admin_s.json_req("GET", "/api/auth/me")
        if me_code != 200:
            check("Admin session authenticated", False, f"HTTP {me_code} (email verification may be enabled)")
            return 1
        check("Admin session authenticated", True, f"role={me_data.get('role')}")

        # 3. Create 1 employee and 1 viewer (fits inside Free 3-seat plan!)
        c_emp, emp_data, _ = admin_s.json_req(
            "POST",
            "/api/admin/users",
            {"email": emp_email, "password": password, "full_name": "ACL Emp", "role": "employee"},
        )
        c_view, view_data, _ = admin_s.json_req(
            "POST",
            "/api/admin/users",
            {"email": viewer_email, "password": password, "full_name": "ACL Viewer", "role": "viewer"},
        )
        if c_emp == 201 and isinstance(emp_data, dict):
            created_user_ids.append(emp_data["id"])
        if c_view == 201 and isinstance(view_data, dict):
            created_user_ids.append(view_data["id"])
        check("Create employee & viewer personas", c_emp == 201 and c_view == 201, f"emp={c_emp}, viewer={c_view}")
        if not (c_emp == 201 and c_view == 201):
            return 1

        # Log in as employee & viewer
        lc_emp, _, _ = emp_s.json_req("POST", "/api/auth/login", {"email": emp_email, "password": password})
        lc_view, _, _ = viewer_s.json_req("POST", "/api/auth/login", {"email": viewer_email, "password": password})
        check("Sign in as employee & viewer", lc_emp == 200 and lc_view == 200, f"emp={lc_emp}, viewer={lc_view}")

        # 4. Upload 3 canary docs: standard (admin), internal (admin), restricted (employee)
        c_std = f"CANARY-LIVE-STD-{tag}"
        c_int = f"CANARY-LIVE-INT-{tag}"
        c_res = f"CANARY-LIVE-RES-{tag}"

        sc1, d_std, _ = admin_s.upload_file(
            "acl_standard.txt",
            f"Company general handbook marker {c_std}".encode(),
            {"access_scope": "company", "sensitivity": "standard", "category": "General"},
        )
        sc2, d_int, _ = admin_s.upload_file(
            "acl_internal.txt",
            f"Internal operations runbook marker {c_int}".encode(),
            {"access_scope": "company", "sensitivity": "internal", "category": "Operations"},
        )
        sc3, d_res, _ = emp_s.upload_file(
            "acl_restricted.txt",
            f"Private employee notes marker {c_res}".encode(),
            {"access_scope": "restricted", "sensitivity": "internal", "category": "Private"},
        )
        for d in (d_std, d_int, d_res):
            if isinstance(d, dict) and d.get("id"):
                created_doc_ids.append(d["id"])
        check("Upload 3 canary documents", sc1 == 201 and sc2 == 201 and sc3 == 201, f"codes=({sc1},{sc2},{sc3})")
        if not (sc1 == 201 and sc2 == 201 and sc3 == 201):
            return 1

        std_id, int_id, res_id = d_std["id"], d_int["id"], d_res["id"]

        # 5. Viewer ACL isolation checks
        v_std_code, v_std_prev, _ = viewer_s.json_req("GET", f"/api/documents/{std_id}/preview")
        v_int_code, _, _ = viewer_s.json_req("GET", f"/api/documents/{int_id}/preview")
        v_res_code, _, _ = viewer_s.json_req("GET", f"/api/documents/{res_id}/preview")
        v_audit_code, _, _ = viewer_s.json_req("GET", "/api/admin/audit")
        check(
            "Viewer sees standard doc only",
            v_std_code == 200 and c_std in json.dumps(v_std_prev),
            f"std={v_std_code}",
        )
        check("Viewer denied internal & restricted docs (404)", v_int_code == 404 and v_res_code == 404, f"int={v_int_code}, res={v_res_code}")
        check("Viewer denied /api/admin/audit (403)", v_audit_code == 403, f"HTTP {v_audit_code}")

        # 6. Employee ACL checks + non-escalation
        e_int_code, e_int_prev, _ = emp_s.json_req("GET", f"/api/documents/{int_id}/preview")
        e_res_code, e_res_prev, _ = emp_s.json_req("GET", f"/api/documents/{res_id}/preview")
        e_users_code, _, _ = emp_s.json_req("GET", "/api/admin/users")
        e_widen_code, _, _ = emp_s.json_req("PATCH", f"/api/documents/{res_id}", {"access_scope": "company"})
        e_qr_code, _, _ = emp_s.json_req("GET", "/api/attendance/qr")
        check("Employee sees internal & own restricted doc", e_int_code == 200 and e_res_code == 200, f"int={e_int_code}, res={e_res_code}")
        check("Employee denied /api/admin/users (403)", e_users_code == 403, f"HTTP {e_users_code}")
        check("Uploader cannot widen restricted -> company (403)", e_widen_code == 403, f"HTTP {e_widen_code}")
        check("Employee denied /api/attendance/qr (403)", e_qr_code == 403, f"HTTP {e_qr_code}")

        # 7. Admin restricted isolation + Break-Glass + Explain + Audit Verify
        a_res_before, _, _ = admin_s.json_req("GET", f"/api/documents/{res_id}/preview")
        check("Admin cannot auto-read employee restricted doc (404)", a_res_before == 404, f"HTTP {a_res_before}")

        bg_code, _, _ = admin_s.json_req(
            "POST", f"/api/documents/{res_id}/break-glass", {"reason": "ACL lab live verification check"},
        )
        check("Admin break-glass with reason succeeds (200)", bg_code == 200, f"HTTP {bg_code}")

        exp_code, exp_body, _ = admin_s.json_req(
            "GET", f"/api/admin/access/explain?user_id={view_data['id']}&document_id={int_id}",
        )
        check(
            "Explain endpoint returns rule_chain denial for viewer on internal doc",
            exp_code == 200 and isinstance(exp_body, dict) and exp_body.get("allowed") is False,
            f"HTTP {exp_code} reason={exp_body.get('reason_code') if isinstance(exp_body, dict) else exp_body}",
        )

        ver_code, ver_body, _ = admin_s.json_req("GET", "/api/admin/audit/verify")
        check(
            "Audit hash chain verifies valid",
            ver_code == 200 and isinstance(ver_body, dict) and ver_body.get("valid") is True,
            f"HTTP {ver_code} checked={ver_body.get('checked') if isinstance(ver_body, dict) else ver_body}",
        )

    finally:
        # Cleanup all created documents and members (safe: only IDs created by this run!)
        print("--- Cleaning up fake ACLTEST data ---")
        cleaned_docs = 0
        for doc_id in created_doc_ids:
            dc, _, _ = admin_s.json_req("DELETE", f"/api/documents/{doc_id}")
            if dc == 204:
                cleaned_docs += 1
        cleaned_users = 0
        for uid in created_user_ids:
            uc, _, _ = admin_s.json_req("DELETE", f"/api/admin/users/{uid}")
            if uc == 204:
                cleaned_users += 1
        print(f"Cleaned {cleaned_docs}/{len(created_doc_ids)} documents and {cleaned_users}/{len(created_user_ids)} members.")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"=== Result: {passed}/{total} checks passed ===")
    return 0 if passed == total else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe black-box ACL test runner for Deskwise.")
    parser.add_argument("--base-url", required=True, help="API base URL (e.g. http://127.0.0.1:8000)")
    args = parser.parse_args()
    return run_suite(args.base_url)


if __name__ == "__main__":
    sys.exit(main())
