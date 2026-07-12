# Lockverity v0.2 Analysis Engine

This document describes the v0.2 analysis engine: how a
repository tree is converted into findings, the contracts every
component satisfies, and the operational limits that protect
the analyzer from hostile input.

## Scope

v0.2 implements:

- Manifest discovery for npm and Python ecosystems.
- Manifest parsers for ``package.json``, ``package-lock.json``,
  ``pnpm-lock.yaml``, ``yarn.lock``, ``requirements.txt``,
  ``pyproject.toml``, and ``poetry.lock``.
- Outbound provider clients for OSV, deps.dev, and OpenSSF
  Scorecard.
- The GitHub Actions workflow analyzer with 15 deterministic
  rules.
- The dependency-graph builder.
- The dependency-path engine.
- 10 vulnerability finding rules and 5 licence inventory rules.
- Exporters for CycloneDX 1.5 JSON, findings JSON, findings CSV,
  and SARIF 2.1.0.
- A synthetic fixture directory covering every required
  scenario.

v0.2 does **not** implement:

- A scan orchestrator that calls the analyzers, runs the
  providers, and writes findings. The contract is in place; the
  executor arrives in v0.3.
- Repository intake (GitHub download, archive upload). The
  analyzer accepts a list of ``(path, bytes)`` tuples, which is
  the same shape a future intake layer will produce.
- Mutating operations (no write back to the database by the
  analyzer modules themselves; the v0.2 modules are pure).

## Layout

```
backend/app/
├── analyzers/
│   ├── github_actions.py        # 15 workflow rules
│   ├── manifest_discovery.py    # StaticAnalyzer for manifests
│   └── dependency_graph.py      # components, edges, missing-lockfile
├── exporters/
│   ├── cyclonedx.py             # CycloneDX 1.5 JSON
│   ├── findings_csv.py          # CSV (formula-injection safe)
│   ├── findings_json.py         # Findings JSON document
│   └── sarif.py                 # SARIF 2.1.0 (location-anchored only)
├── parsers/
│   ├── base.py                  # ManifestParser protocol + helpers
│   ├── npm.py                   # package.json, package-lock.json
│   ├── pnpm.py                  # pnpm-lock.yaml
│   ├── pyproject.py             # pyproject.toml
│   ├── poetry.py                # poetry.lock
│   ├── requirements.py          # requirements.txt
│   └── yarn.py                  # yarn.lock (v1)
├── providers/
│   ├── cache.py                 # in-memory cache contract
│   ├── deps_dev.py              # bounded graph, cycle-safe
│   ├── http_client.py           # timeout, retries, response cap
│   ├── osv.py                   # batched, schema-validated
│   └── scorecard.py             # importer (no binary)
├── rules/
│   ├── base.py                  # shared base + helpers
│   ├── licence.py               # 4 licence rules + 1 inventory
│   └── vulnerability.py         # 10 vulnerability rules
└── utils/
    ├── csv_safety.py            # formula-injection guard
    ├── graph.py                 # bounded DFS, cycle-safe
    ├── manifest_scanner.py      # discovery with limits
    └── yaml_safe.py             # bounded YAML loader
```

## Contracts honoured

Every concrete class satisfies the v0.1 protocols in
``app.providers.contracts``:

- ``ManifestParser.parse(content, path) -> ParserResult[list[dict]]``
- ``VulnerabilityProvider.query(ecosystem, package, version) -> ProviderSuccess | ProviderUnavailable``
- ``DependencyEnrichmentProvider.enrich(ecosystem, package, version) -> ProviderSuccess | ProviderUnavailable``
- ``StaticAnalyzer.analyze(files, scan_run_id) -> AnalyzerResult``
- ``FindingRule.evaluate(evidence, scan_run_id, repository_id) -> tuple[FindingEvidence, ...]``
- ``ReportExporter.export(scan_run_id) -> ProviderSuccess[bytes] | ProviderUnavailable``

## Safety properties

1. **Never execute analyzed code.** No parser, analyzer, or
   provider ever imports a repository module, runs a
   ``setup.py``, invokes ``npm install``, or spawns a
   subprocess. Manifests, lockfiles, and workflows are read as
   bytes; nothing else.
2. **Bounded input.** Every parser uses a bounded JSON or YAML
   loader. The bounded safe YAML loader rejects billion-laughs
   and stack-overflow attempts.
3. **Bounded output.** The CycloneDX and SARIF exporters dump
   via :func:`app.utils.json_safe.dump_bounded_json` and refuse
   to write past a configured size cap.
4. **No silent redaction.** Provider error messages are passed
   through :mod:`app.utils.redaction` before being persisted.
5. **No "no vulnerabilities found" lie.** A provider
   ``unavailable`` outcome is reported as ``LOCK-VULN-007`` and
   the corresponding ``provider_observation`` row, never as
   "no findings".
6. **Bounded graph traversal.** The dependency-path engine
   enforces max depth, max paths, and a per-node fan-in cap.
   Cycles are detected and surfaced.
7. **Deterministic ordering.** Every list of records, paths,
   findings, and components is sorted by a stable key. Re-runs
   of the same scan produce the same output.
8. **Stable finding keys.** Every rule computes a
   ``stable_finding_key`` over the canonical JSON of its
   evidence. The key is the same for re-runs of the same scan.

## Provider-honesty compliance

The providers in v0.2 are designed to comply with
``docs/provider-honesty.md``:

- OSV: batched at 1000 packages per call; per-call retries with
  ``Retry-After``; response size cap; schema validation; honest
  ``unavailable`` outcome; advisory aliases, withdrawn flag,
  affected ranges, and fixed versions preserved exactly as the
  provider reported them.
- deps.dev: bounded graph traversal with explicit depth, node,
  and request caps; cycle detection; in-memory cache; honest
  ``unavailable`` outcome on any HTTP error; the lockfile
  remains authoritative for resolved versions, deps.dev is a
  metadata source.
- Scorecard: import only (no binary); per-check name, score,
  reason, evidence, and source timestamp preserved; missing
  results are reported as ``unavailable`` rather than zero
  score.

## Workflow rules

15 rules live in ``app.analyzers.github_actions.GitHubActionsAnalyzer``:

- ``LOCK-WF-001`` Unpinned third-party action
- ``LOCK-WF-002`` Mutable container tag
- ``LOCK-WF-003`` write-all permissions
- ``LOCK-WF-004`` Missing explicit permissions
- ``LOCK-WF-005`` Dangerous pull_request_target combination
- ``LOCK-WF-006`` Untrusted checkout in privileged context
- ``LOCK-WF-007`` Untrusted expression inside run block
- ``LOCK-WF-008`` Persisted checkout credentials
- ``LOCK-WF-009`` Broad id-token permissions
- ``LOCK-WF-010`` Unsafe workflow_run on self-hosted runner
- ``LOCK-WF-011`` Secrets passed in command arguments
- ``LOCK-WF-012`` Unsafe artifact paths
- ``LOCK-WF-013`` Broad triggers
- ``LOCK-WF-014`` Unpinned setup / deploy action
- ``LOCK-WF-015`` Self-hosted runner on untrusted trigger

A meta-rule ``LOCK-WF-MALFORMED`` is emitted when a workflow
file cannot be parsed as YAML. The meta-rule is not in the 15
because it represents a parser failure, not a workflow-level
finding.

## Vulnerability finding rules

10 rules live in ``app.rules.vulnerability``:

- ``LOCK-VULN-001`` Direct vulnerable dependency
- ``LOCK-VULN-002`` Transitive vulnerable dependency
- ``LOCK-VULN-003`` No fixed version reported
- ``LOCK-VULN-004`` Withdrawn advisory
- ``LOCK-VULN-005`` Unresolved dependency version
- ``LOCK-VULN-006`` Partial provider data
- ``LOCK-VULN-007`` Provider unavailable
- ``LOCK-VULN-008`` Multiple dependency paths
- ``LOCK-VULN-009`` Development dependency vulnerability
- ``LOCK-VULN-010`` Missing lockfile

## Licence finding rules

5 rules live in ``app.rules.licence``:

- ``LOCK-LIC-001`` Unknown licence
- ``LOCK-LIC-002`` Multiple licence assertions
- ``LOCK-LIC-003`` Review-required licence
- ``LOCK-LIC-004`` Provider licence unavailable
- ``LOCK-LIC-INV`` Licence inventory (informational)

The licence rules never provide a legal conclusion. They
surface observations the user can act on.

## Exporters

- ``CycloneDxExporter`` produces a CycloneDX 1.5 SBOM with
  metadata, components, dependencies, and vulnerabilities.
- ``FindingsJsonExporter`` produces a JSON document with the
  full set of findings for a scan.
- ``FindingsCsvExporter`` produces a spreadsheet-safe CSV with
  formula-injection protection on every cell.
- ``SarifStaticFindingsExporter`` produces a SARIF 2.1.0
  document. Only findings with a ``location_path`` are
  included; the count of skipped findings is recorded in the
  ``properties`` block.

## Synthetic fixtures

``backend/tests/fixtures`` contains synthetic data for every
required scenario:

- ``npm/clean``, ``npm/vulnerable``, ``npm/workspace``,
  ``npm/malformed_lock``
- ``python/clean``, ``python/poetry``
- ``mixed``
- ``graph/circular``, ``graph/oversized``
- ``workflows/safe``, ``workflows/unsafe``,
  ``workflows/yaml_aliases``, ``workflows/malformed``
- ``providers/osv_success.json``, ``osv_empty.json``,
  ``osv_partial.json``, ``osv_withdrawn.json``,
  ``osv_missing_severity.json``, ``osv_aliases.json``,
  ``deps_dev_success.json``, ``deps_dev_multiple_licences.json``,
  ``deps_dev_no_licence.json``, ``scorecard_success.json``
- ``exporters/csv-injection.yml``

All fixture files are clearly labelled as synthetic. They
never contain real credentials or production data.

## Tests

Test coverage:

- ``test_yaml_safe.py`` - bounded YAML loader
- ``test_manifest_scanner.py`` - discovery limits and ordering
- ``test_graph.py`` - bounded DFS, cycles, fan-in
- ``test_csv_safety.py`` - formula-injection protection
- ``test_parsers_npm.py`` - package.json, package-lock.json
- ``test_parsers_python.py`` - pnpm, yarn, requirements, pyproject, poetry
- ``test_providers_http_client.py`` - timeout, retry, size cap
- ``test_providers_cache.py`` - cache contract
- ``test_providers_osv.py`` - batching, schema, withdrawn, aliases
- ``test_providers_deps_dev.py`` - bounded graph, cache
- ``test_providers_scorecard.py`` - import-only, no binary
- ``test_analyzer_manifest_discovery.py`` - manifest discovery analyzer
- ``test_analyzer_dependency_graph.py`` - components, edges, missing-lockfile
- ``test_analyzer_github_actions.py`` - 15 workflow rules
- ``test_rules_vulnerability.py`` - 10 vulnerability rules
- ``test_rules_licence.py`` - 4 + 1 licence rules
- ``test_exporters.py`` - CycloneDX, JSON, CSV, SARIF

All tests are mocked (no real network). No test installs or
executes a repository's dependencies.

## Known limitations

- The orchestrator that wires the parsers, analyzers,
  providers, and exporters is not yet implemented. v0.2 ships
  the building blocks; v0.3 will connect them.
- Yarn 2+ (Berry) lockfiles are not supported. v0.2 implements
  Yarn 1 (classic) only.
- Maven, Go, Cargo, Composer, NuGet, and other ecosystems are
  out of scope for v0.2.
- Reachability analysis (whether a vulnerable code path is
  actually called) is explicitly out of scope. Lockverity
  surfaces the manifest-level observation; the developer
  decides whether the code path is reachable.
- The PyYAML dependency is used for safe workflow parsing. It
  is loaded with the bounded safe loader so YAML bombs cannot
  crash the analyzer.
- The Scorecard importer does not run the Scorecard binary. It
  reads published results only.
- Run reachability is not inferred; every vulnerability finding
  is a manifest-level observation, not a verdict.
