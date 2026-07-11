# Finding model

A *finding* is one observable security observation in a scan.
Lockverity's finding model is designed to be evidence-based,
deterministic, and auditable. There is no universal security score;
every finding stands on its own.

## Schema

```
findings
  id                bigint primary key
  scan_run_id       references scan_runs(id) on delete cascade
  repository_id     references repositories(id) on delete cascade
  rule_id           text  (e.g. LOCK-SUPPLY-001)
  category          enum  (one of the documented categories)
  severity          enum  (informational|low|medium|high|critical|unknown)
  confidence        enum  (low|medium|high|confirmed|unknown)
  title             text
  summary           text
  remediation       text  nullable
  evidence_json     text  nullable, bounded
  location_path     text  nullable
  location_start_line int nullable
  location_end_line   int nullable
  stable_key        text  64 chars, sha256 hex
  status            enum  (open|resolved|accepted|suppressed)
  created_at        timestamptz
  updated_at        timestamptz
```

The `(scan_run_id, stable_key)` pair is unique. Two findings with
the same `stable_key` cannot coexist in the same scan.

## Categories

A finding's `category` is one of:

- `dependency` - a manifest or lockfile observation, e.g. a
  workspace-only dependency in a published package.
- `vulnerability` - a component matches a known advisory.
- `workflow` - a CI/CD configuration observation, e.g. a
  `pull_request_target` workflow with checkout of untrusted code.
- `repository_posture` - a repository configuration observation,
  e.g. an archived repository with active issues.
- `licence` - a licence inventory observation, e.g. a copyleft
  licence in a permissively-licensed project.
- `provider` - a provider-availability observation, e.g. a
  rate-limited query.
- `data_quality` - a structural observation about the scanned
  artifacts, e.g. an unparseable manifest.

## Severity vs. confidence

Severity and confidence are independent dimensions. A
critical-severity finding may still have low confidence; a
medium-severity finding may be confirmed. Lockverity renders
both, side by side, and never collapses them into a single score.

A finding is allowed to be `severity=unknown` when the underlying
evidence does not contain a severity label. Lockverity never
invents a severity label.

## Stable key

A finding's `stable_key` is the hex SHA-256 of a canonical JSON
serialization of `(rule_id, normalized_evidence)`. The
normalization is defined in `app/utils/finding_keys.py`. Identical
evidence must produce identical keys, and reruns of the same
scan must dedupe against the same key.

The `stable_key` is what makes scan comparison possible in later
milestones. v0.1 does not yet ship a comparison view; the
contract is in place.

## Evidence

`evidence_json` is bounded (64 KiB) and is the only field that
is allowed to carry arbitrary structured data. The application
never renders `evidence_json` as trusted HTML; the frontend treats
it as text.

A finding with a `location_path` and a `location_start_line` /
`location_end_line` is anchored to a specific file and line
range. The CHECK constraint `range_consistent` ensures
`location_end_line >= location_start_line` when both are present.

## Status

A finding's `status` is one of:

- `open` - the finding is current and unaddressed.
- `resolved` - the finding is no longer observable in the latest
  scan.
- `accepted` - the finding is acknowledged and the team has
  decided to keep it.
- `suppressed` - the finding is hidden from default views by an
  explicit suppression rule.

A scan never silently moves a finding from one status to another;
the status is set when the finding is first written and is updated
only by an explicit transition.

## What this means for users

A user of Lockverity should treat a finding as a pointer to
evidence, not as a verdict. The UI must show:

- the rule that produced the finding,
- the file or component it applies to,
- the severity and confidence separately,
- the evidence (in a bounded, safe form),
- a remediation hint, when one is available.

A finding without a `location_path` is allowed (for example, a
provider-availability finding has no file location). The UI
renders those as "no file location" rather than as "all files".
