# Synthetic Evaluation Fixtures (EXTRAS.md §3)

This directory contains a standalone mini-dataset engineered to test edge cases in deletion auditing.
All expected outputs in `expected_output.csv` were **derived strictly by hand from `problem_statement.md` and `deletion_rules.csv`** without reading or executing the agent's code.

---

## Fixture Descriptions

### 1. `case_syn_01`: Email Reused by a Different User After Deletion
- **Scenario**: User A (`user_synth_01`) registered with `reused.alice@example.com` on `2024-01-01` and requested deletion on `2025-06-01`. On `2026-01-10`, User B (`user_synth_02`) registered with that same email.
- **Rule & Derivation**: As-of resolution for User A's deletion request on `2025-06-01` must resolve to User A (`user_synth_01`), not User B. Investigation reveals a customer support conversation (`support_synth_01`) containing unredacted PII. Rule 05 (`SUPPORT_MESSAGE`) mandates `REDACT`.
- **Expected Status**: `INCOMPLETE`
- **Expected Steps**:
  1. `FINDING` (`support_platform`, `support_synth_01`, `REPORT_EXPOSED_PII`, `PRESENT`, `evidence_synth_01`)
  2. `REMEDIATION` (`support_platform`, `support_synth_01`, `REDACT_RECORD`, `REDACTED`)
  3. `VERIFICATION` (`account_service`, `account_synth_01`, `VERIFY_RECORD_ABSENT`, `ABSENT`)
  4. `VERIFICATION` (`support_platform`, `support_synth_01`, `VERIFY_RECORD_REDACTED`, `REDACTED`)

### 2. `case_syn_02`: Historical Email or Old Phone in Secondary System
- **Scenario**: User `user_synth_03` updated their email from `old.email@example.com` to `new.email@example.com` in `user_audit_log.csv`. The deletion request cited `new.email@example.com`. Primary account was deleted.
- **Rule & Derivation**: Audit agent must reconstruct historical identifiers. Search index entry `search_synth_03` still contains `old.email@example.com` and old phone `+1 555-0199`. Rule 03 (`SEARCH_INDEX_ENTRY`) mandates `DELETE`.
- **Expected Status**: `INCOMPLETE`
- **Expected Steps**:
  1. `FINDING` (`search_service`, `search_synth_03`, `REPORT_REMAINING_RECORD`, `PRESENT`, `evidence_synth_02`)
  2. `REMEDIATION` (`search_service`, `search_synth_03`, `DELETE_RECORD`, `ABSENT`)
  3. `VERIFICATION` (`account_service`, `account_synth_03`, `VERIFY_RECORD_ABSENT`, `ABSENT`)
  4. `VERIFICATION` (`search_service`, `search_synth_03`, `VERIFY_RECORD_ABSENT`, `ABSENT`)

### 3. `case_syn_03`: Sync Job Recreates a Record After the Delete Event
- **Scenario**: User `user_synth_04` had their account deleted on `2026-08-11`. On `2026-08-12`, integration sync job `data_flow_synth_04` ran and recreated `export_synth_04`.
- **Rule & Derivation**: Problem statement requires detecting active processes that can recreate data and ordering remediation: `DISABLE_DATA_FLOW` before `DELETE_RECORD`.
- **Expected Status**: `INCOMPLETE`
- **Expected Steps**:
  1. `FINDING` (`export_service`, `export_synth_04`, `REPORT_REMAINING_RECORD`, `PRESENT`, `evidence_synth_03`)
  2. `FINDING` (`integration_service`, `data_flow_synth_04`, `REPORT_ACTIVE_DATA_FLOW`, `ACTIVE`, `evidence_synth_03`)
  3. `REMEDIATION` (`integration_service`, `data_flow_synth_04`, `DISABLE_DATA_FLOW`, `DISABLED`)
  4. `REMEDIATION` (`export_service`, `export_synth_04`, `DELETE_RECORD`, `ABSENT`)
  5. `VERIFICATION` (`account_service`, `account_synth_04`, `VERIFY_RECORD_ABSENT`, `ABSENT`)
  6. `VERIFICATION` (`export_service`, `export_synth_04`, `VERIFY_RECORD_ABSENT`, `ABSENT`)
  7. `VERIFICATION` (`integration_service`, `data_flow_synth_04`, `VERIFY_DATA_FLOW_DISABLED`, `DISABLED`)

### 4. `case_syn_04`: Tombstone Holding an Email Hash
- **Scenario**: Primary account was replaced by an account tombstone `tombstone_synth_05` holding user ID and SHA-256 email hash.
- **Rule & Derivation**: Rule 15 (`ACCOUNT_TOMBSTONE`) states stable internal user_id is permitted, but direct identifiers such as email and email hash must be removed.
- **Expected Status**: `INCOMPLETE`
- **Expected Steps**:
  1. `FINDING` (`identity_service`, `tombstone_synth_05`, `REPORT_EXPOSED_PII`, `PRESENT`, `evidence_synth_04`)
  2. `REMEDIATION` (`identity_service`, `tombstone_synth_05`, `REDACT_RECORD`, `REDACTED`)
  3. `VERIFICATION` (`identity_service`, `tombstone_synth_05`, `VERIFY_RECORD_REDACTED`, `REDACTED`)

### 5. `case_syn_05`: Fully Compliant COMPLETE Case
- **Scenario**: User requested deletion. Primary account `account_synth_06` is absent, security audit trail `audit_record_synth_06` is retained under Rule 12, and analytics record `analytics_synth_06` is anonymized under Rule 07.
- **Rule & Derivation**: For `COMPLETE`, only `VERIFICATION` steps are returned, all citing valid evidence.
- **Expected Status**: `COMPLETE`
- **Expected Steps**:
  1. `VERIFICATION` (`account_service`, `account_synth_06`, `VERIFY_RECORD_ABSENT`, `ABSENT`, `evidence_synth_05`)
  2. `VERIFICATION` (`security_service`, `audit_record_synth_06`, `VERIFY_RECORD_PRESENT`, `PRESENT`, `evidence_synth_05`)
  3. `VERIFICATION` (`analytics_platform`, `analytics_synth_06`, `VERIFY_RECORD_ANONYMIZED`, `ANONYMIZED`, `evidence_synth_05`)

### 6. `case_syn_06`: Restorable Backup Risk
- **Scenario**: Account deleted, but snapshot backup `backup_synth_07` remains unblocked and restorable in `backup_service`.
- **Rule & Derivation**: Rule 14 (`BACKUP_ARCHIVE`) requires blocking restore access (`BLOCK_RESTORE`).
- **Expected Status**: `INCOMPLETE`
- **Expected Steps**:
  1. `FINDING` (`backup_service`, `backup_synth_07`, `REPORT_RESTORE_RISK`, `ACTIVE`, `evidence_synth_06`)
  2. `REMEDIATION` (`backup_service`, `backup_synth_07`, `BLOCK_RESTORE`, `BLOCKED`)
  3. `VERIFICATION` (`account_service`, `account_synth_07`, `VERIFY_RECORD_ABSENT`, `ABSENT`)
  4. `VERIFICATION` (`backup_service`, `backup_synth_07`, `VERIFY_RESTORE_BLOCKED`, `BLOCKED`)

### 7. `case_syn_07`: Explicit Non-Deletion Request (Multilingual)
- **Scenario**: User submits ticket in Spanish explicitly asking NOT to delete: *"Por favor no eliminen mi cuenta ni borren mis datos. Solo necesito actualizar mi direccion de envio."*
- **Rule & Derivation**: Classifier must detect that deletion was not requested.
- **Expected Status**: `NOT_APPLICABLE`
- **Expected Steps**: `[]`
