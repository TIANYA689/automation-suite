# Public Release Checklist

Use this checklist before pushing Automation Suite to GitHub.

## Required Files

- `LICENSE`
- `README.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`
- `.github/workflows/ci.yml`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/pull_request_template.md`

## Commands

```powershell
python scripts/misc/public_release_check.py
python scripts/misc/mcp_smoke_check.py
git status --short --ignored
```

## Manual Review

- Confirm `.mcp.json` and `.codex/config.toml` only use relative project paths.
- Confirm ignored folders contain no files that must be published.
- Confirm reports and exports are regenerated locally rather than committed.
- Confirm examples use placeholders, not real credentials.
- Confirm README states the authorized-use boundary.
