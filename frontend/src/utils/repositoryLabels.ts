/**
 * Server-side label helpers mirrored in the frontend.
 *
 * The backend computes ``display_name`` and
 * ``canonical_identity`` server-side and returns them on
 * the list endpoint; this module re-implements the same
 * logic for callers that hold a bare ``Repository`` (e.g.
 * the repository detail page, which still uses
 * ``GET /api/v1/repositories/{id}`` and gets the bare
 * ``RepositoryRead`` shape).
 *
 * The two implementations must stay in sync. The
 * authoritative copy is the backend's
 * ``app/api/repositories.py::_display_name`` /
 * ``_canonical_identity``. The v2.0.5 backend test
 * ``tests/test_repository_identification_v2_0_5.py`` pins
 * the backend shape; this module is a faithful TypeScript
 * mirror.
 */

import type { Repository } from "@/api/types";

/**
 * Return the primary human-readable label for a repository.
 *
 * GitHub rows: ``owner/repository``.
 * Uploaded rows: ``original_filename`` if known, else
 * the bounded fallback
 * ``Uploaded archive · upload/<short-key>``.
 */
export function repositoryDisplayName(repo: Repository): string {
  if (repo.source_type === "github") {
    return `${repo.owner}/${repo.name}`;
  }
  if (repo.original_filename) {
    return repo.original_filename;
  }
  const short = (repo.canonical_url ?? "").replace(/^upload:\/\//, "").trim();
  if (!short) {
    return "Uploaded archive";
  }
  return `Uploaded archive \u00b7 upload/${short}`;
}

/**
 * Return the secondary technical identifier for a repository.
 *
 * GitHub rows: the canonical URL.
 * Uploaded rows: ``upload/<short-key>``.
 */
export function repositoryCanonicalIdentity(repo: Repository): string {
  if (repo.source_type === "github") {
    return repo.canonical_url ?? `${repo.owner}/${repo.name}`;
  }
  const short = (repo.canonical_url ?? "").replace(/^upload:\/\//, "").trim();
  if (!short) {
    return "upload://unknown";
  }
  return `upload/${short}`;
}
