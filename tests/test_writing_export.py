import json
import shutil
import tempfile
import uuid
from pathlib import Path

from mempalace.writing_export import _ensure_dir, export_writing_corpus, resolve_project_root


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
    root = Path(tempfile.gettempdir()) / f"mempalace-writing-export-{uuid.uuid4().hex[:8]}"
    _ensure_dir(root)
    return root


def test_resolve_project_root_accepts_vault_root_or_project_dir():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(project_root)

        assert resolve_project_root(str(vault_root), "Witcher-DC") == project_root.resolve()
        assert resolve_project_root(str(project_root), "Witcher-DC") == project_root.resolve()
    finally:
        shutil.rmtree(tmp_path)


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
        assert (output_root / "research" / "dc.md").read_text(encoding="utf-8") == "Apokolips research"
        assert (output_root / "archived_notes" / "1. Chill.md").read_text(encoding="utf-8") == "Archived note"
        assert (output_root / "brainstorms" / "brainstorms" / "angles.md").exists()
        assert not (output_root / "brainstorms" / "brainstorms" / "AGENTS.md").exists()
        assert not any(path.name == "AGENTS.md" for path in output_root.rglob("AGENTS.md"))
        assert not any(path.name == "Chapter 1.txt" for path in output_root.rglob("Chapter 1.txt"))
        assert summary["rooms"]["chat_process"] == 1
        assert summary["rooms"]["research"] == 1
        assert summary["rooms"]["archived_notes"] == 1
        assert summary["rooms"]["brainstorms"] == 1
        assert summary["rooms"]["audits"] == 0
        assert str(project_root / "_story_bible" / "05_Current_Notes.md") in summary["skipped_live_files"]
    finally:
        shutil.rmtree(tmp_path)


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
            dry_run=True,
        )

        assert summary["rooms"]["research"] == 1
        assert summary["rooms"]["archived_notes"] == 1
        assert not output_root.exists()
    finally:
        shutil.rmtree(tmp_path)
