# Writing Sidecar Workflow

Legacy note: the standalone package at `AbubakarMahmood1/writing-sidecar` is now the canonical home for this workflow. This document remains here as branch-history/reference material for `private/writing-cdlc-sidecar`.

This branch adds a private writing-sidecar layer for CDLC projects. The sidecar is
process memory only. It stays separate from the live story bible and active chapter files.

## What It Does

The sidecar exporter builds a derived corpus with fixed rooms:

- `chat_process`
- `brainstorms`
- `audits`
- `discarded_paths`
- `research`
- `archived_notes`

The sidecar flow:

- exports only sidecar-safe material into a derived corpus
- skips live source-of-truth files like `AGENTS.md`, current notes, and active `Chapter *.txt`
- normalizes matching Codex rollout JSONL into `chat_process`
- writes a sidecar `mempalace.yaml` and `.writing-sidecar-state.json`
- tracks staleness from config changes, input changes, missing inputs, and newly eligible inputs
- uses a vault-local runtime cache for Chroma and the ONNX embedder during mine/search

## Default Paths

By default, a project sidecar lives under the vault:

```text
<vault>\.sidecars\<project_slug>\
<vault>\.palaces\<project_slug>\
<vault>\.mempalace-sidecar-runtime\<project_slug>\
```

For `Witcher-DC`, that means:

```text
<vault>\.sidecars\witcher_dc\
<vault>\.palaces\witcher_dc\
<vault>\.mempalace-sidecar-runtime\witcher_dc\
```

## Commands

Scaffold the sidecar layer for a project:

```powershell
mempalace writing-init C:\Users\theab\Documents\writing-vault --project Witcher-DC
```

Check whether the sidecar is clean or stale:

```powershell
mempalace writing-status C:\Users\theab\Documents\writing-vault --project Witcher-DC
```

Export only:

```powershell
mempalace writing-export C:\Users\theab\Documents\writing-vault --project Witcher-DC
```

Export and mine:

```powershell
mempalace writing-export C:\Users\theab\Documents\writing-vault --project Witcher-DC --mine
```

Search with planning intent:

```powershell
mempalace writing-search C:\Users\theab\Documents\writing-vault `
  --project Witcher-DC `
  --query "physician testing sphere"
```

One-shot sync and search:

```powershell
mempalace writing-sync C:\Users\theab\Documents\writing-vault `
  --project Witcher-DC `
  --query "Arthur sponsorship" `
  --mode history
```

## Sync Policy

`writing-sync` and `writing-search` both support:

- `--sync if-needed` — default; rebuild only when stale
- `--sync always` — force export + mine before search
- `--sync never` — do not rebuild; search the existing palace and warn if stale

`--refresh-palace` still forces a full palace rebuild when a sync happens.

## Intent Modes

`writing-search` uses fixed room priority by mode:

- `planning`: `brainstorms`, `discarded_paths`, `audits`, `chat_process`
- `audit`: `audits`, `discarded_paths`, `chat_process`, `archived_notes`
- `history`: `chat_process`, `audits`, `brainstorms`, `discarded_paths`
- `research`: `research`, `archived_notes`

Results are merged by room priority first, then whatever each room search returns. The
sidecar is evidence, not canon. If a sidecar hit conflicts with live story-bible docs,
the live docs win.

## State File

Every successful export writes:

```text
<sidecar output>\.writing-sidecar-state.json
```

It records:

- project, vault, output, palace, and runtime paths
- config fingerprint
- last sync timestamp
- room counts
- tracked inputs with size, mtime, and SHA-256

`writing-status` compares the current eligible inputs to that manifest and reports:

- `manifest_missing`
- `palace_missing`
- `config_changed`
- `input_changed`
- `input_missing`
- `input_added`

## Config

If `writing-sidecar.yaml` exists in the project root, it is loaded automatically.
You can also pass it explicitly with `--config`.

Example:

```yaml
chat_project_terms:
  - League of Demons
  - Arthur sponsorship

chat_exclude_terms:
  - mempalace
  - writing-sidecar

brainstorms:
  - logs/brainstorms

audits:
  - logs/audits

discarded_paths:
  - logs/discarded_paths
```

Relative paths are resolved from the config file's directory.

## Chat Matching

Codex rollouts are included when:

- the session `cwd` is the project directory or a child path
- or the session starts at the vault root and the rollout content contains project evidence

Project evidence can come from:

- the project name
- project-relative path mentions
- extra `chat_project_terms` from `writing-sidecar.yaml`

Vault-root sessions can be excluded with `chat_exclude_terms` when they are really
tooling/admin conversations.

## Scaffold Output

`writing-init` creates, without overwriting by default:

- `writing-sidecar.yaml`
- `logs/README.md`
- `logs/audits/`
- `logs/brainstorms/`
- `logs/discarded_paths/`
- `logs/templates/audit_snapshot.md`
- `logs/templates/chapter_handoff.md`
- `logs/templates/discarded_path.md`

Use `--force` only when you want to replace the scaffold files.

## Notes

- Keep the sidecar palace separate from the live project files.
- The sidecar is for archival/process memory, not live canon.
- `writing-init` does not edit the vault root `.gitignore`; add `.sidecars/`, `.palaces/`, and `.mempalace-sidecar-runtime/` yourself if you want them ignored.
- This branch is legacy/reference only now. New writing-sidecar feature work should land in the standalone `writing-sidecar` repo instead of MemPalace core.
