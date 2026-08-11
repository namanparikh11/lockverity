# Provider-honesty policy

Lockverity distinguishes between *missing data*, *unavailable data*,
*partial data*, and *verified-clean data*. These distinctions are
the foundation of the product's claim to be evidence-based.

## Definitions

- **Not requested data** - the provider was never queried. This
  includes a scan that did not reach the relevant stage and an
  explicit operator choice recorded as `not_requested` with
  reason `disabled_by_operator`.
- **Unavailable data** - the provider was queried and refused or
  could not be reached. The application knows it does not know.
- **Partial data** - the provider returned some records and
  signalled an error or rate limit. The application preserves the
  records that arrived and records the error.
- **Verified-clean data** - the provider was queried, returned
  successfully, and produced no matches. This is the *only*
  state in which "no vulnerabilities found" is a defensible
  statement.

## Rules

1. The application must never report "no vulnerabilities found"
   when the relevant provider was unavailable, rate-limited, or
   not requested.
2. The application must never fabricate a finding, an advisory, or
   a severity score.
3. The application must record every provider call in
   `provider_observations` with at least: provider, operation,
   status, requested_at, completed_at, records_returned, and (if
   applicable) error_code and error_summary.
4. The application must never store raw provider response bodies.
   Only bounded summaries, hashes, and per-record fields are
   persisted.
5. The application must never write provider credentials to the
   database. The `error_summary` field is run through the
   redaction utility before being persisted.
6. The frontend must distinguish the four data states in the UI.
   "No findings" is rendered as "no findings recorded" or "no
   findings for the selected filters", never as "clean".
7. A new finding rule that returns a "no findings" verdict must
   declare which provider evidence it relies on. A rule cannot
   declare "no findings" if no provider was queried.
8. A provider disabled by the operator must be gated before its
   service, client, cache, or network path. It is not unavailable,
   failed, degraded, or evidence of zero findings.

## Implementation

- `app/providers/results.py` defines the result types
  (`ProviderSuccess`, `ProviderPartialResult`,
  `ProviderUnavailable`).
- `app/services/*` translate provider results into the database
  representation.
- `app/api/scans.py` exposes `/scans/{id}/providers` so the UI can
  show availability.
- `frontend/src/components/DataCompletenessNotice.tsx` is the
  reusable banner for "data not available" states.

## What this means for users

A user of Lockverity should never see "scan complete: no
vulnerabilities" without also seeing the provider availability
table. If the table is empty, the scan did not reach the
vulnerability stage. If the table is full of "unavailable" or
"rate_limited" rows, the scan did not get answers from any
provider, and the absence of findings is not a clean bill of
health.
