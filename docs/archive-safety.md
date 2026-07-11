# Archive safety

A user-uploaded archive is treated as hostile input from the moment
it enters the workspace. Lockverity v0.1 validates every entry
before any extraction happens. The validation is intentionally
aggressive; the default behavior is to reject anything that does
not pass every check.

## What we validate

For every entry in a tar or zip archive, the validator checks:

1. **Path traversal** - the entry name is not allowed to contain
   `..` segments after normalization.
2. **Absolute paths** - POSIX absolute paths (`/etc/passwd`) and
   Windows-style absolute paths are rejected.
3. **Drive-letter paths** - paths starting with `C:` (with or
   without a slash) are rejected.
4. **UNC paths** - `\\server\share` and `//server/share` are
   rejected.
5. **Symbolic links** - entries flagged as symlinks are rejected.
6. **Hard links** - entries flagged as hardlinks are rejected.
7. **Duplicate normalized entries** - two entries that normalize
   to the same path are rejected.
8. **Excessive directory depth** - the entry depth (counted in
   normalized segments) must not exceed
   `Settings.archive_max_depth`.
9. **Oversized individual entries** - per-entry size must not
   exceed `Settings.archive_max_file_bytes`.
10. **Excessive uncompressed size** - the running total of
    uncompressed sizes must not exceed
    `Settings.archive_max_uncompressed_bytes`.
11. **Excessive compressed size** - the running total of
    compressed sizes must not exceed
    `Settings.archive_max_compressed_bytes`.
12. **Suspicious compression ratios** - an entry whose
    `size / compressed_size` is at or above
    `Settings.archive_suspicious_ratio` is rejected (zip-bomb
    heuristic).
13. **Excessive file count** - the running count of entries must
    not exceed `Settings.archive_max_file_count`.

The defaults are intentionally conservative. A user can tighten
them in `.env` or via the `LOCKVERITY_ARCHIVE_*` environment
variables; loosening them requires an explicit change to
`app/utils/archive_validation.py`.

## How validation flows

The validator lives in `app/utils/archive_validation.py` and is
deliberately library-agnostic. The scanner layer is responsible
for converting the library-specific entry (`zipfile.ZipInfo`,
`tarfile.TarInfo`) into a neutral `ArchiveEntry` record and
feeding it to the validator.

```
library entry  --(convert)-->  ArchiveEntry
                                  |
                                  v
                       ArchiveValidationCollector
                                  |
                                  v
                            errors or ok
```

A single bad entry fails the entire archive. The first error is
the one surfaced; the rest are still available on the collector
for diagnostics but are not separately persisted.

## Why we don't extract first

Extracting first means the attack has already happened. The
default behavior is to inspect the entry table of the archive,
not the contents of its files. The extraction step is gated
behind a successful validation; the workspace path that
extraction would use is configured separately from the API's
public paths and is not served by HTTP.

## Configuration

The validation limits are configured in `Settings`. The default
values are:

| Setting | Default | Rationale |
| --- | --- | --- |
| `archive_max_compressed_bytes` | 100 MiB | covers most public release tarballs |
| `archive_max_uncompressed_bytes` | 1 GiB | large enough for monorepos |
| `archive_max_file_count` | 100,000 | a generous upper bound |
| `archive_max_file_bytes` | 256 MiB | covers a single large fixture |
| `archive_max_depth` | 64 | matches typical deep layouts |
| `archive_suspicious_ratio` | 200 | well above legitimate compression |

Operators deploying Lockverity against larger archives should
raise the size and count limits in lockstep, not independently.

## Limitations

- A successful validation does not prove the archive is safe to
  use. The validator defends against the most common attack
  shapes; novel attacks require novel defenses.
- The validator is a *static* check. It does not peek inside
  individual file contents; that is the job of analyzers in
  later milestones.
- The validator does not currently understand tar-specific
  metadata like pax extended headers. Adding support for those
  headers requires explicit changes to the conversion layer.

## What this means for users

A user uploading an archive to Lockverity should expect:

- the upload to be rejected if it contains any of the patterns
  above,
- the rejection message to identify the offending entry,
- no partial state in the workspace - either the archive is
  accepted as a whole, or it is rejected as a whole.

A user should *not* expect:

- the application to silently rewrite paths,
- the application to skip just the bad entries,
- the application to give a second chance after a rejection.
