# Ghost Data Still Exists — Deletion Audit Agent

An enterprise-grade, deterministic deletion audit agent built for the **HackerRank Orchestrate (October 2026)** challenge: *Ghost Data Still Exists*.

The system audits customer deletion requests across secondary databases, replicas, support platforms, search indexes, analytics records, backups, and background sync pipelines to determine whether personal data was truly deleted, whether active processes can recreate data, and what ordered remediation plan is required.

---

## 1. Quick Start & Execution

### 1.1 Prerequisites
- Python 3.10+ (Standard library only; zero mandatory third-party dependencies for core execution).
- SQLite3 (included with standard Python).

### 1.2 One-Command Run (Full Dataset)
From the repository root:

```bash
python code/main.py --dataset-dir dataset --out output.csv
```

This reads `dataset/deletion_requests.csv` (518 cases), executes the audit pipeline across all evidence manifests, and generates the submission-ready `output.csv` in the root directory.

### 1.3 Label-Free Output Validation
Run the validator to verify that `output.csv` satisfies all structural, policy, sequence, and manifest rules:

```bash
python code/audit/validate.py --output output.csv --dataset-dir dataset
```

### 1.4 Generating Evaluation & Usage Reports
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

### Key Modules:
1. **Multilingual Classifier (`audit/classify.py`)**:
   Deterministically identifies whether the text actually requests account/data deletion, filtering out address updates, inquiries, or explicit non-deletion instructions (`NOT_APPLICABLE`).
2. **Identity Resolution (`audit/identity.py`)**:
   Reconstructs the full identity timeline for each customer as-of the request timestamp (`requested_at`), tracking identity mutations (renames, phone updates, email updates, and SHA-256 email hashes).
3. **Ingestion & Evidence Harvesting (`audit/ingest.py`)**:
   Parses structured SQLite snapshots, JSON exports, service logs, and system activity logs into a unified fact graph, linking citations (`file_id`, `activity_id`, `audit_id`).
4. **State Reconstruction (`audit/state.py`)**:
   Reconstructs the true state of every resource as-of `audit_at`, treating workflow claims as unverified assertions until substantiated by evidence. Detects post-deletion data recreation by sync jobs.
5. **Policy Assessment (`audit/policy.py`)**:
   Applies `deletion_rules.csv` (15 categories). Protects mandatory retention records (e.g. `SECURITY_AUDIT_LOG`, `LEGAL_HOLD_RECORD`) from deletion.
6. **Topological Planner (`audit/planner.py`)**:
   Emits canonical lifecycle steps sorted strictly by phase (`FINDING` $\to$ `REMEDIATION` $\to$ `VERIFICATION`), operation hierarchy, `system_id`, and `resource_id`.

---

## 3. Security & Privacy

- **No Secrets or API Keys**: The codebase contains no hardcoded credentials, API keys, tokens, or environment secrets.
- **Zero Data Egress**: Customer PII, email addresses, and database captures never leave the local environment.

---

## 4. Limitations & Future Work

1. **Unstructured Scans & Screenshots**: Currently, text and relational evidence formats are parsed deterministically. In environments with scanned PDF forms or non-OCR console screenshots, an optional multimodal VLM (e.g., Gemini 1.5 Flash) with content-hash caching can be attached for visual fact extraction.
2. **Dynamic Schema Evolution**: The policy engine currently models Northstar Shop's 15 categorical rules. Future extensions can ingest dynamic policy manifests at runtime.
