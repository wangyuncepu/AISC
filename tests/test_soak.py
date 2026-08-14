"""Stage 0 (S0.4): soak harness percentile/deadline/report tests.

B-A06: reports p50/p95/max with a hard deadline; samples exceeding the
deadline must be counted and fail the report. The runner is injected so no
subprocess is spawned.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
import unittest.mock
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SOAK = _load("aisc_soak", "scripts/soak/soak.py")


class PercentileTests(unittest.TestCase):
    def test_p50_p95_p100_of_sorted(self):
        vals = sorted([0.5, 0.7, 0.9, 1.1, 1.3, 1.7, 2.0])
        self.assertAlmostEqual(SOAK.percentile(vals, 50), 1.1)
        # rank=(n-1)*0.95=5.7 -> linear interp between 1.7 and 2.0 at 0.7
        self.assertAlmostEqual(SOAK.percentile(vals, 95), 1.7 + 0.7 * 0.3)
        self.assertAlmostEqual(SOAK.percentile(vals, 100), 2.0)
        self.assertAlmostEqual(SOAK.percentile(vals, 0), 0.5)

    def test_empty_samples_raises(self):
        with self.assertRaises(ValueError):
            SOAK.percentile([], 50)


class RunSoakTests(unittest.TestCase):
    def test_report_shape_and_passed_deadline(self):
        def fake_run(command: str) -> float:
            return 0.05  # 50ms per sample

        report = SOAK.run_soak(command="x", samples=5, deadline_ms=100, run=fake_run)
        self.assertEqual(report["samples"], 5)
        self.assertEqual(report["deadline_ms"], 100)
        self.assertEqual(report["p50_ms"], 50.0)
        self.assertEqual(report["p95_ms"], 50.0)
        self.assertEqual(report["max_ms"], 50.0)
        self.assertEqual(report["exceeded_deadline_count"], 0)
        self.assertTrue(report["passed_deadline"])

    def test_over_deadline_fails_report(self):
        def fake_run(command: str) -> float:
            return 0.25  # 250ms > 100ms deadline

        report = SOAK.run_soak(command="x", samples=3, deadline_ms=100, run=fake_run)
        self.assertEqual(report["exceeded_deadline_count"], 3)
        self.assertFalse(report["passed_deadline"])
        self.assertEqual(report["max_ms"], 250.0)

    def test_mixed_samples_report_percentiles(self):
        timings = iter([0.2, 0.1, 0.3, 0.15, 0.5, 0.4, 0.25, 0.35, 0.05, 0.6])

        def fake_run(command: str) -> float:
            return next(timings)

        report = SOAK.run_soak(command="x", samples=10, deadline_ms=1000, run=fake_run)
        self.assertEqual(report["min_ms"], 50.0)
        self.assertEqual(report["max_ms"], 600.0)
        # median of sorted [50,100,150,200,250,300,350,400,500,600] = 275
        self.assertAlmostEqual(report["p50_ms"], 275.0, places=1)
        self.assertTrue(report["passed_deadline"])

    def test_cli_writes_json_and_exit_zero(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            with patch.object(SOAK, "run_soak") as mocked:
                mocked.return_value = {
                    "command": "x", "samples": 2, "deadline_ms": 100,
                    "min_ms": 1.0, "p50_ms": 2.0, "p95_ms": 3.0, "max_ms": 4.0,
                    "mean_ms": 2.5, "exceeded_deadline_count": 0, "passed_deadline": True,
                }
                code = SOAK.main(
                    ["--command", "x", "--samples", "2", "--deadline-ms", "100", "--out", str(out)]
                )
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(data["passed_deadline"])
            self.assertEqual(data["max_ms"], 4.0)

    def test_cli_over_deadline_exits_nonzero(self):
        from unittest.mock import patch

        with patch.object(SOAK, "run_soak") as mocked:
            mocked.return_value = {
                "command": "x", "samples": 1, "deadline_ms": 100,
                "min_ms": 200.0, "p50_ms": 200.0, "p95_ms": 200.0, "max_ms": 200.0,
                "mean_ms": 200.0, "exceeded_deadline_count": 1, "passed_deadline": False,
            }
            code = SOAK.main(["--command", "x", "--samples", "1", "--deadline-ms", "100"])
        self.assertEqual(code, 1)

    def test_cli_invalid_samples_exit_two(self):
        import io
        with unittest.mock.patch("sys.stderr", io.StringIO()):
            code = SOAK.main(["--command", "x", "--samples", "0", "--deadline-ms", "100"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
