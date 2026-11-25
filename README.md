# HomeLab-FastPi

- Service customizations and their post-update checks: [Docker/CUSTOMIZATIONS.md](Docker/CUSTOMIZATIONS.md)
- Updating containers: [Docker/_global/UPDATE-RUNBOOK.md](Docker/_global/UPDATE-RUNBOOK.md)

## CI

GitHub Actions, `.github/workflows/ci.yml`, on every push and pull request (`permissions: contents: read`, actions pinned by commit SHA). Linters come from `.github/scripts/install-tools.sh` (pinned versions, checksums verified).

| Job | What it checks | Local command |
|---|---|---|
| `tests` (x86 and arm64) | every `test_*.py` / `test_*.sh` with `CI=true`; tests that need Docker or the live host are listed in `.github/ci-skip.txt` | `bash .github/scripts/run-tests.sh [PATH_PREFIX]` |
| `shellcheck` | tracked shell scripts, warnings and errors, minus `.github/lint-baseline.toml` | `python3 .github/scripts/lint.py shellcheck` |
| `hadolint` | every Dockerfile, warnings and errors, minus the baseline | `python3 .github/scripts/lint.py hadolint` |
| `compose config and policy` | `docker compose config` of every project (dummy `.env`, `.github/scripts/ci-compose-env.sh`) and the container policy without pulling images | `bash .github/scripts/ci-compose-env.sh && python3 Docker/_global/scripts/policy_check.py --offline` (the script writes `.env` files: only on a clean clone) |
| `gitleaks` | full history, `.gitleaks.toml` | `gitleaks git --config .gitleaks.toml .` |
| `actionlint` | the workflow files | `actionlint` |

| Change | Where |
|---|---|
| A test CI cannot run | line in `.github/ci-skip.txt`: `glob \| reason` |
| A lint finding you do not fix | entry in `.github/lint-baseline.toml` (file, code, count, reason); a new finding or a stale entry fails the job |
| A Python package a test needs | `.github/requirements-ci.txt` |
| An optional variable that must stay blank in the dummy `.env` | `.github/ci-env-blank.txt` |
