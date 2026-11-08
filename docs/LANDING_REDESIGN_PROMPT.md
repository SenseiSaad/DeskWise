# Deskwise — Landing Page Redesign (Handoff Prompt for a Coding AI)

You are implementing a redesign of the public marketing site in `/home/saad/Desktop/OpenVault/frontend` (Next.js 16 App Router, React 19, Tailwind 4, lucide-react, pnpm). Follow this document exactly. Do not touch the workspace (`app/workspace/**`) or the backend unless a section below says so.

## 0. Before you start
1. `git tag backup-pre-landing-v2 && git branch backup/pre-landing-v2` (rollback point).
2. Run `pnpm --dir frontend install` if `node_modules` is missing.
3. Read: `app/page.tsx`, `app/pricing/page.tsx`, `components/marketing/*`, `components/site-header.tsx`, `components/site-footer.tsx`, `app/globals.css` (design tokens, light/dark variables), `components/theme-toggle.tsx`, `components/reveal.tsx`.

## 1. Goals
- Simple, friendly, non-technical language. A shop owner or HR manager must understand it in 5 seconds.
- ONE consistent design, with a **light theme and a dark theme** (the existing theme toggle and `dark` class stay).
  - **Light theme:** fully light page (white / very light gray). Sections are separated by slightly darker borders/bands (e.g. `border-border`, `bg-surface`), never by dark sections.
  - **Dark theme:** fully dark page (near-black). Sections are separated by slightly lighter borders/bands.
  - Use semantic tokens (`bg-background`, `bg-surface`, `text-foreground`, `text-muted-foreground`, `border-border`, `accent`). **No hard-coded hex colors in components** (current `#0d0d0f`, `#0a0a0c`, `#ff5b24`, `#f3efe5` in marketing components must go). Orange is the single accent: define/adjust `--accent` in `globals.css` for both themes (light ≈ `#e8501a`, dark ≈ `#ff6a35`) and ensure contrast ≥ 4.5:1 for text.
- Text sizes: body ≥ 14px, no `text-[10px]`/`text-[11px]` in marketing pages.
- Remove the video completely.

## 2. Remove
- `components/marketing/product-showcase.tsx` (video player version) — replace per section 4.
- `public/feature-scroll.mp4`, `public/pricing-reference.jpg`.
- From the homepage only (keep the files, they may still be used by other routes): `SectorStrip`, `SystemSection`, `SecuritySection`, `AwsInfrastructure`, `HeroDemo` usage. Check other imports before deleting any file; do not break `/infrastructure`, `/policy`, `/about`, `/help`.
- `frontend/pre-redesign-backup/` can stay untouched.

## 3. Homepage structure (`app/page.tsx`)
Order, each a component in `components/marketing/`:
1. `SiteHeader` — links: Features, How it works, Pricing, About; right side: theme toggle, "Sign in", "Start free" button. Mobile: slide-down menu. Update `NAV` anchors and the IntersectionObserver ids in `site-header.tsx`.
2. `Hero` — headline "Your company knowledge. Answered in seconds." one sentence, primary CTA "Start free" (`/enterprise?tab=create`), secondary "See how it works" (`#story`). Right side: a pure CSS/React animated **chat mockup** (no images/video): a question bubble, an answer bubble with a "Source: Employee Handbook, page 18" chip, then a small "Leave request — ready to download" card. Loops with gentle fade-in steps; static if `prefers-reduced-motion`.
3. `ScrollStory` (new, **the key feature**, id `story`) — see section 4.
4. `HowItWorks` — 3 steps: Sign up → Upload documents → Ask. Reuse the big-numeral visual style of the story (01/02/03), light/dark aware.
5. `PricingSection` — see section 5. id `pricing`.
6. `FaqSection` — keep current 6 questions (already non-technical). Style with tokens.
7. `FinalCta` — one headline, one button.
8. `SiteFooter`.

## 4. ScrollStory — scroll animation spec (replaces the video)
Reference (user's recording): a tall page where each chapter shows a **huge bold numeral on the left** (01, 02, 03…), and to its right a **heading with a thin horizontal rule above it, a small label under the heading, and a paragraph**; chapters scroll past a fixed top bar, with a thin vertical progress rail at the far left.

Build `components/marketing/scroll-story.tsx` (`'use client'`):
- Desktop (≥ lg): two-column layout inside one tall section (`min-h` ≈ 100vh × number of chapters).
  - Left column `position: sticky; top: 6rem`: the giant numeral (font-display, ~`clamp(8rem, 18vw, 16rem)`, weight 700, tracking tight, `text-foreground`). The numeral crossfades/slides vertically when the active chapter changes.
  - Right column: the chapters stacked, each with: thin rule (`border-t border-foreground/80`), heading (text-2xl/3xl), small muted label, 3–4 line paragraph, and a **visual panel** (see below). Active chapter at full opacity, others at ~35% opacity, transition 300ms.
  - A thin vertical progress rail on the left edge (fixed within the section) filling with accent color according to scroll progress, plus small dots per chapter.
- Active chapter detection: `IntersectionObserver` on each chapter (`rootMargin: '-45% 0px -45% 0px'`). Progress via a scroll listener using `requestAnimationFrame`. No animation libraries.
- Mobile (< lg): no sticky; each chapter is a stacked block with its own numeral above the heading, reveal-on-scroll via the existing `Reveal`.
- `prefers-reduced-motion`: no transitions/transforms; all chapters fully visible.
- Accessibility: semantic `<ol>`, each chapter an `<li>` with `aria-label`; headings in order (section `h2`, chapters `h3`).

Chapters (copy is final, keep simple):
1. **Ask** — label "Instant answers". "Ask a question in plain English or Roman Urdu. Deskwise reads your company documents and answers with the exact page it found it on."
2. **Generate** — label "Ready-to-send forms". "Need a leave request or an HR letter? Deskwise fills in your name, role and dates and gives you a copy-paste-ready document to download as Word or PDF."
3. **Protect** — label "Private by default". "People only see what belongs to them. Payroll stays with HR, contracts stay with Finance, and nothing is used to train public AI."
4. **Prove** — label "Full history". "Every upload, question and download is recorded, so you can always see who did what and when."

Visual panels (no screenshots exist; build as small React/CSS mockups, ~320×220 card, token colors):
1. chat bubble + source chip; 2. a mini form card with filled fields and "Download DOCX/PDF" buttons; 3. a file list with lock icons and two avatars with different access; 4. a short audit timeline (4 rows).
Panels animate in (opacity + translateY 12px) when their chapter becomes active.

## 5. Pricing — 4 plans (keep current dark/orange card look but theme-aware)
Update `components/marketing/pricing-section.tsx` (used by homepage and `/pricing`):
| Plan | Price | Notes |
|---|---|---|
| Free | $0 | for trying out |
| Go | $19/mo | small teams |
| Plus | $49/mo | "Most popular" |
| Max | $129/mo | large organizations |
- 4 cards (grid `sm:grid-cols-2 xl:grid-cols-4`), feature checklist per card, CTA "Start free" (Free) / "Choose Go|Plus|Max".
- Comparison table with 4 plan columns: members, documents, storage, monthly AI questions, form generator, departments, bring-your-own AI key, audit log, support. **Use the real limits from the backend `Plan` data** (`backend/core/views.py` fallback plans + `seed_plans` command); do not invent limits that contradict them.
- Replace all hard-coded colors with tokens; table header uses `bg-accent text-accent-foreground`.
- Fix honesty issues in current copy: remove "Founded by data experts… analytics platforms" boilerplate and fake features ("200+ templates", "Premium widgets", "Real-time data processing"). Write copy that matches Deskwise.
- Backend rename (small, do together): rename plans Free/Starter/Business/Enterprise → Free/Go/Plus/Max in `seed_plans` + the fallback list in `views.py` (keep prices 0/19/49/129 and existing limits and IDs), update `frontend/lib/pricing.ts` taglines, and fix any tests/strings referencing old names (`backend/tests/test_plans.py`, `test_billing.py`, `test_feature_guards.py`, `frontend/lib/pricing.test.ts`). Stripe code reads `plan.name`, so no other change is needed.

## 6. Theme implementation notes
- Edit tokens in `app/globals.css` so that `:root` is clean light (background `#ffffff`, surface `#f6f7f9`, border `#e3e5ea`) and `.dark` is clean dark (background `#0e0f12`, surface `#16181d`, border `#272a31`). Remove the beige "parchment" palette from marketing surfaces. Do not break workspace pages that use the same tokens — after changing tokens, open `/workspace` and make sure it is still readable in both themes.
- Section separation: alternate `bg-background` and `bg-surface` bands with `border-y border-border` (light: band slightly darker than page; dark: band slightly lighter).
- Cards: `bg-surface border border-border rounded-2xl`; hover lifts border to `border-foreground/30`.

## 7. Acceptance criteria
- No `<video>` anywhere on marketing pages; `grep -r "feature-scroll" frontend` returns nothing.
- `grep -rE "#[0-9a-fA-F]{6}" frontend/components/marketing frontend/app/pricing frontend/app/page.tsx` returns no color literals (except inside SVG illustrations if unavoidable).
- Scroll story works at 1440px (sticky numeral + progress rail), 768px and 390px (stacked), and with reduced motion.
- Both themes verified visually on `/` and `/pricing`; toggle works without flash.
- `pnpm --dir frontend typecheck`, `pnpm --dir frontend test`, `pnpm --dir frontend build` pass; `backend/.venv/bin/pytest backend/tests` passes (224 tests).
- Lighthouse (desktop) accessibility ≥ 95 on `/`.
- Run locally with `./start-dev.sh restart` and report the URLs. Commit as `feat(ui): landing redesign v2 (scroll story, 4 plans, light/dark)`.

## 8. Out of scope
Workspace redesign, Stripe/payment logic, auth flows, infrastructure pages' content.
