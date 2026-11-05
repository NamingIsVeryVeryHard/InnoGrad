# Changelog

## material-review-5

- Added `paper-v2` and `annual-v2` rule templates with `level` (blocking/advisory) and `on_uncertain` (correction/hint) routing fields; v1 templates are kept only for previously frozen submissions.
- Added the `proofs_not_required` applicability condition so annual reports do not require achievement proofs unless the task sets `proof_attachments_required`.
- Clarified that `limitations` only list gaps that make a conclusion uncertain; settled conclusions carry no generic caveats.
- Relaxed matching guidance for titles, venues, name romanization and date precision; contribution checks no longer require proof of author division of labour.
- Evidence, quoting, per-rule coverage and frozen-rule requirements are unchanged.

## material-review-4

- Clarified evidence copying, proof requirements, identity, contribution, and annual coverage.
- Documented inline packages and optional workspace-relative files for complete review in one session, without changing the input or output schemas.
- Required complete source reads, same-session correction when validation feedback is provided, and a checks-only JSON response.

## 1.0.0

- Added frozen paper and annual review rule manifests.
- Added structured evidence-bound output contract.
