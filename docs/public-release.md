# Public Release Checklist

Use this checklist before pushing Automation Suite to GitHub.

## Required Files

- `LICENSE`
- `README.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `.github/workflows/ci.yml`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/pull_request_template.md`

## Commands

```powershell
python scripts/misc/public_release_check.py
git status --short --ignored
```

## Manual Review

- Confirm ignored folders contain no files that must be published.
- Confirm reports and exports are regenerated locally rather than committed.
- Confirm examples use placeholders, not real credentials.
- Confirm README states the authorized-use boundary.

## Scope: what the checker looks at

The checker does **not** walk the working tree. It asks git for
`git ls-files --cached --others --exclude-standard` — that is, *everything that is
tracked, plus everything untracked but not ignored*. In other words: **what would
actually be published.**

This matters because the two lists used to be maintained separately, and they had
already drifted. Concretely, `tools/automation-modules/邮箱/22do_free_receiver/data/`
held a saved inbox summary containing a real third-party address; it is gitignored
and never published, yet the old hardcoded prefix list did not know that and kept
scanning it. `.trae/`, `CLAUDE.md` and `.workbuddy-ai/` had the same problem in the
other direction: they are gitignored, but only `.gitignore` knew.

The report now prints `scanned_files` so the scope is visible rather than assumed.
If git is unavailable the checker falls back to `is_ignored()`, which is an
approximation and does not read `.gitignore`.

## PII rule

The checker reports email addresses that look personal. An address is **allowed**
when either condition holds:

- its domain is reserved for documentation (`example.com`, `example.net`,
  `example.org`, anything under `.test`, `.invalid`, `.localhost`, `.local`); or
- its local part is an explicitly declared non-personal name (`demo`, `test`,
  `test123`, `abc123`, `abc12345`, `user`, `sender`, `admin`, `noreply`, `pass`,
  and a few more — see `NON_PERSONAL_LOCAL_PARTS`).

The local-part list is matched **exactly, never as a substring**, because a
substring match would silently pass a real address whose local part merely
contains one of those words. Domain matching is likewise exact for named domains,
so a lookalike such as a domain merely *ending* in `example.com` is still reported.

Both halves are needed. A domain-only allowlist would flag the mail-module
documentation, which legitimately discusses temporary-mail services — and a rule
that cries wolf gets switched off, which is worse than having no rule.

**This is noise reduction and mis-paste prevention, not a security boundary.** It
catches "a real value from a capture was copied into a readable file by hand"; it
does not stop deliberate evasion. The real boundary is not copying real values into
readable files in the first place — see the `projects/` capture rules in
`.gitignore`.

When it fires, the fix is to replace the value with a reserved-domain placeholder,
**not** to add the address to the allowlist.
