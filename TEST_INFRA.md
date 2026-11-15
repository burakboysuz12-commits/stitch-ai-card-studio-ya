# Test Infrastructure Specification (TEST_INFRA.md)
**Project**: Cloud-Enabled Business Card Decomposition & Interactive Editing System  
**Framework**: Python `unittest` (Standard Library) / `pytest` Dual-Compatible Headless Harness  
**Version**: 1.0.0  
**Updated**: 2026-11-15T00:12:00Z  

---

## 1. Overview & Objectives

The End-to-End (E2E) Test Infrastructure provides automated, deterministic, headless verification of the entire card decomposition, cloud web server, and natural language editing system.

### Core Objectives:
1. **Headless Execution**: 100% display-server independent. Executes in continuous integration (GitHub Actions), containerized sandboxes (Docker / Render), and local developer terminals on Windows and Linux without GUI display dependencies.
2. **Zero-Dependency Core**: The master test runner (`run_e2e_tests.py`) runs on standard Python 3.8+ with no required third-party testing dependencies, while remaining fully discoverable by `pytest`.
3. **Objective Mathematical Fidelity**: Eliminates subjective visual inspections by utilizing Structural Similarity Index Measure (SSIM >= 0.92), Difference Hash (dHash distance <= 6 bits), and OCR character accuracy (>= 98%).
4. **Hermetic Test Isolation**: Guarantees zero side-effects across test runs via dynamic ephemeral ports (`port 0`), isolated temporary directories, and sandboxed environment variables.

---

## 2. Directory & File Structure

```
tests/
├── e2e/
│   ├── __init__.py
│   ├── harness.py                     # Ephemeral server, sandbox context managers, SSIM/dHash
│   ├── test_tier1_features.py         # Tier 1: Core Feature Coverage (Happy Path, F1-F12)
│   ├── test_tier2_boundaries.py       # Tier 2: Boundary, Edge Cases & Negative Inputs
│   ├── test_tier3_cross_feature.py    # Tier 3: Cross-Feature Integration & Contract Round-Trips
│   ├── test_tier4_real_world.py       # Tier 4: Real-World Scenarios against kartvizit_son_orijinal.png
│   └── test_tier5_adversarial.py      # Tier 5: Stress, Concurrency & Adversarial Hardening
run_e2e_tests.py                       # Unified CLI test runner with tier selection & export
```

---

## 3. Test Tier Taxonomy

| Tier | Category | Target Scope | Criteria & Pass Thresholds |
|------|----------|--------------|----------------------------|
| **Tier 1** | Feature Coverage (Happy Path) | Features 1–12 fundamental contracts | Status 200/201, valid JSON schemas, 1024x686 bounds, 100% pass |
| **Tier 2** | Boundary & Corner Cases | Extreme inputs, missing fields, malformed data | Correct 400/404 HTTP errors, graceful fallbacks, zero unhandled 500s |
| **Tier 3** | Cross-Feature Integration | Full subsystem pipelines (Engine ↔ Server ↔ State) | Full state round-trip, layer consistency across REST API |
| **Tier 4** | Real-World Workloads | Production decomposition of `kartvizit_son_orijinal.png` | SSIM >= 0.92, dHash <= 6, icon preservation mean diff <= 0.05 |
| **Tier 5** | Adversarial Hardening | Rapid repeated edits, boundary clamping, concurrency | Memory stability, coordinate containment inside 1024x686 |

---

## 4. Execution Commands

### 4.1 Master Headless Runner (`run_e2e_tests.py`)
```bash
# Run complete test suite across all tiers
python run_e2e_tests.py

# Run specific tier
python run_e2e_tests.py --tier 1
python run_e2e_tests.py --tier 2
python run_e2e_tests.py --tier 3
python run_e2e_tests.py --tier 4

# Run with verbose real-time streaming and fail-fast
python run_e2e_tests.py --tier 1 -v -x

# Generate structured JSON and JUnit XML reports for CI
python run_e2e_tests.py --json reports/test_report.json --junit-xml reports/junit.xml

# Filter by test name or feature
python run_e2e_tests.py -k test_f2_health_check
```

### 4.2 Standard Pytest Execution
```bash
# Run all tests via pytest
pytest tests/e2e

# Run tier 1 tests
pytest tests/e2e -k tier1 -v

# Run with JUnit XML export
pytest tests/e2e --junitxml=reports/junit.xml
```

### 4.3 Python Standard Library Discovery
```bash
python -m unittest discover -s tests/e2e -p "test_*.py" -v
```

---

## 5. Test Isolation & Sandboxing Principles

1. **Network Isolation**: All server integration tests MUST use `EphemeralServer(handler)` or bind to port `0`. Hardcoding port `8000` or `18765` is strictly forbidden in test suites.
2. **Filesystem Isolation**: Any test creating or modifying files MUST use `with isolated_sandbox() as tmpdir:` and perform work inside `tmpdir`. Modifying files in the root workspace during tests is strictly forbidden.
3. **Environment Isolation**: Any test altering environment variables (`PORT`, `HOST`, etc.) MUST wrap execution with `with isolated_environ(...):`.
4. **Display Independence**: GUI toolkits (`Tkinter`, `customtkinter`) MUST NEVER be imported in test suites. Headless backend `MPLBACKEND="Agg"` is enforced automatically by `harness.py`.
5. **Deterministic Timeouts**: All network requests and thread joins MUST include explicit timeouts (`timeout=5.0`s).

---

## 6. Exit Codes & Reporting Schema

### Exit Codes:
- `0`: All executed tests passed.
- `1`: One or more tests failed or errored.
- `2`: Runner argument or discovery syntax error.

### JSON Schema Output (`--json`):
```json
{
  "summary": {
    "total": 60,
    "passed": 60,
    "failed": 0,
    "errors": 0,
    "skipped": 0,
    "total_duration_seconds": 4.125,
    "timestamp": "2026-11-15T00:10:00Z"
  },
  "tests": [
    {
      "id": "tests.e2e.test_tier1_features.TestWebServer.test_f2_01_health_check",
      "name": "test_f2_01_health_check",
      "class": "TestWebServer",
      "module": "tests.e2e.test_tier1_features",
      "status": "PASS",
      "duration": 0.042,
      "error": null
    }
  ]
}
```
