# Writing Sidecar Workflow

This branch adds a private workflow for turning curated writing-process material into a
derived MemPalace corpus without mining the live `writing-vault` project directly.

## What It Does

`mempalace writing-export` builds a staging corpus with fixed rooms:

- `chat_process`
- `brainstorms`
- `audits`
- `discarded_paths`
- `research`
- `archived_notes`

The exporter:

- copies archived and research material into a separate sidecar directory
- skips live source-of-truth files like `AGENTS.md`, current notes, and active `Chapter *.txt`
- normalizes matching Codex rollout JSONL into `chat_process`
- writes a sidecar `mempalace.yaml` so the exported corpus is mineable immediately

## Basic Usage

Export only:

```powershell
mempalace writing-export C:\Users\theab\Documents\writing-vault --project Witcher-DC
```

Export and mine into a dedicated sidecar palace:

```powershell
mempalace writing-export C:\Users\theab\Documents\writing-vault --project Witcher-DC --mine
```

One-shot sync, mine, and search:

```powershell
mempalace writing-sync C:\Users\theab\Documents\writing-vault `
  --project Witcher-DC `
  --query "Arthur sponsorship" `
  --room chat_process
```

Export, mine, and rebuild the target palace from scratch:

```powershell
mempalace writing-export C:\Users\theab\Documents\writing-vault --project Witcher-DC --mine --refresh-palace
```

Use explicit output and palace paths:

```powershell
mempalace writing-export C:\Users\theab\Documents\writing-vault `
  --project Witcher-DC `
  --out C:\Users\theab\Documents\writing-vault\.sidecars\witcher-dc `
  --mine `
  --sidecar-palace C:\Users\theab\Documents\writing-vault\.palaces\witcher-dc
```

## Optional Config

If `writing-sidecar.yaml` exists in the project root, it is loaded automatically.
You can also pass it explicitly with `--config`.

Example:

```yaml
chat_project_terms:
  - Arthur sponsorship
  - Atlantis intake

brainstorms:
  - ../extras/brainstorms

audits:
  - ../extras/audits

discarded_paths:
  - ../extras/discarded
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

This is meant to catch real `writing-vault` root sessions without blindly attaching every
vault-level chat to every project sidecar.

## Search Workflow

When you use `--mine`, the default wing name is:

```text
<project_slug>_writing_sidecar
```

For `Witcher-DC`, that means:

```text
witcher_dc_writing_sidecar
```

Example search:

```powershell
mempalace search "Arthur sponsorship" --wing witcher_dc_writing_sidecar --room chat_process
```

`writing-sync` runs that flow for you:

- exports the sidecar corpus
- mines it into the project sidecar palace
- runs an optional search against the `witcher_dc_writing_sidecar` wing

## Notes

- The sidecar palace should stay separate from your live project files.
- `--refresh-palace` is useful when you want exact sync and do not want stale drawers from
  files that were removed from the exported corpus.
- This branch is intentionally private and writing-specific. It is not designed for upstreaming
  as-is.
