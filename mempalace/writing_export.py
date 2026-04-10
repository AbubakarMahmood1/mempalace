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
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import yaml

from .normalize import normalize

DEFAULT_CODEX_HOME = Path(os.path.expanduser("~/.codex"))
DEFAULT_STAGING_ROOT = Path(os.path.expanduser("~/.mempalace/staging"))
DEFAULT_PALACE_ROOT = Path(os.path.expanduser("~/.mempalace/palaces"))
DEFAULT_WRITING_CONFIG_FILENAMES = ("writing-sidecar.yaml", "writing-sidecar.yml")
DEFAULT_RUNTIME_DIRNAME = ".mempalace-sidecar-runtime"
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
ROOM_DESCRIPTIONS = {
    "chat_process": "Normalized AI conversations and process chatter tied to this project.",
    "brainstorms": "Idea dumps, alternatives, and exploratory notes.",
    "audits": "Review passes, criticism, and structured analysis.",
    "discarded_paths": "Cut scenes, abandoned branches, and paths not chosen.",
    "research": "Reference material and research notes safe to archive.",
    "archived_notes": "Archived chapter notes and historical planning material.",
}


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
    return DEFAULT_STAGING_ROOT / _project_slug(project)


def default_palace_dir(project: str) -> Path:
    """Default palace directory for a writing sidecar."""
    return DEFAULT_PALACE_ROOT / f"{_project_slug(project)}_writing_sidecar"


def default_runtime_dir(vault_root: Path, project: str) -> Path:
    """Default runtime/cache directory for sidecar mining and search."""
    return vault_root / DEFAULT_RUNTIME_DIRNAME / _project_slug(project)


def export_writing_corpus(
    vault_dir: str,
    project: str,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    mine_after_export: bool = False,
    palace_path: str = None,
    runtime_root: str = None,
    refresh_palace: bool = False,
    dry_run: bool = False,
) -> dict:
    """Export a curated writing-process corpus into fixed sidecar rooms."""
    project_root = resolve_project_root(vault_dir, project)
    vault_root = resolve_vault_root(vault_dir, project_root)
    output_root = Path(out_dir).expanduser().resolve() if out_dir else default_output_dir(project)
    codex_root = Path(codex_home).expanduser().resolve() if codex_home else DEFAULT_CODEX_HOME
    sidecar_runtime_root = (
        Path(runtime_root).expanduser().resolve()
        if runtime_root
        else default_runtime_dir(vault_root, project).resolve()
    )
    writing_config, loaded_config_path = _load_writing_export_config(project_root, config_path)
    config_base_dir = loaded_config_path.parent if loaded_config_path else project_root
    project_terms = _build_project_terms(
        project,
        project_root,
        writing_config.get("chat_project_terms", []),
    )
    excluded_chat_terms = _build_term_list(writing_config.get("chat_exclude_terms", []))
    brainstorm_inputs = _merge_opt_in_paths(
        config_base_dir,
        writing_config.get("brainstorms", []),
        brainstorm_paths or [],
    )
    audit_inputs = _merge_opt_in_paths(
        config_base_dir,
        writing_config.get("audits", []),
        audit_paths or [],
    )
    discarded_inputs = _merge_opt_in_paths(
        config_base_dir,
        writing_config.get("discarded_paths", []),
        discarded_paths or [],
    )

    summary = {
        "project_root": str(project_root),
        "vault_root": str(vault_root),
        "output_root": str(output_root),
        "rooms": {room: 0 for room in FIXED_ROOMS},
        "skipped_live_files": [],
        "skipped_missing_paths": [],
        "loaded_config_path": str(loaded_config_path) if loaded_config_path else None,
        "generated_config_path": str(output_root / "mempalace.yaml"),
        "palace_path": None,
        "runtime_root": str(sidecar_runtime_root),
        "mine_skipped": None,
    }

    if not dry_run:
        _ensure_dir(output_root)
        _write_export_gitignore(output_root)
        _write_sidecar_config(output_root, project)
        for room in FIXED_ROOMS:
            room_dir = output_root / room
            if room_dir.exists():
                shutil.rmtree(room_dir)
            _ensure_dir(room_dir)

    _export_codex_chat_process(
        codex_root=codex_root,
        project_root=project_root,
        vault_root=vault_root,
        project_terms=project_terms,
        excluded_chat_terms=excluded_chat_terms,
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
        raw_paths=brainstorm_inputs,
        room_name="brainstorms",
        output_root=output_root,
        project_root=project_root,
        summary=summary,
        dry_run=dry_run,
    )
    _copy_opt_in_paths(
        raw_paths=audit_inputs,
        room_name="audits",
        output_root=output_root,
        project_root=project_root,
        summary=summary,
        dry_run=dry_run,
    )
    _copy_opt_in_paths(
        raw_paths=discarded_inputs,
        room_name="discarded_paths",
        output_root=output_root,
        project_root=project_root,
        summary=summary,
        dry_run=dry_run,
    )

    if mine_after_export:
        if dry_run:
            summary["mine_skipped"] = "dry_run"
        else:
            target_palace = (
                Path(palace_path).expanduser().resolve() if palace_path else default_palace_dir(project)
            )
            _mine_exported_sidecar(
                output_root=output_root,
                project=project,
                palace_path=target_palace,
                runtime_root=sidecar_runtime_root,
                refresh_palace=refresh_palace,
            )
            summary["palace_path"] = str(target_palace)

    return summary


def print_export_summary(summary: dict, dry_run: bool = False):
    """Render a compact export summary."""
    print(f"\n{'=' * 55}")
    print("  MemPalace Writing Export")
    print(f"{'=' * 55}")
    print(f"  Project: {summary['project_root']}")
    print(f"  Vault:   {summary['vault_root']}")
    print(f"  Output:  {summary['output_root']}")
    if dry_run:
        print("  DRY RUN — nothing was written")
    if summary.get("loaded_config_path"):
        print(f"  Config:  {summary['loaded_config_path']}")
    elif summary.get("generated_config_path") and not dry_run:
        print(f"  Config:  {summary['generated_config_path']}")
    if summary.get("palace_path"):
        print(f"  Palace:  {summary['palace_path']}")
    if summary.get("runtime_root") and (summary.get("palace_path") or summary.get("mine_skipped")):
        print(f"  Runtime: {summary['runtime_root']}")
    if summary.get("mine_skipped") == "dry_run":
        print("  Mine:    skipped because --dry-run was used")
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
    vault_root: Path,
    project_terms: list,
    excluded_chat_terms: list,
    output_root: Path,
    summary: dict,
    dry_run: bool,
):
    sessions_root = codex_root / "sessions"
    if not sessions_root.exists():
        return

    room_dir = output_root / "chat_process"
    for rollout_path in sorted(sessions_root.rglob("*.jsonl")):
        if not _rollout_matches_project(
            rollout_path,
            project_root=project_root,
            vault_root=vault_root,
            project_terms=project_terms,
            excluded_chat_terms=excluded_chat_terms,
        ):
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


def _rollout_matches_project(
    rollout_path: Path,
    project_root: Path,
    vault_root: Path,
    project_terms: list,
    excluded_chat_terms: list,
) -> bool:
    project_norm = _normalized_path(project_root)
    vault_norm = _normalized_path(vault_root)
    session_within_vault = False
    mentions_project = False
    mentions_excluded = False
    try:
        with open(rollout_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = entry.get("payload", {})
                if not isinstance(payload, dict):
                    continue

                session_cwd = payload.get("cwd")
                if isinstance(session_cwd, str) and session_cwd.strip():
                    session_norm = _normalized_path(Path(session_cwd))
                    if _path_matches_root(session_norm, project_norm):
                        return True
                    if _path_matches_root(session_norm, vault_norm):
                        session_within_vault = True

                if session_within_vault:
                    if _payload_mentions_project(
                        payload,
                        project_root=project_root,
                        project_terms=project_terms,
                    ):
                        mentions_project = True
                    if excluded_chat_terms and _payload_mentions_terms(payload, excluded_chat_terms):
                        mentions_excluded = True
    except OSError:
        return False
    return session_within_vault and mentions_project and not mentions_excluded


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

        source_label = _safe_name(source_path.name)
        export_root = room_dir if source_label == room_name else room_dir / source_label
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


def _merge_opt_in_paths(base_dir: Path, config_paths: list, cli_paths: list) -> list:
    merged = []
    seen = set()
    for raw_path in list(config_paths or []) + list(cli_paths or []):
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).resolve()
        else:
            candidate = candidate.resolve()
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            merged.append(key)
    return merged


def _load_writing_export_config(project_root: Path, config_path: str = None):
    candidate = None
    if config_path:
        candidate = Path(config_path).expanduser().resolve()
    else:
        for filename in DEFAULT_WRITING_CONFIG_FILENAMES:
            auto_candidate = project_root / filename
            if auto_candidate.exists():
                candidate = auto_candidate.resolve()
                break

    if candidate is None:
        return {}, None
    if not candidate.exists():
        raise FileNotFoundError(f"Writing sidecar config not found: {candidate}")

    with open(candidate, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("Writing sidecar config must be a mapping")
    return data, candidate


def resolve_vault_root(vault_dir: str, project_root: Path) -> Path:
    """Infer the vault root even when the caller passes a direct project path."""
    base_path = Path(vault_dir).expanduser().resolve()
    if base_path == project_root:
        return project_root.parent
    return base_path


def _project_slug(project: str) -> str:
    return _safe_name(project.lower().replace(" ", "_").replace("-", "_"))


def _project_wing(project: str) -> str:
    return f"{_project_slug(project)}_writing_sidecar"


def _build_project_terms(project: str, project_root: Path, extra_terms: list) -> list:
    terms = {
        project,
        project_root.name,
        project_root.name.replace("-", " "),
        project_root.name.replace("_", " "),
        project_root.name.replace("-", "_"),
    }
    for term in extra_terms or []:
        if isinstance(term, str) and term.strip():
            terms.add(term.strip())
    return sorted(terms)


def _build_term_list(extra_terms: list) -> list:
    terms = set()
    for term in extra_terms or []:
        if isinstance(term, str) and term.strip():
            terms.add(term.strip())
    return sorted(terms)


def _mine_exported_sidecar(
    output_root: Path,
    project: str,
    palace_path: Path,
    runtime_root: Path,
    refresh_palace: bool = False,
):
    from .miner import mine

    output_root = output_root.resolve()
    palace_path = palace_path.expanduser().resolve()
    runtime_root = runtime_root.expanduser().resolve()

    try:
        palace_path.relative_to(output_root)
    except ValueError:
        pass
    else:
        raise ValueError("Palace path must be outside the exported sidecar directory")

    try:
        runtime_root.relative_to(output_root)
    except ValueError:
        pass
    else:
        raise ValueError("Runtime root must be outside the exported sidecar directory")

    if refresh_palace and palace_path.exists():
        shutil.rmtree(palace_path)

    with _sidecar_runtime_environment(runtime_root):
        _ensure_dir(palace_path)
        mine(
            project_dir=str(output_root),
            palace_path=str(palace_path),
            wing_override=_project_wing(project),
            agent="writing_export",
            limit=0,
            dry_run=False,
            respect_gitignore=True,
            include_ignored=[],
        )


def _payload_mentions_project(payload: dict, project_root: Path, project_terms: list) -> bool:
    project_norm = _normalized_path(project_root)
    project_texts = {
        project_norm,
        project_norm.replace("\\", "/"),
        *[_normalize_text(term) for term in project_terms],
    }

    for value in _iter_payload_strings(payload):
        normalized = _normalize_text(value)
        if not normalized:
            continue
        if project_norm in normalized or project_norm.replace("\\", "/") in normalized:
            return True
        if any(term and term in normalized for term in project_texts):
            return True

        candidate_paths = re.findall(r"[A-Za-z]:[\\/][^\"'\r\n]+", value)
        for candidate in candidate_paths:
            if _path_matches_root(_normalized_path(Path(candidate)), project_norm):
                return True

    return False


def _payload_mentions_terms(payload: dict, terms: list) -> bool:
    normalized_terms = [_normalize_text(term) for term in terms if isinstance(term, str) and term.strip()]
    if not normalized_terms:
        return False

    for value in _iter_payload_strings(payload):
        if _looks_like_path(value):
            continue
        normalized = _normalize_text(value)
        if not normalized:
            continue
        if any(term and term in normalized for term in normalized_terms):
            return True

    return False


def _iter_payload_strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_payload_strings(item)
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _iter_payload_strings(nested)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9:/\\._-]+", " ", value.lower()).strip()


def _path_matches_root(candidate_norm: str, root_norm: str) -> bool:
    return candidate_norm == root_norm or candidate_norm.startswith(root_norm + os.sep)


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


def _looks_like_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("\\\\"))


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


def _write_sidecar_config(output_root: Path, project: str):
    config_path = output_root / "mempalace.yaml"
    config = {
        "wing": _project_wing(project),
        "rooms": [
            {
                "name": room,
                "description": ROOM_DESCRIPTIONS[room],
                "keywords": [room, room.replace("_", " ")],
            }
            for room in FIXED_ROOMS
        ],
    }
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)


@contextmanager
def _sidecar_runtime_environment(runtime_root: Path):
    runtime_root = runtime_root.expanduser().resolve()
    home_root = runtime_root / "home"
    cache_root = runtime_root / "cache"
    tmp_root = runtime_root / "tmp"
    chroma_cache_root = cache_root / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"

    for path in (runtime_root, home_root, cache_root, tmp_root, chroma_cache_root):
        _ensure_dir(path)

    env_updates = {
        "HOME": str(home_root),
        "USERPROFILE": str(home_root),
        "HOMEDRIVE": home_root.drive or "C:",
        "HOMEPATH": str(home_root).replace(home_root.drive or "C:", "", 1) or "\\",
        "TMP": str(tmp_root),
        "TEMP": str(tmp_root),
        "TMPDIR": str(tmp_root),
        "XDG_CACHE_HOME": str(cache_root),
        "HF_HOME": str(cache_root / "huggingface"),
        "TRANSFORMERS_CACHE": str(cache_root / "huggingface" / "transformers"),
        "CHROMA_CACHE_DIR": str(cache_root / "chroma"),
    }
    previous_env = {key: os.environ.get(key) for key in env_updates}
    previous_tempdir = tempfile.tempdir
    previous_download_path = None

    try:
        for key, value in env_updates.items():
            os.environ[key] = value
        tempfile.tempdir = str(tmp_root)
        try:
            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
        except Exception:
            pass
        try:
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

            previous_download_path = ONNXMiniLM_L6_V2.DOWNLOAD_PATH
            ONNXMiniLM_L6_V2.DOWNLOAD_PATH = str(chroma_cache_root)
        except Exception:
            pass
        yield runtime_root
    finally:
        try:
            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
        except Exception:
            pass
        try:
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

            if previous_download_path is not None:
                ONNXMiniLM_L6_V2.DOWNLOAD_PATH = previous_download_path
        except Exception:
            pass
        tempfile.tempdir = previous_tempdir
        for key, old_value in previous_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
