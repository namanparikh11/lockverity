# Privacy policy

Last updated: 15 August 2026.

Lockverity is a local-first software supply-chain evidence tool. This policy describes what the application processes locally and what it sends to external services. Repository content and package coordinates can contain personal, confidential, or identifying information; this policy does not classify them as non-personal data.

## Local runtime and storage

The backend and interface run on the operator's machine. Current Windows development builds render the existing React interface in a dedicated Microsoft Edge WebView2 window connected only to the loopback FastAPI origin; source workflows can use a normal browser. Lockverity stores its database, logs, scan results, provider observations, workspaces, uploaded archives, and runtime state in locally configured paths. Windows installer and portable-package defaults place runtime data under `%LOCALAPPDATA%\Lockverity`; source deployments can configure equivalent database and workspace locations.

The Windows GUI does not expose a Python-to-JavaScript bridge. Approved HTTPS documentation and evidence links open in the operator's system browser; unexpected top-level WebView navigation is blocked. Current-source installers embed Microsoft's signed Evergreen WebView2 bootstrapper and may contact Microsoft to install the runtime only when WebView2 is missing. The portable launcher performs no silent runtime download and instead shows an actionable prerequisite message.

## GitHub repository retrieval

Submitting a GitHub repository necessarily contacts GitHub before analysis. Lockverity sends the repository owner and name and, when supplied, the requested branch, tag, or commit identifier. It retrieves repository metadata, resolves the requested ref to a commit SHA, and downloads the repository tarball. GitHub retrieval is required for a GitHub repository scan and has no provider-disable control.

## OSV

When OSV is selected and applicable, Lockverity sends the package ecosystem, package name, and observed version when available to `api.osv.dev`. It uses those coordinates to request vulnerability evidence. OSV is enabled by default for backward compatibility and can be disabled for each scan before execution.

## deps.dev

When deps.dev is selected and applicable, Lockverity sends the package ecosystem, package name, and concrete package version to `api.deps.dev`. It uses those coordinates to request package and dependency metadata. deps.dev is enabled by default for backward compatibility and can be disabled for each scan before execution.

## OpenSSF Scorecard

When OpenSSF Scorecard is selected for a supported GitHub repository, Lockverity sends the GitHub platform identifier, repository owner, and repository name to `api.securityscorecards.dev`. Scorecard is enabled by default for applicable GitHub scans and can be disabled for each scan before execution. It is not applicable to uploaded archives.

## Archive uploads

Uploaded ZIP bytes are quarantined, validated, extracted, and analyzed locally. Lockverity does not upload the archive or its source files to GitHub, OSV, deps.dev, or OpenSSF Scorecard. Package coordinates discovered inside an archive may be sent to OSV or deps.dev only when the operator leaves those providers selected for that scan. OpenSSF Scorecard is not requested for archive scans.

## Optional GitHub token

An operator can set `LOCKVERITY_GITHUB_TOKEN` in the local backend environment to authenticate GitHub API requests and increase the applicable rate limit. The token is not requested by or embedded in the browser frontend. Lockverity does not persist it in scan observations, reports, or exports; provider errors and URLs pass through redaction before persistence.

## Provider choice and network activity

OSV, deps.dev, and OpenSSF Scorecard are independent, request-scoped choices shown before scan execution. Applicable choices default to enabled. A provider disabled by the operator is recorded as not requested, and Lockverity performs no client, cache, or network operation for that provider during that execution attempt. Local manifest, dependency, workflow, and rule analysis continues when all optional evidence providers are disabled.

## Third-party privacy policies

Use of selected external providers is also subject to those providers' privacy policies:

- GitHub: [GitHub General Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).
- OSV and deps.dev (Google-hosted services): [Google Privacy Policy](https://policies.google.com/privacy).
- OpenSSF Scorecard: [Linux Foundation Privacy Policy](https://www.linuxfoundation.org/legal/privacy-policy).

## Telemetry and analytics

Lockverity does not include product telemetry, analytics, advertising identifiers, user accounts, or cloud inference. It does not send local scan results to a Lockverity-operated service.

See also the [provider-honesty policy](provider-honesty.md), [security boundaries](security-boundaries.md), and [security policy](../SECURITY.md).
