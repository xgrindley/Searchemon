# Releases and test builds

Repository: https://github.com/xgrindley/Searchemon

## Branches

| Branch | Purpose | Who changes it |
|---|---|---|
| `main` | The stable release. Only changes when you say a build is stable | Promoted from `test` on your word |
| `test` | The current test build. Day-to-day work lands here | Every change |
| `build/vX.Y` | Frozen copy of one test build, for going back to it | Created once, never changed |
| `release/vN.0` | Frozen copy of one stable release | Created once, never changed |
| `test/<name>` | A risky or big piece of work kept apart (for example `test/ui-redesign`) | Merged into `test` when it works |

`main` is never edited directly and never receives untested work.

## When work goes to GitHub

GitHub is not touched on every change. Work is built and checked here and copied to your PC folder first.
Nothing is pushed to `test`, `build/vX.Y` or `main` until you have tested the build and say it is approved.
After you approve, one push saves that build (and the frozen `build/vX.Y` copy) to GitHub. Stable
promotion to `main` is a separate step that only happens when you say a build is stable.

## Version numbers

- **Stable releases count up whole numbers:** v1.0, v2.0, v3.0. Each is a tag on `main`.
- **Test builds count up from the release they follow:** after v1.0 come v1.1, v1.2, v1.3. After v2.0 come v2.1, v2.2.
- Before the first stable release, test builds were v0.1 to v0.6. v1.0 is v0.6 promoted (2026-10-25).
- The `VERSION` file holds the number.
- Every numbered build is kept as its own branch so it can be installed later: test builds as `build/v1.1`,
  stable releases as `release/v2.0` (plus a `v2.0` tag and GitHub Release when one can be created;
  Claude's session cannot create tags or Releases, so for stable releases you click **Releases > Draft a
  new release** on GitHub, pick the `release/vN.0` branch, and mark it Latest).

## Promoting a build to stable

1. You tell Claude "v1.4 is stable".
2. `test` is merged into `main`, the version becomes the next whole number (v2.0), and `release/v2.0` is saved.
3. `test` continues from v2.1.

## Installing on your PC

```powershell
cd "$HOME\Documents\poke-restock"
.\update.ps1                         # newest stable release
.\update.ps1 -Channel test           # newest test build
.\update.ps1 -Channel test/ui-redesign
.\update.ps1 -Channel v1.2           # an exact build
```

An update saves a snapshot first, so `.\versions.ps1 restore` undoes it. Settings and data are never touched.

## Keep out of the repository

`config.yaml` (your webhooks and keys), `data\`, `.venv\`, and `versions\` are in `.gitignore`. Never paste a webhook URL into a file that gets committed; the repository is public.
