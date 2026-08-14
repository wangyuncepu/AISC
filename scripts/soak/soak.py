"""Stage 0 (S0.4) soak harness: fixed-sample latency report with a hard deadline.

Runs a command *samples* times, records wall-clock durations, and reports
p50/p95/max (never just the mean) plus whether any sample exceeded the hard
deadline. The runner is injectable so tests can fake timings without spawning
subprocesses.

Usage:
    python scripts/soak/soak.py \\
        --command "python -m pytest tests/test_baseline.py -q" \\
        --samples 5 --deadline-ms 2000 --out soak-report.json

The report is JSON with `passed_deadline=false` if any sample exceeded the
deadline; a non-zero exit is returned in that case so CI can gate on it.
"""

from __future__ import annotations

import argparse
import json
import shlex
import statistics
import subprocess
import sys
import time
from typing import Callable, List, Optional


RunFn = Callable[[str], float]


def percentile(sorted_vals: List[float], p: float) -> float:
    """Linear-interpolated percentile over ascending values (nearest-rank edges)."""
    if not sorted_vals:
        raise ValueError("no samples")
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]
    rank = (len(sorted_vals) - 1) * (p / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = rank - low
    return sorted_vals[low] + frac * (sorted_vals[high] - sorted_vals[low])


def real_run(command: str, deadline_ms: int) -> float:
    """Run *command* (shell tokenized) and return elapsed seconds.

    A command that does not finish within *deadline_ms* is counted as elapsed
    equal to the deadline (i.e. over budget), never left hanging.
    """
    argv = shlex.split(command)
    started = time.perf_counter()
    try:
        subprocess.run(
            argv,
            capture_output=True,
            timeout=deadline_ms / 1000.0,
        )
    except subprocess.TimeoutExpired:
        return deadline_ms / 1000.0
    return time.perf_counter() - started


def run_soak(
    *,
    command: str,
    samples: int,
    deadline_ms: int,
    run: Optional[RunFn] = None,
) -> dict:
    """Collect *samples* durations and build the latency report."""
    runner = run or (lambda cmd: real_run(cmd, deadline_ms))
    durations: List[float] = []
    exceeded: List[float] = []
    for _ in range(samples):
        elapsed = runner(command)
        durations.append(elapsed)
        if elapsed * 1000.0 > deadline_ms:
            exceeded.append(elapsed)

    durations.sort()
    return {
        "command": command,
        "samples": samples,
        "deadline_ms": deadline_ms,
        "min_ms": round(durations[0] * 1000.0, 2),
        "p50_ms": round(percentile(durations, 50) * 1000.0, 2),
        "p95_ms": round(percentile(durations, 95) * 1000.0, 2),
        "max_ms": round(durations[-1] * 1000.0, 2),
        "mean_ms": round(statistics.mean(durations) * 1000.0, 2),
        "exceeded_deadline_count": len(exceeded),
        "passed_deadline": len(exceeded) == 0,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed-sample soak with hard deadline")
    parser.add_argument("--command", required=True, help="Command to run per sample")
    parser.add_argument("--samples", type=int, default=5, help="Number of samples")
    parser.add_argument("--deadline-ms", type=int, default=2000, help="Hard deadline per sample")
    parser.add_argument("--out", type=str, default=None, help="Write JSON report to this path")
    args = parser.parse_args(argv or sys.argv[1:])

    if args.samples <= 0:
        print("soak: --samples must be > 0", file=sys.stderr)
        return 2
    if args.deadline_ms <= 0:
        print("soak: --deadline-ms must be > 0", file=sys.stderr)
        return 2

    report = run_soak(
        command=args.command,
        samples=args.samples,
        deadline_ms=args.deadline_ms,
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=True, indent=2)

    return 0 if report["passed_deadline"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
