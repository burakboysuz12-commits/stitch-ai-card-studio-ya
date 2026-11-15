#!/usr/bin/env python3
"""
run_e2e_tests.py — Unified Headless E2E Test Suite Runner.
Zero external dependencies; compatible with Python 3.8+ (unittest) and pytest.
"""

import argparse
import io
import json
import os
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional


def tier(level: int):
    """Decorator to assign an execution tier (1..5) to a TestCase or test method."""
    def decorator(obj):
        obj.__tier__ = level
        return obj
    return decorator


class E2ETestResult(unittest.TestResult):
    """Custom TestResult collecting detailed execution metrics and structured records."""

    def __init__(self, verbose: bool = False):
        super().__init__()
        self.verbose = verbose
        self.records: List[Dict[str, Any]] = []
        self._test_start_time = 0.0
        self.start_wall_time = time.time()

    def startTest(self, test: unittest.TestCase):
        super().startTest(test)
        self._test_start_time = time.perf_counter()
        if self.verbose:
            sys.stdout.write(f"  RUNNING: {test.id()} ... ")
            sys.stdout.flush()

    def addSuccess(self, test: unittest.TestCase):
        super().addSuccess(test)
        duration = time.perf_counter() - self._test_start_time
        self.records.append({
            "id": test.id(),
            "name": test._testMethodName,
            "class": test.__class__.__name__,
            "module": test.__class__.__module__,
            "status": "PASS",
            "duration": duration,
            "error": None
        })
        if self.verbose:
            sys.stdout.write(f"\033[92mPASS\033[0m ({duration:.3f}s)\n")
        else:
            sys.stdout.write(".")
            sys.stdout.flush()

    def addFailure(self, test: unittest.TestCase, err):
        super().addFailure(test, err)
        duration = time.perf_counter() - self._test_start_time
        err_msg = self._exc_info_to_string(err, test)
        self.records.append({
            "id": test.id(),
            "name": test._testMethodName,
            "class": test.__class__.__name__,
            "module": test.__class__.__module__,
            "status": "FAIL",
            "duration": duration,
            "error": err_msg
        })
        if self.verbose:
            sys.stdout.write(f"\033[91mFAIL\033[0m ({duration:.3f}s)\n")
        else:
            sys.stdout.write("F")
            sys.stdout.flush()

    def addError(self, test: unittest.TestCase, err):
        super().addError(test, err)
        duration = time.perf_counter() - self._test_start_time
        err_msg = self._exc_info_to_string(err, test)
        self.records.append({
            "id": test.id(),
            "name": test._testMethodName,
            "class": test.__class__.__name__,
            "module": test.__class__.__module__,
            "status": "ERROR",
            "duration": duration,
            "error": err_msg
        })
        if self.verbose:
            sys.stdout.write(f"\033[93mERROR\033[0m ({duration:.3f}s)\n")
        else:
            sys.stdout.write("E")
            sys.stdout.flush()

    def addSkip(self, test: unittest.TestCase, reason: str):
        super().addSkip(test, reason)
        self.records.append({
            "id": test.id(),
            "name": test._testMethodName,
            "class": test.__class__.__name__,
            "module": test.__class__.__module__,
            "status": "SKIP",
            "duration": 0.0,
            "reason": reason
        })
        if self.verbose:
            sys.stdout.write(f"\033[94mSKIP\033[0m ({reason})\n")
        else:
            sys.stdout.write("S")
            sys.stdout.flush()


def filter_test_suite(suite: unittest.TestSuite, target_tier: Optional[int], name_filter: Optional[str]) -> unittest.TestSuite:
    """Recursively filter test cases by tier and name pattern."""
    filtered = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            sub = filter_test_suite(item, target_tier, name_filter)
            if sub.countTestCases() > 0:
                filtered.addTest(sub)
        elif isinstance(item, unittest.TestCase):
            method = getattr(item, item._testMethodName, None)
            item_tier = getattr(method, "__tier__", getattr(item, "__tier__", None))

            # Module/class name fallback: infer tier from filename e.g. test_tier1_*.py
            if item_tier is None:
                mod_name = item.__class__.__module__.lower()
                for t in range(1, 6):
                    if f"tier{t}" in mod_name or f"tier_{t}" in mod_name:
                        item_tier = t
                        break

            # Tier check
            tier_match = (target_tier is None) or (item_tier == target_tier)

            # Name filter check
            name_match = (name_filter is None) or (name_filter.lower() in item.id().lower())

            if tier_match and name_match:
                filtered.addTest(item)
    return filtered


def export_json_report(
    result: E2ETestResult,
    total_time: float,
    output_path: str,
    total_discovered: Optional[int] = None
):
    """Write comprehensive test results as JSON."""
    executed = len(result.records)
    passed = max(0, executed - len(result.failures) - len(result.errors) - len(result.skipped))
    summary_data = {
        "total": executed,
        "passed": passed,
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "total_duration_seconds": round(total_time, 4),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(result.start_wall_time))
    }
    if total_discovered is not None and total_discovered > executed:
        summary_data["discovered"] = total_discovered
        summary_data["aborted"] = total_discovered - executed

    report = {
        "summary": summary_data,
        "tests": result.records
    }
    dir_name = os.path.dirname(os.path.abspath(output_path))
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def export_junit_xml(result: E2ETestResult, total_time: float, output_path: str):
    """Write standard JUnit XML report for CI integration."""
    suite_el = ET.Element("testsuite", {
        "name": "E2E_Headless_Card_Suite",
        "tests": str(len(result.records)),
        "failures": str(len(result.failures)),
        "errors": str(len(result.errors)),
        "skipped": str(len(result.skipped)),
        "time": f"{total_time:.4f}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(result.start_wall_time))
    })

    for rec in result.records:
        case_el = ET.SubElement(suite_el, "testcase", {
            "classname": f"{rec['module']}.{rec['class']}",
            "name": rec["name"],
            "time": f"{rec['duration']:.4f}"
        })
        if rec["status"] == "FAIL":
            fail_el = ET.SubElement(case_el, "failure", {"message": "Assertion failed"})
            fail_el.text = rec.get("error", "")
        elif rec["status"] == "ERROR":
            err_el = ET.SubElement(case_el, "error", {"message": "Unexpected error"})
            err_el.text = rec.get("error", "")
        elif rec["status"] == "SKIP":
            skip_el = ET.SubElement(case_el, "skipped", {"message": rec.get("reason", "Skipped")})

    tree = ET.ElementTree(suite_el)
    dir_name = os.path.dirname(os.path.abspath(output_path))
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(
        description="Headless E2E Test Suite Runner for Cloud Business Card Decomposition & Web System."
    )
    parser.add_argument("--tier", choices=["1", "2", "3", "4", "5", "all"], default="all",
                        help="Filter tests by execution tier (default: all).")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Path to write structured JSON test report.")
    parser.add_argument("--junit-xml", dest="xml_path", default=None,
                        help="Path to write standard JUnit XML test report.")
    parser.add_argument("--filter", "-k", dest="filter_pattern", default=None,
                        help="Filter tests by substring match on ID.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose real-time test progress.")
    parser.add_argument("--fail-fast", "-x", action="store_true",
                        help="Stop suite on first failure.")
    parser.add_argument("--start-dir", default=os.path.join(os.path.dirname(__file__), "tests", "e2e"),
                        help="Directory to discover tests in (default: tests/e2e).")

    args = parser.parse_args()

    # Verify discovery directory
    start_dir = os.path.abspath(args.start_dir)
    if not os.path.isdir(start_dir):
        print(f"\033[91mERROR: Discovery start directory '{start_dir}' does not exist.\033[0m")
        return 2

    # Parse target tier
    target_tier = None if args.tier == "all" else int(args.tier)

    print("======================================================================")
    print("           STITCH AI+ HEADLESS E2E TEST RUNNER")
    print("======================================================================")
    print(f"Discovery Directory: {start_dir}")
    print(f"Target Tier:         {args.tier.upper()}")
    if args.filter_pattern:
        print(f"Name Filter:         {args.filter_pattern}")
    print("----------------------------------------------------------------------")

    # Discover tests
    loader = unittest.TestLoader()
    raw_suite = loader.discover(start_dir=start_dir, pattern="test_*.py")
    suite = filter_test_suite(raw_suite, target_tier, args.filter_pattern)
    total_tests = suite.countTestCases()

    if total_tests == 0:
        print(f"\033[93mWARNING: No tests matched criteria (Tier={args.tier}, Filter={args.filter_pattern}).\033[0m")
        return 0

    print(f"Discovered {total_tests} test cases. Commencing execution...\n")

    result = E2ETestResult(verbose=args.verbose)
    result.failfast = args.fail_fast

    t_start = time.perf_counter()
    suite.run(result)
    t_total = time.perf_counter() - t_start

    print("\n----------------------------------------------------------------------")
    print(f"Execution Completed in {t_total:.3f} seconds.")
    executed = len(result.records)
    passed = max(0, executed - len(result.failures) - len(result.errors) - len(result.skipped))
    aborted = max(0, total_tests - executed)
    summary_msg = (
        f"Summary: \033[92m{passed} PASSED\033[0m | "
        f"\033[91m{len(result.failures)} FAILED\033[0m | "
        f"\033[93m{len(result.errors)} ERRORS\033[0m | "
        f"\033[94m{len(result.skipped)} SKIPPED\033[0m"
    )
    if aborted > 0:
        summary_msg += f" | \033[90m{aborted} ABORTED (fail-fast)\033[0m"
    print(summary_msg)

    # Print failure details (in both normal and verbose modes)
    if result.failures or result.errors:
        print("\n========================= FAILURE DETAILS ============================")
        for test, err in result.failures:
            print(f"\nFAIL: {test.id()}")
            print(err)
        for test, err in result.errors:
            print(f"\nERROR: {test.id()}")
            print(err)

    # Export reports with clean error handling (exit code 2 on unwritable path)
    if args.json_path:
        try:
            export_json_report(result, t_total, args.json_path, total_discovered=total_tests)
            print(f"JSON Report written to: {args.json_path}")
        except Exception as exc:
            print(f"\033[91mERROR: Failed to write JSON report to '{args.json_path}': {exc}\033[0m")
            return 2

    if args.xml_path:
        try:
            export_junit_xml(result, t_total, args.xml_path)
            print(f"JUnit XML written to:   {args.xml_path}")
        except Exception as exc:
            print(f"\033[91mERROR: Failed to write JUnit XML report to '{args.xml_path}': {exc}\033[0m")
            return 2

    print("======================================================================")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
