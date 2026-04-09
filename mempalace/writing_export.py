#!/usr/bin/env python3
"""
writing_export.py — Build a writing-process sidecar corpus outside the live project.

This command exports selected process memory into a staging directory that can be
initialized and mined with normal MemPalace commands. It does not mutate the live
story bible or active chapter files.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .normalize import normalize

DEFAULT_CODEX_HOME = Path(os.path.expanduser("~/.codex"))
DEFAULT_STAGING_ROOT = Path(os.path.expanduser("~/.mempalace/staging"))
FIXED_ROOMS = (
    "chat_process",
    "brainstorms",
    "audits",
    "discarded_paths",
    "research",
    "archived_notes",
)
LIVE_GATEWAY_FILES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}
LIVE_NOTES_FILES = {"05_Current_Notes.md", "05_Current_Chapter_Notes.md"}


def resolve_project_root(vault_dir: str, project: str) -> Path:
    """Resolve a project path from either a vault root or a direct project path."""
    base_path = Path(vault_dir).expanduser().resolve()
    if not base_path.exists():
        raise FileNotFoundError(f"Vault path not found: {base_path}")

    direct_match = base_path.name.lower() == project.lower()
    candidate = base_path / project

    if direct_match and base_path.is_dir():
        return base_path
    if candidate.is_dir():
        return candidate.resolve()

    raise FileNotFoundError(
        f"Could not resolve project '{project}' from {base_path}. "
        "Pass the vault root or the project directory itself."
    )


def default_output_dir(project: str) -> Path:
    """Default staging directory for writing sidecars."""
    slug = _safe_name(project.lower().replace(" ", "_").replace("-", "_"))
    return DEFAULT_STAGING_ROOT / slug


def export_writing_corpus(
    vault_dir: str,
    project: str,
    out_dir: str = None,
    codex_home: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    dry_run: bool = False,
) -> dict:
    """Export a curated writing-process corpus into fixed sidecar rooms."""
    project_root = resolve_project_root(vault_dir, project)
    output_root = Path(out_dir).expanduser().resolve() if out_dir else default_output_dir(project)
    codex_root = Path(codex_home).expanduser().resolve() if codex_home else DEFAULT_CODEX_HOME

    summary = {
        "project_root": str(project_root),
        "output_root": str(output_root),
        "rooms": {room: 0 for room in FIXED_ROOMS},
        "skipped_live_files": [],
        "skipped_missing_paths": [],
    }

    if not dry_run:
        _ensure_dir(output_root)
        _write_export_gitignore(output_root)
        for room in FIXED_ROOMS:
            room_dir = output_root / room
            if room_dir.exists():
                shutil.rmtree(room_dir)
            _ensure_dir(room_dir)

    _export_codex_chat_process(
        codex_root=codex_root,
        project_root=project_root,
        output_root=output_root,
        summary=summary,
        dry_run=dry_run,
    )
    _copy_tree_if_present(
        source_dir=project_root / "_story_bible" / "research",
        room_name="research",
        output_root=output_root,
        project_root=project_root,
        summary=summary,
        dry_run=dry_run,
    )
    _copy_tree_if_present(
        source_dir=project_root / "_story_bible" / "chapters",
        room_name="archived_notes",
        output_root=output_root,
        project_root=project_root,
        summary=summary,
        dry_run=dry_run,
    )

    _copy_opt_in_paths(
        raw_paths=brainstorm_paths or [],
        room_name="brainstorms",
        output_root=output_root,
        project_root=project_root,
        summary=summary,
        dry_run=dry_run,
    )
    _copy_opt_in_paths(
        raw_paths=audit_paths or [],
        room_name="audits",
        output_root=output_root,
        project_root=project_root,
        summary=summary,
        dry_run=dry_run,
    )
    _copy_opt_in_paths(
        raw_paths=discarded_paths or [],
        room_name="discarded_paths",
        output_root=output_root,
        project_root=project_root,
        summary=summary,
        dry_run=dry_run,
    )

    return summary


def print_export_summary(summary: dict, dry_run: bool = False):
    """Render a compact export summary."""
    print(f"\n{'=' * 55}")
    print("  MemPalace Writing Export")
    print(f"{'=' * 55}")
    print(f"  Project: {summary['project_root']}")
    print(f"  Output:  {summary['output_root']}")
    if dry_run:
        print("  DRY RUN — nothing was written")
    print("\n  By room:")
    for room, count in summary["rooms"].items():
        print(f"    {room:20} {count}")
    if summary["skipped_live_files"]:
        print("\n  Skipped live source-of-truth files:")
        for path in summary["skipped_live_files"]:
            print(f"    {path}")
    if summary["skipped_missing_paths"]:
        print("\n  Missing optional paths:")
        for path in summary["skipped_missing_paths"]:
            print(f"    {path}")
    print(f"\n{'=' * 55}\n")


def _export_codex_chat_process(
    codex_root: Path,
    project_root: Path,
    output_root: Path,
    summary: dict,
    dry_run: bool,
):
    sessions_root = codex_root / "sessions"
    if not sessions_root.exists():
        return

    room_dir = output_root / "chat_process"
    for rollout_path in sorted(sessions_root.rglob("*.jsonl")):
        if not _rollout_matches_project(rollout_path, project_root):
            continue
        try:
            transcript = normalize(str(rollout_path))
        except Exception:
            continue
        if not transcript.strip():
            continue

        summary["rooms"]["chat_process"] += 1
        if dry_run:
            continue

        relative = rollout_path.relative_to(sessions_root).with_suffix(".txt")
        filename = _safe_name("__".join(relative.parts))
        target_path = room_dir / filename
        _ensure_dir(target_path.parent)
        target_path.write_text(transcript, encoding="utf-8")


def _rollout_matches_project(rollout_path: Path, project_root: Path) -> bool:
    project_norm = _normalized_path(project_root)
    try:
        with open(rollout_path, "r", encoding="utf-8", errors="replace") as f:
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "session_meta":
                    continue
                payload = entry.get("payload", {})
                if not isinstance(payload, dict):
                    return False
                session_cwd = payload.get("cwd")
                if not session_cwd:
                    return False
                session_norm = _normalized_path(Path(session_cwd))
                return session_norm == project_norm or session_norm.startswith(project_norm + os.sep)
    except OSError:
        return False
    return False


def _copy_tree_if_present(
    source_dir: Path,
    room_name: str,
    output_root: Path,
    project_root: Path,
    summary: dict,
    dry_run: bool,
):
    if not source_dir.exists():
        return

    room_dir = output_root / room_name
    for source_path in sorted(source_dir.rglob("*")):
        if not source_path.is_file():
            continue
        if _should_skip_live_file(source_path, project_root):
            summary["skipped_live_files"].append(str(source_path))
            continue

        summary["rooms"][room_name] += 1
        if dry_run:
            continue

        target_path = room_dir / source_path.relative_to(source_dir)
        _ensure_dir(target_path.parent)
        shutil.copy2(source_path, target_path)


def _copy_opt_in_paths(
    raw_paths: list,
    room_name: str,
    output_root: Path,
    project_root: Path,
    summary: dict,
    dry_run: bool,
):
    room_dir = output_root / room_name
    for raw_path in raw_paths:
        source_path = Path(raw_path).expanduser().resolve()
        if not source_path.exists():
            summary["skipped_missing_paths"].append(str(source_path))
            continue

        if source_path.is_file():
            if _should_skip_live_file(source_path, project_root):
                summary["skipped_live_files"].append(str(source_path))
                continue
            summary["rooms"][room_name] += 1
            if dry_run:
                continue
            target_path = room_dir / _safe_name(source_path.name)
            _ensure_dir(target_path.parent)
            shutil.copy2(source_path, target_path)
            continue

        export_root = room_dir / _safe_name(source_path.name)
        for nested_path in sorted(source_path.rglob("*")):
            if not nested_path.is_file():
                continue
            if _should_skip_live_file(nested_path, project_root):
                summary["skipped_live_files"].append(str(nested_path))
                continue
            summary["rooms"][room_name] += 1
            if dry_run:
                continue
            target_path = export_root / nested_path.relative_to(source_path)
            _ensure_dir(target_path.parent)
            shutil.copy2(nested_path, target_path)


def _should_skip_live_file(path: Path, project_root: Path) -> bool:
    if path.name in LIVE_GATEWAY_FILES:
        return True

    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return False

    if len(relative.parts) == 1 and path.match("Chapter *.txt"):
        return True

    if relative.parts[:1] == ("_story_bible",):
        if len(relative.parts) == 2 and relative.name in LIVE_NOTES_FILES:
            return True
        if len(relative.parts) == 2 and relative.suffix.lower() == ".md":
            return True

    return False


def _normalized_path(path: Path) -> str:
    return str(path.expanduser().resolve()).rstrip("\\/").lower()


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "export"


def _ensure_dir(path: Path):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        if os.name != "nt":
            raise
        literal_path = str(path).replace("'", "''")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"New-Item -ItemType Directory -Path '{literal_path}' -Force | Out-Null",
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def _write_export_gitignore(output_root: Path):
    gitignore_path = output_root / ".gitignore"
    gitignore_path.write_text("entities.json\nmempalace.yaml\n", encoding="utf-8")
