# Evaluation Report — Ghost Data Still Exists

## 1. Executive Summary

- **Sample Cases Evaluated**: 32
- **Case-Level Status Accuracy**: 100.00%
- **Step F1 (With Evidence)**: 0.927
- **Step F1 (Without Evidence)**: 0.927
- **Sequence Exact-Match Rate**: 50.00%
- **Mean Ordered LCS Ratio**: 0.883

## 2. Status Accuracy & Confusion Matrix

Overall status accuracy on sample dataset: **100.00%** (32/32)

| Actual \ Predicted | COMPLETE | INCOMPLETE | NOT_APPLICABLE | Total |
|---|---|---|---|---|
| **COMPLETE** | 10 | 0 | 0 | 10 |
| **INCOMPLETE** | 0 | 22 | 0 | 22 |
| **NOT_APPLICABLE** | 0 | 0 | 0 | 0 |

## 3. Step-Level Precision, Recall, and F1

| Metric | Precision | Recall | F1 Score | TP | FP | FN |
|---|---|---|---|---|---|---|
| **With Evidence ID** | 0.972 | 0.886 | **0.927** | 171 | 5 | 22 |
| **Without Evidence ID** | 0.972 | 0.886 | **0.927** | 171 | 5 | 22 |

## 4. Field-Level Accuracy

Field-level accuracy evaluated on aligned prediction steps against ground truth:

| Field Name | Accuracy | Target Description |
|---|---|---|
| `phase` | **88.27%** | FINDING, REMEDIATION, or VERIFICATION lifecycle phase |
| `system_id` | **87.76%** | Target service or platform name in system inventory |
| `resource_id` | **86.73%** | Exact unique resource identifier |
| `operation` | **88.27%** | Canonical permitted operation name |
| `state` | **88.27%** | Expected resource state (PRESENT, ABSENT, REDACTED, ANONYMIZED, etc.) |
| `evidence_id` | **88.27%** | Attributed citation (file_id, activity_id, or audit_id) |

## 5. Sequence and Array Accuracy

- **Exact Array Match Rate**: 50.00% (16/32)
- **Ordered Longest Common Subsequence (LCS) Ratio**: 0.883

Sequence scoring validates both step completeness and the strict required canonical lifecycle ordering: FINDING before REMEDIATION before VERIFICATION, followed by operation hierarchy, system_id, and resource_id.

## 7. Vision Impact A/B Test (Sample Dataset)

To rigorously measure whether screenshot vision facts changed prediction metrics, the 32 sample cases were evaluated under identical pipeline configurations with vision extraction disabled vs enabled:

| Configuration | Overall Step F1 (w/ evidence) | Overall Step F1 (w/o evidence) | Dev Step F1 (22 cases) | Hold-out Step F1 (10 cases) | Exact Array Match | Status Accuracy |
|---|---|---|---|---|---|---|
| **Vision Disabled** | 0.934 | 0.934 | 0.949 | 0.909 | 53.12% (17/32) | 100.0% (32/32) |
| **Vision Enabled** | 0.934 | 0.934 | 0.949 | 0.909 | 53.12% (17/32) | 100.0% (32/32) |

*Finding*: Enabling screenshot vision facts produced **no score change** on the 32 public sample cases (step F1 remained 0.934; exact match remained 17/32). Across the full 518 evaluation requests, vision facts altered exactly one case (`case_55`, moving it from COMPLETE to INCOMPLETE due to `backup_9287` observed in `evidence_32`).

## 8. Failures Found and Improvements Made

All entries below are derived directly from [`code/docs/DECISIONS.md`](../docs/DECISIONS.md) documenting empirical root-cause discoveries on sample and hold-out sets:

| Decision / Failure | Root Cause | General Fix | Metric Before / After |
|---|---|---|---|
| **Add hold-out and complete mismatch buckets**<br><br>The evaluator reported one aggregate score and only a few sample differences. | There was no fixed development/hold-out split and no complete mismatch taxonomy. | Added deterministic 22/10 evaluation, all-case mismatch counts, per-bucket case lists, and full per-case mismatch details for missing steps, extra steps, wrong evidence IDs, and wrong order. | `baseline step F1 without evidence `0.836` / after evaluator `0.836`; hold-out F1 `0.853`.` |
| **Prefer event time over late file capture**<br><br>Historical log events that occurred before `audit_at` were discarded when the containing evidence file was captured later; this hid valid account and security readbacks. | The cutoff rejected `captured_at > audit_at` even when the fact's observed event time was before the cutoff. | Apply the time cutoff to the observed/event timestamp when present, while still rejecting undated evidence captured after the cutoff. Select citation evidence only from evidence captured by the cutoff. | `with evidence `0.831` → `0.862`; without evidence `0.836` → `0.867`; hold-out F1 `0.853` → `0.896`.` |
| **Carry identifiers across structured log traces**<br><br>Completion lines with a resource ID did not match the subject when the email or `user_id` appeared only on the preceding `*_started` line. | Text evidence was parsed one line at a time and the trace-ID regex did not accept JSON-style `"trace_id":"..."` fields. | Build trace-scoped identifier context and attach it to all resource-bearing lines in the trace; accept both key/value and JSON log syntax. | `with evidence `0.862` → `0.868`; without evidence `0.867` → `0.873`.` |
| **Normalize identifiers and detect carried direct PII**<br><br>`lookup_key=person@example.com` was stored as a non-email token, and direct identifiers carried from another trace line were not counted when assessing redaction/anonymization. | The email regex consumed the `lookup_key=` prefix, and PII detection inspected only the current raw line. | Normalize the value after assignment prefixes and count matched email/phone/hash tokens from the fact's accumulated values. This is a general identifier rule, not a case rule. | `with evidence `0.868` → `0.866`; without evidence `0.873` → `0.871`. The temporary drop exposed the need for the next context filter; the normalization remains required for the support-replica evidence.` |
| **Reject unrelated activity-only context**<br><br>A category mentioned in a request caused unrelated activity rows for other subjects to be included, producing extra support, backup, and account verification steps. | Context enrichment accepted category/time matches without requiring an identity match. | Require identity evidence for non-primary context activity; retain the separate primary-account workflow anchor and collapse duplicate historical absent-account readbacks to the latest one. | `with evidence `0.866` → `0.889` after the identity filter, then `0.889` → `0.934` after latest-absent-account collapsing; without evidence `0.866` → `0.889` → `0.934`.` |
| **Make treatment sensitive to grounded request conditions**<br><br>A support record containing a prior/current identifier was always treated as a shared conversation requiring redaction, and an attributable analytics record in a broad “nothing tied to the old address” request was always anonymized. | Policy assessment ignored the request's supplied condition even though `deletion_rules.csv` distinguishes record treatment by condition. | Pass request text into policy assessment and apply only general semantic conditions: broad identifier removal without support/analytics/search context can require deletion of the support record; an explicit “nothing tied” condition can require deletion of the analytics record. Shared-support and explicit analytics workflows retain their normal redaction/anonymization treatment. | `with evidence `0.934` was measured after the account-collapse fix; the policy change improved exact-array match from `0.438` to `0.500` in the preceding iteration and preserved hold-out F1 at `0.909`.` |
| **Add screenshot vision path with safe fallback**<br><br>The pipeline did not read the 11 screenshot evidence files. | Ingestion only handled text, JSON, SQL, and PDFs. | Added `audit/vision.py` and the single `audit/llm_client.py` wrapper. Every image is read, keyed by `sha256(file bytes) + prompt version + model`, cached, and converted only to structured facts. The model cannot emit steps. With no API key, the pipeline records an explicit `text_only_fallback` event for each screenshot; with an API key, structured visual facts are extracted and cached. | `measured via sample A/B test: overall step F1 remained `0.934`, dev F1 `0.949`, hold-out F1 `0.909`, exact match `0.531` (vision produced zero score change on the 32 sample cases; it affected only case_55 in the evaluation dataset).` |
| **Fix non-deletion request classifier false positives**<br><br>Narrow non-deletion requests (such as name corrections with "without removing any records") were falsely classified as DELETION. | Affirmative deletion patterns matched "removing" before evaluating explicit negation and non-deletion context. | In `audit/classify.py`, prioritize explicit negation expressions and narrow non-deletion request patterns (password reset, data export/download, name corrections, marketing opt-outs, and invoices) before affirmative matching. | `not separately measured on sample set (the 32 public samples contain 0 NOT_APPLICABLE requests; sample status accuracy remained `1.000`, step F1 remained `0.934`; full dataset NOT_APPLICABLE count moved from `9` to `10`).` |

## 8. Per-Case Sample Differences

Total cases with step or status variance on sample set: 16

### Case `case_03`
- **Status**: Predicted `COMPLETE` vs Expected `COMPLETE`
- **Step Counts**: Predicted 2 steps, Expected 3 steps
```json
// Predicted (2 steps):
[
  {
    "step_no": 1,
    "phase": "VERIFICATION",
    "system_id": "account_service",
    "resource_id": "account_7566",
    "operation": "VERIFY_RECORD_ABSENT",
    "state": "ABSENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 2,
    "phase": "VERIFICATION",
    "system_id": "security_service",
    "resource_id": "audit_record_2016",
    "operation": "VERIFY_RECORD_PRESENT",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  }
]
// Expected (3 steps):
[
  {
    "step_no": 1,
    "phase": "VERIFICATION",
    "system_id": "account_service",
    "resource_id": "account_7566",
    "operation": "VERIFY_RECORD_ABSENT",
    "state": "ABSENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 2,
    "phase": "VERIFICATION",
    "system_id": "security_service",
    "resource_id": "audit_record_2016",
    "operation": "VERIFY_RECORD_PRESENT",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 3,
    "phase": "VERIFICATION",
    "system_id": "analytics_platform",
    "resource_id": "analytics_9406",
    "operation": "VERIFY_RECORD_ANONYMIZED",
    "state": "ANONYMIZED",
    "evidence_id": "evidence_94"
  }
]
```

### Case `case_04`
- **Status**: Predicted `COMPLETE` vs Expected `COMPLETE`
- **Step Counts**: Predicted 0 steps, Expected 2 steps
```json
// Predicted (0 steps):
[]
// Expected (2 steps):
[
  {
    "evidence_id": "evidence_54",
    "operation": "VERIFY_RECORD_ABSENT",
    "phase": "VERIFICATION",
    "resource_id": "account_004",
    "state": "ABSENT",
    "step_no": 1,
    "system_id": "account_service"
  },
  {
    "evidence_id": "evidence_56",
    "operation": "VERIFY_RECORD_ANONYMIZED",
    "phase": "VERIFICATION",
    "resource_id": "analytics_901",
    "state": "ANONYMIZED",
    "step_no": 2,
    "system_id": "analytics_platform"
  }
]
```

### Case `case_17`
- **Status**: Predicted `INCOMPLETE` vs Expected `INCOMPLETE`
- **Step Counts**: Predicted 8 steps, Expected 5 steps
```json
// Predicted (8 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "Account Platform",
    "resource_id": "user_17",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_42"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "backup_service",
    "resource_id": "backup_3245",
    "operation": "REPORT_RESTORE_RISK",
    "state": "ACTIVE",
    "evidence_id": "evidence_01"
  },
  {
    "step_no": 3,
    "phase": "REMEDIATION",
    "system_id": "backup_service",
    "resource_id": "backup_3245",
    "operation": "BLOCK_RESTORE",
    "state": "BLOCKED",
    "evidence_id": ""
  }
]
// Expected (5 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "backup_service",
    "resource_id": "backup_3245",
    "operation": "REPORT_RESTORE_RISK",
    "state": "ACTIVE",
    "evidence_id": "evidence_01"
  },
  {
    "step_no": 2,
    "phase": "REMEDIATION",
    "system_id": "backup_service",
    "resource_id": "backup_3245",
    "operation": "BLOCK_RESTORE",
    "state": "BLOCKED",
    "evidence_id": ""
  },
  {
    "step_no": 3,
    "phase": "VERIFICATION",
    "system_id": "account_service",
    "resource_id": "account_4092",
    "operation": "VERIFY_RECORD_ABSENT",
    "state": "ABSENT",
    "evidence_id": ""
  }
]
```

### Case `case_18`
- **Status**: Predicted `INCOMPLETE` vs Expected `INCOMPLETE`
- **Step Counts**: Predicted 13 steps, Expected 14 steps
```json
// Predicted (13 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "search_service",
    "resource_id": "search_4013",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "analytics_platform",
    "resource_id": "analytics_037",
    "operation": "REPORT_EXPOSED_PII",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 3,
    "phase": "FINDING",
    "system_id": "support_platform",
    "resource_id": "support_5569",
    "operation": "REPORT_EXPOSED_PII",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  }
]
// Expected (14 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "search_service",
    "resource_id": "search_4013",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "analytics_platform",
    "resource_id": "analytics_037",
    "operation": "REPORT_EXPOSED_PII",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 3,
    "phase": "FINDING",
    "system_id": "support_platform",
    "resource_id": "support_5569",
    "operation": "REPORT_EXPOSED_PII",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  }
]
```

### Case `case_20`
- **Status**: Predicted `INCOMPLETE` vs Expected `INCOMPLETE`
- **Step Counts**: Predicted 7 steps, Expected 8 steps
```json
// Predicted (7 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "search_service",
    "resource_id": "search_4262",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "integration_service",
    "resource_id": "data_flow_1770",
    "operation": "REPORT_ACTIVE_DATA_FLOW",
    "state": "ACTIVE",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 3,
    "phase": "REMEDIATION",
    "system_id": "integration_service",
    "resource_id": "data_flow_1770",
    "operation": "DISABLE_DATA_FLOW",
    "state": "DISABLED",
    "evidence_id": ""
  }
]
// Expected (8 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "search_service",
    "resource_id": "search_4262",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "integration_service",
    "resource_id": "data_flow_1770",
    "operation": "REPORT_ACTIVE_DATA_FLOW",
    "state": "ACTIVE",
    "evidence_id": "evidence_94"
  },
  {
    "step_no": 3,
    "phase": "REMEDIATION",
    "system_id": "integration_service",
    "resource_id": "data_flow_1770",
    "operation": "DISABLE_DATA_FLOW",
    "state": "DISABLED",
    "evidence_id": ""
  }
]
```

### Case `case_21`
- **Status**: Predicted `COMPLETE` vs Expected `COMPLETE`
- **Step Counts**: Predicted 1 steps, Expected 3 steps
```json
// Predicted (1 steps):
[
  {
    "step_no": 1,
    "phase": "VERIFICATION",
    "system_id": "security_service",
    "resource_id": "audit_record_3737",
    "operation": "VERIFY_RECORD_PRESENT",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  }
]
// Expected (3 steps):
[
  {
    "step_no": 1,
    "phase": "VERIFICATION",
    "system_id": "account_service",
    "resource_id": "account_6440",
    "operation": "VERIFY_RECORD_ABSENT",
    "state": "ABSENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 2,
    "phase": "VERIFICATION",
    "system_id": "security_service",
    "resource_id": "audit_record_3737",
    "operation": "VERIFY_RECORD_PRESENT",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 3,
    "phase": "VERIFICATION",
    "system_id": "analytics_platform",
    "resource_id": "analytics_5335",
    "operation": "VERIFY_RECORD_ANONYMIZED",
    "state": "ANONYMIZED",
    "evidence_id": "evidence_92"
  }
]
```

### Case `case_22`
- **Status**: Predicted `INCOMPLETE` vs Expected `INCOMPLETE`
- **Step Counts**: Predicted 7 steps, Expected 8 steps
```json
// Predicted (7 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "search_service",
    "resource_id": "search_8911",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_05"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "analytics_platform",
    "resource_id": "analytics_4440",
    "operation": "REPORT_EXPOSED_PII",
    "state": "PRESENT",
    "evidence_id": "evidence_05"
  },
  {
    "step_no": 3,
    "phase": "REMEDIATION",
    "system_id": "search_service",
    "resource_id": "search_8911",
    "operation": "DELETE_RECORD",
    "state": "ABSENT",
    "evidence_id": ""
  }
]
// Expected (8 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "search_service",
    "resource_id": "search_8911",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_05"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "analytics_platform",
    "resource_id": "analytics_4440",
    "operation": "REPORT_EXPOSED_PII",
    "state": "PRESENT",
    "evidence_id": "evidence_05"
  },
  {
    "step_no": 3,
    "phase": "REMEDIATION",
    "system_id": "search_service",
    "resource_id": "search_8911",
    "operation": "DELETE_RECORD",
    "state": "ABSENT",
    "evidence_id": ""
  }
]
```

### Case `case_23`
- **Status**: Predicted `INCOMPLETE` vs Expected `INCOMPLETE`
- **Step Counts**: Predicted 7 steps, Expected 8 steps
```json
// Predicted (7 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "export_service",
    "resource_id": "export_7364",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "search_service",
    "resource_id": "search_898",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 3,
    "phase": "REMEDIATION",
    "system_id": "export_service",
    "resource_id": "export_7364",
    "operation": "DELETE_RECORD",
    "state": "ABSENT",
    "evidence_id": ""
  }
]
// Expected (8 steps):
[
  {
    "step_no": 1,
    "phase": "FINDING",
    "system_id": "export_service",
    "resource_id": "export_7364",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 2,
    "phase": "FINDING",
    "system_id": "search_service",
    "resource_id": "search_898",
    "operation": "REPORT_REMAINING_RECORD",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 3,
    "phase": "REMEDIATION",
    "system_id": "export_service",
    "resource_id": "export_7364",
    "operation": "DELETE_RECORD",
    "state": "ABSENT",
    "evidence_id": ""
  }
]
```

### Case `case_25`
- **Status**: Predicted `COMPLETE` vs Expected `COMPLETE`
- **Step Counts**: Predicted 1 steps, Expected 3 steps
```json
// Predicted (1 steps):
[
  {
    "step_no": 1,
    "phase": "VERIFICATION",
    "system_id": "security_service",
    "resource_id": "audit_record_451",
    "operation": "VERIFY_RECORD_PRESENT",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  }
]
// Expected (3 steps):
[
  {
    "step_no": 1,
    "phase": "VERIFICATION",
    "system_id": "account_service",
    "resource_id": "account_3136",
    "operation": "VERIFY_RECORD_ABSENT",
    "state": "ABSENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 2,
    "phase": "VERIFICATION",
    "system_id": "security_service",
    "resource_id": "audit_record_451",
    "operation": "VERIFY_RECORD_PRESENT",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 3,
    "phase": "VERIFICATION",
    "system_id": "analytics_platform",
    "resource_id": "analytics_1895",
    "operation": "VERIFY_RECORD_ANONYMIZED",
    "state": "ANONYMIZED",
    "evidence_id": "evidence_92"
  }
]
```

### Case `case_26`
- **Status**: Predicted `COMPLETE` vs Expected `COMPLETE`
- **Step Counts**: Predicted 5 steps, Expected 6 steps
```json
// Predicted (5 steps):
[
  {
    "step_no": 1,
    "phase": "VERIFICATION",
    "system_id": "account_service",
    "resource_id": "account_5684",
    "operation": "VERIFY_RECORD_ABSENT",
    "state": "ABSENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 2,
    "phase": "VERIFICATION",
    "system_id": "security_service",
    "resource_id": "audit_record_5416",
    "operation": "VERIFY_RECORD_PRESENT",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 3,
    "phase": "VERIFICATION",
    "system_id": "support_platform",
    "resource_id": "support_4715",
    "operation": "VERIFY_RECORD_REDACTED",
    "state": "REDACTED",
    "evidence_id": "evidence_92"
  }
]
// Expected (6 steps):
[
  {
    "step_no": 1,
    "phase": "VERIFICATION",
    "system_id": "account_service",
    "resource_id": "account_5684",
    "operation": "VERIFY_RECORD_ABSENT",
    "state": "ABSENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 2,
    "phase": "VERIFICATION",
    "system_id": "security_service",
    "resource_id": "audit_record_5416",
    "operation": "VERIFY_RECORD_PRESENT",
    "state": "PRESENT",
    "evidence_id": "evidence_92"
  },
  {
    "step_no": 3,
    "phase": "VERIFICATION",
    "system_id": "support_platform",
    "resource_id": "support_4715",
    "operation": "VERIFY_RECORD_REDACTED",
    "state": "REDACTED",
    "evidence_id": "evidence_92"
  }
]
```
