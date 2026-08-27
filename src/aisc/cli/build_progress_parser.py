"""v2.1.7 S4 (Gate-S4): docker build output → structured build.progress.

Pure, stateful parser fed with the raw docker stdout/stderr chunks (the same
bytes that ride ``build.output``). Emits at most one ``ProgressUpdate`` per
recognised line; unrecognised lines are ignored — the raw log is the only
place they matter (honest-progress rule: never fabricate a step).

Two output formats are recognised (the docker argv deliberately stays
untouched — forcing ``--progress=plain`` would break the legacy builder):

* BuildKit plain (piped stdout uses it automatically):
  ``#12 [3/7] RUN apt-get update`` / ``#12 CACHED`` / ``#12 DONE ...`` /
  ``#12 exporting to image`` / ``naming to docker.io/super-claude:latest``.
* Legacy builder: ``Step 3/12 : RUN ...`` / ``Successfully built <id>``.

Honesty invariants enforced here (Gate-S4 §1):
  * ``percent`` only when a step mapping is known; monotonic, never lower;
  * never reaches 100 (capped at 99.9) — only build.complete means done;
  * pull work is its own indeterminate phase (no fake byte percent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# BuildKit plain: "#12 [3/7] RUN apt-get update" (inner stage step) or
# "#12 exporting to image" (phase text without [i/t]).
_BUILDKIT_STEP = re.compile(r"^#\d+ \[(\d+)/(\d+)\] (.*)$")
_BUILDKIT_PHASE = re.compile(r"^#\d+ (.+)$")

# "transferring context: 247.12MB 5.2s" / "... 1.2GB done" — cumulative
# bytes WITHOUT a total (BuildKit never announces the context size), so the
# prepare bar can only be determinate against an ESTIMATED denominator.
_CONTEXT_BYTES = re.compile(
    r"^transferring context: ([\d.]+)\s*(B|kB|MB|GB|TB)\b", re.I
)
_UNIT_MULT = {"b": 1.0, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12}


def _fmt_mb(n: float) -> str:
    return f"{n / 1e6:.1f}MB"


def parse_context_bytes(line: str) -> Optional[float]:
    """Cumulative transferred bytes from a `transferring context:` line."""
    m = _CONTEXT_BYTES.match(line)
    if not m:
        return None
    return float(m.group(1)) * _UNIT_MULT[m.group(2).lower()]
# Legacy builder: "Step 3/12 : RUN ..." / bare "Step 3 : ..."
_LEGACY_STEP = re.compile(r"^Step (\d+)(?:/(\d+))? : (.*)$")

_PHASE_PATTERNS = (
    (re.compile(r"^(?:resolve|pulling|sha256:|docker\.io|Downloading|extracting|Pulling)", re.I), "pull"),
    (re.compile(r"^(?:transferring context|load build definition|load \.dockerignore|load metadata)", re.I), "prepare"),
    (re.compile(r"^exporting (?:to image|layers|manifest)", re.I), "export"),
    (re.compile(r"^(?:naming to|writing image|loaded image|tagged)", re.I), "export"),
    (re.compile(r"^Successfully (?:built|tagged)", re.I), "done"),
)


@dataclass
class ProgressUpdate:
    """One build.progress payload (Gate-S4 §1 field contract)."""

    phase: str
    step_current: Optional[int]
    step_total: Optional[int]
    percent: Optional[float]
    progress_kind: str  # determinate | indeterminate
    summary: str


class BuildProgressParser:
    """Feed raw chunks; collect :class:`ProgressUpdate` for each recognised
    line. Monotonic by construction: percent only ever rises."""

    def __init__(self, context_total_bytes: Optional[float] = None) -> None:
        self._step_current = 0
        self._step_total: Optional[int] = None
        self._last_percent = 0.0
        self._phase = "prepare"
        # Estimated context denominator from the PREVIOUS build's log
        # (Gate-S4 §1 amendment): enables a determinate prepare bar that is
        # explicitly marked ≈ in the summary and capped at 95.
        self._context_total_bytes = context_total_bytes

    # -- helpers -----------------------------------------------------------

    def _percent(self, current: int, total: Optional[int]) -> Optional[float]:
        if not total or total <= 0 or current < 1:
            return None
        raw = min(current / total, 1.0) * 100.0
        # Never 100 before build.complete, never regress.
        raw = min(raw, 99.9)
        if raw < self._last_percent:
            raw = self._last_percent
        self._last_percent = raw
        return round(raw, 1)

    def _update(
        self,
        phase: str,
        summary: str,
        *,
        step_current: Optional[int] = None,
        step_total: Optional[int] = None,
    ) -> ProgressUpdate:
        self._phase = phase
        cur = step_current if step_current is not None else self._step_current
        tot = step_total if step_total is not None else self._step_total
        if step_total is not None and (self._step_total is None or step_total > self._step_total):
            self._step_total = step_total
        if cur is not None and cur >= 0:
            self._step_current = cur
        percent = self._percent(cur, tot) if phase == "steps" else None
        return ProgressUpdate(
            phase=phase,
            step_current=cur if phase == "steps" else None,
            step_total=tot if phase == "steps" else None,
            percent=percent,
            progress_kind="determinate" if percent is not None else "indeterminate",
            summary=summary,
        )

    def _context_update(self, line: str) -> ProgressUpdate:
        """`transferring context` — cumulative bytes only. With an estimated
        denominator from the previous build, emit a determinate ≈ percent
        (capped at 95 — the real total is unknown); otherwise stay
        indeterminate with the live byte count as the summary."""
        self._phase = "prepare"
        cur = parse_context_bytes(line)
        total = self._context_total_bytes
        if cur is not None and total and total > 0:
            raw = min(cur / total, 0.95) * 100.0
            if raw < self._last_percent:
                raw = self._last_percent
            self._last_percent = raw
            return ProgressUpdate(
                phase="prepare",
                step_current=None,
                step_total=int(total),
                percent=round(raw, 1),
                progress_kind="determinate",
                summary=f"≈ {_fmt_mb(cur)} / ≈ {_fmt_mb(total)}",
            )
        return ProgressUpdate(
            phase="prepare",
            step_current=None,
            step_total=None,
            percent=None,
            progress_kind="indeterminate",
            summary=line,
        )

    # -- api ---------------------------------------------------------------

    @property
    def phase(self) -> str:
        return self._phase

    def feed(self, chunk: str) -> list[ProgressUpdate]:
        """Parse one raw chunk; return the updates for its recognised lines."""
        updates: list[ProgressUpdate] = []
        for line in chunk.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            upd = self._parse_line(stripped)
            if upd is not None:
                updates.append(upd)
        return updates

    def _parse_line(self, line: str) -> Optional[ProgressUpdate]:
        m = _BUILDKIT_STEP.match(line)
        if m:
            cur, tot, desc = int(m.group(1)), int(m.group(2)), m.group(3)
            return self._update("steps", desc, step_current=cur, step_total=tot)

        m = _LEGACY_STEP.match(line)
        if m:
            cur = int(m.group(1))
            tot = int(m.group(2)) if m.group(2) else None
            return self._update("steps", m.group(3), step_current=cur, step_total=tot)

        for pattern, phase in _PHASE_PATTERNS:
            if pattern.match(line):
                if phase == "prepare":
                    return self._context_update(line)
                return self._update(phase, line)

        # BuildKit bare phase lines ("#12 exporting to image", "#7 DONE").
        m = _BUILDKIT_PHASE.match(line)
        if m:
            text = m.group(1).strip()
            if text.lower() == "done":
                # completion of a single step — not the build's end
                return None
            # 2026-08-27 manual test (full-cache build): a CACHED step carries
            # no [i/t] header, so a fully-cached build otherwise shows ZERO
            # motion. Surface it as an indeterminate steps-phase update — no
            # fabricated step number, percent stays honest (null).
            if text.lower() == "cached":
                return ProgressUpdate(
                    phase="steps",
                    step_current=None,
                    step_total=self._step_total,
                    percent=None,
                    progress_kind="indeterminate",
                    summary="CACHED",
                )
            mapped = next((p for pat, p in _PHASE_PATTERNS if pat.match(text)), None)
            if mapped:
                return self._update(mapped, text)
        return None
