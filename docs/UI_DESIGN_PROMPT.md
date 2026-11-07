# Prompt for claude.ai — TenderIQ UI screen designs

Copy everything below the line into claude.ai.

---

You are a senior product designer. Design the UI screens for **TenderIQ**, a web app for bid teams at IT companies in Pakistan who respond to government tenders (PPRA). Output **static, high-fidelity screen frames only** — like Figma frames. No backend, no real logic. Build each screen as a separate frame at **1440 × 1024 desktop** size, laid out side by side on one canvas page (HTML + Tailwind is fine), with a frame title above each one.

## What the product does (so the screens make sense)
1. The user uploads a **tender PDF** (100–300 pages) and the company's documents (profile, project completion letters, CVs, ISO certificates, audited financials).
2. AI agents read everything and list every **requirement** in the tender, each with its page number and the exact quote.
3. Each requirement gets one of four **compliance statuses**: Compliant, Partial, Non-compliant, Unverified.
4. The system recommends **Bid / Bid with conditions / No bid**, and gives a list of missing documents.
5. It drafts a **technical proposal** section by section. Missing facts show as yellow `[CLIENT INPUT REQUIRED: …]` badges.
6. An **auditor** checks the draft, then a **human approves** it. They can then export Word + Excel files. Nothing is ever submitted automatically.

## Visual direction
- Feel: a calm, trustworthy **"bid office"** tool, not a flashy AI toy. Dense but readable, like Linear or Stripe Dashboard.
- Colours: ink text `#14233a`, muted `#5a6779`, background `#f5f7f8`, cards white with `#d9e0e6` borders, one accent teal-blue `#1f6f8b`.
- **Status colours are fixed and used everywhere:** Compliant green `#1e7a4f` on `#e3f3ea` · Partial amber `#9a6400` on `#fbf0d9` · Non-compliant red `#b3362c` on `#f9e4e1` · Unverified grey `#5f6b78` on `#eceff2`.
- Type: "Sora" for headings, "Source Sans 3" for body (Google Fonts). Numbers in tables use tabular figures.
- Icons: lucide. Radius 8–12 px. Soft shadows only on dialogs.
- Source chips everywhere: a small pill `Tender.pdf · p.14` that looks clickable.
- Use realistic sample data: tender "Supply & Installation of Hospital Network Infrastructure", Ref "PPRA/IT/2026/0147", buyer "Sindh Health Department", deadline 28 Nov 2026, company "Quadgentics (Pvt) Ltd", amounts in PKR, requirement codes like `ELG-003`, `TEC-014`, evidence codes like `EV-PRJ-007`.

## App shell (on every signed-in screen)
Left sidebar: logo "TenderIQ", Dashboard, Tenders, Knowledge base, Settings; the org name + user at the bottom. Top bar: page title, search, and a "New tender" primary button. Tender pages have a sub-header with the tender title, reference, a deadline countdown and a status pill, plus **tabs: Run · Analysis · Compliance · Proposal · Review**.

## Frames to design (in this order)
1. **Login / Create organisation** — split screen: left a product message ("Know if you qualify before you write a word"), right a form. Show the sign-in state.
2. **Dashboard** — 3 stat cards (Tenders, Awaiting review, Approved), a "Recent tenders" table (title, buyer, deadline, recommendation pill, status, last updated), an empty-state variant as a small inset frame.
3. **New tender** — step layout: (1) tender title, (2) drag-and-drop zone for tender PDF + addenda (show 2 uploaded files with page counts and "Extracted ✓"; one addendum marked #1), (3) company documents: choose from the knowledge base (checkbox list with document kind tags: Company profile, Project credential, CV, Certification, Financial statement) or upload, (4) big "Start analysis" button with an estimated time/cost note.
4. **Live run** — a pipeline diagram of the agents: Ingest → (Tender Reader ∥ Company Researcher) → Compliance Checker → Bid decision → (Solution Designer ∥ Form detection) → Proposal Writer → Auditor → Human review → Done. Nodes coloured by state (done green, running teal with a spinner, waiting grey, failed red). Right side: a live step log with timestamps ("Tender Reader: window 4/9 …"), a cost meter ("$0.84 of $5.00 budget"), tokens used. Show one failed-node variant with an error panel and a "Retry from this step" button.
5. **Analysis** — tender metadata card (reference, buyer, deadline, bid security, submission method, scope summary). Requirements table with filter chips (category, mandatory only, confidence) and columns: code, category, requirement, Mandatory badge, confidence, source chip. Show a **page preview drawer** open on the right: the PDF page text with the quoted sentence highlighted.
6. **Compliance** — top: a large **bid decision banner** in its "Bid with conditions" amber state, with 3 plain-language reasons. Then summary counters for the 4 statuses (with a small stacked bar). Then the compliance table: code, requirement, status chip, evidence codes, rule applied (e.g. "R5 · capped: self-declared only"), gap / action. One row expanded to show an evidence popover with the quote + page. Right column: "Missing information" checklist grouped by severity (Blocker, High, Medium, Low) with checkboxes. Export to Excel button. Add a small extra frame showing the **No bid** red banner variant listing the blocking requirements.
7. **Proposal workspace** — 3 columns: left a section list (18 sections; ticks, a warning dot on sections with audit findings, an "edited" marker); centre the section editor showing formatted text with yellow `[CLIENT INPUT REQUIRED: …]` badges inline; right panel tabs: Citations (claim → evidence codes), Placeholders (list to fill), Audit findings (severity pill BLOCKER/MAJOR/MINOR, description, suggested fix). Buttons: Save, Regenerate section (with an instructions popover).
8. **Review & approve** — audit summary (passed/failed, blocker/major/minor counts, "1 automatic revision used"), checklist of what will be exported, buttons: Approve, Request changes, Download draft (watermarked), Export Word, Export Excel (disabled until approved — show the disabled state with a tooltip). Include the **Request changes dialog** as an overlay frame: choose sections + notes.
9. **Knowledge base** — the company's reusable documents: table with kind, file, pages, extracted facts count, last used, verification badges (Documented / Self-declared / Expired) and an "Evidence register" tab preview (code, category, description, source chip, status).

## Rules for every frame
- Show realistic data, never lorem ipsum.
- Include at least one loading skeleton, one empty state and one error state across the set (label which).
- Accessible contrast (WCAG AA), visible focus rings on one focused control, labelled inputs.
- Show prices nowhere in proposal content: the product never puts prices in the technical proposal.
- Keep the copy short and plain (a bid manager reads it, not an engineer).

Deliver: all frames on one canvas, then a short list of the reusable components you used (StatusChip, SourceChip, BidDecisionBanner, PipelineNode, DataTable, Drawer, Dialog, PlaceholderBadge, SeverityPill) with their variants, so a developer can build them.
