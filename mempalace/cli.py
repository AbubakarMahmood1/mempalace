#!/usr/bin/env python3
"""
MemPalace — Give your AI a memory. No API key required.

Two ways to ingest:
  Projects:      mempalace mine ~/projects/my_app          (code, docs, notes)
  Conversations: mempalace mine ~/chats/ --mode convos     (Claude, ChatGPT, Slack)

Same palace. Same search. Different ingest strategies.

Commands:
    mempalace init <dir>                  Detect rooms from folder structure
    mempalace split <dir>                 Split concatenated mega-files into per-session files
    mempalace mine <dir>                  Mine project files (default)
    mempalace mine <dir> --mode convos    Mine conversation exports
    mempalace writing-init <dir>          Scaffold sidecar files for a writing project
    mempalace writing-export <dir>        Build a writing-process sidecar corpus
    mempalace writing-status <dir>        Show whether a writing sidecar is current or stale
    mempalace writing-search <dir>        Query a writing sidecar by intent
    mempalace writing-export <dir> --mine Export and mine into a dedicated sidecar palace
    mempalace writing-sync <dir>          Export, mine, and optionally search a writing sidecar
    mempalace search "query"              Find anything, exact words
    mempalace mcp                         Show MCP setup command
    mempalace wake-up                     Show L0 + L1 wake-up context
    mempalace wake-up --wing my_app       Wake-up for a specific project
    mempalace status                      Show what's been filed

Examples:
    mempalace init ~/projects/my_app
    mempalace mine ~/projects/my_app
    mempalace mine ~/chats/claude-sessions --mode convos
    mempalace writing-init ~/writing-vault --project Witcher-DC
    mempalace writing-export ~/writing-vault --project Witcher-DC
    mempalace writing-status ~/writing-vault --project Witcher-DC
    mempalace writing-search ~/writing-vault --project Witcher-DC --query "Arthur sponsorship"
    mempalace writing-export ~/writing-vault --project Witcher-DC --mine
    mempalace writing-sync ~/writing-vault --project Witcher-DC --query "Arthur sponsorship"
    mempalace search "why did we switch to GraphQL"
    mempalace search "pricing discussion" --wing my_app --room costs
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

from .config import MempalaceConfig


def cmd_init(args):
    import json
    from pathlib import Path
    from .entity_detector import scan_for_detection, detect_entities, confirm_entities
    from .room_detector_local import detect_rooms_local

    # Pass 1: auto-detect people and projects from file content
    print(f"\n  Scanning for entities in: {args.dir}")
    files = scan_for_detection(args.dir)
    if files:
        print(f"  Reading {len(files)} files...")
        detected = detect_entities(files)
        total = len(detected["people"]) + len(detected["projects"]) + len(detected["uncertain"])
        if total > 0:
            confirmed = confirm_entities(detected, yes=getattr(args, "yes", False))
            # Save confirmed entities to <project>/entities.json for the miner
            if confirmed["people"] or confirmed["projects"]:
                entities_path = Path(args.dir).expanduser().resolve() / "entities.json"
                with open(entities_path, "w") as f:
                    json.dump(confirmed, f, indent=2)
                print(f"  Entities saved: {entities_path}")
        else:
            print("  No entities detected — proceeding with directory-based rooms.")

    # Pass 2: detect rooms from folder structure
    detect_rooms_local(project_dir=args.dir, yes=getattr(args, "yes", False))
    MempalaceConfig().init()


def cmd_mine(args):
    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    include_ignored = []
    for raw in args.include_ignored or []:
        include_ignored.extend(part.strip() for part in raw.split(",") if part.strip())

    if args.mode == "convos":
        from .convo_miner import mine_convos

        mine_convos(
            convo_dir=args.dir,
            palace_path=palace_path,
            wing=args.wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            extract_mode=args.extract,
        )
    else:
        from .miner import mine

        mine(
            project_dir=args.dir,
            palace_path=palace_path,
            wing_override=args.wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            respect_gitignore=not args.no_gitignore,
            include_ignored=include_ignored,
        )


def cmd_search(args):
    from .searcher import search, SearchError

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    try:
        search(
            query=args.query,
            palace_path=palace_path,
            wing=args.wing,
            room=args.room,
            n_results=args.results,
        )
    except SearchError:
        sys.exit(1)


def cmd_wakeup(args):
    """Show L0 (identity) + L1 (essential story) — the wake-up context."""
    from .layers import MemoryStack

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    stack = MemoryStack(palace_path=palace_path)

    text = stack.wake_up(wing=args.wing)
    tokens = len(text) // 4
    print(f"Wake-up text (~{tokens} tokens):")
    print("=" * 50)
    print(text)


def cmd_split(args):
    """Split concatenated transcript mega-files into per-session files."""
    from .split_mega_files import main as split_main
    import sys

    # Rebuild argv for split_mega_files argparse
    argv = ["--source", args.dir]
    if args.output_dir:
        argv += ["--output-dir", args.output_dir]
    if args.dry_run:
        argv.append("--dry-run")
    if args.min_sessions != 2:
        argv += ["--min-sessions", str(args.min_sessions)]

    old_argv = sys.argv
    sys.argv = ["mempalace split"] + argv
    try:
        split_main()
    finally:
        sys.argv = old_argv


def cmd_status(args):
    from .miner import status

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    status(palace_path=palace_path)


def cmd_writing_export(args):
    from .writing_export import export_writing_corpus, print_export_summary

    summary = export_writing_corpus(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        mine_after_export=args.mine,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
        refresh_palace=args.refresh_palace,
        dry_run=args.dry_run,
    )
    print_export_summary(summary, dry_run=args.dry_run)


def cmd_writing_status(args):
    from .writing_export import get_writing_sidecar_status, print_writing_status

    status = get_writing_sidecar_status(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
    )
    print_writing_status(status)


def cmd_writing_search(args):
    from .writing_export import (
        _project_wing,
        _sidecar_runtime_environment,
        export_writing_corpus,
        get_writing_sidecar_status,
        print_export_summary,
        print_writing_search_results,
        print_writing_status,
        search_writing_sidecar,
    )

    status = get_writing_sidecar_status(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
    )

    should_sync = args.sync == "always" or (args.sync == "if-needed" and status["stale"])
    if should_sync:
        summary = export_writing_corpus(
            vault_dir=args.dir,
            project=args.project,
            out_dir=args.out,
            codex_home=args.codex_home,
            config_path=args.config,
            brainstorm_paths=args.brainstorms,
            audit_paths=args.audits,
            discarded_paths=args.discarded_paths,
            mine_after_export=True,
            palace_path=args.sidecar_palace,
            runtime_root=args.runtime_root,
            refresh_palace=args.refresh_palace,
            dry_run=False,
        )
        print_export_summary(summary, dry_run=False)
        status = get_writing_sidecar_status(
            vault_dir=args.dir,
            project=args.project,
            out_dir=args.out,
            codex_home=args.codex_home,
            config_path=args.config,
            brainstorm_paths=args.brainstorms,
            audit_paths=args.audits,
            discarded_paths=args.discarded_paths,
            palace_path=args.sidecar_palace,
            runtime_root=args.runtime_root,
        )
    else:
        if args.sync == "never" and status["stale"]:
            print("  Warning: sidecar is stale; searching existing palace because --sync never was used.\n")
        else:
            print_writing_status(status)

    palace_path = Path(status["palace_path"])
    if not palace_path.exists():
        print(f"\n  No palace found at {palace_path}")
        print("  Run writing-sync or use --sync always/if-needed to build it first.")
        sys.exit(1)

    with _sidecar_runtime_environment(Path(status["runtime_root"])):
        results = search_writing_sidecar(
            query=args.query,
            palace_path=str(palace_path),
            wing=_project_wing(args.project),
            mode=args.mode,
            n_results=args.results,
        )

    if results.get("error"):
        print(f"\n  Search error: {results['error']}")
        sys.exit(1)
    print_writing_search_results(results)


def cmd_writing_init(args):
    from .writing_export import print_scaffold_summary, scaffold_writing_sidecar

    summary = scaffold_writing_sidecar(
        vault_dir=args.dir,
        project=args.project,
        force=args.force,
    )
    print_scaffold_summary(summary)


def cmd_writing_sync(args):
    from .writing_export import (
        _project_wing,
        _sidecar_runtime_environment,
        export_writing_corpus,
        get_writing_sidecar_status,
        print_export_summary,
        print_writing_search_results,
        print_writing_status,
        search_writing_sidecar,
    )

    status = get_writing_sidecar_status(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
    )

    should_sync = (
        args.refresh_palace
        or args.sync == "always"
        or (args.sync == "if-needed" and status["stale"])
    )
    if should_sync:
        summary = export_writing_corpus(
            vault_dir=args.dir,
            project=args.project,
            out_dir=args.out,
            codex_home=args.codex_home,
            config_path=args.config,
            brainstorm_paths=args.brainstorms,
            audit_paths=args.audits,
            discarded_paths=args.discarded_paths,
            mine_after_export=True,
            palace_path=args.sidecar_palace,
            runtime_root=args.runtime_root,
            refresh_palace=args.refresh_palace,
            dry_run=False,
        )
        print_export_summary(summary, dry_run=False)
        status = get_writing_sidecar_status(
            vault_dir=args.dir,
            project=args.project,
            out_dir=args.out,
            codex_home=args.codex_home,
            config_path=args.config,
            brainstorm_paths=args.brainstorms,
            audit_paths=args.audits,
            discarded_paths=args.discarded_paths,
            palace_path=args.sidecar_palace,
            runtime_root=args.runtime_root,
        )
    else:
        if args.sync == "never" and status["stale"]:
            print("  Warning: sidecar is stale; skipping rebuild because --sync never was used.\n")
        else:
            print("  Sidecar is current; skipping rebuild.\n")
        print_writing_status(status)

    if not args.query:
        return

    palace_path = Path(status["palace_path"])
    if not palace_path.exists():
        print(f"\n  No palace found at {palace_path}")
        print("  Run writing-sync without --sync never, or use --sync always.")
        sys.exit(1)

    with _sidecar_runtime_environment(Path(status["runtime_root"])):
        if args.mode:
            results = search_writing_sidecar(
                query=args.query,
                palace_path=str(palace_path),
                wing=_project_wing(args.project),
                mode=args.mode,
                n_results=args.results,
            )
            if results.get("error"):
                print(f"\n  Search error: {results['error']}")
                sys.exit(1)
            print_writing_search_results(results)
            return

        from .searcher import SearchError, search

        try:
            search(
                query=args.query,
                palace_path=str(palace_path),
                wing=_project_wing(args.project),
                room=args.room,
                n_results=args.results,
            )
        except SearchError:
            sys.exit(1)


def cmd_repair(args):
    """Rebuild palace vector index from SQLite metadata."""
    import chromadb
    import shutil

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    # Try to read existing drawers
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        total = col.count()
        print(f"  Drawers found: {total}")
    except Exception as e:
        print(f"  Error reading palace: {e}")
        print("  Cannot recover — palace may need to be re-mined from source files.")
        return

    if total == 0:
        print("  Nothing to repair.")
        return

    # Extract all drawers in batches
    print("\n  Extracting drawers...")
    batch_size = 5000
    all_ids = []
    all_docs = []
    all_metas = []
    offset = 0
    while offset < total:
        batch = col.get(limit=batch_size, offset=offset, include=["documents", "metadatas"])
        all_ids.extend(batch["ids"])
        all_docs.extend(batch["documents"])
        all_metas.extend(batch["metadatas"])
        offset += batch_size
    print(f"  Extracted {len(all_ids)} drawers")

    # Backup and rebuild
    palace_path = palace_path.rstrip(os.sep)
    backup_path = palace_path + ".backup"
    if os.path.exists(backup_path):
        shutil.rmtree(backup_path)
    print(f"  Backing up to {backup_path}...")
    shutil.copytree(palace_path, backup_path)

    print("  Rebuilding collection...")
    client.delete_collection("mempalace_drawers")
    new_col = client.create_collection("mempalace_drawers")

    filed = 0
    for i in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[i : i + batch_size]
        batch_docs = all_docs[i : i + batch_size]
        batch_metas = all_metas[i : i + batch_size]
        new_col.add(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
        filed += len(batch_ids)
        print(f"  Re-filed {filed}/{len(all_ids)} drawers...")

    print(f"\n  Repair complete. {filed} drawers rebuilt.")
    print(f"  Backup saved at {backup_path}")
    print(f"\n{'=' * 55}\n")


def cmd_hook(args):
    """Run hook logic: reads JSON from stdin, outputs JSON to stdout."""
    from .hooks_cli import run_hook

    run_hook(hook_name=args.hook, harness=args.harness)


def cmd_instructions(args):
    """Output skill instructions to stdout."""
    from .instructions_cli import run_instructions

    run_instructions(name=args.name)


def cmd_mcp(args):
    """Show how to wire MemPalace into MCP-capable hosts."""
    base_server_cmd = "python -m mempalace.mcp_server"

    if args.palace:
        resolved_palace = str(Path(args.palace).expanduser())
        server_cmd = f"{base_server_cmd} --palace {shlex.quote(resolved_palace)}"
    else:
        server_cmd = base_server_cmd

    print("MemPalace MCP quick setup:")
    print(f"  claude mcp add mempalace -- {server_cmd}")
    print("\nRun the server directly:")
    print(f"  {server_cmd}")

    if not args.palace:
        print("\nOptional custom palace:")
        print(f"  claude mcp add mempalace -- {base_server_cmd} --palace /path/to/palace")
        print(f"  {base_server_cmd} --palace /path/to/palace")


def cmd_compress(args):
    """Compress drawers in a wing using AAAK Dialect."""
    import chromadb
    from .dialect import Dialect

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    # Load dialect (with optional entity config)
    config_path = args.config
    if not config_path:
        for candidate in ["entities.json", os.path.join(palace_path, "entities.json")]:
            if os.path.exists(candidate):
                config_path = candidate
                break

    if config_path and os.path.exists(config_path):
        dialect = Dialect.from_config(config_path)
        print(f"  Loaded entity config: {config_path}")
    else:
        dialect = Dialect()

    # Connect to palace
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        sys.exit(1)

    # Query drawers in batches to avoid SQLite variable limit (~999)
    where = {"wing": args.wing} if args.wing else None
    _BATCH = 500
    docs, metas, ids = [], [], []
    offset = 0
    while True:
        try:
            kwargs = {"include": ["documents", "metadatas"], "limit": _BATCH, "offset": offset}
            if where:
                kwargs["where"] = where
            batch = col.get(**kwargs)
        except Exception as e:
            if not docs:
                print(f"\n  Error reading drawers: {e}")
                sys.exit(1)
            break
        batch_docs = batch.get("documents", [])
        if not batch_docs:
            break
        docs.extend(batch_docs)
        metas.extend(batch.get("metadatas", []))
        ids.extend(batch.get("ids", []))
        offset += len(batch_docs)
        if len(batch_docs) < _BATCH:
            break

    if not docs:
        wing_label = f" in wing '{args.wing}'" if args.wing else ""
        print(f"\n  No drawers found{wing_label}.")
        return

    print(
        f"\n  Compressing {len(docs)} drawers"
        + (f" in wing '{args.wing}'" if args.wing else "")
        + "..."
    )
    print()

    total_original = 0
    total_compressed = 0
    compressed_entries = []

    for doc, meta, doc_id in zip(docs, metas, ids):
        compressed = dialect.compress(doc, metadata=meta)
        stats = dialect.compression_stats(doc, compressed)

        total_original += stats["original_chars"]
        total_compressed += stats["compressed_chars"]

        compressed_entries.append((doc_id, compressed, meta, stats))

        if args.dry_run:
            wing_name = meta.get("wing", "?")
            room_name = meta.get("room", "?")
            source = Path(meta.get("source_file", "?")).name
            print(f"  [{wing_name}/{room_name}] {source}")
            print(
                f"    {stats['original_tokens']}t -> {stats['compressed_tokens']}t ({stats['ratio']:.1f}x)"
            )
            print(f"    {compressed}")
            print()

    # Store compressed versions (unless dry-run)
    if not args.dry_run:
        try:
            comp_col = client.get_or_create_collection("mempalace_compressed")
            for doc_id, compressed, meta, stats in compressed_entries:
                comp_meta = dict(meta)
                comp_meta["compression_ratio"] = round(stats["ratio"], 1)
                comp_meta["original_tokens"] = stats["original_tokens"]
                comp_col.upsert(
                    ids=[doc_id],
                    documents=[compressed],
                    metadatas=[comp_meta],
                )
            print(
                f"  Stored {len(compressed_entries)} compressed drawers in 'mempalace_compressed' collection."
            )
        except Exception as e:
            print(f"  Error storing compressed drawers: {e}")
            sys.exit(1)

    # Summary
    ratio = total_original / max(total_compressed, 1)
    orig_tokens = Dialect.count_tokens("x" * total_original)
    comp_tokens = Dialect.count_tokens("x" * total_compressed)
    print(f"  Total: {orig_tokens:,}t -> {comp_tokens:,}t ({ratio:.1f}x compression)")
    if args.dry_run:
        print("  (dry run -- nothing stored)")


def main():
    parser = argparse.ArgumentParser(
        description="MemPalace — Give your AI a memory. No API key required.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--palace",
        default=None,
        help="Where the palace lives (default: from ~/.mempalace/config.json or ~/.mempalace/palace)",
    )

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Detect rooms from your folder structure")
    p_init.add_argument("dir", help="Project directory to set up")
    p_init.add_argument(
        "--yes", action="store_true", help="Auto-accept all detected entities (non-interactive)"
    )

    # mine
    p_mine = sub.add_parser("mine", help="Mine files into the palace")
    p_mine.add_argument("dir", help="Directory to mine")
    p_mine.add_argument(
        "--mode",
        choices=["projects", "convos"],
        default="projects",
        help="Ingest mode: 'projects' for code/docs (default), 'convos' for chat exports",
    )
    p_mine.add_argument("--wing", default=None, help="Wing name (default: directory name)")
    p_mine.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Don't respect .gitignore files when scanning project files",
    )
    p_mine.add_argument(
        "--include-ignored",
        action="append",
        default=[],
        help="Always scan these project-relative paths even if ignored; repeat or pass comma-separated paths",
    )
    p_mine.add_argument(
        "--agent",
        default="mempalace",
        help="Your name — recorded on every drawer (default: mempalace)",
    )
    p_mine.add_argument("--limit", type=int, default=0, help="Max files to process (0 = all)")
    p_mine.add_argument(
        "--dry-run", action="store_true", help="Show what would be filed without filing"
    )
    p_mine.add_argument(
        "--extract",
        choices=["exchange", "general"],
        default="exchange",
        help="Extraction strategy for convos mode: 'exchange' (default) or 'general' (5 memory types)",
    )

    # search
    p_search = sub.add_parser("search", help="Find anything, exact words")
    p_search.add_argument("query", help="What to search for")
    p_search.add_argument("--wing", default=None, help="Limit to one project")
    p_search.add_argument("--room", default=None, help="Limit to one room")
    p_search.add_argument("--results", type=int, default=5, help="Number of results")

    # writing-export
    p_writing_export = sub.add_parser(
        "writing-export",
        help="Build a writing-process sidecar corpus outside the live project",
    )
    p_writing_export.add_argument("dir", help="Vault root or project directory")
    p_writing_export.add_argument(
        "--project",
        required=True,
        help="Project name to export (for example: Witcher-DC)",
    )
    p_writing_export.add_argument(
        "--out",
        default=None,
        help="Output directory (default: <vault>/.sidecars/<project>)",
    )
    p_writing_export.add_argument(
        "--codex-home",
        default=None,
        help="Codex home directory to scan for rollout JSONL (default: ~/.codex)",
    )
    p_writing_export.add_argument(
        "--config",
        default=None,
        help="Optional writing-sidecar YAML config with extra paths and chat match terms",
    )
    p_writing_export.add_argument(
        "--brainstorms",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the brainstorms room; repeat as needed",
    )
    p_writing_export.add_argument(
        "--audits",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the audits room; repeat as needed",
    )
    p_writing_export.add_argument(
        "--discarded-paths",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the discarded_paths room; repeat as needed",
    )
    p_writing_export.add_argument(
        "--mine",
        action="store_true",
        help="Mine the exported sidecar into a dedicated palace after export",
    )
    p_writing_export.add_argument(
        "--sidecar-palace",
        default=None,
        help="Palace directory for --mine (default: <vault>/.palaces/<project>)",
    )
    p_writing_export.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime/cache directory for sidecar mining (default: <vault>/.mempalace-sidecar-runtime/<project>)",
    )
    p_writing_export.add_argument(
        "--refresh-palace",
        action="store_true",
        help="If used with --mine, rebuild the target palace directory before mining",
    )
    p_writing_export.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be exported without writing files",
    )

    # writing-sync
    p_writing_sync = sub.add_parser(
        "writing-sync",
        help="Export and mine a writing sidecar, then optionally run a search",
    )
    p_writing_sync.add_argument("dir", help="Vault root or project directory")
    p_writing_sync.add_argument(
        "--project",
        required=True,
        help="Project name to sync (for example: Witcher-DC)",
    )
    p_writing_sync.add_argument(
        "--out",
        default=None,
        help="Output directory (default: <vault>/.sidecars/<project>)",
    )
    p_writing_sync.add_argument(
        "--codex-home",
        default=None,
        help="Codex home directory to scan for rollout JSONL (default: ~/.codex)",
    )
    p_writing_sync.add_argument(
        "--config",
        default=None,
        help="Optional writing-sidecar YAML config with extra paths and chat match terms",
    )
    p_writing_sync.add_argument(
        "--brainstorms",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the brainstorms room; repeat as needed",
    )
    p_writing_sync.add_argument(
        "--audits",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the audits room; repeat as needed",
    )
    p_writing_sync.add_argument(
        "--discarded-paths",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the discarded_paths room; repeat as needed",
    )
    p_writing_sync.add_argument(
        "--sidecar-palace",
        default=None,
        help="Palace directory for the synced sidecar (default: <vault>/.palaces/<project>)",
    )
    p_writing_sync.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime/cache directory for sidecar mining and search (default: <vault>/.mempalace-sidecar-runtime/<project>)",
    )
    p_writing_sync.add_argument(
        "--refresh-palace",
        action="store_true",
        help="Rebuild the target palace directory before mining",
    )
    p_writing_sync.add_argument(
        "--sync",
        choices=["always", "if-needed", "never"],
        default="if-needed",
        help="When to rebuild the sidecar before any optional search (default: if-needed)",
    )
    p_writing_sync.add_argument(
        "--query",
        default=None,
        help="Optional search query to run after the sync finishes",
    )
    p_writing_sync.add_argument(
        "--mode",
        choices=["planning", "audit", "history", "research"],
        default=None,
        help="Intent-aware sidecar search mode for the optional post-sync query",
    )
    p_writing_sync.add_argument(
        "--room",
        default=None,
        help="Optional room filter for the post-sync search",
    )
    p_writing_sync.add_argument(
        "--results",
        type=int,
        default=5,
        help="Number of post-sync search results to show",
    )

    # writing-status
    p_writing_status = sub.add_parser(
        "writing-status",
        help="Show whether a writing sidecar is current, stale, or not built yet",
    )
    p_writing_status.add_argument("dir", help="Vault root or project directory")
    p_writing_status.add_argument(
        "--project",
        required=True,
        help="Project name to inspect (for example: Witcher-DC)",
    )
    p_writing_status.add_argument(
        "--out",
        default=None,
        help="Output directory (default: <vault>/.sidecars/<project>)",
    )
    p_writing_status.add_argument(
        "--codex-home",
        default=None,
        help="Codex home directory to scan for rollout JSONL (default: ~/.codex)",
    )
    p_writing_status.add_argument(
        "--config",
        default=None,
        help="Optional writing-sidecar YAML config with extra paths and chat match terms",
    )
    p_writing_status.add_argument(
        "--brainstorms",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the brainstorms room; repeat as needed",
    )
    p_writing_status.add_argument(
        "--audits",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the audits room; repeat as needed",
    )
    p_writing_status.add_argument(
        "--discarded-paths",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the discarded_paths room; repeat as needed",
    )
    p_writing_status.add_argument(
        "--sidecar-palace",
        default=None,
        help="Palace directory for the sidecar (default: <vault>/.palaces/<project>)",
    )
    p_writing_status.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime/cache directory for sidecar mining and search (default: <vault>/.mempalace-sidecar-runtime/<project>)",
    )

    # writing-search
    p_writing_search = sub.add_parser(
        "writing-search",
        help="Search a writing sidecar with planning/audit/history/research intent modes",
    )
    p_writing_search.add_argument("dir", help="Vault root or project directory")
    p_writing_search.add_argument(
        "--project",
        required=True,
        help="Project name to search (for example: Witcher-DC)",
    )
    p_writing_search.add_argument(
        "--query",
        required=True,
        help="Search query to run against the writing sidecar",
    )
    p_writing_search.add_argument(
        "--mode",
        choices=["planning", "audit", "history", "research"],
        default="planning",
        help="Intent mode used to prioritize sidecar rooms (default: planning)",
    )
    p_writing_search.add_argument(
        "--sync",
        choices=["always", "if-needed", "never"],
        default="if-needed",
        help="When to rebuild the sidecar before search (default: if-needed)",
    )
    p_writing_search.add_argument(
        "--out",
        default=None,
        help="Output directory (default: <vault>/.sidecars/<project>)",
    )
    p_writing_search.add_argument(
        "--codex-home",
        default=None,
        help="Codex home directory to scan for rollout JSONL (default: ~/.codex)",
    )
    p_writing_search.add_argument(
        "--config",
        default=None,
        help="Optional writing-sidecar YAML config with extra paths and chat match terms",
    )
    p_writing_search.add_argument(
        "--brainstorms",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the brainstorms room; repeat as needed",
    )
    p_writing_search.add_argument(
        "--audits",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the audits room; repeat as needed",
    )
    p_writing_search.add_argument(
        "--discarded-paths",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the discarded_paths room; repeat as needed",
    )
    p_writing_search.add_argument(
        "--sidecar-palace",
        default=None,
        help="Palace directory for the sidecar (default: <vault>/.palaces/<project>)",
    )
    p_writing_search.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime/cache directory for sidecar mining and search (default: <vault>/.mempalace-sidecar-runtime/<project>)",
    )
    p_writing_search.add_argument(
        "--refresh-palace",
        action="store_true",
        help="If a rebuild happens, recreate the target palace from scratch first",
    )
    p_writing_search.add_argument(
        "--results",
        type=int,
        default=5,
        help="Number of search results to show",
    )

    # writing-init
    p_writing_init = sub.add_parser(
        "writing-init",
        help="Scaffold writing-sidecar files and templates for a project",
    )
    p_writing_init.add_argument("dir", help="Vault root or project directory")
    p_writing_init.add_argument(
        "--project",
        required=True,
        help="Project name to scaffold (for example: Witcher-DC)",
    )
    p_writing_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing scaffold files",
    )

    # compress
    p_compress = sub.add_parser(
        "compress", help="Compress drawers using AAAK Dialect (~30x reduction)"
    )
    p_compress.add_argument("--wing", default=None, help="Wing to compress (default: all wings)")
    p_compress.add_argument(
        "--dry-run", action="store_true", help="Preview compression without storing"
    )
    p_compress.add_argument(
        "--config", default=None, help="Entity config JSON (e.g. entities.json)"
    )

    # wake-up
    p_wakeup = sub.add_parser("wake-up", help="Show L0 + L1 wake-up context (~600-900 tokens)")
    p_wakeup.add_argument("--wing", default=None, help="Wake-up for a specific project/wing")

    # split
    p_split = sub.add_parser(
        "split",
        help="Split concatenated transcript mega-files into per-session files (run before mine)",
    )
    p_split.add_argument("dir", help="Directory containing transcript files")
    p_split.add_argument(
        "--output-dir",
        default=None,
        help="Write split files here (default: same directory as source files)",
    )
    p_split.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be split without writing files",
    )
    p_split.add_argument(
        "--min-sessions",
        type=int,
        default=2,
        help="Only split files containing at least N sessions (default: 2)",
    )

    # hook
    p_hook = sub.add_parser(
        "hook",
        help="Run hook logic (reads JSON from stdin, outputs JSON to stdout)",
    )
    hook_sub = p_hook.add_subparsers(dest="hook_action")
    p_hook_run = hook_sub.add_parser("run", help="Execute a hook")
    p_hook_run.add_argument(
        "--hook",
        required=True,
        choices=["session-start", "stop", "precompact"],
        help="Hook name to run",
    )
    p_hook_run.add_argument(
        "--harness",
        required=True,
        choices=["claude-code", "codex"],
        help="Harness type (determines stdin JSON format)",
    )

    # instructions
    p_instructions = sub.add_parser(
        "instructions",
        help="Output skill instructions to stdout",
    )
    instructions_sub = p_instructions.add_subparsers(dest="instructions_name")
    for instr_name in ["init", "search", "mine", "help", "status"]:
        instructions_sub.add_parser(instr_name, help=f"Output {instr_name} instructions")

    # repair
    sub.add_parser(
        "repair",
        help="Rebuild palace vector index from stored data (fixes segfaults after corruption)",
    )

    # mcp
    sub.add_parser(
        "mcp",
        help="Show MCP setup command for connecting MemPalace to your AI client",
    )

    # status
    sub.add_parser("status", help="Show what's been filed")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Handle two-level subcommands
    if args.command == "hook":
        if not getattr(args, "hook_action", None):
            p_hook.print_help()
            return
        cmd_hook(args)
        return

    if args.command == "instructions":
        name = getattr(args, "instructions_name", None)
        if not name:
            p_instructions.print_help()
            return
        args.name = name
        cmd_instructions(args)
        return

    dispatch = {
        "init": cmd_init,
        "mine": cmd_mine,
        "split": cmd_split,
        "search": cmd_search,
        "mcp": cmd_mcp,
        "writing-init": cmd_writing_init,
        "writing-export": cmd_writing_export,
        "writing-status": cmd_writing_status,
        "writing-search": cmd_writing_search,
        "writing-sync": cmd_writing_sync,
        "compress": cmd_compress,
        "wake-up": cmd_wakeup,
        "repair": cmd_repair,
        "status": cmd_status,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
