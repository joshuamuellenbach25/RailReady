# Phase 3: Web frontend (public demo) on the shared backend
Version: phase-3. Context: docs/spec/overview.md (F-18..F-20, F-21). Builds on the Phase 1–2 backend (backend, OpenAPI at /api/openapi.json) and Expo app (mobile) as delivered. Web app lives in frontend (React). Same auth, DB, object storage, pricing/gates, no frontend copies of business rules.

## Goal
A visitor opens the public website in a fresh browser, starts an isolated demo session, and completes jobs -> evidence/findings -> estimate -> proposal/contract -> customer acceptance -> work order on desktop layouts, using the same persisted records the mobile app reads/writes.

## Functional requirements
- REQ-97 [always] The system shall serve a public entry at `/` and `/demo` with "Open demo workspace" and "Field app" actions, short instructions and "Fictional sample data" labels.
- REQ-98 [event] When a visitor taps Open demo workspace, the system shall create an isolated demo session with new IDs and sign the visitor in to it.
- REQ-99 [always] The system shall restrict a demo session to its own fictional records.
- REQ-100 [event] When a visitor taps Reset demo, the system shall create a new isolated session leaving prior sessions' history intact.
- REQ-101 [unwanted] If demo session creation exceeds its rate limit, then the system shall show "Too many demo sessions – try again in a minute".
- REQ-102 [always] The system shall support staff sign-in on web with the same seeded accounts and server-resolved roles.
- REQ-103 [always] The system shall show `/office/jobs` listing each job's customer/site, visit status, findings count, estimate status, proposal version, contract status and work order.
- REQ-104 [always] The system shall show `/office/inbox` with Submitted visits separate from draft transfers.
- REQ-105 [always] The system shall show `/office/visits/:id` with photos, highlighted candidate regions, candidate decisions, transcripts, proposed fields with excerpts, discrepancies, coverage gaps and prior findings side by side.
- REQ-106 [event] When a reviewer confirms, corrects, dismisses or requests a closer photo on web, the system shall record it through the same API as mobile.
- REQ-107 [optional] Where the browser supports it, the system shall allow photo file upload into a draft visit through the same evidence/manifest/receipt flow.
- REQ-108 [always] The system shall label a prepared genuine analysis "Saved analysis" with its model id, prompt version and run time.
- REQ-109 [always] The system shall show `/office/visits/:id/estimate` with package preview/add, manual lines, quantity origins, review state, warnings, server totals, tax treatment and margin.
- REQ-110 [always] The system shall show agreement preview beside the estimate with validate blockers.
- REQ-111 [always] The system shall show `/office/proposals/:id` with customer-safe preview, versions, publish, share link, revoke and change requests.
- REQ-112 [always] The system shall show `/office/contracts` and `/office/contracts/:id` with the frozen issued document, template version/hash, document hash, status and acceptance evidence.
- REQ-113 [always] The system shall show `/p/:token` customer page with scope, photos, totals, agreement, terms, expiry, Accept and Request changes.
- REQ-114 [always] The system shall show `/office/work-orders/:id` with frozen scope separate from crew/date/access planning.
- REQ-115 [event] When a user opens print for a proposal or contract, the system shall open the server print HTML.
- REQ-116 [unwanted] If any API call fails, then the system shall show the server's error message and keep the user's inputs.
- REQ-117 [always] The system shall show the same record IDs and revisions on web and mobile for the same job.
- REQ-118 [unwanted] If a foreman signs in on web, then the system shall hide estimator actions and the server shall return 403 on them.
- REQ-119 [always] The system shall not expose demo-session or staff records to the customer page.

## Quality requirements
Q-17 Tag: Demo.Usability | Scale: minutes for a first-time visitor to go landing -> work order unaided | Meter: human / scripted run | Must: 6 | Plan: 3
Q-18 Tag: Demo.Isolation | Scale: foreign/staff records visible from a demo session (probes) | Meter: API test 10 probes | Must: 0 | Plan: 0
Q-19 Tag: Web.Layout | Scale: broken/clipped layouts at 1440px and 360px | Meter: screenshots | Must: 0 | Plan: 0
Q-20 Tag: Web.Speed | Scale: ms to render jobs list / visit review | Meter: browser timing x3 | Must: 3000 | Plan: 1200
Q-21 Tag: Parity.Trust | Scale: mismatched ids/totals between web and mobile for same job | Meter: tester | Must: 0 | Plan: 0
