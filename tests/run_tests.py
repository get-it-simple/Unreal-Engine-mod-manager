from __future__ import annotations

import argparse
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def iter_cases(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_cases(item)
        else:
            yield item


def discover_tests(root: Path) -> list[str]:
    suite = unittest.defaultTestLoader.discover(str(root), pattern="test_*.py", top_level_dir=".")
    return sorted(test.id() for test in iter_cases(suite) if not test.id().startswith("unittest.loader._FailedTest"))


def worker_count(value: str, total: int) -> int:
    if value == "auto":
        cpu_count = os.cpu_count() or 1
        return max(1, min(total, cpu_count))
    return max(1, min(total, int(value)))


def run_test(test_id: str) -> tuple[str, int, str]:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", test_id],
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return test_id, result.returncode, output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run project tests, optionally in parallel.")
    parser.add_argument("--jobs", default="auto", help="Number of parallel workers, or auto.")
    parser.add_argument("--tests-dir", default="tests")
    args = parser.parse_args(argv)

    root = Path(args.tests_dir)
    test_ids = discover_tests(root)
    if not test_ids:
        print("No tests found.")
        return 1

    jobs = worker_count(args.jobs, len(test_ids))
    print(f"Running {len(test_ids)} tests with {jobs} worker(s).")

    failures = []
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(run_test, test_id): test_id for test_id in test_ids}
        for future in as_completed(futures):
            test_id, code, output = future.result()
            print(f"\n== {test_id} ==")
            print(output.rstrip())
            if code:
                failures.append(test_id)

    if failures:
        print("\nFailed tests:")
        for test_id in failures:
            print(f" - {test_id}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
