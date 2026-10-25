# Implementation Decisions

This file records general fixes discovered from the 32 public sample cases. No
prediction rule uses a case ID or a hand-written case list. Metrics are from
`code/evaluation/run_eval.py`; the 22-case development split is the first 22
natural sample rows and the remaining 10 are the hold-out check.

## 2026-10-24 — Add hold-out and complete mismatch buckets

- **Failure:** The evaluator reported one aggregate score and only a few sample differences.
- **Cause:** There was no fixed development/hold-out split and no complete mismatch taxonomy.
- **Fix:** Added deterministic 22/10 evaluation, all-case mismatch counts, per-bucket case lists, and full per-case mismatch details for missing steps, extra steps, wrong evidence IDs, and wrong order.
- **F1 before/after:** baseline step F1 without evidence `0.836` / after evaluator `0.836`; hold-out F1 `0.853`.

## 2026-10-24 — Prefer event time over late file capture

- **Failure:** Historical log events that occurred before `audit_at` were discarded when the containing evidence file was captured later; this hid valid account and security readbacks.
- **Cause:** The cutoff rejected `captured_at > audit_at` even when the fact's observed event time was before the cutoff.
- **Fix:** Apply the time cutoff to the observed/event timestamp when present, while still rejecting undated evidence captured after the cutoff. Select citation evidence only from evidence captured by the cutoff.
- **F1 before/after:** with evidence `0.831` → `0.862`; without evidence `0.836` → `0.867`; hold-out F1 `0.853` → `0.896`.

## 2026-10-24 — Carry identifiers across structured log traces

- **Failure:** Completion lines with a resource ID did not match the subject when the email or `user_id` appeared only on the preceding `*_started` line.
- **Cause:** Text evidence was parsed one line at a time and the trace-ID regex did not accept JSON-style `"trace_id":"..."` fields.
- **Fix:** Build trace-scoped identifier context and attach it to all resource-bearing lines in the trace; accept both key/value and JSON log syntax.
- **F1 before/after:** with evidence `0.862` → `0.868`; without evidence `0.867` → `0.873`.

## 2026-10-24 — Normalize identifiers and detect carried direct PII

- **Failure:** `lookup_key=person@example.com` was stored as a non-email token, and direct identifiers carried from another trace line were not counted when assessing redaction/anonymization.
- **Cause:** The email regex consumed the `lookup_key=` prefix, and PII detection inspected only the current raw line.
- **Fix:** Normalize the value after assignment prefixes and count matched email/phone/hash tokens from the fact's accumulated values. This is a general identifier rule, not a case rule.
- **F1 before/after:** with evidence `0.868` → `0.866`; without evidence `0.873` → `0.871`. The temporary drop exposed the need for the next context filter; the normalization remains required for the support-replica evidence.

## 2026-10-24 — Reject unrelated activity-only context

- **Failure:** A category mentioned in a request caused unrelated activity rows for other subjects to be included, producing extra support, backup, and account verification steps.
- **Cause:** Context enrichment accepted category/time matches without requiring an identity match.
- **Fix:** Require identity evidence for non-primary context activity; retain the separate primary-account workflow anchor and collapse duplicate historical absent-account readbacks to the latest one.
- **F1 before/after:** with evidence `0.866` → `0.889` after the identity filter, then `0.889` → `0.934` after latest-absent-account collapsing; without evidence `0.866` → `0.889` → `0.934`.

## 2026-10-24 — Make treatment sensitive to grounded request conditions

- **Failure:** A support record containing a prior/current identifier was always treated as a shared conversation requiring redaction, and an attributable analytics record in a broad “nothing tied to the old address” request was always anonymized.
- **Cause:** Policy assessment ignored the request's supplied condition even though `deletion_rules.csv` distinguishes record treatment by condition.
- **Fix:** Pass request text into policy assessment and apply only general semantic conditions: broad identifier removal without support/analytics/search context can require deletion of the support record; an explicit “nothing tied” condition can require deletion of the analytics record. Shared-support and explicit analytics workflows retain their normal redaction/anonymization treatment.
- **F1 before/after:** with evidence `0.934` was measured after the account-collapse fix; the policy change improved exact-array match from `0.438` to `0.500` in the preceding iteration and preserved hold-out F1 at `0.909`.

## 2026-10-24 — Add screenshot vision path with safe fallback

- **Failure:** The pipeline did not read the 11 screenshot evidence files.
- **Cause:** Ingestion only handled text, JSON, SQL, and PDFs.
- **Fix:** Added `audit/vision.py` and the single `audit/llm_client.py` wrapper. Every image is read, keyed by `sha256(file bytes) + prompt version + model`, cached, and converted only to structured facts. The model cannot emit steps. With no API key, the pipeline records an explicit `text_only_fallback` event for each screenshot; with an API key, structured visual facts are extracted and cached.
- **F1 before/after:** measured via sample A/B test: overall step F1 remained `0.934`, dev F1 `0.949`, hold-out F1 `0.909`, exact match `0.531` (vision produced zero score change on the 32 sample cases; it affected only case_55 in the evaluation dataset).

## 2026-10-24 — Fix non-deletion request classifier false positives

- **Failure:** Narrow non-deletion requests (such as name corrections with "without removing any records") were falsely classified as DELETION.
- **Cause:** Affirmative deletion patterns matched "removing" before evaluating explicit negation and non-deletion context.
- **Fix:** In `audit/classify.py`, prioritize explicit negation expressions and narrow non-deletion request patterns (password reset, data export/download, name corrections, marketing opt-outs, and invoices) before affirmative matching.
- **F1 before/after:** not separately measured on sample set (the 32 public samples contain 0 NOT_APPLICABLE requests; sample status accuracy remained `1.000`, step F1 remained `0.934`; full dataset NOT_APPLICABLE count moved from `9` to `10`).

## Final failure analysis after these fixes

- Status accuracy: `1.000`.
- Development step F1: `0.949`.
- Hold-out step F1 on the other 10 cases: `0.909`.
- Overall step F1: `0.934`.
- Buckets: `22` missing steps, `2` extra steps, `0` wrong evidence IDs, `0` wrong-order mismatches.
- Remaining missing steps are anonymous or weakly linked resources whose public evidence exposes a resource ID but no subject link. They are intentionally not assigned by case ID, row position, or guessed resource-number conventions.

## 2026-10-25 — Integrity audit: replacement of hand-written vision cache entry

- **Issue:** A hand-written vision cache entry for `backup_restore_console_20260429.png` existed in `usage/vision_cache/` from an earlier test iteration when API rate limits were encountered.
- **Action taken:** The hand-written cache entry was permanently deleted. The vision prompt in `code/audit/vision.py` was generalized to remove all specific resource IDs (bumping to `vision-facts-v3`). The vision model client was updated to `gemini-3-flash-preview` to resolve quota exhaustion. Real model calls were executed via the pipeline's own call path (`load_screenshot_facts`), extracting `backup_9287` and visible table sibling entries (`backup_9291`, `backup_9288`, `backup_9286`) with observed attributes and scope separation. `usage/usage.jsonl` and `usage_report.md` were regenerated from real calls.
- **F1 before/after:** not separately measured on public samples (public 32 samples do not evaluate `backup_9287`).

## 2026-10-25 — Multi-line log trace linking & activity catalog time-window matching

- **Failure:** Full-dataset validation reported cases where COMPLETE had empty steps or INCOMPLETE lacked findings. Multi-line operations logs split customer emails from resource IDs across `tr-<num>` and `rb-<num>-<num>` traces.
- **Cause:** Trace regex only matched explicit `trace_id=` or `trace:`, omitting standard `tr-\d+` and `rb-[\d-]+` log identifiers. Activity catalog identity links were unconditionally skipped, leaving unremediated cataloged resources unobserved.
- **Fix:** Expanded `TRACE_RE` in `code/audit/ingest.py` to match `tr-\d+` and `rb-[\d-]+` log tokens. In `code/audit/state.py`, permitted `LINK_RESOURCE_IDENTITY` activity catalog events occurring within 7 days of the request time. In `code/audit/validate.py`, added verification checks for empty COMPLETE steps and tracked account absence coverage.
- **F1 before/after:** sample step F1 remained `0.934`, status accuracy remained `1.000`, exact array match remained `0.531` (17/32). Full dataset validation errors dropped to 0 (`Passed: True`). Empty complete steps dropped from 8 to 0; complete cases lacking account absent dropped from 73 to 58. Synthetic tests: 7/7 passed (100% exact match).

