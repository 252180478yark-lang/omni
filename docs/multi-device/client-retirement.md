# Legacy client retirement readiness

Physical retirement is an R3 action and is intentionally not performed by the S7–S14 candidate.

The readiness report is fail-closed. It requires all of the following before an owner may review an R3 retirement request:

- at least 14 consecutive days of telemetry coverage;
- zero exclusive-capability use during that window;
- matching source and target checksums for SQLite state, attachments, and settings;
- an explicit secret reauthorization result (the secret value is never exported or inspected);
- successful Host Bridge and restore smoke evidence.

`GET /api/v1/compatibility/retirement-report?client_id=...` reports blockers and always returns `physical_retirement_allowed: false`. A later explicit owner Gate is the only authority that can approve deletion, uninstall, archive, or data cleanup.

For an offline inventory, run `python -B scripts/client_retirement_audit.py --input <manifest> --as-of <ISO-8601>`. The manifest contains checksums and boolean reconciliation evidence only; it must not contain tokens, cookies, keychain values, webhook URLs, or attachment contents.
