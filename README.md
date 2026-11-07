# TenderIQ

**Tender intelligence and proposal drafting for bid teams.**

TenderIQ reads a tender document, checks whether your company qualifies for it, recommends whether
to bid, and drafts the technical proposal and tender forms. Every finding points back to the page
it came from, every claim about your company is backed by your own documents, and nothing is final
until a person on your team approves it.

TenderIQ is a **multi-agent system**: a team of specialised AI agents, each an expert in one part
of the bid process, works through the tender together, handing results from one to the next. It
is also a **multi-tenant platform**: one installation serves many companies, and each company
works in its own fully separate, private workspace.

## Demo

<video src="https://github.com/user-attachments/assets/8a4642cb-3239-4d03-a28d-133161b28566" controls width="100%"></video>
---

## Contents

- [The problem it solves](#the-problem-it-solves)
- [TenderIQ at a glance](#tenderiq-at-a-glance)
- [The journey of a tender](#the-journey-of-a-tender)
- [A team of AI agents](#a-team-of-ai-agents)
- [What TenderIQ does, in detail](#what-tenderiq-does-in-detail)
- [The screens](#the-screens)
- [Principles TenderIQ never breaks](#principles-tenderiq-never-breaks)
- [One platform, many organisations](#one-platform-many-organisations)
- [Security and privacy](#security-and-privacy)
- [Who it is for](#who-it-is-for)
- [What stays in your hands](#what-stays-in-your-hands)
- [Glossary](#glossary)
- [For developers](#for-developers)

---

## The problem it solves

Public tenders are long, dense and unforgiving. A typical tender runs to dozens or hundreds of
pages, and addenda issued later can change the rules. Before writing a single word of the
proposal, a bid team has to:

- find every requirement, including the mandatory ones that disqualify you if missed,
- check each one against the company's real credentials: registrations, certificates, audited
  accounts, staff CVs and completed projects,
- notice when a certificate will have expired by the submission deadline,
- decide quickly whether the tender is worth pursuing at all,
- write a long technical proposal that answers every requirement,
- and fill in the tender's own forms in the exact format it asks for.

This is slow, manual reading and cross-checking, usually done under deadline pressure. Mistakes
are costly. One missed requirement, an expired certificate, an overstated claim or a price
slipped into the technical envelope can get a bid rejected after weeks of work.

TenderIQ does the reading, cross-checking and first drafting for you, so the team spends its time
on judgement, strategy and making the bid stronger.

---

## TenderIQ at a glance

| You give it | You get back |
|---|---|
| The tender document and any addenda | A full list of requirements, each linked to its page |
| Your company documents (once, then reused) | A structured register of your company's evidence |
| A click to start the analysis | A compliance matrix showing what you meet and what you don't |
| | A bid / no-bid recommendation with clear reasons |
| | A checklist of missing information, ranked by urgency |
| | A proposed technical solution and delivery plan |
| | A complete draft technical proposal |
| | Pre-filled drafts of the tender's prescribed forms |
| | A quality check of the proposal before you see it |
| Your review and approval | A finished Word proposal and Excel compliance workbook |

---

## The journey of a tender

1. **Create the tender and upload documents.** Add the main tender document plus any addenda or
   corrigenda, in the order they were issued.
2. **Choose company documents.** Pick documents from your company knowledge base or upload new
   ones: company profile, project completion letters, staff CVs, certificates, registration and
   tax documents, audited financial statements.
3. **Start the analysis and watch it live.** A progress view shows each stage as it runs, how
   long it took and how much it cost. If a stage fails, you can retry it without starting over.
4. **Read the tender analysis.** See the tender's key facts and every requirement, filterable by
   category, mandatory/optional and confidence.
5. **Check compliance and the bid decision.** See where your company stands on each requirement,
   the overall recommendation, and what is still missing.
6. **Work on the proposal.** Read and edit each section, see which evidence supports each claim,
   fill in the marked gaps, and regenerate any single section you want rewritten.
7. **Review and approve.** Look over the quality-check results, then approve the proposal or send
   it back with notes on what to change.
8. **Export.** Download the final Word proposal and Excel compliance workbook.

---

## A team of AI agents

A real bid team splits the work: someone reads the tender, someone gathers the company
credentials, someone checks compliance, a solution architect designs the approach, writers draft
the proposal and a reviewer checks it all. TenderIQ works the same way. Instead of one AI trying
to do everything at once, the work is divided between **specialised agents**, each with one clear
job.

| Agent | Its job |
|---|---|
| **Document reader** | Reads every uploaded file page by page, including tables and scanned pages |
| **Tender analyst** | Extracts the tender's key facts and every requirement, then applies the addenda |
| **Evidence collector** | Turns your company documents into a structured evidence register |
| **Compliance checker** | Matches each requirement to your evidence and decides its status |
| **Bid advisor** | Makes the bid / no-bid recommendation and explains the reasons |
| **Solution architect** | Designs the technical approach, architecture, phases, risks and gaps |
| **Forms specialist** | Finds the tender's prescribed forms and drafts them from your evidence |
| **Proposal writers** | Write the proposal, one section per writer, several at the same time |
| **Auditor** | Checks the finished proposal for unsupported claims, gaps, pricing and contradictions |
| **Human reviewer** | You: the final approval step, which no agent can skip |

### How the agents work together

- **In order, and in parallel where possible.** Each agent starts when the work it depends on is
  ready. Independent work runs at the same time: the tender analyst and the evidence collector
  work side by side, and the proposal sections are written in parallel. This makes a full analysis
  much faster.
- **Through a shared case file.** Agents never talk to each other directly. Each one reads what it
  needs from the shared record of the tender and adds its own results to it, so every step is
  recorded and traceable.
- **Each agent is checked.** An agent's output must match a strict format before it is accepted.
  Fixed rules then double-check the agents' judgement: compliance statuses, numeric thresholds and
  the bid decision are decided by rules, not by an agent's opinion alone.
- **The auditor can send work back.** If the auditor finds serious problems, the affected
  sections go back to the writers for one automatic revision before reaching you.
- **You can watch them work.** The live progress screen shows each agent as it starts, finishes
  or fails, with its time and cost. A failed agent can be retried from where it stopped, without
  repeating the work already done.
- **Agents cannot act outside TenderIQ.** They read documents and produce drafts. None of them can
  send, submit or publish anything.

---

## What TenderIQ does, in detail

### 1. Reads every document properly

- Accepts PDF and Word documents.
- Reads text and tables page by page, keeping track of exactly which page everything came from.
- Handles **scanned documents**: pages that are only images are read with text recognition (OCR).
- Warns you when a document could not be read well, for example when many pages came out blank,
  so you know where to double-check.

### 2. Understands the tender

TenderIQ pulls out the tender's **key facts**:

- title, reference number and procuring entity,
- submission deadline and bid validity period,
- bid security required,
- submission method (for example single-stage two-envelope),
- a short summary of the scope of work,
- the evaluation criteria and the marks each one carries,
- and the proposal structure, if the tender prescribes one.

It then lists **every requirement**, each sorted into a category and given a reference code:

| Category | Code | Examples |
|---|---|---|
| Eligibility | ELG | Company registration, tax status, not blacklisted |
| Financial | FIN | Minimum turnover, bank statements, bid security |
| Experience | EXP | Number and value of similar completed projects |
| Personnel | PER | Key staff, required qualifications, years of experience |
| Certification | CER | ISO, CMMI and other required certificates |
| Technical | TEC | Specifications and functional requirements |
| Submission | SUB | Format, envelopes, deadlines |
| Deliverable | DEL | What must be delivered |
| Evaluation | EVL | How bids will be scored |
| Commercial | COM | Payment terms and penalties (for information) |

For each requirement you see whether it is **mandatory or optional**, the **exact quote and page**
it came from, and a **confidence level**. TenderIQ checks that every quote really appears on the
cited page; if it cannot confirm it, the requirement is marked low-confidence instead of being
quietly dropped.

**Addenda are applied automatically.** When an addendum changes, adds or removes a requirement,
TenderIQ updates the list in issue order, and the old version is shown as replaced, not deleted.

### 3. Builds your company knowledge base

Your company documents are turned into an **evidence register**: a structured list of everything
that can prove what your company has done and holds.

| Evidence type | What is captured |
|---|---|
| Projects | Client, title, value, dates, sector, technologies, completion status |
| Financials | Turnover or net worth, financial year, value, whether audited |
| Personnel | Name, role, years of experience, qualifications, certifications |
| Certifications | Name, issuer, issue and expiry dates, scope |
| Registrations | Company and tax registration authority and date |
| Capabilities and partnerships | Services, products and partner status |

Every item is marked by how well it is proven:

- **Documented:** backed by a proper document such as a certificate, completion letter or
  audited statement.
- **Self-declared:** only stated in the company profile, with no supporting document.
- **Expired:** a certificate whose expiry date falls before today or before this tender's
  deadline. The same certificate can be valid for one tender and expired for another.

The knowledge base belongs to your organisation and is **reused across tenders**. Each document is
read once; the next tender starts with everything already in place.

### 4. Checks compliance requirement by requirement

For each requirement, TenderIQ finds the most relevant evidence in your knowledge base and gives
one of four statuses:

| Status | Meaning |
|---|---|
| 🟢 Compliant | Met, and backed by at least one valid, documented evidence item |
| 🟡 Partial | Partly met, or met only by self-declared evidence that needs documentary proof |
| 🔴 Non-compliant | Not met, or the only proof has expired |
| ⚪ Unverified | No relevant evidence found either way |

Every status shows its reasoning, the evidence it relied on (with quote and page), what the gap is,
and what action would close it.

**Numbers are checked by calculation, not judgement.** For requirements such as "average annual
turnover of at least PKR 100 million over 3 years", "at least 3 similar government projects of
PKR 50 million each in the last 5 years", "10 years in business" or "5 certified engineers",
TenderIQ counts and adds up the qualifying evidence itself:

- documented evidence alone meets the threshold → **Compliant**,
- it only meets the threshold once self-declared evidence is included → **Partial**, with a note
  saying which items need proof,
- documented evidence reaches at least half the threshold → **Partial**,
- less than half → **Non-compliant**,
- no evidence of that kind at all → **Unverified**.

If amounts are in a different currency from the one the tender asks for, TenderIQ does not guess
the conversion; it asks you for the figure in the right currency.

### 5. Recommends whether to bid

TenderIQ gives one of three recommendations, decided by clear rules:

| Recommendation | When |
|---|---|
| **Bid** | All mandatory requirements are met |
| **Bid with conditions** | Nothing mandatory is failed, but some mandatory items are only partial or unverified and need action |
| **No bid** | At least one mandatory requirement is not met |

The recommendation comes with plain-language reasons and a list of the **blocking requirements**.
A No-bid result is shown as a persistent red banner so nobody misses it. Where the tender publishes
evaluation marks, TenderIQ also estimates how well your evidence covers them.

### 6. Lists what is missing

Every requirement that is not fully compliant becomes an item on the **missing-information
checklist**: renew this certificate, add this CV, attach the audited accounts for this year,
provide documentary proof for that project. Items that would block a mandatory requirement are
marked as **blockers** so the team knows what to chase first.

### 7. Designs the technical solution

Before writing the proposal, TenderIQ works out what you will actually propose, based on the
tender's technical requirements and your company's real capabilities:

- the overall approach and solution architecture, with each component mapped to the
  requirements it answers,
- delivery phases with objectives, activities, deliverables, durations and dependencies,
- testing, deployment and support approach,
- assumptions and risks, each with its impact and mitigation,
- and **capability gaps**: places where the tender asks for something your evidence does not
  cover.

Every mandatory technical requirement is either traced to a part of the solution or listed openly
as a gap.

### 8. Writes the proposal, section by section

Each section is written separately, using only the requirements, evidence and solution details
relevant to that section. If the tender prescribes a proposal structure, TenderIQ follows it;
otherwise it uses this standard structure:

| Section | Built from |
|---|---|
| Cover page | Company and tender details |
| Table of contents | Generated automatically |
| Executive summary | Tender facts, solution summary, strongest evidence |
| Understanding of requirements | Scope, technical requirements and deliverables |
| Company profile | Registrations, capabilities, financials |
| Proposed technical solution | The solution design |
| Solution architecture | Architecture components |
| Scope of work | Deliverables |
| Implementation methodology | Delivery phases |
| Project timeline | Phases, as a table |
| Team composition | Staff evidence matched to personnel requirements |
| Relevant project experience | Projects matched to experience requirements |
| Testing and quality assurance | Testing approach |
| Deployment and commissioning | Deployment approach |
| Support and maintenance | Support model |
| Assumptions and dependencies | Assumptions and risks |
| Annex A: Compliance matrix | The compliance results |
| Annex B: Prescribed forms | The form drafts |

Every factual statement about your company is linked to the evidence that supports it. Anything
TenderIQ cannot know is left as a highlighted placeholder, such as
`[CLIENT INPUT REQUIRED: name of project manager]`, and all placeholders are collected in one list
so none are forgotten.

You can **edit any section** yourself or **regenerate a single section**. Your manual edits are
never overwritten unless you ask for that section to be rewritten, and every revision is kept as
a new version.

### 9. Prepares the tender's own forms

TenderIQ finds the forms the tender requires (bid forms, schedules, annexes, affidavits,
undertakings, CV formats and so on) and drafts them from your evidence. Each field is marked as
filled, needing your input, or not applicable. Two kinds of fields are always left for you:

- **Signatures, stamps, signing dates and acceptance of declarations** are never filled in.
- **Financial forms** are skipped entirely, because pricing belongs to your financial bid.

### 10. Checks the proposal before you see it

Before the proposal reaches a reviewer, TenderIQ runs a quality check that looks for:

| Problem | Example |
|---|---|
| Unsupported claim | "We have completed 20 government projects" with no evidence behind it |
| Invented name | A client or certification mentioned in the text that is not in your evidence |
| Broken reference | A citation that points to evidence or a requirement that does not exist |
| Missing mandatory coverage | A mandatory requirement not answered anywhere |
| Missing section | A required section left out |
| Pricing leak | A price, rate or fee appearing in the technical proposal |
| Contradiction | Two sections that disagree |
| Structure deviation | Sections not in the order the tender prescribes |
| Inconsistent terms | The same thing called different names in different sections |

Each issue is rated **blocker**, **major** or **minor**, with a suggested fix. If serious issues are
found, TenderIQ rewrites the affected sections **once** automatically and checks again. Anything
still unresolved is flagged for the reviewer rather than looped on endlessly.

Pricing that slips into technical content is removed automatically and replaced with a note that
commercial content belongs in the financial proposal. Turnover and past project values in the
company profile and experience sections are allowed, because tenders ask for them.

### 11. Waits for human approval

The analysis always stops and waits for a person. The reviewer sees the quality-check summary and
either:

- **approves** the proposal, which marks the tender as approved and unlocks the final export, or
- **requests changes**, choosing which sections to redo and adding notes, after which TenderIQ
  revises them and returns the proposal for review.

### 12. Exports ready-to-use files

**Word proposal**

- Professional A4 layout with consistent headings, a header showing the tender reference, and a
  footer with page numbers and "Confidential".
- Cover page with your company name, tender title, reference, procuring entity and date.
- Automatic table of contents.
- Placeholders highlighted in yellow so they stand out.
- Annex A with the compliance matrix and Annex B with the prescribed forms.
- Internal evidence references are kept out of the submission copy. An optional internal review
  copy adds an evidence reference list at the end.
- Before approval you can download a draft, watermarked "DRAFT — NOT FOR SUBMISSION".

**Excel compliance workbook**

| Sheet | Contents |
|---|---|
| Compliance | Every requirement with its status, evidence and source page, with filters and colour coding |
| Missing information | The checklist of what still needs to be provided |
| Evidence register | Your company evidence used for this tender |

---

## The screens

| Screen | What you do there |
|---|---|
| **Login** | Sign in to your organisation's workspace |
| **Dashboard** | See how many tenders you have, which are awaiting review and which are approved, plus recent tenders |
| **New tender** | Upload the tender and addenda, pick company documents, start the analysis |
| **Live progress** | Watch each stage run, see time and cost, retry a failed stage |
| **Tender analysis** | Read the tender's key facts and browse all requirements with their sources |
| **Compliance** | See the bid recommendation, compliance summary, full compliance table and missing-information checklist |
| **Proposal workspace** | Move between sections, edit text, see supporting evidence, track placeholders and quality-check findings, regenerate a section |
| **Review** | Read the quality-check summary, approve or request changes, export files |

Throughout the app, every requirement, evidence item and claim carries a small source tag such as
`Tender · p.12`. Clicking it opens that page with the quoted text highlighted.

---

## Principles TenderIQ never breaks

1. **Nothing is invented.** No made-up projects, clients, certifications, staff, qualifications or
   figures. If it is not in your documents, it does not appear as fact.
2. **No mandatory requirement is silently skipped.** Every requirement gets exactly one status,
   and every mandatory one is answered in the proposal or the compliance annex.
3. **Gaps are always visible.** Missing information is marked as
   `[CLIENT INPUT REQUIRED: …]` and listed, never papered over.
4. **Compliant means proven.** A requirement is only marked Compliant when valid, documented,
   non-expired evidence supports it.
5. **Rules have the final say.** The AI suggests matches and drafts text, but fixed rules decide
   compliance status, numeric thresholds and the bid recommendation.
6. **Technical and financial stay separate.** No pricing ever appears in the technical proposal or
   non-financial forms.
7. **A person always signs off.** Nothing is final without human approval, and TenderIQ cannot
   submit anything anywhere.

---

## One platform, many organisations

TenderIQ is multi-tenant. Many companies use the same platform at once, and each one is a separate
**organisation** with its own:

- users and team roles,
- tenders, analyses and proposals,
- company knowledge base and evidence register,
- uploaded files and exports,
- jurisdiction setting, which decides the procurement rules and form formats it works with.

Organisations are completely isolated from each other. Every piece of data belongs to exactly one
organisation, and every request is checked against the signed-in user's organisation, so one
company can never see, search or download another company's tenders, documents or evidence.
This isolation is tested by deliberately trying to access another organisation's data.

Usage limits also apply per organisation, so one busy organisation cannot slow the platform down
for the others.

---

## Security and privacy

- **Private workspaces.** Each organisation's tenders, documents and evidence are completely
  separate. One organisation can never see another's data (see
  [One platform, many organisations](#one-platform-many-organisations)).
- **Secure sign-in.** Passwords are stored securely and sessions expire automatically.
- **Safe file handling.** Uploaded files are checked for their real type and size, and unsafe
  content such as embedded scripts is rejected. Files can only be downloaded by signed-in users of
  the owning organisation.
- **Documents are treated as data, not instructions.** Text inside a tender cannot steer TenderIQ
  into doing something it should not, and the AI has no ability to act outside the system.
- **Sensitive details stay out of logs.** Full document text and registration or tax numbers are
  never written to logs.
- **Encryption** in transit and at rest in production.
- **Fair-use limits and cost budgets.** Usage limits per user and organisation, and a spending
  limit per analysis that stops it before costs run over.

---

## Who it is for

TenderIQ is built for companies that bid on public sector contracts, with a focus on **IT tenders
in Pakistan's public procurement system (PPRA-style)**. The jurisdiction is configurable, so the
same platform works for other markets such as the GCC.

Each organisation has its own workspace, and team members have roles:

| Role | Typical use |
|---|---|
| Admin | Manages the organisation and its users |
| Bid manager | Runs tenders, reviews results, approves proposals |
| Technical lead | Reviews and edits the technical solution and proposal |
| Viewer | Read-only access to results |

---

## What stays in your hands

TenderIQ prepares the bid; your team stays in control of it. By design, TenderIQ does **not**:

- submit bids to any procurement portal,
- prepare financial bids or pricing,
- sign documents or make legally binding declarations,
- search portals for new tenders,
- provide win/loss or competitor analysis.

---

## Glossary

| Term | Meaning |
|---|---|
| **Tender** | A formal invitation from a public body for companies to bid for a contract |
| **Addendum / corrigendum** | A later notice that changes or corrects the original tender |
| **Requirement** | Anything the tender says a bidder must have, do or submit |
| **Mandatory requirement** | A requirement that disqualifies the bid if not met |
| **Evidence** | A fact about your company backed by a source document |
| **Compliance matrix** | A table showing, for each requirement, whether you meet it and why |
| **Bid / no-bid** | The decision whether a tender is worth pursuing |
| **Prescribed form** | A form the tender requires you to fill in its own format |
| **Two-envelope system** | Technical and financial bids submitted and evaluated separately |
| **Placeholder** | A marked gap in the proposal that your team must fill in |

---

## For developers

Setup, architecture and build details live in the `docs/` folder:

- [Technical specification](docs/TECHNICAL_PRD.md): full system design
- [Build rules](docs/MASTER_PROMPT.md): coding conventions for this project
- [Decisions log](docs/DECISIONS.md): choices made during the build

Quick start with Docker:

```bash
cp .env.example .env
docker compose up -d --build
```

Set `JWT_SECRET` and the AI provider API keys in `.env` first. The app opens at
http://localhost:3000 and the API at http://localhost:8000/api/v1. If those ports are taken, set
`DB_PORT`, `BACKEND_PORT`, `FRONTEND_PORT`, `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` in `.env`.

Local development needs Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20+ and Docker:

```bash
docker compose up -d db
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

Tests and checks:

```bash
cd backend && uv run pytest && uv run ruff check . && uv run mypy app
cd frontend && npm run lint && npx tsc --noEmit
```
