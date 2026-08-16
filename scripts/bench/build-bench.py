#!/usr/bin/env python3
"""Build backend benchmark (Stage 4, A-DG05-1).

Measures wall-clock for the Build path on both backends so the SDK-migration
GO/NO-GO is evidence-based, not guesswork:

- ``cli``: ``docker build`` via CliGateway.run_captured (the current default).
- ``sdk``: docker-py ``client.images.build`` spike (EXPERIMENT ONLY — the plan
  keeps Build on the CLI backend until this benchmark says otherwise).

Output: a baseline JSON (p50/p95/max ms + exit codes + image ref) that feeds
the GO/NO-GO decision in ``docs/plans/aisc-next/stage-4-docker-gateway/``.

Usage (requires a reachable Docker daemon):
    python scripts/bench/build-bench.py [--backend cli|sdk|both] [--samples N] [--tag TAG]

The default fixture is a tiny static Dockerfile so the build is fast and
repeatable (no network, no large context). Samples default to 3 (each build
takes ~1-2s for the tiny fixture); use --samples 5+ for tighter p95.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aisc.adapters.docker_gateway import CliGateway, create_docker_gateway  # noqa: E402
from aisc.domain.models import BuildPlan  # noqa: E402

# Base image must be cached locally (no network during the benchmark); the CI
# baseline uses whatever is present. Fall back to a common local image so a
# fresh checkout still produces a repeatable (offline) build.
TINY_BASE = "python:3.12-slim"
TINY_DOCKERFILE = (
    f"FROM {TINY_BASE}\n"
    "COPY --chown=0:0 . /bench\n"
    "RUN echo built > /bench/.built\n"
)


def percentile(sorted_vals: List[float], p: float) -> float:
    """Linear-interpolated percentile over ascending values (nearest-rank edges)."""
    if not sorted_vals:
        return 0.0
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]
    idx = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def make_fixture() -> Path:
    root = Path(__file__).resolve().parent / ".bench-fixture"
    root.mkdir(exist_ok=True)
    (root / "Dockerfile").write_text(TINY_DOCKERFILE, encoding="utf-8")
    (root / "payload.txt").write_text("hello", encoding="utf-8")
    return root


def bench_cli(root: Path, tag: str, samples: int) -> dict:
    gw = CliGateway()
    plan = BuildPlan(tag=tag, root=str(root), dockerfile=str(root / "Dockerfile"))
    durations: List[float] = []
    exit_codes: List[int] = []
    for _ in range(samples):
        start = time.monotonic()
        result = gw.build_image(plan)
        durations.append(time.monotonic() - start)
        exit_codes.append(result.operation.exit_code)
    durations.sort()
    return {
        "backend": "cli",
        "samples": samples,
        "p50_ms": round(percentile(durations, 50) * 1000, 2),
        "p95_ms": round(percentile(durations, 95) * 1000, 2),
        "max_ms": round(durations[-1] * 1000, 2),
        "exit_codes": exit_codes,
        "image_ref": tag,
    }


def bench_sdk(root: Path, tag: str, samples: int) -> dict:
    """SDK spike — EXPERIMENT ONLY (D4-05: Build stays CLI until benchmark says GO)."""
    import docker

    client = docker.from_env()
    durations: List[float] = []
    exit_codes: List[int] = []
    for _ in range(samples):
        start = time.monotonic()
        try:
            _, logs = client.images.build(
                path=str(root),
                dockerfile="Dockerfile",
                tag=tag,
                rm=True,
            )
            exit_codes.append(0)
            for _chunk in logs:
                pass  # consume the generator
        except Exception as exc:  # noqa: BLE001
            exit_codes.append(1)
            print(f"[sdk] build error: {exc}", file=sys.stderr)
        durations.append(time.monotonic() - start)
    durations.sort()
    return {
        "backend": "sdk",
        "samples": samples,
        "p50_ms": round(percentile(durations, 50) * 1000, 2),
        "p95_ms": round(percentile(durations, 95) * 1000, 2),
        "max_ms": round(durations[-1] * 1000, 2),
        "exit_codes": exit_codes,
        "image_ref": tag,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=["cli", "sdk", "both"], default="both")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--tag", default="aisc-bench:local")
    args = ap.parse_args(argv)

    root = make_fixture()
    results: List[dict] = []
    if args.backend in ("cli", "both"):
        print(f"[cli] benchmarking docker build x{args.samples} …", file=sys.stderr)
        results.append(bench_cli(root, args.tag, args.samples))
    if args.backend in ("sdk", "both"):
        print(f"[sdk] benchmarking docker-py build x{args.samples} …", file=sys.stderr)
        results.append(bench_sdk(root, args.tag, args.samples))

    manifest = {
        "generated_at_utc": "",  # stamped by caller (Date.now is blocked in scripts)
        "tool": "scripts/bench/build-bench.py",
        "dockerfile": TINY_DOCKERFILE.splitlines()[0],
        "results": results,
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
