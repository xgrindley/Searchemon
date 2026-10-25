# Releases and test builds

Repository: https://github.com/xgrindley/Searchemon

## Branches

| Branch | Purpose | Who changes it |
|---|---|---|
| `main` | The stable release. Only changes when you say a build is stable | Promoted from `test` on your word |
| `test` | The current test build. Day-to-day work lands here | Every change |
| `test/<name>` | A risky or big piece of work kept apart (for example `test/ui-redesign`) | Merged into `test` when it works |

`main` is never edited directly and never receives untested work.

## Version numbers

- **Stable releases count up whole numbers:** v1.0, v2.0, v3.0. Each is a tag on `main`.
- **Test builds count up from the release they follow:** after v1.0 come v1.1, v1.2, v1.3. After v2.0 come v2.1, v2.2.
- Before the first stable release, test builds are v0.1, v0.2, v0.3.
- The `VERSION` file holds the number. Each tagged test build is marked as a pre-release on GitHub.

## Promoting a build to stable

1. You tell Claude "v1.4 is stable".
2. `test` is merged into `main`, the version becomes the next whole number (v2.0), and `main` is tagged `v2.0`.
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
