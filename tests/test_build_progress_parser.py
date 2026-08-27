"""v2.1.7 S4 (Gate-S4): BuildProgressParser contract tests.

Pins the honesty invariants frozen in docs/plans/2.1.7-dev-plans/gate-s4-events.md:
determinate percent ONLY from a real step mapping, monotonic, capped below
100 until build.complete; pull phase is indeterminate; unknown lines are
ignored (no fabricated steps).
"""

from __future__ import annotations

import unittest

from aisc.cli.build_progress_parser import BuildProgressParser


def phases(updates):
    return [u.phase for u in updates]


class BuildkitPlainTests(unittest.TestCase):
    def test_step_lines_map_to_determinate_percent(self):
        p = BuildProgressParser()
        ups = p.feed("#5 [1/4] FROM node:20-slim\n#6 [2/4] WORKDIR /app\n")
        self.assertEqual(phases(ups), ["steps", "steps"])
        self.assertEqual(ups[-1].step_current, 2)
        self.assertEqual(ups[-1].step_total, 4)
        self.assertEqual(ups[-1].percent, 50.0)
        self.assertEqual(ups[-1].progress_kind, "determinate")
        self.assertEqual(ups[-1].summary, "WORKDIR /app")

    def test_percent_monotonic_even_on_out_of_order_lines(self):
        p = BuildProgressParser()
        p.feed("#5 [3/4] RUN a\n")
        ups = p.feed("#9 [1/4] RUN b\n")  # BuildKit inner-stage numbering regressed
        self.assertEqual(ups[0].percent, 75.0, "percent must never regress")

    def test_percent_never_reaches_100_before_complete(self):
        p = BuildProgressParser()
        ups = p.feed("#5 [4/4] RUN last\n")
        self.assertLess(ups[0].percent, 100.0)
        ups = p.feed("#9 exporting to image\n")
        self.assertEqual(ups[0].phase, "export")

    def test_cached_lines_surface_as_indeterminate_steps_done_stays_silent(self):
        # 2026-08-27 manual test: a fully-cached build has no [i/t] headers;
        # CACHED must still show motion (indeterminate, honest percent=None).
        p = BuildProgressParser()
        ups = p.feed("#5 CACHED\n#6 DONE 0.1s\n")
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0].phase, "steps")
        self.assertEqual(ups[0].progress_kind, "indeterminate")
        self.assertIsNone(ups[0].percent)
        self.assertIsNone(ups[0].step_current, "no fabricated step number")
        self.assertEqual(ups[0].summary, "CACHED")

    def test_context_transfer_maps_to_prepare_with_live_summary(self):
        p = BuildProgressParser()
        ups = p.feed("transferring context: 247.12MB 5.2s\ndone\n")
        self.assertEqual(ups[0].phase, "prepare")
        self.assertIn("247.12MB", ups[0].summary)
        self.assertEqual(ups[0].progress_kind, "indeterminate")

    def test_context_transfer_determinate_against_estimated_total(self):
        p = BuildProgressParser(context_total_bytes=500e6)
        ups = p.feed("transferring context: 247.5MB 5.2s\n")
        self.assertEqual(ups[0].progress_kind, "determinate")
        self.assertEqual(ups[0].percent, 49.5)
        self.assertIn("≈", ups[0].summary)
        # Capped at 95 — the real total is unknown (estimate semantics).
        ups = p.feed("transferring context: 900MB 12.0s\n")
        self.assertEqual(ups[0].percent, 95.0)
        self.assertLess(ups[0].percent, 100)


class LegacyBuilderTests(unittest.TestCase):
    def test_legacy_step_lines_map(self):
        p = BuildProgressParser()
        ups = p.feed("Step 2/12 : RUN apt-get update\n")
        self.assertEqual(ups[0].phase, "steps")
        self.assertEqual(ups[0].step_current, 2)
        self.assertEqual(ups[0].step_total, 12)
        self.assertAlmostEqual(ups[0].percent, 16.7)

    def test_legacy_without_total_is_indeterminate(self):
        p = BuildProgressParser()
        ups = p.feed("Step 3 : RUN x\n")
        self.assertEqual(ups[0].progress_kind, "indeterminate")
        self.assertIsNone(ups[0].percent)


class PhaseAndNoiseTests(unittest.TestCase):
    def test_pull_lines_are_indeterminate_pull_phase(self):
        p = BuildProgressParser()
        ups = p.feed("sha256:abc123 Pulling fs layer\nDownloading  12.3MB/54.2MB\n")
        self.assertTrue(all(u.phase == "pull" for u in ups))
        self.assertTrue(all(u.progress_kind == "indeterminate" for u in ups))
        self.assertTrue(all(u.percent is None for u in ups))

    def test_unknown_noise_produces_nothing(self):
        p = BuildProgressParser()
        ups = p.feed("random vendor output\nwarning: something\n\n  \n")
        self.assertEqual(ups, [])

    def test_mixed_chunk_splits_lines_correctly(self):
        p = BuildProgressParser()
        ups = p.feed("#5 [1/2] RUN a\nnoise\n#6 [2/2] RUN b\n")
        self.assertEqual(len(ups), 2)
        self.assertEqual(ups[-1].percent, 100.0 - 0.1, "capped at 99.9, never 100")


if __name__ == "__main__":
    unittest.main()
