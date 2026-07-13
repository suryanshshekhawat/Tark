#!/usr/bin/env python3
"""Benchmark harness for the real pipeline.

All tuning up to this point was manual one-off runs against a live Claude API
and a live Lean subprocess, and the verified count swung by 1-2 steps between
identical inputs (decompose() and the ensemble candidates are not
deterministic). This script replaces those anecdotal comparisons with
repeated runs + aggregated stats, so a real regression can be told apart from
run-to-run noise.

Costs real Claude API calls and real Lean subprocess time per run — default
repeat count is intentionally 1; raise it deliberately.

Usage:
    python scripts/bench.py                      # all fixtures, 1 run each
    python scripts/bench.py --repeat 3            # 3 runs each, adds stdev
    python scripts/bench.py --fixture sqrt2       # just one fixture
    python scripts/bench.py --json out.json       # also dump raw per-run JSON
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ on sys.path

from app.pipeline.real_pipeline import run_real_pipeline  # noqa: E402
from app.validation.latex_validator import LatexValidator  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Group index of the field we care about per tark.timing log line — these
# mirror the exact log formats in real_pipeline.py; if those change, update
# the corresponding pattern here rather than silently under-counting.
_LEAN_CHECK_RE = re.compile(
    r"lean_check step=(?P<step>\S+) attempt=(?P<attempt>\S+) "
    r"semaphore_wait_s=(?P<wait>[\d.]+) check_s=(?P<check>[\d.]+) verdict=(?P<verdict>\S+)"
)


class _CollectingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@dataclass
class RunResult:
    fixture: str
    wall_time_s: float
    steps_total: int
    steps_verified: int
    steps_refuted: int
    lean_checks: int
    lean_semaphore_wait_total_s: float
    log_lines: list[str] = field(default_factory=list)


async def _run_once(fixture_name: str, latex: str) -> RunResult:
    validation = LatexValidator().validate(latex)
    if not validation.ok:
        raise RuntimeError(f"{fixture_name}: validation failed: {validation.error}")

    handler = _CollectingHandler()
    timing_logger = logging.getLogger("tark.timing")
    prev_level = timing_logger.level
    timing_logger.addHandler(handler)
    timing_logger.setLevel(logging.INFO)

    verified = refuted = total = 0
    t0 = time.monotonic()
    try:
        async for step in run_real_pipeline(validation.normalized_source):
            total += 1
            if step.verdict.value == "VERIFIED":
                verified += 1
            elif step.verdict.value == "REFUTED":
                refuted += 1
    finally:
        timing_logger.removeHandler(handler)
        timing_logger.setLevel(prev_level)
    wall = time.monotonic() - t0

    lean_checks = 0
    wait_total = 0.0
    for line in handler.lines:
        m = _LEAN_CHECK_RE.match(line)
        if m:
            lean_checks += 1
            wait_total += float(m.group("wait"))

    return RunResult(
        fixture=fixture_name,
        wall_time_s=wall,
        steps_total=total,
        steps_verified=verified,
        steps_refuted=refuted,
        lean_checks=lean_checks,
        lean_semaphore_wait_total_s=wait_total,
        log_lines=handler.lines,
    )


def _summarize(results: list[RunResult]) -> dict:
    wall_times = [r.wall_time_s for r in results]
    verified_rates = [r.steps_verified / r.steps_total if r.steps_total else 0.0 for r in results]
    return {
        "fixture": results[0].fixture,
        "runs": len(results),
        "wall_time_s_mean": statistics.mean(wall_times),
        "wall_time_s_stdev": statistics.stdev(wall_times) if len(wall_times) > 1 else 0.0,
        "verified_rate_mean": statistics.mean(verified_rates),
        "lean_checks_mean": statistics.mean(r.lean_checks for r in results),
        "lean_semaphore_wait_s_mean": statistics.mean(r.lean_semaphore_wait_total_s for r in results),
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=1, help="runs per fixture (default 1)")
    parser.add_argument("--fixture", type=str, default=None, help="run only this fixture (filename stem)")
    parser.add_argument("--json", type=str, default=None, help="write raw per-run results to this JSON file")
    args = parser.parse_args()

    fixture_paths = sorted(FIXTURES_DIR.glob("*.tex"))
    if args.fixture:
        fixture_paths = [p for p in fixture_paths if p.stem == args.fixture]
        if not fixture_paths:
            print(f"No fixture named {args.fixture!r} in {FIXTURES_DIR}", file=sys.stderr)
            sys.exit(1)

    all_results: list[RunResult] = []
    summaries = []
    for path in fixture_paths:
        latex = path.read_text()
        fixture_results = []
        for i in range(args.repeat):
            print(f"[{path.stem}] run {i + 1}/{args.repeat}...", file=sys.stderr)
            result = await _run_once(path.stem, latex)
            fixture_results.append(result)
            all_results.append(result)
        summaries.append(_summarize(fixture_results))

    header = f"{'fixture':<24} {'runs':>4} {'wall(s)':>9} {'±stdev':>8} {'verified%':>10} {'lean_checks':>12} {'sem_wait(s)':>12}"
    print()
    print(header)
    print("-" * len(header))
    for s in summaries:
        print(
            f"{s['fixture']:<24} {s['runs']:>4} {s['wall_time_s_mean']:>9.1f} "
            f"{s['wall_time_s_stdev']:>8.1f} {s['verified_rate_mean'] * 100:>9.1f}% "
            f"{s['lean_checks_mean']:>12.1f} {s['lean_semaphore_wait_s_mean']:>12.1f}"
        )

    if args.json:
        payload = {
            "summaries": summaries,
            "runs": [
                {
                    "fixture": r.fixture,
                    "wall_time_s": r.wall_time_s,
                    "steps_total": r.steps_total,
                    "steps_verified": r.steps_verified,
                    "steps_refuted": r.steps_refuted,
                    "lean_checks": r.lean_checks,
                    "lean_semaphore_wait_total_s": r.lean_semaphore_wait_total_s,
                }
                for r in all_results
            ],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f"\nWrote raw results to {args.json}")


if __name__ == "__main__":
    asyncio.run(_main())
