#!/usr/bin/env python3
"""Install AISC's bundled skills into cc-switch only when synchronization is needed."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import TextIO


BUNDLED_SKILLS = (
    ("caveman", "Ultra-compressed agent communication", "JuliusBrussee", "caveman"),
    (
        "document-skills",
        "Bundled document creation and editing skills",
        "anthropics",
        "skills",
    ),
    ("grill-me", "Relentless plan and design interview", "mattpocock", "skills"),
    (
        "superpowers",
        "Structured software engineering workflows",
        "obra",
        "superpowers",
    ),
)
REVISION_FILE = ".aisc-bundle.sha256"
MARKER_FILE = ".aisc-bundled-skills.sha256"
LOCK_FILE = ".aisc-bundled-skills.lock"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _load_skill_states(db_path: Path) -> dict[str, tuple[bool, bool]]:
    connection = sqlite3.connect(
        f"file:{db_path}?mode=ro",
        timeout=10,
        uri=True,
    )
    try:
        rows = connection.execute(
            """
            SELECT name, enabled_claude, enabled_codex
            FROM skills
            WHERE name IN (?, ?, ?, ?)
            """,
            tuple(skill[0] for skill in BUNDLED_SKILLS),
        ).fetchall()
    finally:
        connection.close()
    return {
        name: (bool(enabled_claude), bool(enabled_codex))
        for name, enabled_claude, enabled_codex in rows
    }


def sync_required(
    *,
    config_dir: Path,
    skills_home: Path,
    bundle_dir: Path,
    revision: str,
) -> tuple[bool, str]:
    marker = config_dir / MARKER_FILE
    if not marker.is_file() or _read_text(marker) != revision:
        return True, "bundled skills revision changed"

    for name, *_ in BUNDLED_SKILLS:
        if not (bundle_dir / name).is_dir():
            raise FileNotFoundError(f"bundled skill missing: {bundle_dir / name}")
        if not (config_dir / "skills" / name).is_dir():
            return True, f"cc-switch source missing: {name}"

    db_path = config_dir / "cc-switch.db"
    if not db_path.is_file():
        return True, "cc-switch database missing"
    try:
        states = _load_skill_states(db_path)
    except (OSError, sqlite3.Error):
        return True, "cc-switch skill state unreadable"

    for name, *_ in BUNDLED_SKILLS:
        state = states.get(name)
        if state is None:
            return True, f"cc-switch registration missing: {name}"
        enabled_claude, enabled_codex = state
        if enabled_claude and not (
            skills_home / ".claude" / "skills" / name
        ).is_dir():
            return True, f"Claude target missing: {name}"
        if enabled_codex and not (
            skills_home / ".codex" / "skills" / name
        ).is_dir():
            return True, f"Codex target missing: {name}"

    return False, "current"


def _register_skills(config_dir: Path) -> None:
    db_path = config_dir / "cc-switch.db"
    connection = sqlite3.connect(db_path, timeout=10)
    try:
        now = int(time.time())
        for name, description, owner, repo in BUNDLED_SKILLS:
            connection.execute(
                """
                INSERT OR IGNORE INTO skills (
                    id, name, description, directory,
                    repo_owner, repo_name, repo_branch,
                    enabled_claude, enabled_codex, installed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"aisc:{name}",
                    name,
                    description,
                    name,
                    owner,
                    repo,
                    "main",
                    1,
                    1,
                    now,
                    now,
                ),
            )
            # Metadata follows the image, but existing enable/disable choices belong
            # to the user and must survive container restarts and image upgrades.
            connection.execute(
                """
                UPDATE skills
                SET description = ?, directory = ?, repo_owner = ?, repo_name = ?,
                    repo_branch = ?, updated_at = ?
                WHERE name = ?
                """,
                (description, name, owner, repo, "main", now, name),
            )
        connection.commit()
    finally:
        connection.close()


def _run_cc_switch(args: list[str], log: TextIO, *, check: bool) -> None:
    subprocess.run(
        ["cc-switch", *args],
        check=check,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )


def synchronize(
    *,
    config_dir: Path,
    bundle_dir: Path,
    revision: str,
    log: TextIO,
) -> None:
    for name, *_ in BUNDLED_SKILLS:
        source = bundle_dir / name
        if not source.is_dir():
            raise FileNotFoundError(f"bundled skill missing: {source}")
        destination = config_dir / "skills" / name
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, dirs_exist_ok=True)

    # This command creates or migrates cc-switch.db. A non-zero result is
    # tolerated only when the database is already usable by the registration step.
    _run_cc_switch(["skills", "list"], log, check=False)
    _register_skills(config_dir)
    _run_cc_switch(["skills", "sync-method", "copy"], log, check=True)
    _run_cc_switch(["skills", "sync"], log, check=True)

    marker = config_dir / MARKER_FILE
    temporary_marker = config_dir / f"{MARKER_FILE}.tmp"
    temporary_marker.write_text(f"{revision}\n", encoding="utf-8")
    os.replace(temporary_marker, marker)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--skills-home", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--mode", default="auto")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.config_dir.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)

    mode = args.mode.lower()
    with args.log.open("a", encoding="utf-8") as log:
        if mode not in {"auto", "always", "off"}:
            print(
                f"unknown AISC_SKILLS_SYNC={args.mode!r}; falling back to auto",
                file=log,
            )
            mode = "auto"
        if mode == "off":
            print("off")
            return 0

        try:
            revision = _read_text(args.bundle_dir / REVISION_FILE)
            if not revision:
                raise ValueError("bundled skills revision is empty")

            import fcntl

            with (args.config_dir / LOCK_FILE).open("a+", encoding="utf-8") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                except OSError as exc:
                    # Docker Desktop bind mounts may not implement advisory locks.
                    # Synchronization is idempotent, so continue without the guard.
                    print(
                        f"skill sync lock unavailable; continuing without it: {exc}",
                        file=log,
                    )
                required, reason = sync_required(
                    config_dir=args.config_dir,
                    skills_home=args.skills_home,
                    bundle_dir=args.bundle_dir,
                    revision=revision,
                )
                if mode == "always":
                    required, reason = True, "forced by AISC_SKILLS_SYNC=always"
                if not required:
                    print("current")
                    return 0

                print(f"sync required: {reason}", file=log)
                synchronize(
                    config_dir=args.config_dir,
                    bundle_dir=args.bundle_dir,
                    revision=revision,
                    log=log,
                )
        except Exception:
            traceback.print_exc(file=log)
            return 1

    print("synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
