# Jernigan Structure Atlas: saved static deployment

This source-only delivery recipe is proposed for **benavt/jernigan-structure-atlas**,
with the intended Pages address `https://benavt.github.io/jernigan-structure-atlas/`.
The repository, release and Pages deployment must be created **only after the user
approves the reviewed exact bundle digest**. This directory creates none of them.
The scientific source repository **benavt/Jernigan remains private**.

The initial proposed public scope is the reviewed 2J5X saved Atlas preview of the complete 11,000-model cohort
and its separately labeled historical 7,005-model comparison. Public assets include
saved projection coordinates and memberships, scores already present in the Atlas,
MCMC/DISCO selected panels, representative structures and aligned ensembles, native
Bonsai trees, selected evidence downloads, and the reviewed PDF/PPTX reports.
It does not include the native complete model population, input sidecars, private
machine locations, credentials or working arrays. Actual public scope is defined by the
reviewed `export-manifest.json`; this description is not publication approval.
Missing confidence evidence and unavailable historical views remain visible.

## Inputs and independence

The only deployment inputs are this source recipe and an already rendered,
privacy-reviewed static `site.tar.gz`, identified by its **exact SHA-256**. No
submodules, Structure Clustering installation, private host, private compute service,
scientific runtime, input model population, computation or external paid API is
required to unpack or serve the release. Viewer scripts and assets belong in the
saved static bundle, using relative URLs compatible with the Pages project path.

`export-manifest.json` must be UTF-8 JSON with `schema_version: 1`,
`project: "jernigan-structure-atlas"`, `scientific_execution: false` and a `files`
array. Each row contains `path`, integer `bytes`, and lowercase 64-character
`sha256`. The manifest lists every static file except itself. `index.html` and
`.nojekyll` are required. No undeclared file, duplicate path, symlink, hard link,
nonregular member, encoded/traversal path, hidden source directory, tar extension
header or appended archive is allowed. There are finite limits of 10,000 files,
950,000,000 expanded asset bytes and an 8,000,000-byte manifest. The header scan
bounds decompression and rejects extension payloads before tarfile parses them.
This integrity gate does not replace privacy review or scientific review.

## Package an already reviewed directory

With Python 3.11 or later and only its standard library:

```sh
python scripts/package_site.py /path/to/reviewed/static-site --output /path/to/site.tar.gz
```

The packager requires a fresh archive path outside the static directory. It checks
the directory against the exact manifest, normalizes file order, ownership, mode,
mtime and gzip metadata, embeds the exact initial manifest bytes and fixed reviewed artifact lengths,
then independently verifies the produced archive and rechecks source stability before
exposing its final filename. Equal directory bytes produce equal archive bytes.
It never renders analyses or writes into the saved directory. USTAR is used;
paths that do not fit USTAR must be renamed during a separately reviewed export.

Record the resulting `bundle_sha256`, complete file list, evidence/coverage report
and intended public download list for approval. Do not upload the bundle yet.

## Reproduce the public static build locally

```sh
python scripts/deploy_bundle.py /path/to/site.tar.gz --sha256 EXACT_APPROVED_SHA256 --output /fresh/static-build
```

Serve the fresh build with a static HTTP server bound only to the loopback interface.

The deployment verifier is completely standalone: copying only
`scripts/deploy_bundle.py` to an empty directory suffices. It hashes the actual
archive, validates its contract and every allowlisted file before creating the
output, and refuses an existing output directory. It does not overwrite a prior
site. A failure leaves the affected inputs in place for investigation; an I/O
failure during final extraction may leave a partial new output, which must not be
published. Review the actual site on desktop and narrow screens, WebGL fallback,
requested views and download bytes before approving public delivery.

## Deployment after exact approval

1. Create the separate public delivery repository with this recipe; keep scientific
   source and bulk private. Configure GitHub Pages to build from GitHub Actions.
2. Upload the approved `site.tar.gz` as a release asset. Uploading to a public
   release makes its downloads public and therefore requires approval first.
3. Manually dispatch **Deploy reviewed saved Atlas** on `main`, supplying the
   approved release tag and exact approved bundle SHA-256.
4. The prepare job has read-only repository permission. It downloads exactly
   `site.tar.gz`, verifies/unpacks it, and uploads the Pages artifact. Only the
   dependent deploy job receives `pages: write` and `id-token: write` permission.
5. Verify the real public deep link, controls, fallback and downloads. Preserve the
   release manifest, review receipt and deployment evidence. Fleet sealing and
   archive/restoration acceptance remain separate handoff checks.

The workflow is manual-only, serializes deployments without cancellation, and has
finite ten-minute job limits. Inputs are passed through quoted environment
variables rather than interpolated into shell code. GitHub Action source commits
were verified by read-only GitHub API on 2026-11-17:

| Action tag | Exact source commit |
| --- | --- |
| actions/checkout v4 | `11d5960a326750d5838078e36cf38b85af677262` |
| actions/setup-python v5 | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| actions/upload-pages-artifact v3 | `56afc609e74202658d3ffba0e8f6dda462b719fa` |
| actions/deploy-pages v4 | `d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e` |

## Focused verification

```sh
python -m unittest discover -s tests -v
```

The twelve tests cover exact round trips, archive and artifact mutations, traversal
and encoded paths, unsafe links/nonregular members, duplicates and size bounds,
wrong contracts/allowlists, extension and appended tar rejection, overwrite and
symlinked output protection, deterministic packaging, changed source rejection,
concurrent manifest/source replacement, changes during extraction, and isolated
deployment without project/runtime imports. They do not establish
visual browser acceptance, privacy clearance or publication authorization.
