# Contributing to obsidian-epost-import

This started as a personal tool and is shared publicly as-is, but issues and
pull requests are welcome.

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). Be
respectful and constructive, assume good faith, keep discussion on the code.

## Prerequisites

See the README's [Prerequisites](README.md#prerequisites) section — Docker
Engine + Compose v2, a `linux/amd64` host, and (for working from source)
`git`.

## Getting started

```bash
git clone https://github.com/dvalfrid/obsidian-epost-import
cd obsidian-epost-import
cp .env.example .env
# fill in .env — see README "Quick start — from source"
docker compose up -d --build
```

For changes to just the Python importer, you don't need the full stack
running:

```bash
cd mail-importer
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python -m py_compile mailimporter/*.py
```

## Development workflow

1. **Open an issue first** for anything beyond a trivial fix — describe the
   bug (repro steps, expected behavior) or the feature (what changes for the
   user and why).
2. **Branch** from `main`.
3. **Implement** the change.
4. **Verify it actually works** against the running stack, not just that it
   compiles — this project's bugs have historically been the kind that only
   show up against a real IMAP/HTTP round-trip (see CLAUDE.md's invariants
   for examples). At minimum: `docker compose up -d --build <service>`
   (never just `restart` — see CLAUDE.md) and check `docker compose logs`.
5. Update **README.md** for anything user-facing, and **CLAUDE.md** for
   anything an AI assistant or future maintainer would need to know to work
   on the project safely (invariants, gotchas, architecture).
6. Open a pull request.

## Commit message format

This repo uses [Conventional Commits](https://www.conventionalcommits.org/),
enforced in spirit rather than by a bot — **`release-please` depends on this
to generate `CHANGELOG.md` and cut version bumps**, so it matters:

```
<type>: <short summary>

[optional longer body]
```

Common types: `feat` (new capability, minor version bump), `fix` (bug fix,
patch bump), `docs`, `chore`, `ci`, `refactor`. Only `feat`/`fix`/`perf` show
up in the changelog.

## Continuous integration

`.github/workflows/ci.yml` runs on every push/PR:

- `verify` — Python/shell syntax checks, `docker compose config` validation.
- `images` — builds all three images (`obsidian`, `bridge`, `mail-importer`);
  only pushes to GHCR once `verify` passes, and never on a pull request.

## Releases

Handled by `release-please` (`.github/workflows/release-please.yml`): it
opens/updates a release PR from Conventional Commits on `main`. Merging that
PR cuts a `vX.Y.Z` tag, which triggers CI to publish versioned images
(`:X.Y.Z`, `:X.Y`, `:X`, `:latest`). See CLAUDE.md "Release & CI" for the
full mechanics.

## Project layout

See the README's [Contents](README.md#contents) section, and CLAUDE.md for
the architecture and the invariants that keep the importer crash-safe and
the Obsidian/Bridge containers correctly isolated.
