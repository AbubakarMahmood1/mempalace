import json
import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

from chromadb.api.client import SharedSystemClient

from mempalace.writing_export import (
    _ensure_dir,
    default_runtime_dir,
    export_writing_corpus,
    resolve_project_root,
)


def write_file(path: Path, content: str):
    _ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def build_codex_rollout(path: Path, cwd: str, user_text: str, assistant_text: str):
    entries = [
        {
            "timestamp": "2026-04-09T13:28:53.003Z",
            "type": "session_meta",
            "payload": {"id": path.stem, "cwd": cwd},
        },
        {
            "timestamp": "2026-04-09T13:28:53.011Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": user_text},
        },
        {
            "timestamp": "2026-04-09T13:28:53.200Z",
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": assistant_text},
        },
        {
            "timestamp": "2026-04-09T13:28:53.300Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "ignored tool output",
            },
        },
    ]
    write_file(path, "\n".join(json.dumps(entry) for entry in entries))


def make_temp_dir() -> Path:
    root = (
        Path(__file__).resolve().parents[1]
        / "test-artifacts-writing-export"
        / f"mempalace-writing-export-{uuid.uuid4().hex[:8]}"
    )
    _ensure_dir(root)
    return root


def cleanup_temp_dir(path: Path):
    SharedSystemClient.clear_system_cache()
    shutil.rmtree(path, ignore_errors=True)


def test_resolve_project_root_accepts_vault_root_or_project_dir():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(project_root)

        assert resolve_project_root(str(vault_root), "Witcher-DC") == project_root.resolve()
        assert resolve_project_root(str(project_root), "Witcher-DC") == project_root.resolve()
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_writing_corpus_curates_rooms_and_skips_live_files():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        codex_home = tmp_path / ".codex"

        write_file(project_root / "AGENTS.md", "live gateway")
        write_file(project_root / "Chapter 1.txt", "active chapter")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "live notes")
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        write_file(project_root / "_story_bible" / "chapters" / "1. Chill.md", "Archived note")

        brainstorm_dir = tmp_path / "extras" / "brainstorms"
        write_file(brainstorm_dir / "angles.md", "Atlantis intake angles")
        write_file(brainstorm_dir / "AGENTS.md", "should be excluded")

        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "09" / "rollout-a.jsonl",
            cwd=str(project_root),
            user_text="Why did Arthur sponsor Ciri?",
            assistant_text="Arthur takes responsibility for her intake.",
        )
        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "09" / "rollout-b.jsonl",
            cwd=str(tmp_path / "other-project"),
            user_text="Ignore me",
            assistant_text="Wrong project",
        )

        summary = export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            codex_home=str(codex_home),
            brainstorm_paths=[str(brainstorm_dir)],
            audit_paths=[str(project_root / "_story_bible" / "05_Current_Notes.md")],
        )

        chat_files = list((output_root / "chat_process").glob("*.txt"))
        assert len(chat_files) == 1
        assert "Arthur takes responsibility" in chat_files[0].read_text(encoding="utf-8")

        assert (output_root / ".gitignore").read_text(encoding="utf-8") == "entities.json\nmempalace.yaml\n"
        config_text = (output_root / "mempalace.yaml").read_text(encoding="utf-8")
        assert "wing: witcher_dc_writing_sidecar" in config_text
        assert (output_root / "research" / "dc.md").read_text(encoding="utf-8") == "Apokolips research"
        assert (output_root / "archived_notes" / "1. Chill.md").read_text(encoding="utf-8") == "Archived note"
        assert (output_root / "brainstorms" / "angles.md").exists()
        assert not (output_root / "brainstorms" / "brainstorms" / "angles.md").exists()
        assert not any(path.name == "AGENTS.md" for path in output_root.rglob("AGENTS.md"))
        assert not any(path.name == "Chapter 1.txt" for path in output_root.rglob("Chapter 1.txt"))
        assert summary["rooms"]["chat_process"] == 1
        assert summary["rooms"]["research"] == 1
        assert summary["rooms"]["archived_notes"] == 1
        assert summary["rooms"]["brainstorms"] == 1
        assert summary["rooms"]["audits"] == 0
        assert summary["runtime_root"] == str(default_runtime_dir(vault_root.resolve(), "Witcher-DC"))
        assert str(project_root / "_story_bible" / "05_Current_Notes.md") in summary["skipped_live_files"]
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_writing_corpus_matches_vault_root_rollouts_and_config_paths():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        codex_home = tmp_path / ".codex"
        config_path = project_root / "writing-sidecar.yaml"

        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        write_file(tmp_path / "extras" / "audits" / "chapter-1.md", "Arthur sponsorship audit")
        write_file(
            config_path,
            "\n".join(
                [
                    "chat_project_terms:",
                    "  - Arthur sponsorship",
                    "audits:",
                    "  - ../../extras/audits",
                ]
            ),
        )

        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "10" / "rollout-a.jsonl",
            cwd=str(vault_root),
            user_text="Arthur sponsorship in Witcher-DC still needs work.",
            assistant_text="Let's review the Atlantis intake consequences.",
        )
        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "10" / "rollout-b.jsonl",
            cwd=str(vault_root),
            user_text="Completely unrelated root-level task.",
            assistant_text="No project evidence here.",
        )

        summary = export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            codex_home=str(codex_home),
        )

        chat_files = list((output_root / "chat_process").glob("*.txt"))
        assert len(chat_files) == 1
        assert "Atlantis intake consequences" in chat_files[0].read_text(encoding="utf-8")
        assert (output_root / "audits" / "chapter-1.md").read_text(encoding="utf-8") == (
            "Arthur sponsorship audit"
        )
        assert summary["loaded_config_path"] == str(config_path.resolve())
        assert summary["rooms"]["audits"] == 1
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_then_mine_sidecar_is_searchable():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"
        codex_home = tmp_path / ".codex"

        write_file(project_root / "_story_bible" / "research" / "atlantis.md", "Atlantis intake politics")
        write_file(project_root / "_story_bible" / "chapters" / "1. Chill.md", "Arthur sponsorship fallout")
        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "10" / "rollout-a.jsonl",
            cwd=str(vault_root),
            user_text="Let's review Witcher-DC Arthur intake fallout.",
            assistant_text="Arthur takes responsibility for Ciri's Atlantis intake.",
        )

        script = textwrap.dedent(
            f"""
            from unittest.mock import patch

            from chromadb.api.client import SharedSystemClient
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

            from mempalace.searcher import search_memories
            from mempalace.writing_export import export_writing_corpus, _project_wing


            def fake_embed(self, input):
                terms = ['arthur', 'ciri', 'atlantis', 'intake', 'witcher', 'dc', 'audit', 'research']
                return [[float(text.lower().count(term)) for term in terms] for text in input]


            with patch.object(ONNXMiniLM_L6_V2, '__call__', fake_embed):
                summary = export_writing_corpus(
                    vault_dir={str(vault_root)!r},
                    project='Witcher-DC',
                    out_dir={str(output_root)!r},
                    codex_home={str(codex_home)!r},
                    mine_after_export=True,
                    palace_path={str(palace_root)!r},
                    runtime_root={str(runtime_root)!r},
                    refresh_palace=True,
                )
                results = search_memories(
                    'Arthur Atlantis intake',
                    {str(palace_root)!r},
                    wing=_project_wing('Witcher-DC'),
                    room='chat_process',
                    n_results=2,
                )

            assert summary['palace_path'] == {str(palace_root.resolve())!r}
            assert summary['runtime_root'] == {str(runtime_root.resolve())!r}
            assert not results.get('error')
            assert results['results']
            assert any('Arthur takes responsibility' in hit['text'] for hit in results['results'])
            SharedSystemClient.clear_system_cache()
            print('ok')
            """
        )

        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert "ok" in completed.stdout
    finally:
        cleanup_temp_dir(tmp_path)


def test_writing_sync_cli_mines_and_searches():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"
        codex_home = tmp_path / ".codex"

        write_file(project_root / "_story_bible" / "research" / "atlantis.md", "Atlantis intake politics")
        write_file(project_root / "_story_bible" / "chapters" / "1. Chill.md", "Arthur sponsorship fallout")
        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "10" / "rollout-a.jsonl",
            cwd=str(vault_root),
            user_text="Let's review Witcher-DC Arthur intake fallout.",
            assistant_text="Arthur takes responsibility for Ciri's Atlantis intake.",
        )

        script = textwrap.dedent(
            f"""
            from unittest.mock import patch
            import contextlib
            import io
            import sys

            from chromadb.api.client import SharedSystemClient
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

            from mempalace.cli import main


            def fake_embed(self, input):
                terms = ['arthur', 'ciri', 'atlantis', 'intake', 'witcher', 'dc', 'audit', 'research']
                return [[float(text.lower().count(term)) for term in terms] for text in input]


            with patch.object(ONNXMiniLM_L6_V2, '__call__', fake_embed):
                sys.argv = [
                    'mempalace',
                    'writing-sync',
                    {str(vault_root)!r},
                    '--project',
                    'Witcher-DC',
                    '--out',
                    {str(output_root)!r},
                    '--codex-home',
                    {str(codex_home)!r},
                    '--sidecar-palace',
                    {str(palace_root)!r},
                    '--runtime-root',
                    {str(runtime_root)!r},
                    '--refresh-palace',
                    '--query',
                    'Arthur sponsorship',
                    '--room',
                    'chat_process',
                    '--results',
                    '2',
                ]
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    main()
                output = buf.getvalue()

            assert 'MemPalace Writing Export' in output
            assert 'Results for: "Arthur sponsorship"' in output
            assert 'Arthur takes responsibility for Ciri' in output
            assert {str(palace_root.resolve())!r} in output
            assert {str(runtime_root.resolve())!r} in output
            SharedSystemClient.clear_system_cache()
            print('ok')
            """
        )

        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert "ok" in completed.stdout
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_writing_corpus_dry_run_counts_without_writing():
    tmp_path = make_temp_dir()
    try:
        project_root = tmp_path / "Witcher-DC"
        output_root = tmp_path / "sidecar"

        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        write_file(project_root / "_story_bible" / "chapters" / "1. Chill.md", "Archived note")

        summary = export_writing_corpus(
            vault_dir=str(project_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            mine_after_export=True,
            dry_run=True,
        )

        assert summary["rooms"]["research"] == 1
        assert summary["rooms"]["archived_notes"] == 1
        assert summary["mine_skipped"] == "dry_run"
        assert summary["runtime_root"] == str(default_runtime_dir(tmp_path.resolve(), "Witcher-DC"))
        assert not output_root.exists()
    finally:
        cleanup_temp_dir(tmp_path)
