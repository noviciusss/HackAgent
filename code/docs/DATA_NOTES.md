# DATA_NOTES.md — Dataset Analysis and Specification

*All figures, schemas, value sets, and hash algorithms documented herein are directly mined and verified from the official `dataset/` files.*

---

## 1. Dataset Inventory & Schema Definitions

The dataset consists of 6 primary structured relational files in `dataset/` and an evidence repository in `dataset/evidence/`.

| File | Rows | Schema (Ordered Columns) | Description |
|---|---|---|---|
| `deletion_requests.csv` | 518 | `case_id`, `email`, `requested_at`, `reported_status`, `reported_at`, `audit_at`, `request_text` | All 518 deletion cases requiring audit. |
| `sample_deletion_requests.csv` | 32 | `case_id`, `email`, `requested_at`, `reported_status`, `reported_at`, `audit_at`, `request_text` | Sample subset (`case_01` to `case_32`) for baseline evaluation. |
| `sample_output.csv` | 32 | `case_id`, `deletion_status`, `steps_json` | Canonical ground-truth answers for the 32 sample cases. |
| `user_identities.csv` | 850 | `user_id`, `name`, `email`, `phone`, `email_hash`, `updated_at` | Primary user identity registry with direct identifiers and hashes. |
| `user_audit_log.csv` | 306 | `audit_id`, `user_id`, `event_time`, `field_name`, `old_value`, `new_value` | Historical identity change log tracking renames, phone updates, and email changes. |
| `system_activity.csv` | 4,011 | `activity_id`, `event_time`, `event_type`, `source_system`, `target_system`, `resource_id`, `reported_result`, `details` | System-wide operational events across services and batch workflows. |
| `deletion_rules.csv` | 15 | `rule_id`, `data_category`, `condition`, `required_action` | Canonical 15-rule policy table governing data categories and required actions. |
| `evidence_files.csv` | 94 | `file_id`, `file_path`, `origin`, `captured_at` | Manifest of 94 multimodal evidence artifacts in `dataset/evidence/`. |

---

## 2. Value Sets & System Inventory

### 2.1 Systems & Services (11 Active Services)
Directly extracted from `system_activity.csv` (`source_system` and `target_system`):
- `account_service`: Primary authentication and account management database.
- `profile_service`: User profile attributes, preferences, and secondary metadata.
- `security_service`: Security audit log retention and access controls.
- `search_service`: Full-text customer and support ticket index.
- `support_platform`: Customer support tickets, message threads, and attachments.
- `export_service`: User data exports and compliance archives.
- `integration_service`: Background synchronization pipelines, ETL, and webhooks.
- `backup_service`: Database snapshots, cold storage archives, and restore handlers.
- `analytics_platform`: Behavioral events, user telemetry, and telemetry aggregation.
- `notification_service`: Transactional email delivery and SMS notifications.
- `archive_service`: Long-term legal holds and compliance storage.

### 2.2 Event Types & Distribution (4,011 Total Events)
Mined from `system_activity.csv`:
| Event Type | Count | Lifecycle Meaning in Deletion Audit |
|---|---|---|
| `DELETE_RECORD` | 890 | Workflow claim indicating a record deletion was attempted. |
| `UPDATE_RECORD` | 672 | Record modification in primary or secondary datastores. |
| `SYNC_RECORD` | 447 | Background replication/synchronization between services. |
| `INDEX_RECORD` | 400 | Ingestion of customer data into search indexes. |
| `SEND_EMAIL` | 368 | Notification sent to user containing email address. |
| `REFRESH_CACHE` | 284 | Cache repopulation or invalidation event. |
| `RETAIN_RECORD` | 206 | Policy-mandated preservation of audit or compliance records. |
| `ANONYMIZE_RECORD` | 204 | Pseudonymization or de-identification of analytics profiles. |
| `REDACT_RECORD` | 173 | Redaction of direct identifiers in shared contexts. |
| `CREATE_EXPORT` | 155 | Generation of compliance data export bundle. |
| `CHECK_DATA_FLOW` | 89 | Verification check for active integration pipelines. |
| `DISABLE_DATA_FLOW` | 36 | Deactivation of background synchronization jobs. |
| `BLOCK_RESTORE` | 36 | Revocation or blocking of backup restore capabilities. |
| `CHECK_RESTORE_ACCESS`| 28 | Audit query on whether a backup snapshot is restorable. |
| `LINK_RESOURCE_IDENTITY` | 12 | Identity linkage event associating identifiers with user IDs. |
| `CLASSIFY_REQUEST` | 10 | Intake classification of user request intent. |
| `RESTORE_BACKUP` | 1 | Restoration of database from backup snapshot. |

### 2.3 Reported Results in Activity Log
- `SUCCESS`: 2,914 events (72.65%)
- `FAILED`: 721 events (17.98%) — e.g. sync failures, index drop failures
- `PARTIAL`: 376 events (9.37%) — e.g. partial redactions or timeouts

*Crucial rule*: Reported results and workflow claims are **claims**, not ground truth. State must be determined by inspecting evidence at `audit_at`.

---

## 3. Identity Resolution & Hash Computation

### 3.1 Hash Algorithm Verification
Empirical verification on `dataset/user_identities.csv`:
- `email_hash` is computed as the lowercase, stripped UTF-8 string passed to standard **SHA-256**:
  $$\text{email\_hash} = \text{SHA256}(\text{strip}(\text{lower}(\text{email})))$$
- Example:
  - Email: `amina.elmasri@gmail.com`
  - Computed SHA-256: `d4e1f59abcf9a1e0cfdc7c27ad6c07ed4ff88b326a16ed5eed5ec6bc31618c93`
  - Stored Hash: `d4e1f59abcf9a1e0cfdc7c27ad6c07ed4ff88b326a16ed5eed5ec6bc31618c93` (Match: 100%)

### 3.2 Historical Identity Tracking (`user_audit_log.csv`)
306 historical mutation records distributed across 3 field types:
- `email`: 107 change events
- `email_hash`: 107 change events (synchronized with email updates)
- `phone`: 92 change events

Identity resolution must resolve the target `user_id` as-of the request timestamp `requested_at`, and assemble the **full set of current and historical identifiers** (all names, prior emails, prior phone numbers, and hashes) up to `audit_at`.

---

## 4. Evidence Formats & Origins

The 94 files in `dataset/evidence_files.csv` span 6 file types:
- `.json` (28 files): Structured database dumps, customer snapshot bundles, and API responses.
- `.log` (26 files): Observability exports, service events, and search index diagnostic traces.
- `.sql` (24 files): SQLite-executable relational exports of primary and replica databases.
- `.png` (11 files): Admin portal screenshots, search index inspectors, and console views.
- `.pdf` (4 files): Scanned customer agreements, handover forms, and export summaries.
- `.txt` (1 file): Customer account handover exports.

Evidence manifests provide the required citations for `steps_json`:
- `evidence_id` in output must resolve to a valid `file_id` (from `evidence_files.csv`), `activity_id` (from `system_activity.csv`), or `audit_id` (from `user_audit_log.csv`).

---

## 5. Deletion Policy Rules (`deletion_rules.csv`)

| Rule ID | Category | Condition | Action | Canonical Step Operation |
|---|---|---|---|---|
| `rule_01` | `USER_PROFILE` | Always | `DELETE` | `DELETE_RECORD` / `VERIFY_RECORD_ABSENT` |
| `rule_02` | `SECONDARY_IDENTIFIER` | Always | `DELETE` | `DELETE_RECORD` / `VERIFY_RECORD_ABSENT` |
| `rule_03` | `SEARCH_INDEX_ENTRY` | Always | `DELETE` | `DELETE_RECORD` / `VERIFY_RECORD_ABSENT` |
| `rule_04` | `CACHE_ENTRY` | Always | `DELETE` | `DELETE_RECORD` / `VERIFY_RECORD_ABSENT` |
| `rule_05` | `SUPPORT_MESSAGE` | Shared context | `REDACT` | `REDACT_RECORD` / `VERIFY_RECORD_REDACTED` |
| `rule_06` | `SUPPORT_ATTACHMENT` | Subject-only | `DELETE` | `DELETE_RECORD` / `VERIFY_RECORD_ABSENT` |
| `rule_07` | `ANALYTICS_PROFILE` | Attributable | `ANONYMIZE` | `ANONYMIZE_RECORD` / `VERIFY_RECORD_ANONYMIZED` |
| `rule_08` | `PRODUCT_TELEMETRY` | Attributable | `ANONYMIZE` | `ANONYMIZE_RECORD` / `VERIFY_RECORD_ANONYMIZED` |
| `rule_09` | `USER_EXPORT` | Always | `DELETE` | `DELETE_RECORD` / `VERIFY_RECORD_ABSENT` |
| `rule_10` | `MARKETING_PROFILE` | Always | `DELETE` | `DELETE_RECORD` / `VERIFY_RECORD_ABSENT` |
| `rule_11` | `EMAIL_DELIVERY_LOG` | Contains email | `REDACT` | `REDACT_RECORD` / `VERIFY_RECORD_REDACTED` |
| `rule_12` | `SECURITY_AUDIT_LOG` | Within retention period | `RETAIN` | `VERIFY_RECORD_PRESENT` (*must NOT delete*) |
| `rule_13` | `LEGAL_HOLD_RECORD` | Active legal hold | `RETAIN` | `VERIFY_RECORD_PRESENT` (*must NOT delete*) |
| `rule_14` | `BACKUP_ARCHIVE` | Restore blockable | `RETAIN` | `BLOCK_RESTORE` / `VERIFY_RESTORE_BLOCKED` |
| `rule_15` | `ACCOUNT_TOMBSTONE` | Tombstone reference | `REDACT` | `REDACT_RECORD` / `VERIFY_RECORD_REDACTED` |

---

## 6. Sample Ground-Truth Conventions (`sample_output.csv`)

Analysis of `dataset/sample_output.csv` (32 cases) reveals key structural conventions:
1. **Status Breakdown**:
   - `COMPLETE`: 10 cases (31.25%)
   - `INCOMPLETE`: 22 cases (68.75%)
   - `NOT_APPLICABLE`: 0 cases in sample (appears in full 518-case dataset)
2. **`COMPLETE` Cases**:
   - Only contain `VERIFICATION` steps.
   - Every verification step cites a non-empty `evidence_id`.
   - Never contain `FINDING` or `REMEDIATION`.
3. **`INCOMPLETE` Cases**:
   - Contain `FINDING` steps (all with non-empty `evidence_id`).
   - Contain proposed `REMEDIATION` steps (all with empty `""` `evidence_id`).
   - Contain future `VERIFICATION` steps (all with empty `""` `evidence_id`).
   - Every `FINDING` on `(system_id, resource_id)` matches a `REMEDIATION` step.
   - Every `REMEDIATION` on `(system_id, resource_id)` matches a `VERIFICATION` step.
4. **`NOT_APPLICABLE` Cases**:
   - Strictly serialized as `case_id,NOT_APPLICABLE,[]`.
5. **Ordering**:
   - Primary: Phase (`FINDING` $\to$ `REMEDIATION` $\to$ `VERIFICATION`).
   - Secondary: Canonical operation rank per problem statement.
   - Tertiary: `system_id` ascending.
   - Quaternary: `resource_id` ascending.
