# Step 7 — hostile re-review: findings and fixes

**Date:** 2026-11-24. **Project:** Deskwise / OpenVault_clean.
**Target:** the current, uncommitted working tree, including the previous audit's fixes. This is not an audit of bare `HEAD`.
**Review pass:** report and tests only. **Fix pass (this update):** all 10 findings are fixed in the application code (see "Fix status"). No model or migration change was needed, nothing was committed, and there were no live-site or external-service requests.

## Fix status (all 10 fixed)

The 14 attack tests were turned into ordinary regression tests (the `xfail` markers are gone) and 17 more tests check that legitimate flows still work. `backend/tests/test_step7_hostile_review.py` now has **48 tests, all passing**. The full backend suite: **442 passed, 14 skipped, 1 failed**. The one failure is `test_rag_units.py::test_gemini_and_bedrock_parallel_embed`, which failed before any of this work and is unrelated.

| ID | Fix | Where |
|---|---|---|
| S7-01 | MFA challenges carry the user's `token_version`. Password reset, logout-all, deactivation and promotion bump it, so any challenge issued earlier is refused. Challenges from before the deploy lack the field and are refused too (they live 5 minutes). | `mfa.py` (`issue_challenge`, `challenge_is_current`), `views.py` (`mfa_activate`, `mfa_verify`) |
| S7-02 | A first-time `enroll` challenge can only enable MFA on an account where it is still off, and the write is a conditional update. Replacing an authenticator needs a `rotate` challenge, which only the authenticated `/auth/mfa/setup` issues. | `views.py` (`mfa_activate`, `mfa_setup`) |
| S7-03 | An invitation only completes a **pending** account (no usable password yet). It is refused for accounts that already have a password, are inactive, or are platform-level. A password reset also retires outstanding invitations, and accepting one revokes older sessions. | `views.py` (`join_company`, `reset_password`) |
| S7-04 | Every login gets a session id (`sid`) that is carried through refresh rotations. Logout denylists the session, so access tokens copied before a refresh die with it. Other devices are unaffected. | `auth.py`, `views.py` (`logout`, `refresh`) |
| S7-05 | `/documents/confirm` uses the filename authorised at presign time and ignores the client's. The type and byte checks therefore can't be switched by renaming. | `views.py` (`upload_confirm`) |
| S7-06 | New `storage.delete_checked()` reports failure. The cleanup job and confirm-time rejection remove or burn the pending row **only after** the object is really gone, so failures are retried. The sweep walks rows by primary key in batches, so rows that keep failing can't starve the rest. | `storage.py`, `tasks.py`, `views.py` |
| S7-07 | The workflow path honours `enable_docgen`: no leave-form proposal is offered, confirm returns 403 (without burning the token), and the form download is gated like the other document-generation endpoints. | `workflow.py`, `views.py` |
| S7-08 | Template-based answers record the template's document id (`docgen.template_context_with_sources` → `stream_answer(template_source_ids=…)`), so they are masked when access is revoked. The room bot records it as a source as well. | `docgen.py`, `rag.py`, `views.py`, `team_chat.py` |
| S7-09 | New `BotSourceFilter`: a DeskWise answer is masked for any reader who can't currently open every document it cites. It applies to room history and pinned messages. It is dropped from room search, global search and room summaries, so matching text can't leak. | `team_chat.py`, `team_chat_views.py`, `views.py` |
| S7-10 | Promotion revokes every existing session, refresh token and unused one-time token. As defence in depth, platform-level accounts are only accepted with a token that completed two-factor sign-in (`mfa` claim), for REST and WebSocket. The claim survives refresh rotations. | `create_platform_admin.py`, `auth.py`, `ws.py`, `views.py` |

### Behaviour changes to expect after deploying

- **Platform/root admins must sign in once more.** Existing root sessions have no `mfa` claim, so they get a 401 and the normal login + TOTP flow fixes it. Ordinary users are not affected.
- **MFA or invitation steps in flight at deploy time** (5 minutes for challenges) must be restarted.
- **An invitation can no longer be used on an account that already has a password.** Admin-created accounts without a password work as before.
- **Bot answers in shared rooms can now show as "[This answer used a document you do not have access to.]"** for readers without current access to the cited documents. This includes answers whose source was later archived or unapproved.
- **`/documents/confirm` ignores the client `filename`.** The shipped frontend sends the same name, so nothing changes for it.
- **Reproduction commands below describe the original review.** They now pass instead of reporting failures.

## Results and limits

- **10 demonstrated findings**, reproduced by **14 attack tests**. All are now **fixed** (see "Fix status").
- **17 passing control tests**: the corresponding attacks were blocked in these local tests. A passing test is not a general guarantee of safety.
- No unauthenticated, arbitrary cross-tenant document IDOR was demonstrated. The strongest results are stale credentials gaining platform authority, invitation-based account recovery bypasses, and protected document content surviving AI/history permission checks.
- All requests run through local `APIClient`, including real cookie-JWT authentication. No `force_authenticate` is used.
- The tests enable rate limiting, use a private LocMem cache, use Django's in-memory email backend and block outbound socket connections. Test accounts, passwords, tokens and document markers are synthetic.
- R2 is an in-memory fake **below** `core.storage`, so the real range-read, deletion and cleanup code executes. Indexing is skipped in R2 acceptance tests; those prove acceptance into `Document`, not successful indexing or execution of the uploaded bytes.
- The LLM is deterministic: it echoes supplied context or returns a chosen intent. This tests application data-flow/authorization, **not** whether a real model can be successfully prompt-injected. Google verification is mocked only in a blocked-account-linking control; no Google signature bypass is claimed.
- Database setup and operator actions occur only in pytest's isolated test database. The promotion tests invoke the real `create_platform_admin --promote` command there; the attacker cannot promote an account.

### Reproduce

```bash
cd backend
.venv/bin/python -m pytest tests/test_step7_hostile_review.py -o addopts='--disable-warnings' -q
```

When the review was first run, the 14 attack tests were strict `xfail`s. Running them with `--runxfail` showed the original failures (14 failed, 17 passed). After the fixes the markers were removed, so the whole file passes.

Original review run: 31 tests, 17 passed and 14 strict `xfail`s. With `--runxfail`, 14 failed (the intended security assertions, not setup errors) and 17 passed.

**Severity:** P0 = takeover/cross-tenant exposure without a privileged prerequisite; P1 = account/platform compromise with a credential or privileged transition prerequisite; P2 = authorization/revocation/policy failure with additional prerequisites; P3 = defense-in-depth. None of these is classified P0.

## Confirmed findings

| ID | Severity | Demonstrated issue | Attack tests | Status |
|---|---|---|---:|---|
| S7-01 | P1 | Pending MFA challenges survive password reset / logout-all and mint current-generation sessions | 2 | Fixed |
| S7-02 | P1 | A second outstanding enrollment challenge can replace an already-enabled authenticator | 1 | Fixed |
| S7-03 | P1 | Old invitations remain password-setting capabilities after recovery and bypass MFA on promoted accounts | 2 | Fixed |
| S7-04 | P2 | Logout does not invalidate earlier access JWTs from the same refreshed session | 1 | Fixed |
| S7-05 | P3 | Changing the confirm filename bypasses the presigned binary format check | 1 | Fixed |
| S7-06 | P2 | Failed R2 deletion permanently loses the cleanup obligation | 2 | Fixed |
| S7-07 | P2 | AI-confirm can generate a downloadable form despite `enable_docgen=False` | 1 | Fixed |
| S7-08 | P2 | Template-derived LLM answers omit source IDs and remain readable after grant revocation | 1 | Fixed |
| S7-09 | P2 | Newly admitted low-clearance room members receive old bot answers from restricted documents | 1 | Fixed |
| S7-10 | P1 | Pre-promotion password-only JWTs gain platform powers without MFA | 2 | Fixed |

### S7-01 — MFA challenges are outside the revocation boundary (P1)

**Where:** `backend/core/mfa.py:117-134`; `backend/core/views.py:533-552`, `:561-577`; `backend/core/auth.py:76-81`.

**Prerequisite:** possession of a still-unexpired MFA challenge issued before a revocation event. For an already-enrolled account, a valid TOTP is also necessary. For enrollment, the old challenge already contains the attacker-known enrollment seed.

**Local evidence:**
1. Start a platform-admin enrollment through `/api/auth/login`.
2. Reset that user's password through `/api/auth/reset-password`; confirm that `token_version` increased.
3. Complete the **old** challenge through `/api/auth/mfa/activate`: **200**, followed by **200** from `/api/auth/me`.
4. Separately, create an enrolled admin's login challenge, invoke `/api/auth/logout-all` in a valid victim session, then complete the pending challenge: again **200** and a usable session.

The signed payload contains user, purpose, enrollment seed and nonce, but no credential/session generation. Completion checks active-user status, not the password/token generation used when the challenge was issued. Cookie issuance then stamps the user's **new** version onto the tokens. This lets a pending credential survive the recovery operation intended to revoke it. Enrollment and login challenges last five minutes.

**Tests:** `test_s701_enrollment_challenge_cannot_restore_session_after_password_reset`; `test_s701_login_challenge_is_revoked_by_logout_all`.

### S7-02 — Completing enrollment does not invalidate competing enrollments (P1)

**Where:** `backend/core/views.py:533-549`; `backend/core/mfa.py:117-122`.

**Prerequisite:** an attacker obtained their own password-only enrollment challenge before the owner completed enrollment. This is more than the already-documented trust-on-first-use problem: the attacker can win **after** the owner enrolled successfully.

**Local evidence:** obtain two enrollment challenges via two logins. Complete the owner's first challenge. Complete the second challenge with its own seed's next-step code (still in the allowed TOTP window): **200**. The stored `mfa_secret` is now the second seed.

The endpoint writes the challenge's seed even when the account already has MFA enabled. Burning the first nonce does not invalidate the second. The replay limiter can delay this by a time step but does not authorize the competing seed.

**Impact:** replacement of the owner's authenticator and a fresh platform-admin session without proving the already-enabled authenticator.

**Test:** `test_s702_old_enrollment_cannot_replace_the_completed_enrollment`.

### S7-03 — Invitation tokens are an independent, long-lived password reset path (P1)

**Where:** `backend/core/views.py:1089-1121`, `:883-890`.

**Prerequisite:** a copied, unconsumed invitation token for the victim. Invitations last seven days. This is not guessing a token or registering an arbitrary victim.

**Local evidence, recovered account:** start with an invited account with no usable password and an unconsumed invitation. Reset its password using a valid reset link, and log in with the recovered password. Present the old invitation to `/api/auth/join` with a new attacker-chosen password: **200**. The password is replaced, the attacker has a usable session, and the victim's existing session remains usable.

Reset invalidates only `password_reset` tokens. Invitation acceptance neither requires that the account still be pending nor revokes existing sessions after changing the password.

**Local evidence, promoted account:** issue an invitation, legitimately promote the account with the real operator command, and configure MFA on it. Redeem its outstanding invitation without any TOTP. `/api/admin/reports` returns **200**. `/auth/join` sets cookies directly rather than using the platform-admin MFA gate.

**Impact:** an old invitation can undo password recovery. If the account is subsequently promoted while its invitation survives, the same link bypasses platform MFA. Promotion is an explicit prerequisite, not an attacker-accessible operation.

**Tests:** `test_s703_old_invitation_cannot_reset_password_and_preserve_sessions`; `test_s703_invitation_after_platform_promotion_does_not_skip_mfa`.

### S7-04 — Logout revokes one access token, not the refreshed session's older access tokens (P2)

**Where:** `backend/core/views.py:598-621`, `:701-707`; `backend/core/auth.py:22-36`.

**Prerequisite:** an access JWT copied before its session refreshed, and the token is still within its normal lifetime.

**Local evidence:** log in; save access JWT A; refresh, receiving B; log out normally; replay A in a separate local client's access cookie. `/api/auth/me` returns **200**.

Logout denylists the currently presented access JTI (B), while rotation blacklists only the old refresh token. JWT A is neither denylisted nor tied to a revoked session-family identifier. The exposure is bounded by A's remaining access lifetime; this does not show an indefinite session or a refresh-token blacklist bypass.

**Test:** `test_s704_logout_revokes_pre_rotation_access_token`.

### S7-05 — The filename checked at confirm is not the one that was authorized at presign (P3)

**Where:** `backend/core/views.py:1422-1431`, `:1445-1466`, `:1486-1489`, `:1506`, `:1568-1575`; `backend/core/uploads.py:125-136`.

**Prerequisite:** an authenticated uploader using their own presigned key.

**Local evidence:** presign `report.pdf`; verify that the signed `ContentType` is `application/pdf`; place non-PDF bytes in the fake object; confirm that same key with `filename=notes.txt`: **201**, creating a `Document`. Confirming the same kind of bytes as `report.pdf` in the control test yields **400**, deletes the object, and performs `Range: bytes=0-2047`.

`PendingUpload.filename` is recorded but not enforced. Magic validation and the stored content type instead use the new client filename. A text extension takes the no-binary-signature path.

**Impact limit:** demonstrates bypass of the promised presigned format binding, not RCE/XSS. Text extensions already accept arbitrary byte prefixes. No real R2 policy or public bucket behavior was tested.

**Test:** `test_s705_changing_confirm_filename_cannot_bypass_binary_magic`.

### S7-06 — R2 delete failures are swallowed, then cleanup records are deleted/burned (P2)

**Where:** `backend/core/storage.py:150-158`; `backend/core/tasks.py:91-100`; `backend/core/views.py:1472-1480`.

**Prerequisite:** a transient object-service error while deleting an expired or rejected upload. The fake raises a deterministic `OSError`; no real R2 outage is claimed.

**Local evidence:**
- **Expiry:** upload, expire the pending row, make the fake object's delete fail, then call authenticated `/api/cron/maintenance`. Response is **200** and the cron reports the object purged, but it still exists and its pending row is gone.
- **Rejection:** confirm invalid PDF bytes while delete fails. Response is **400**, but the object still exists and the pending row is marked consumed. Expiring it and running the cron still does not remove it or leave a retryable row.

`storage.delete` swallows the failure. The callers therefore remove the only cleanup record or exclude it permanently by setting `consumed=True`.

**Impact:** orphaned, billable objects survive indefinitely under the application's cleanup mechanism after a transient deletion failure. The test proves loss of the retry obligation; it does not estimate production storage cost.

**Test:** `test_s706_cleanup_does_not_forget_an_object_whose_delete_failed`, parametrized as `expiry` and `rejection`.

### S7-07 — Workflow confirmation bypasses the document-generation feature gate (P2)

**Where:** `backend/core/views.py:3811-3828`, `:3833-3864`; `backend/core/workflow.py:118-133`, `:274-294`.

**Prerequisite:** a regular authenticated user in a company with AI chat enabled but document generation disabled. The fake model emits a supported `leave_request` intent.

**Local evidence:** with `enable_docgen=False`, `/api/docgen` returns **403**. `/api/ask` still issues the leave-request proposal. Confirming it returns **200** with a generated filename/download URL; fetching `/api/workflow/forms/<user>/<filename>` returns **200**.

The confirm endpoint gates AI chat but not document generation. The workflow-form download endpoint does not gate document generation either.

**Impact:** a disabled feature remains executable through an alternate AI route. This is not a bypass of Confirm: the test explicitly confirms the proposal.

**Test:** `test_s707_leave_proposal_cannot_execute_when_docgen_disabled`.

### S7-08 — Mixed template/LLM answers have no revocation provenance (P2)

**Where:** `backend/core/views.py:2196`, `:2283-2287`, `:2351-2361`; `backend/core/rag.py:900-916`, `:1014-1025`, `:1118-1125`; `backend/core/docgen.py:806-825`.

**Prerequisite:** an employee initially has a download-enabled grant to a restricted uploaded template. Its grant is later revoked.

**Local evidence:** use `/api/ask` with `outputs=["text","form"]` and a uniquely matching restricted template. The echo model's streamed answer contains the private template marker. Delete the grant; the document preview is now **404**. Fetch the conversation: the saved LLM answer is still `masked=false` and contains the marker.

When `template_text` is supplied, `stream_answer` deliberately uses no retrieved chunks. It derives all source IDs/names from those empty chunks and saves `source_document_ids=[]`. The correctly tagged deterministic artifact/message generated later does not repair the preceding LLM message's missing provenance.

**Impact:** previously protected template content remains retrievable through conversation history after live document access is denied. The fake model makes the data-flow deterministic; no claim is made about how often a real model would quote the template. The underlying template-source omission is independent of model behavior.

**Test:** `test_s708_template_derived_llm_answer_is_masked_after_grant_revocation`.

### S7-09 — Safe room retrieval does not make historical bot messages safe for new members (P2)

**Where:** `backend/core/team_chat.py:268-338`, `:475-486`, `:755-810`, `:814-828`, `:1000-1022`; `backend/core/team_chat_views.py:233-267`.

**Prerequisite:** an admin admits a new low-clearance member to a private room that already contains bot answers derived from restricted documents. This requires authorized room membership management; the newcomer cannot add themselves in the test.

**Local evidence:** create a private room whose existing members have grants to an internal, restricted document. A member asks the bot about it; the echo answer and its source ID are saved. Add a viewer without document access through the room PATCH endpoint. Their document preview returns **404**, but the room messages endpoint returns **200** including the old answer's restricted marker and source metadata.

The room-safe intersection applies to retrieval when generating a new answer, not to serialization of old answers for each reader. Unlike personal conversation history, room history has no current-document-access masking.

**Impact:** a new member who never had access to the source document receives its bot-derived content. If admitting a member is intended to disclose all historical sourced content regardless of document ACL, that is a policy decision to document; the test demonstrates the actual mismatch, not the admin's intent.

**Test:** `test_s709_new_lower_clearance_room_member_cannot_read_old_protected_bot_answer`.

### S7-10 — Promotion upgrades existing password-only sessions into platform sessions (P1)

**Where:** `backend/core/management/commands/create_platform_admin.py:89-95`; `backend/core/auth.py:140-144`; `backend/core/permissions.py:27-32`; `backend/core/views.py:2973-2975`, `:3736-3753`.

**Prerequisite:** a legitimate operator promotes an account for which an attacker holds a still-valid ordinary-user JWT. The tests invoke the real management command only as the operator.

**Local evidence:** log in as an ordinary employee, obtaining a password-only session. Platform endpoints initially return **403**. Promote the account using `create_platform_admin --promote`. No MFA is enabled and `token_version` is unchanged. Reuse the **old** session:
- platform company directory: **200**;
- change another tenant's plan: **200**, and the other tenant's plan actually changes;
- platform reports: **200**.

A fresh password login correctly requests MFA enrollment, demonstrating that the existing-session path skips the intended new-login gate. JWT authentication reads the freshly promoted database flags and grants platform authority to the old token. No user-accessible privilege field was forged.

**Impact:** promotion makes previously issued/stolen password-only credentials usable for platform operations without enrolling or completing MFA. Tenant-content guards do not prevent the demonstrated platform-level directory and plan mutation.

**Tests:** `test_s710_pre_promotion_session_cannot_get_platform_powers_without_mfa`; `test_s710_pre_promotion_session_cannot_use_platform_authority_without_mfa`.

## Blocked attacks (17 passing controls)

Every attempted control below has an endpoint-level pytest in the same review file.

| Attack | Test | Result |
|---|---|---|
| Another tenant's document metadata, preview, download and versions | `test_cross_tenant_document_idor_is_blocked` (4 variants) | 404 |
| Another tenant's document PATCH, share creation and deletion | `test_cross_tenant_mutation_and_share_are_blocked` | 404, row unchanged |
| Another user's artifact GET/download or conversation GET | `test_cross_tenant_artifact_and_conversation_idor_are_blocked` | 404 |
| Keep reading/asking an externally shared document after share revocation; download a view-only share | `test_external_share_revocation_blocks_read_and_rag` | Read revoked; RAG marker absent; view-only download 403 |
| Retrieve unshared other-tenant chunks through AI chat | `test_ai_rag_cannot_retrieve_unshared_other_tenant_chunks` | Marker absent |
| Confirm non-PDF bytes without renaming | `test_bad_pdf_without_rename_is_rejected_and_removed` | 400, object deleted, correct range request |
| Confirm another user's pending upload key to read/delete their object | `test_forged_other_users_upload_key_is_not_read_or_deleted` | 403; object neither fetched nor deleted |
| Forge a proposal signature, use another user's proposal, reuse a confirmed proposal, or add an external recipient | `test_proposal_forgery_other_user_and_reuse_are_blocked` | Rejected; only one email to the asking user |
| Read/edit/delete another tenant's room messages | `test_cross_tenant_team_room_and_message_ids_are_blocked` | 404 |
| Change a signed-in profile with an untrusted Origin | `test_untrusted_origin_cannot_change_an_authenticated_profile` | 403, profile unchanged |
| Dodge account lockout by rotating IPs | `test_account_lockout_cannot_be_bypassed_by_changing_ips` | 429 after ten failures |
| Complete a burned MFA challenge with a correct TOTP | `test_burned_mfa_challenge_does_not_accept_correct_code` | Rejected, no session |
| Google-link an already-bound email using a different verified provider sub | `test_google_different_sub_cannot_link_to_bound_account` | 403, no session; verified claims are mocked |
| Upload a filename containing `..` | `test_direct_upload_zip_path_traversal_filename_is_rejected` | 400, no Document row |

## Suspicious but not verified — not counted as findings

1. **Concurrent state transitions:** MFA attempt checking/burning, refresh rotation/reuse grace, Google first-link binding, simultaneous password resets and plan quota checks. SQLite/LocMem sequential tests do not establish PostgreSQL/Redis race behavior. I did not claim a concurrency exploit.
2. **Real object-store capabilities:** rewriting an already-confirmed key with a still-valid PUT URL, presigned Content-Length enforcement, ranged GET behavior, bucket privacy and lifecycle policies. No live R2 calls were made.
3. **Long-lived channels / generated outputs:** already-open WebSocket revocation and broader provenance for exported/copied answers. This review uses HTTP test clients, not a browser or ASGI WebSocket client.
4. **LLM network boundary:** DNS rebinding after URL validation, credential routing, genuine model prompt injection, and source-access changes during streaming. Providers/DNS were not contacted; deterministic fake responses cannot validate those infrastructure/model attacks.
5. **Identity lifecycle:** reassignment of a Google Workspace email after a sub has been bound, company transfers, and pre-existing legacy error/source metadata. No real Google provider or production rows were inspected.

## Verification and handoff

- **Original review:** 31 tests, 17 passed, 14 failing security assertions (strict `xfail`).
- **After the fixes:** `tests/test_step7_hostile_review.py` has 48 tests, all passing, with the 14 attack tests now plain regression tests. Other files touched: `test_ai_content_audit_findings.py` now patches `storage.delete_checked`.
- **Full backend suite:** 442 passed, 14 skipped, 1 failed. The failure is `test_rag_units.py::test_gemini_and_bedrock_parallel_embed`, which predates this work.
- **Not verified:** the frontend was not rebuilt, since no frontend file changed. Behaviour against a real shared cache (Redis), real R2 and a real browser is unverified, as before. The new session-denylist, challenge and TOTP state live in the shared cache.
- No commits were made. The working tree already contained substantial uncommitted changes before this review.
