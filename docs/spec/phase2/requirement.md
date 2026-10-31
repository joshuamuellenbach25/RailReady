# Phase 2: Estimating, contract packet, publish, customer decision, work order
Version: phase-2. Context: docs/spec/overview.md (F-11..F-17, F-23 change-request topic). Builds on Phase 1 backend + Expo app as delivered (MongoDB standalone: no multi-document transactions, use single-document conditional updates + unique indexes; see deviations).

## Goal
An estimator, on the mobile app (and via API usable by the later web app), turns a submitted visit's confirmed findings into a reviewed tie-replacement estimate with exact pricing, previews the illustrative agreement packet, publishes one immutable proposal+agreement version, shares a revocable customer link; the customer accepts or requests changes; acceptance creates exactly one work order with crew/date/access planning.

## Functional requirements
Estimate
- REQ-49 [event] When the estimator taps Preview tie package on a confirmed observation, the system shall show proposed lines with quantity origins before any line is added.
- REQ-50 [event] When the estimator taps Add package, the system shall add the package lines once per observation revision.
- REQ-51 [unwanted] If Add package is retried for the same observation revision, then the system shall return the existing lines without duplicates.
- REQ-52 [always] The system shall derive each-priced tie lines from the confirmed repair quantity, never the inspected quantity.
- REQ-53 [always] The system shall give hour, equipment-day and trip lines their own configured allowance basis marked "Needs review".
- REQ-54 [state] While material responsibility is Customer, the system shall omit the tie material purchase line.
- REQ-55 [state] While material responsibility is Customer, the system shall show "Ties supplied by customer" on the proposal.
- REQ-56 [unwanted] If tie package pricing is requested without confirmed location, repair quantity/unit, specification, material responsibility or access disposition, then the system shall list each missing fact as a blocker.
- REQ-57 [always] The system shall keep crosstie and switch-tie specifications distinct without substitution.
- REQ-58 [event] When the estimator adds a manual line, the system shall require a category, description, quantity, unit, unit cost, markup, taxable flag and reason.
- REQ-59 [event] When a source fact changes (scope, location, quantity, specification, supplier, access), the system shall mark dependent lines "Needs review" keeping estimator edits.
- REQ-60 [event] When a second mobilization line is added in the estimate, the system shall warn "Duplicate mobilization" and require a reason to keep it.
- REQ-61 [always] The system shall store on each line category, description, quantity/unit, unit cost, markup %, taxable flag, rate/package version, observation revision, quantity origin, assumption, reviewer and time.
Money (server-authoritative, exact decimal, USD)
- REQ-62 [always] The system shall compute internal cost = roundHalfUp(Q×C,2), selling line total = roundHalfUp(Q×C×(1+M/100),2), subtotal = sum of line totals, tax = roundHalfUp(sum taxable totals × tax%/100,2), total = subtotal + tax.
- REQ-63 [always] The system shall compute margin as (subtotal - sum internal costs)/subtotal and show "N/A" when the subtotal is zero.
- REQ-64 [unwanted] If a quantity is nonpositive, a unit is missing, a cost/markup/tax is negative, a value is nonfinite or exceeds 4 decimal places, then the system shall reject it with a field error.
- REQ-65 [always] The system shall ignore client-supplied totals and recompute on the server.
- REQ-66 [unwanted] If a line has zero selling price, then the system shall require explicit estimator review of it.
- REQ-67 [always] The system shall display the configured tax treatment text, not an automatic "Taxes not included" label.
Agreement packet
- REQ-68 [always] The system shall seed agreement template v1 labeled "Illustrative sample – not contractor-approved terms" with required variables: contractor legal identity, customer/site, proposal/version, scope, quantities, total/currency/tax treatment, schedule wording, assumptions/exclusions, payment terms, validity, acceptance wording.
- REQ-69 [event] When the estimator opens Agreement preview, the system shall render the populated agreement beside the estimate.
- REQ-70 [unwanted] If a required variable is missing, the price/scope is stale, or term edits are unreviewed, then the system shall block issue with the named blocker.
Publish
- REQ-71 [event] When the estimator taps Validate, the system shall list every publish-gate blocker returned by the server.
- REQ-72 [unwanted] If the draft has no included paid line, an unconfirmed scope/location, unresolved discrepancy, unreviewed line, undispositioned access uncertainty, missing selected media, invalid terms, past expiry or stale revision, then the system shall block publish with that blocker.
- REQ-73 [always] The system shall not let a reason, "Not applicable", General repair or a manual line clear a missing pricing fact.
- REQ-74 [event] When the estimator publishes, the system shall freeze proposal + agreement snapshot (fields, selected photos, lines, totals, terms, coverage, expiry, template version/hash, document content/hash, issuer/time) as numbered version N.
- REQ-75 [unwanted] If publish is retried with the same draft revision and idempotency key, then the system shall return the same version.
- REQ-76 [event] When version N+1 is published before acceptance, the system shall mark version N "Superseded".
- REQ-77 [always] The system shall keep published snapshots and their referenced originals unchanged by later edits.
Customer link
- REQ-78 [event] When the estimator taps Share, the system shall issue a link token of >=128 random bits stored hashed.
- REQ-79 [always] The system shall serve the customer only an allowlisted snapshot and selected photos, excluding cost, markup, margin, audio, transcripts, audit, dismissed candidates and model data.
- REQ-80 [event] When the estimator revokes a link, the system shall deny reading and decisions on it.
- REQ-81 [always] The system shall resolve expiry from site-local date/time + timezone into a UTC instant displayed with timezone.
- REQ-82 [state] While a version is Superseded or Expired, the system shall show it read-only with acceptance disabled.
Decisions & work order
- REQ-83 [event] When the customer submits Accept with name, valid email and the checked agreement box, the system shall record the decision with agreement hash/version and server time.
- REQ-84 [event] When an acceptance is recorded, the system shall create exactly one work order for that engagement.
- REQ-85 [unwanted] If acceptance is retried, concurrent, or races a revise/revoke/change-request/expiry, then the system shall produce one consistent outcome with at most one work order.
- REQ-86 [unwanted] If name, email or the agreement box is missing, then the system shall reject acceptance with field errors.
- REQ-87 [event] When the customer requests changes with name, email and comment, the system shall record them against the exact version and disable its acceptance.
- REQ-88 [event] When a change request is saved, the system shall store a Jev topic suggestion (price, scope, schedule, terms, other) shown to staff only.
- REQ-89 [event] When the estimator copies a changed-requested version to a new draft, the system shall preserve the feedback and history.
- REQ-90 [unwanted] If a commercial republish is attempted after acceptance, then the system shall reject it with 409.
- REQ-91 [always] The system shall show the work order's frozen accepted scope separately from editable crew, date and access status.
- REQ-92 [always] The system shall start work-order access at "Not arranged" with human-entered transitions to Requested and Confirmed.
- REQ-93 [always] The system shall never label a work order repaired, released or permitted to start.
- REQ-94 [event] When staff or customer opens print for a version, the system shall serve printable HTML from the frozen snapshot only.
- REQ-95 [always] The system shall provide every estimator action of this phase in the Expo app.
- REQ-96 [always] The system shall show the customer page at route /p/:token in the Expo web build. (interpreted; web app mirrors in Phase 3)

## Quality requirements
Q-11 Tag: Money.Correctness | Scale: cents of error vs spec formula on R32/R33 cases + 20 random | Meter: API test | Must: 0 | Plan: 0
Q-12 Tag: Decision.Integrity | Scale: work orders per engagement after 10 concurrent accepts | Meter: API race test | Must: 1 | Plan: 1
Q-13 Tag: Customer.Exposure | Scale: internal fields/media present in customer API, media and print | Meter: API + DOM scan | Must: 0 | Plan: 0
Q-14 Tag: Snapshot.Immutability | Scale: changed bytes in published snapshot/document hash after draft/catalog/template edits | Meter: API test | Must: 0 | Plan: 0
Q-15 Tag: Estimator.Usability | Scale: minutes for estimator to go submitted visit -> published on phone | Meter: human | Must: 10 | Plan: 4
Q-16 Tag: Print.Cosmetic | Scale: clipped sections/illegible text on print preview with long scope + 4 photos | Meter: screenshot review | Must: 0 | Plan: 0
