#!/usr/bin/env python3
"""A deliberately small, educational Git-like version-control client."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY_DIRECTORY = ".minigit"


def repository_root() -> Path:
    """Find the nearest directory containing this program's repository data."""
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        if (directory / REPOSITORY_DIRECTORY).is_dir():
            return directory
    raise SystemExit("Not a minigit repository. Run 'minigit.py init' first.")


def repository_paths(root: Path) -> dict[str, Path]:
    metadata = root / REPOSITORY_DIRECTORY
    return {
        "metadata": metadata,
        "objects": metadata / "objects",
        "index": metadata / "index.json",
        "head": metadata / "HEAD",
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def store_object(objects: Path, kind: str, content: bytes) -> str:
    """Store a content-addressed object and return its SHA-256 identifier."""
    payload = kind.encode("utf-8") + b"\0" + content
    object_id = hashlib.sha256(payload).hexdigest()
    object_path = objects / object_id
    if not object_path.exists():
        object_path.write_bytes(payload)
    return object_id


def object_id_for(kind: str, content: bytes) -> str:
    """Return the ID an object would have without writing it to disk."""
    payload = kind.encode("utf-8") + b"\0" + content
    return hashlib.sha256(payload).hexdigest()


def read_object(objects: Path, object_id: str) -> tuple[str, bytes]:
    """Read an object and split its type from its content."""
    try:
        payload = (objects / object_id).read_bytes()
        kind, content = payload.split(b"\0", maxsplit=1)
    except (FileNotFoundError, ValueError):
        raise SystemExit(f"Repository object '{object_id}' is missing or invalid.")
    return kind.decode("utf-8"), content


def command_init(_: argparse.Namespace) -> None:
    root = Path.cwd().resolve()
    paths = repository_paths(root)
    if paths["metadata"].exists():
        print(f"Repository already exists in {paths['metadata']}")
        return

    paths["objects"].mkdir(parents=True)
    write_json(paths["index"], {})
    paths["head"].write_text("", encoding="utf-8")
    print(f"Initialized empty minigit repository in {paths['metadata']}")


def command_add(arguments: argparse.Namespace) -> None:
    root = repository_root()
    paths = repository_paths(root)
    index = read_json(paths["index"], {})

    for supplied_path in arguments.files:
        file_path = (Path.cwd() / supplied_path).resolve()
        if not file_path.is_file():
            raise SystemExit(f"Cannot add '{supplied_path}': it is not a file.")
        try:
            relative_path = file_path.relative_to(root)
        except ValueError:
            raise SystemExit(f"Cannot add '{supplied_path}': it is outside this repository.")
        if REPOSITORY_DIRECTORY in relative_path.parts:
            raise SystemExit("Cannot add files inside .minigit.")

        object_id = store_object(paths["objects"], "blob", file_path.read_bytes())
        index[relative_path.as_posix()] = object_id
        print(f"staged {relative_path}")

    write_json(paths["index"], index)


def make_tree(index: dict[str, str]) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for file_name, object_id in index.items():
        node = tree
        *directories, leaf = file_name.split("/")
        for directory in directories:
            node = node.setdefault(directory, {})
        node[leaf] = {"type": "blob", "object": object_id}
    return tree


def flatten_tree(tree: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Turn a nested tree object back into a path-to-blob mapping."""
    files: dict[str, str] = {}
    for name, value in tree.items():
        path = f"{prefix}/{name}" if prefix else name
        if value.get("type") == "blob":
            files[path] = value["object"]
        else:
            files.update(flatten_tree(value, path))
    return files


def latest_tree(paths: dict[str, Path]) -> dict[str, str]:
    """Return the files recorded by HEAD, or an empty mapping before the first commit."""
    head = paths["head"].read_text(encoding="utf-8").strip()
    if not head:
        return {}
    kind, raw_commit = read_object(paths["objects"], head)
    if kind != "commit":
        raise SystemExit("HEAD does not point to a commit object.")
    commit = json.loads(raw_commit)
    kind, raw_tree = read_object(paths["objects"], commit["tree"])
    if kind != "tree":
        raise SystemExit("The latest commit does not point to a tree object.")
    return flatten_tree(json.loads(raw_tree))


def command_commit(arguments: argparse.Namespace) -> None:
    root = repository_root()
    paths = repository_paths(root)
    index = read_json(paths["index"], {})
    if not index:
        raise SystemExit("Nothing staged. Add at least one file before committing.")

    tree_id = store_object(
        paths["objects"],
        "tree",
        json.dumps(make_tree(index), sort_keys=True).encode("utf-8"),
    )
    parent = paths["head"].read_text(encoding="utf-8").strip() or None
    commit = {
        "tree": tree_id,
        "parent": parent,
        "message": arguments.message,
        "author": os.environ.get("USER", "unknown"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    commit_id = store_object(
        paths["objects"],
        "commit",
        json.dumps(commit, sort_keys=True).encode("utf-8"),
    )
    paths["head"].write_text(commit_id + "\n", encoding="utf-8")
    print(f"Committed {commit_id[:12]}: {arguments.message}")


def command_log(_: argparse.Namespace) -> None:
    root = repository_root()
    paths = repository_paths(root)
    current = paths["head"].read_text(encoding="utf-8").strip()
    if not current:
        print("No commits yet.")
        return

    while current:
        kind, raw_commit = read_object(paths["objects"], current)
        if kind != "commit":
            raise SystemExit(f"Object '{current}' is not a commit.")
        commit = json.loads(raw_commit)
        print(f"commit {current}")
        print(f"Author: {commit['author']}")
        print(f"Date:   {commit['timestamp']}")
        print(f"\n    {commit['message']}\n")
        current = commit["parent"] or ""


def working_files(root: Path) -> dict[str, Path]:
    """Find normal files in the repository, excluding MiniGit's own metadata."""
    files = {}
    for path in root.rglob("*"):
        if path.is_file() and REPOSITORY_DIRECTORY not in path.parts:
            files[path.relative_to(root).as_posix()] = path
    return files


def command_status(_: argparse.Namespace) -> None:
    root = repository_root()
    paths = repository_paths(root)
    index = read_json(paths["index"], {})
    committed = latest_tree(paths)
    files = working_files(root)

    staged = [path for path in index if index[path] != committed.get(path)]
    changed = [
        path
        for path in index
        if path not in files
        or object_id_for("blob", files[path].read_bytes()) != index[path]
    ]
    untracked = sorted(path for path in files if path not in index)

    if not staged and not changed and not untracked:
        print("Working tree clean.")
        return
    if staged:
        print("Changes staged for commit:")
        for path in sorted(staged):
            print(f"  staged: {path}")
    if changed:
        print("Changes not staged:")
        for path in sorted(changed):
            label = "deleted" if path not in files else "modified"
            print(f"  {label}: {path}")
    if untracked:
        print("Untracked files:")
        for path in untracked:
            print(f"  {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A tiny educational Git-like client")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize a repository")
    init.set_defaults(handler=command_init)

    add = commands.add_parser("add", help="stage files")
    add.add_argument("files", nargs="+", help="files to stage")
    add.set_defaults(handler=command_add)

    commit = commands.add_parser("commit", help="save the staged state")
    commit.add_argument("-m", "--message", required=True, help="commit message")
    commit.set_defaults(handler=command_commit)

    log = commands.add_parser("log", help="show commit history")
    log.set_defaults(handler=command_log)

    status = commands.add_parser("status", help="show staged and working-file changes")
    status.set_defaults(handler=command_status)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
