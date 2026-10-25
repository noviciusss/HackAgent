# Ghost Data Still Exists — Deletion Audit Agent

An enterprise-grade, deterministic deletion audit agent built for the **HackerRank Orchestrate (October 2026)** challenge: *Ghost Data Still Exists*.

The system audits customer deletion requests across secondary databases, replicas, support platforms, search indexes, analytics records, backups, and background sync pipelines to determine whether personal data was truly deleted, whether active processes can recreate data, and what ordered remediation plan is required.

---

## 1. Quick Start & Execution

### 1.1 Prerequisites & Setup
- Python 3.10+ (Standard library only; zero mandatory third-party dependencies for core execution).
- SQLite3 (included with standard Python).

### 1.2 The Single Run Command (Full Dataset)
From the repository root:

```bash
python code/main.py
```
*(Optionally specify explicit paths: `python code/main.py --dataset-dir dataset --out output.csv`)*

This reads `dataset/deletion_requests.csv` (518 cases), executes the audit pipeline across all evidence manifests, and generates the submission-ready `output.csv` in the root directory.

### 1.3 Vision Mode and `--no-vision` Flag
By default, the pipeline utilizes visual evidence extracted from console screenshots via the local cache in `code/vision_cache/`:
- **Default Vision Model**: `gemini-3-flash-preview` (a preview multimodal foundation model).
- **Cache Behavior**: All 11 screenshots in `dataset/evidence/images/` were processed through the pipeline's genuine `load_screenshot_facts()` call path with generic prompt version `vision-facts-v3` and cached as deterministic fact payloads in `code/vision_cache/`. Because `gemini-3-flash-preview` is a preview model, the local cache is what ensures 100% reproducible execution and allows the entire audit run to complete with `cache hits: 11, api calls: 0` without requiring an active `GEMINI_API_KEY`.
- **Disabling Vision**: To run the pipeline purely on text, relational, JSON, and log evidence without visual evidence, pass `--no-vision`:
  ```bash
  python code/main.py --no-vision --out output.csv
  ```
- **Vision Impact (Measured on 518 cases)**: Exactly **9 cases** differ with vision enabled vs without vision (`--no-vision`): `case_33`, `case_34`, `case_35`, `case_39`, `case_45`, `case_50`, `case_52`, `case_53`, and `case_55`. Vision uncovers unblocked backup archives (`backup_9287`), customer export bundles, and console attachments that only appear in console screenshots.

### 1.4 Label-Free Output Validation
Run the validator to verify that `output.csv` satisfies all structural, policy, sequence, and manifest rules:

```bash
python code/audit/validate.py --output output.csv --dataset-dir dataset
```

### 1.5 Generating Evaluation & Usage Reports
To reproduce both required evaluation deliverables:

```bash
# 1. Evaluate sample predictions and synthetic fixtures
python code/main.py --dataset-dir dataset --requests-file dataset/sample_deletion_requests.csv --out sample_pred.csv
python code/evaluation/make_eval_report.py --pred sample_pred.csv --labels dataset/sample_output.csv --synthetic-pred code/evaluation/synthetic/pred_output.csv --synthetic-labels code/evaluation/synthetic/expected_output.csv

# 2. Generate token usage report
python code/evaluation/make_usage_report.py
```

---

## 2. Architecture & Design Summary

The architecture follows a **deterministic-core first** philosophy. In regulatory compliance, data retention, and privacy auditing, non-deterministic reasoning can introduce hallucinations, omitted evidence citations, or inconsistent remediation ordering.

```
                               ┌────────────────────────┐
                               │ Deletion Request (CSV) │
                               └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │ Multilingual Classifier│ (classify.py)
                               │ (DELETION vs NOT_APPL) │
                               └───────────┬────────────┘
                                           │ (DELETION)
                                           ▼
                               ┌────────────────────────┐
                               │  Identity As-Of Engine │ (identity.py)
                               │ (Current + Historical) │
                               └───────────┬────────────┘
                                           │
                                           ▼
┌────────────────────────┐     ┌────────────────────────┐
│ Multi-Source Ingestion │ ──▶ │ State Reconstruction   │ (state.py)
│ (JSON, SQL, Logs, Act) │     │ (Evidence at audit_at) │
└────────────────────────┘     └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │  Policy Engine (15 R)  │ (policy.py)
                               │  (Assess Compliance)   │
                               └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │  Topological Planner   │ (planner.py)
                               │ (Phase/Op Canonical)   │
                               └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │      output.csv        │ (serialize.py)
                               └────────────────────────┘
```

### Key Modules & Grounded Heuristics:
1. **Multilingual Classifier (`audit/classify.py`)**:
   Deterministically identifies whether the text actually requests account/data deletion, filtering out address updates, inquiries, or explicit non-deletion instructions (`NOT_APPLICABLE`).
2. **Identity Resolution (`audit/identity.py`)**:
   Reconstructs the full identity timeline for each customer as-of the request timestamp (`requested_at`), tracking identity mutations (renames, phone updates, email updates, and SHA-256 email hashes).
3. **Trace-ID Log Correlation (`audit/ingest.py`)**:
   Operations logs frequently split single requests across lines (e.g. line 1 logging the user email on a lookup event, while subsequent lines log the resource ID). The parser handles:
   - Key-value trace identifiers: `trace_id="<id>"` and `trace:<id>`.
   - Microservice correlation tokens: `\b(tr-\d+)\b`.
   - Replication bridge tokens: `\b(rb-[\d-]+)\b`.
   Lines sharing the same trace token automatically inherit resolved subject identifiers.
4. **State Reconstruction & 7-Day Window Heuristic (`audit/state.py`)**:
   Reconstructs the true state of every resource as-of `audit_at`. Activity catalog identity links (`LINK_RESOURCE_IDENTITY`) are bounded to a **7-day window** relative to `requested_at` (`|event_time - requested_at| <= 7 days`). This binds cataloged resources to the specific deletion request life-cycle without leaking historical resources from prior requests across months.
   - **Sensitivity Analysis**: Running the full 518 dataset across **3 days**, **7 days**, and **14 days** yielded exactly **0 cases changed (0.0%)**, demonstrating extreme robustness to window length because all true workflow catalog events occur within ~2.13 days of request initiation.
5. **Policy Assessment (`audit/policy.py`)**:
   Applies `deletion_rules.csv` (15 categories). Protects mandatory retention records (e.g. `SECURITY_AUDIT_LOG`, `LEGAL_HOLD_RECORD`) from deletion.
6. **Topological Planner (`audit/planner.py`)**:
   Emits canonical lifecycle steps sorted strictly by phase (`FINDING` $\to$ `REMEDIATION` $\to$ `VERIFICATION`), operation hierarchy, `system_id`, and `resource_id`.

---

## 3. Security & Privacy

- **Zero API Keys in Codebase**: Verified via `git grep -i "AIza"` that zero credentials or API keys exist in code, configuration, or transcripts.
- **Offline Reproducibility**: The pipeline executes fully offline without internet connectivity via cached visual extractions in `code/vision_cache/`.

---

## 4. Benchmark & Validation Results

### 4.1 Full Dataset (518 Cases)
- **Label-Free Validation**: Passed 100% (`Passed: True`, 0 errors).
- **Status Distribution**: `COMPLETE: 112`, `INCOMPLETE: 396`, `NOT_APPLICABLE: 10`.
- **Empty Complete Steps**: **0 cases** (initial 8 empty cases eliminated by requiring verified assessments).
- **COMPLETE Cases without Account Absence**: **58 cases** (measured final count, reduced from 73 after multi-line trace linking). These 58 cases correspond to requests where primary profiles were pruned on replica snapshots without explicit primary service event readbacks before cutoff.

### 4.2 Public Sample Benchmark (32 Cases) & Split Analysis
- **Status Accuracy**: **1.000** (32 / 32 cases).
- **Step F1 (with & without evidence)**: **0.9344** (171 TP, 2 FP, 22 FN).
- **Exact-Match Rate**: **17 / 32 cases (53.1%)**.
- **Dev Split (First 22 Cases)**: Step F1 = **0.9487** (111 TP, 2 FP, 10 FN), exact match = 16/22 (72.7%).
- **Hold-Out Split (Last 10 Cases)**: Step F1 = **0.9091** (60 TP, 0 FP, 12 FN), exact match = 1/10 (10.0%).
- **Mismatches**: 22 false negatives across 15 cases (primarily unlinked secondary analytics records or replica account snapshots where log evidence captures occurred after the respective `audit_at` cutoffs); and 2 false positives.

### 4.3 Synthetic Evaluation Fixtures (EXTRAS.md §3)
- **Authorship**: 7 AI-authored, human-verified edge-case fixtures created strictly from `problem_statement.md` and `deletion_rules.csv` without reading code (`case_syn_01..07`).
- **Fixture Results**:
  - `case_syn_01` (Email Reused After Deletion): PASS (4 steps)
  - `case_syn_02` (Historical Email in Secondary System): PASS (4 steps)
  - `case_syn_03` (Sync Job Recreates Record Post-Delete): PASS (7 steps)
  - `case_syn_04` (Tombstone Holding Email Hash): PASS (3 steps)
  - `case_syn_05` (Fully Compliant COMPLETE Case): PASS (3 steps)
  - `case_syn_06` (Restorable Backup Risk): PASS (4 steps)
  - `case_syn_07` (Explicit Multilingual Non-Deletion): PASS (0 steps)
  - **Overall Synthetic Score**: **100% exact match** (7 / 7 cases, status accuracy = 1.000, step F1 = 1.000).


