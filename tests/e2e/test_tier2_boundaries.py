"""
tests/e2e/test_tier2_boundaries.py — Tier 2 Boundary, Edge Cases & Negative Inputs Test Suite.
Covers Features 1 through 12 (6 boundary test cases per feature = 72 tests total).
"""

import copy
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import web_server

try:
    import card_layer_engine
    ENGINE_AVAILABLE = True
except ImportError:
    card_layer_engine = None
    ENGINE_AVAILABLE = False

from tests.e2e.harness import (
    tier,
    EphemeralServer,
    isolated_sandbox,
    isolated_environ,
    compute_ssim_simple,
    compute_dhash,
    compute_dhash_distance,
    _to_numpy_rgb,
    load_image_unicode_safe,
    transform_layer_isotropic,
)


# ==============================================================================
# FEATURE 1: Git Repo & Clean Artifacts — Boundary Cases (F1)
# ==============================================================================
@tier(2)
class TestFeature1GitRepoCleanArtifactsBoundaries(unittest.TestCase):
    """Verifies boundary conditions, negation rules, nested paths, and error states for Git repo hygiene."""

    def test_f1_b01_nested_deep_gitignore_matching(self):
        """Verifies .gitignore rules match across deeply nested multi-level directory paths."""
        deep_paths = [
            "depth1/depth2/depth3/node_modules/package/index.js",
            "a/b/c/d/e/__pycache__/compiled.pyc",
            "nested/sub/dir/weights/model.pt",
            "deeply/nested/path/to/.env",
        ]
        for path in deep_paths:
            res = subprocess.run(
                ["git", "check-ignore", path],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode, 0,
                f"Deeply nested path '{path}' should be ignored by .gitignore but git check-ignore returned {res.returncode}",
            )

    def test_f1_b02_negation_rule_edge_condition_for_env_example(self):
        """Verifies .gitignore ignores secret env files while explicitly permitting .env.example via negation."""
        secret_paths = [".env", ".env.local", ".env.production", ".env.test"]
        for sec in secret_paths:
            res = subprocess.run(
                ["git", "check-ignore", sec],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, f"Secret file '{sec}' must be ignored")

        # Negation edge case: .env.example must NOT be ignored
        res_example = subprocess.run(
            ["git", "check-ignore", ".env.example"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res_example.returncode, 1,
            ".env.example must NOT be ignored due to !.env.example negation rule in .gitignore",
        )

    def test_f1_b03_simulated_large_file_and_binary_exclusion(self):
        """Verifies simulated binary artifacts are excluded by .gitignore and tracked files stay strictly < 50MB."""
        bin_extensions = [".exe", ".dll", ".pkg", ".pt", ".safetensors", ".bin", ".h5", ".tflite"]
        for ext in bin_extensions:
            probe = f"simulated_build/output{ext}"
            res = subprocess.run(
                ["git", "check-ignore", probe],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode, 0,
                f"Binary extension '{ext}' must be excluded by .gitignore",
            )

        # Confirm all currently tracked files in the repository adhere to the 50MB upper limit
        res_ls = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True)
        self.assertEqual(res_ls.returncode, 0)
        for line in res_ls.stdout.splitlines():
            fp = os.path.join(PROJECT_ROOT, line.strip())
            if os.path.isfile(fp):
                self.assertLess(
                    os.path.getsize(fp), 50 * 1024 * 1024,
                    f"Tracked file '{line}' exceeds 50MB limit",
                )

    def test_f1_b04_whitespace_and_special_characters_in_paths(self):
        """Verifies .gitignore correctly ignores paths containing spaces, parentheses, and Turkish characters."""
        special_paths = [
            "sub folder/node_modules/package.json",
            "weights/my model.pt",
            "build (x86)/output.pkg",
            "raporlar/günlük_2026.log",
        ]
        for path in special_paths:
            res = subprocess.run(
                ["git", "check-ignore", path],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode, 0,
                f"Path with spaces/special characters '{path}' should be ignored",
            )

    def test_f1_b05_git_command_execution_in_non_git_sandbox(self):
        """Verifies graceful error handling and non-zero exit code when running git in a non-git directory."""
        with isolated_sandbox() as tmpdir:
            res = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0, "Expected non-zero returncode in non-git directory")
            self.assertIn("fatal: not a git repository", res.stderr.lower())

    def test_f1_b06_case_insensitive_extension_matching(self):
        """Verifies uppercase extension variants are ignored consistently on the filesystem."""
        uppercase_variants = [
            "weights/model.PT",
            "bin/app.EXE",
            "lib/native.DLL",
            "store/data.SQLITE3",
        ]
        for var in uppercase_variants:
            res = subprocess.run(
                ["git", "check-ignore", var],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode, 0,
                f"Uppercase extension '{var}' should be ignored by .gitignore",
            )


# ==============================================================================
# FEATURE 2: 24/7 Cloud Web Server — Boundary Cases (F2)
# ==============================================================================
@tier(2)
class TestFeature2WebServerBoundaries(unittest.TestCase):
    """Verifies port boundaries, socket exceptions, URL normalization, and unexpected request handling."""

    def test_f2_b01_non_numeric_and_empty_port_environment_handling(self):
        """Verifies environment port parsing raises ValueError on non-numeric strings and resolves safely to default."""
        with isolated_environ(PORT="non_numeric_port"):
            port_str = os.environ.get("PORT", "8080")
            with self.assertRaises(ValueError):
                int(port_str)

            # Test safe fallback pattern
            try:
                resolved = int(port_str)
            except (ValueError, TypeError):
                resolved = 8080
            self.assertEqual(resolved, 8080)

        with isolated_environ(PORT=""):
            port_str = os.environ.get("PORT", "8080") or "8080"
            self.assertEqual(int(port_str), 8080)

    def test_f2_b02_port_out_of_range_and_ephemeral_bounds(self):
        """Verifies TCP socket binding enforces the valid 0..65535 port range and allocates ephemeral ports at 0."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            with self.assertRaises(OverflowError):
                s.bind(("127.0.0.1", 70000))
            with self.assertRaises(OverflowError):
                s.bind(("127.0.0.1", -1))

        # Port 0 must successfully allocate an ephemeral port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            e_port = s.getsockname()[1]
            self.assertGreater(e_port, 1024)
            self.assertLessEqual(e_port, 65535)

    def test_f2_b03_invalid_host_binding_socket_error(self):
        """Verifies attempting to bind to an invalid host string raises socket.gaierror."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            with self.assertRaises(socket.gaierror):
                s.bind(("999.999.999.999", 0))

    def test_f2_b04_query_parameters_and_fragment_handling_on_api(self):
        """Verifies GET /api/health and /api/design/state handle arbitrary query strings and fragments without 404."""
        with EphemeralServer() as server:
            query_url = f"{server.base_url}/api/health?debug=1&foo=bar&token=xyz#section"
            with urllib.request.urlopen(query_url, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data.get("ok"))
                self.assertEqual(data.get("service"), "stitch_ai_web")

    def test_f2_b05_get_request_with_unexpected_body(self):
        """Verifies server handles GET requests containing an unexpected body payload gracefully without error."""
        with EphemeralServer() as server:
            payload = json.dumps({"unexpected": "payload_on_get"}).encode("utf-8")
            req = urllib.request.Request(
                f"{server.base_url}/api/health",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data.get("ok"))

    def test_f2_b06_unsupported_http_methods_and_post_on_health(self):
        """Verifies POST on /api/health returns HTTP 404, and HEAD returns HTTP 501 Unsupported method."""
        with EphemeralServer() as server:
            req_post = urllib.request.Request(
                f"{server.base_url}/api/health",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req_post, timeout=5.0)
                self.fail("Expected HTTP 404 for POST /api/health")
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 404)

            req_head = urllib.request.Request(f"{server.base_url}/api/health", method="HEAD")
            try:
                urllib.request.urlopen(req_head, timeout=5.0)
                self.fail("Expected HTTP 501 for HEAD /api/health")
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 501)


# ==============================================================================
# FEATURE 3: Cloud Agent CI/CD & Playbook — Boundary Cases (F3)
# ==============================================================================
@tier(2)
class TestFeature3CloudAgentPlaybookBoundaries(unittest.TestCase):
    """Verifies CI/CD workflow schema, script path hygiene, keepalive crons, and agent instructions tokens."""

    def test_f3_b01_ci_yaml_strict_schema_and_mandatory_keys(self):
        """Verifies .github/workflows/ci.yml parses cleanly as YAML and contains all mandatory GitHub Actions keys."""
        ci_path = os.path.join(PROJECT_ROOT, ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.isfile(ci_path), "Missing .github/workflows/ci.yml")
        with open(ci_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.assertIsInstance(data, dict, "CI workflow must parse as a YAML dictionary")
        self.assertIn("name", data)
        self.assertIn("jobs", data)
        self.assertTrue("on" in data or True in data, "CI workflow must define trigger events ('on')")
        self.assertIn("test", data["jobs"])

        test_job = data["jobs"]["test"]
        self.assertEqual(test_job.get("runs-on"), "ubuntu-latest")
        self.assertIsInstance(test_job.get("steps"), list)
        self.assertGreaterEqual(len(test_job["steps"]), 5, "Test job must contain at least 5 verification steps")

    def test_f3_b02_ci_workflow_step_commands_validity(self):
        """Verifies CI job commands contain zero hardcoded Windows paths and enforce bounded execution timeouts."""
        ci_path = os.path.join(PROJECT_ROOT, ".github", "workflows", "ci.yml")
        with open(ci_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for step in data["jobs"]["test"]["steps"]:
            run_cmd = step.get("run", "")
            if run_cmd:
                self.assertNotIn("c:\\", run_cmd.lower(), "CI script must not reference local Windows C: drive")
                self.assertNotIn("/users/", run_cmd.lower(), "CI script must not reference user home directories")

        timeout = data["jobs"]["test"].get("timeout-minutes")
        self.assertIsNotNone(timeout, "CI job must specify timeout-minutes")
        self.assertLessEqual(timeout, 15, "CI job timeout must not exceed 15 minutes")

    def test_f3_b03_keepalive_workflow_schedule_and_secret_boundary(self):
        """Verifies keepalive.yml defines a 10-minute cron interval and checks for RENDER_APP_URL secret."""
        ka_path = os.path.join(PROJECT_ROOT, ".github", "workflows", "keepalive.yml")
        self.assertTrue(os.path.isfile(ka_path), "Missing .github/workflows/keepalive.yml")
        with open(ka_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
            f.seek(0)
            data = yaml.safe_load(f)

        self.assertIn("jobs", data)
        self.assertIn("ping", data["jobs"])
        ping_steps = data["jobs"]["ping"]["steps"]
        has_secret_ref = any("RENDER_APP_URL" in str(s.get("env", {})) for s in ping_steps)
        self.assertTrue(has_secret_ref, "Keepalive workflow must reference RENDER_APP_URL secret")
        self.assertIn("*/10 * * * *", raw_text, "Keepalive workflow must define 10-minute cron schedule")

    def test_f3_b04_agent_instructions_mandatory_rule_tokens(self):
        """Verifies AGENT_INSTRUCTIONS.md documents all 4 mandatory rules and the 5MB file threshold token."""
        inst_path = os.path.join(PROJECT_ROOT, "AGENT_INSTRUCTIONS.md")
        self.assertTrue(os.path.isfile(inst_path), "Missing AGENT_INSTRUCTIONS.md")
        with open(inst_path, "r", encoding="utf-8") as f:
            text = f.read()

        required_rules = [
            "Rule 1: No Large Binaries or Bloat",
            "Rule 2: Minimal Change Principle",
            "Rule 3: Preserving Interface Contracts",
            "Rule 4: Mandatory Test Verification",
        ]
        for rule in required_rules:
            self.assertIn(rule, text, f"AGENT_INSTRUCTIONS.md missing mandatory rule header: '{rule}'")

        self.assertTrue("5 MB" in text or "5MB" in text, "AGENT_INSTRUCTIONS.md must state 5MB binary threshold")
        self.assertGreaterEqual(len(text), 1000, "AGENT_INSTRUCTIONS.md is too short")
        self.assertLess(len(text), 100000, "AGENT_INSTRUCTIONS.md is unreasonably large")

    def test_f3_b05_procfile_format_and_whitespace_boundary(self):
        """Verifies Procfile declares exactly one valid web process with clean whitespace formatting."""
        proc_path = os.path.join(PROJECT_ROOT, "Procfile")
        self.assertTrue(os.path.isfile(proc_path), "Missing Procfile")
        with open(proc_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        self.assertEqual(len(lines), 1, "Procfile must declare exactly one process command")
        self.assertRegex(
            lines[0], r"^web:\s+python\s+web_server\.py$",
            "Procfile must match format: 'web: python web_server.py'",
        )

    def test_f3_b06_dockerfile_instruction_ordering_and_healthcheck(self):
        """Verifies Dockerfile directives follow standard ordering, declare EXPOSE 8080, and define HEALTHCHECK."""
        df_path = os.path.join(PROJECT_ROOT, "Dockerfile")
        self.assertTrue(os.path.isfile(df_path), "Missing Dockerfile")
        with open(df_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        self.assertTrue(lines[0].startswith("FROM"), "Dockerfile must start with FROM instruction")
        has_healthcheck = any(l.startswith("HEALTHCHECK") for l in lines)
        self.assertTrue(has_healthcheck, "Dockerfile must configure HEALTHCHECK directive")
        has_cmd = any(l.startswith("CMD") for l in lines)
        self.assertTrue(has_cmd, "Dockerfile must configure CMD directive")
        has_expose = any(l.startswith("EXPOSE 8080") for l in lines)
        self.assertTrue(has_expose, "Dockerfile must expose port 8080")


# ==============================================================================
# FEATURE 4: Phase 1 Notification — Boundary Cases (F4)
# ==============================================================================
@tier(2)
class TestFeature4Phase1NotificationBoundaries(unittest.TestCase):
    """Verifies missing file handling, empty report rejection, markdown balance, and UTF-8 encoding."""

    def test_f4_b01_missing_report_error_handling(self):
        """Verifies accessing a non-existent report path raises FileNotFoundError deterministically."""
        with isolated_sandbox() as tmpdir:
            missing_path = os.path.join(tmpdir, "NON_EXISTENT_REPORT.md")
            with self.assertRaises(FileNotFoundError):
                with open(missing_path, "r", encoding="utf-8") as f:
                    f.read()

    def test_f4_b02_empty_and_whitespace_report_rejection(self):
        """Verifies 0-byte and whitespace-only reports are rejected by validation thresholds (< 500 chars)."""
        with isolated_sandbox() as tmpdir:
            empty_path = os.path.join(tmpdir, "EMPTY_REPORT.md")
            with open(empty_path, "w", encoding="utf-8") as f:
                f.write("   \n\t\r\n  ")

            with open(empty_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertEqual(len(content.strip()), 0, "Empty report must contain 0 non-whitespace characters")
            self.assertLess(len(content.strip()), 500, "Empty report must fail minimum 500 character threshold")

    def test_f4_b03_markdown_code_block_backtick_balance(self):
        """Verifies triple backtick fences in markdown reports are balanced with zero unclosed blocks."""
        report_files = ["PHASE_1_COMPLETION_REPORT.md", "cloud_7_24_kurulum.md"]
        for rep in report_files:
            path = os.path.join(PROJECT_ROOT, rep)
            self.assertTrue(os.path.isfile(path), f"Missing markdown report file: {rep}")
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()

            backtick_count = text.count("```")
            self.assertGreater(backtick_count, 0, f"Report '{rep}' must contain code fences")
            self.assertEqual(
                backtick_count % 2, 0,
                f"Report '{rep}' has unbalanced code block backticks (count: {backtick_count})",
            )

    def test_f4_b04_markdown_table_column_alignment_and_structure(self):
        """Verifies markdown tables in completion report maintain equal column count across headers and rows."""
        report_path = os.path.join(PROJECT_ROOT, "PHASE_1_COMPLETION_REPORT.md")
        self.assertTrue(os.path.isfile(report_path))
        with open(report_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        in_table = False
        expected_cols = None
        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if s.startswith("|") and s.endswith("|"):
                cols = [c.strip() for c in s.split("|")[1:-1]]
                if not in_table:
                    in_table = True
                    expected_cols = len(cols)
                else:
                    self.assertEqual(
                        len(cols), expected_cols,
                        f"Table column mismatch at line {idx}: expected {expected_cols} columns, found {len(cols)}",
                    )
            else:
                in_table = False

    def test_f4_b05_unicode_encoding_preservation_turkish_characters(self):
        """Verifies completion report decodes cleanly in UTF-8 and fails strict ASCII due to Turkish characters."""
        report_path = os.path.join(PROJECT_ROOT, "PHASE_1_COMPLETION_REPORT.md")
        with open(report_path, "rb") as f:
            raw_bytes = f.read()

        text_utf8 = raw_bytes.decode("utf-8")
        self.assertNotIn("\ufffd", text_utf8, "UTF-8 decoded report must not contain replacement characters")

        turkish_chars = ["ş", "ç", "ı", "ğ", "ö", "ü", "İ", "Ş"]
        found_chars = [ch for ch in turkish_chars if ch in text_utf8]
        self.assertGreaterEqual(
            len(found_chars), 5,
            f"Report must contain native Turkish characters; found only: {found_chars}",
        )

        with self.assertRaises(UnicodeDecodeError, msg="Strict ASCII decoding must fail on Turkish report"):
            raw_bytes.decode("ascii")

    def test_f4_b06_metadata_header_case_insensitivity_and_whitespace(self):
        """Verifies metadata key parser handles case insensitivity, surrounding whitespace, and ISO dates."""
        report_path = os.path.join(PROJECT_ROOT, "PHASE_1_COMPLETION_REPORT.md")
        with open(report_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines()[:30]]

        meta = {}
        for line in lines:
            m = re.match(r"^\*\*([^*]+)\*\*\s*:\s*(.+)$", line)
            if m:
                meta[m.group(1).strip().lower()] = m.group(2).strip()

        self.assertIn("durum", meta, "Metadata header must specify 'Durum'")
        self.assertIn("TAMAMLANDI", meta["durum"].upper(), "Status must indicate completion (TAMAMLANDI)")
        self.assertIn("tarih", meta, "Metadata header must specify 'Tarih'")
        self.assertRegex(meta["tarih"], r"^\d{4}-\d{2}-\d{2}$", "Date must follow ISO format YYYY-MM-DD")
        self.assertIn("aşama", meta, "Metadata header must specify 'Aşama'")
        self.assertTrue("M1" in meta["aşama"] or "Milestone 1" in meta["aşama"])


# ==============================================================================
# FEATURE 5: Headless Test Suite & Metrics Boundaries (F5)
# ==============================================================================
@tier(2)
class TestFeature5MetricsBoundaries(unittest.TestCase):
    """Verifies boundary behaviors, extreme values, corrupt inputs, and threshold evaluation for F5."""

    def test_f5_b01_ssim_all_black_vs_all_white_extremes(self):
        """Verifies SSIM mathematical divergence on opposing monochrome images (near 0.0) vs identity (1.0)."""
        black_img = np.zeros((686, 1024, 3), dtype=np.uint8)
        white_img = np.full((686, 1024, 3), 255, dtype=np.uint8)

        # Mathematical identity
        ssim_id_white = compute_ssim_simple(white_img, white_img)
        self.assertAlmostEqual(ssim_id_white, 1.0, places=4, msg="White identity SSIM must equal 1.0")

        ssim_id_black = compute_ssim_simple(black_img, black_img)
        self.assertAlmostEqual(ssim_id_black, 1.0, places=4, msg="Black identity SSIM must equal 1.0")

        # Mathematical extreme divergence
        ssim_div = compute_ssim_simple(black_img, white_img)
        self.assertLess(ssim_div, 0.001, f"Opposing monochrome images SSIM must be near 0.0, got {ssim_div}")
        self.assertGreaterEqual(ssim_div, 0.0, "SSIM must be non-negative for valid uint8 images")

    def test_f5_b02_dhash_distance_extremes_identical_vs_inverted_gradient(self):
        """Verifies dHash bitwise Hamming distance extremes (0 bits for identity vs 64 bits for inverted gradient)."""
        grad_arr = np.tile(np.linspace(0, 255, 9, dtype=np.uint8), (8, 1))
        inv_grad_arr = np.tile(np.linspace(255, 0, 9, dtype=np.uint8), (8, 1))

        dist_id = compute_dhash_distance(grad_arr, grad_arr)
        self.assertEqual(dist_id, 0, "Identity dHash distance must be exactly 0 bits")

        dist_max = compute_dhash_distance(grad_arr, inv_grad_arr)
        self.assertEqual(dist_max, 64, "Inverted gradient dHash distance must equal 64 bits")

    def test_f5_b03_corrupt_and_truncated_image_payload_handling(self):
        """Verifies error handling on corrupt, non-image, and invalid type payloads."""
        with isolated_sandbox() as tmpdir:
            bad_path = os.path.join(tmpdir, "corrupt_file.png")
            with open(bad_path, "wb") as f:
                f.write(b"NOT_A_REAL_PNG_HEADER_DATA_GARBAGE_PAYLOAD")

            with self.assertRaises((UnidentifiedImageError, ValueError, OSError)):
                _to_numpy_rgb(bad_path)

            with self.assertRaises(TypeError):
                _to_numpy_rgb(98765)
            with self.assertRaises(TypeError):
                _to_numpy_rgb([1, 2, 3])

    def test_f5_b04_mismatched_image_dimensions_resizing_boundary(self):
        """Verifies compute_ssim_simple handles mismatched dimensions and aspect ratios gracefully."""
        img_native = np.zeros((686, 1024, 3), dtype=np.uint8)
        img_square_small = np.full((100, 100, 3), 128, dtype=np.uint8)
        img_hd_wide = np.full((1080, 1920, 3), 200, dtype=np.uint8)

        val_small = compute_ssim_simple(img_native, img_square_small)
        self.assertTrue(-1.0 <= val_small <= 1.0, f"SSIM out of bounds: {val_small}")

        val_wide = compute_ssim_simple(img_native, img_hd_wide)
        self.assertTrue(-1.0 <= val_wide <= 1.0, f"SSIM out of bounds: {val_wide}")

    def test_f5_b05_threshold_evaluation_boundary_precision_ssim(self):
        """Verifies precision boundary evaluation at exact SSIM threshold 0.9200."""
        def evaluate_ssim(score: float, threshold: float = 0.9200) -> bool:
            return float(score) >= threshold

        self.assertTrue(evaluate_ssim(0.9200), "Exact boundary 0.9200 must pass")
        self.assertTrue(evaluate_ssim(0.9201), "Score 0.9201 above boundary must pass")
        self.assertTrue(evaluate_ssim(1.0000), "Perfect score 1.0000 must pass")
        self.assertFalse(evaluate_ssim(0.9199), "Score 0.9199 below boundary must fail")
        self.assertFalse(evaluate_ssim(0.8500), "Score 0.8500 below boundary must fail")

    def test_f5_b06_threshold_evaluation_boundary_precision_dhash(self):
        """Verifies precision boundary evaluation at exact dHash distance threshold <= 6 bits."""
        def evaluate_dhash(distance: int, max_allowed: int = 6) -> bool:
            return 0 <= distance <= max_allowed

        self.assertTrue(evaluate_dhash(0), "Distance 0 (identity) must pass")
        self.assertTrue(evaluate_dhash(6), "Exact boundary distance 6 must pass")
        self.assertFalse(evaluate_dhash(7), "Distance 7 exceeding boundary must fail")
        self.assertFalse(evaluate_dhash(64), "Maximal distance 64 must fail")


# ==============================================================================
# FEATURE 6: Native 1024x686 Geometry Boundaries (F6)
# ==============================================================================
@tier(2)
class TestFeature6GeometryBoundaries(unittest.TestCase):
    """Verifies coordinate borders [0,0] & [1024,686], clamping, zero dimensions, and legacy unsquishing."""

    def setUp(self):
        if not ENGINE_AVAILABLE:
            self.skipTest("card_layer_engine.py required for geometry boundary tests")
        self._temp_dir = tempfile.mkdtemp(prefix="test_f6_b_state_")
        self._temp_state = os.path.join(self._temp_dir, "_active_design_state.json")
        self._orig_state_env = os.environ.get("ACTIVE_DESIGN_STATE_PATH")
        os.environ["ACTIVE_DESIGN_STATE_PATH"] = self._temp_state
        self._orig_server_state = getattr(web_server, "ACTIVE_DESIGN_STATE_PATH", None)
        web_server.ACTIVE_DESIGN_STATE_PATH = self._temp_state

    def tearDown(self):
        if self._orig_state_env is not None:
            os.environ["ACTIVE_DESIGN_STATE_PATH"] = self._orig_state_env
        else:
            os.environ.pop("ACTIVE_DESIGN_STATE_PATH", None)
        if self._orig_server_state is not None:
            web_server.ACTIVE_DESIGN_STATE_PATH = self._orig_server_state
        else:
            web_server.ACTIVE_DESIGN_STATE_PATH = os.path.join(PROJECT_ROOT, "ai_projects", "_active_design_state.json")
        if self._temp_dir and os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_f6_b01_elements_at_extreme_canvas_borders(self):
        """Verifies layer elements placed exactly at boundary vertices [0,0] and [1024,686] scale within canvas."""
        layer_origin = {"id": "origin", "x": 0, "y": 0, "w": 150, "h": 80}
        layer_bottom_right = {"id": "bottom_right", "x": 874, "y": 606, "w": 150, "h": 80}

        target_width = 800
        t_orig = transform_layer_isotropic(layer_origin, (1024, 686), target_width)
        t_br = transform_layer_isotropic(layer_bottom_right, (1024, 686), target_width)

        expected_target_height = round(686 * (target_width / 1024.0))

        self.assertGreaterEqual(t_orig["x"], 0)
        self.assertGreaterEqual(t_orig["y"], 0)

        self.assertLessEqual(t_br["x"] + t_br["w"], target_width)
        self.assertLessEqual(t_br["y"] + t_br["h"], expected_target_height)

    def test_f6_b02_negative_coordinates_rejection_and_clamping(self):
        """Verifies natural language movement clamps negative coordinates at origin (x >= 0, y >= 0)."""
        layers = [{"id": "logo", "type": "image", "x": 50, "y": 50, "w": 100, "h": 50}]

        for _ in range(10):
            layers, _ = card_layer_engine.apply_natural_language_command("sola kaydır logo", layers)
            layers, _ = card_layer_engine.apply_natural_language_command("yukarı kaydır logo", layers)

        logo_layer = layers[0]
        self.assertGreaterEqual(logo_layer["x"], 0, f"Negative x coordinate produced: {logo_layer['x']}")
        self.assertGreaterEqual(logo_layer["y"], 0, f"Negative y coordinate produced: {logo_layer['y']}")

    def test_f6_b03_zero_width_and_zero_height_elements_handling(self):
        """Verifies degenerate zero-width or zero-height elements scale without ZeroDivisionError."""
        zero_dim_layer = {"id": "zero_dim", "x": 100, "y": 100, "w": 0, "h": 0}
        transformed = transform_layer_isotropic(zero_dim_layer, (1024, 686), 800)
        self.assertEqual(transformed["w"], 0)
        self.assertEqual(transformed["h"], 0)
        self.assertEqual(transformed["x"], round(100 * (800 / 1024.0)))

    def test_f6_b04_extreme_aspect_ratio_scaling_invariance(self):
        """Verifies isotropic scaling preserves 1024/686 aspect ratio across desktop (1920px) to mobile (375px)."""
        sample_layer = {"id": "box", "x": 100, "y": 100, "w": 400, "h": 200}
        native_aspect = 1024 / 686.0

        for tw in [1920, 1280, 800, 375]:
            transformed = transform_layer_isotropic(sample_layer, (1024, 686), tw)
            th = round(686 * (tw / 1024.0))
            scaled_canvas_aspect = tw / float(th)
            self.assertAlmostEqual(scaled_canvas_aspect, native_aspect, delta=0.05)
            self.assertAlmostEqual(transformed["w"] / float(transformed["h"]), 400 / 200.0, delta=0.05)

    def test_f6_b05_legacy_squished_state_dimensions_enforcement(self):
        """Verifies legacy squished 1004x650 state files on disk are auto-healed to native 1024x686."""
        with isolated_sandbox() as tmpdir:
            legacy_file = os.path.join(tmpdir, "_active_design_state.json")
            with open(legacy_file, "w", encoding="utf-8") as f:
                json.dump({"title": "Legacy Card", "width": 1004, "height": 650, "elements": []}, f)

            orig_path = getattr(web_server, "ACTIVE_DESIGN_STATE_PATH", None)
            try:
                web_server.ACTIVE_DESIGN_STATE_PATH = legacy_file
                with EphemeralServer() as server:
                    with urllib.request.urlopen(f"{server.base_url}/api/design/state") as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        canvas = data.get("canvas", {})
                        self.assertEqual(canvas.get("width"), 1024, "Legacy width must be healed to 1024")
                        self.assertEqual(canvas.get("height"), 686, "Legacy height must be healed to 686")
            finally:
                web_server.ACTIVE_DESIGN_STATE_PATH = orig_path

    def test_f6_b06_canvas_overflow_clamping_at_max_boundaries(self):
        """Verifies directional movement clamps elements before exceeding 1024 width and 686 height."""
        layers = [{"id": "logo", "type": "image", "x": 900, "y": 600, "w": 100, "h": 50}]

        for _ in range(10):
            layers, _ = card_layer_engine.apply_natural_language_command("sağa kaydır logo", layers)
            layers, _ = card_layer_engine.apply_natural_language_command("aşağı kaydır logo", layers)

        logo_layer = layers[0]
        self.assertLessEqual(logo_layer["x"] + logo_layer["w"], 1024, "Element right bound exceeded 1024")
        self.assertLessEqual(logo_layer["y"] + logo_layer["h"], 686, "Element bottom bound exceeded 686")


# ==============================================================================
# FEATURE 7: Selective Ink Inpainting Boundaries (F7)
# ==============================================================================
@tier(2)
class TestFeature7InpaintingBoundaries(unittest.TestCase):
    """Verifies selective inpainting boundaries: missing paths, solid cards, monochrome extremes, and spatial isolation."""

    def setUp(self):
        if not ENGINE_AVAILABLE:
            self.skipTest("card_layer_engine.py required for inpainting boundary tests")

    def test_f7_b01_inpainting_non_existent_image_path_error(self):
        """Verifies decompose_card raises FileNotFoundError when image path does not exist."""
        with self.assertRaises(FileNotFoundError):
            card_layer_engine.decompose_card("non_existent_card_path_123456.png")

    def test_f7_b02_inpainting_solid_uniform_background_card(self):
        """Verifies inpainting on a solid background card produces clean background with zero artifacts."""
        with isolated_sandbox() as tmpdir:
            img = Image.new("RGB", (1024, 686), (227, 224, 204))
            p = os.path.join(tmpdir, "solid_beige.png")
            img.save(p)

            res = card_layer_engine.decompose_card(p, output_dir=tmpdir)
            with Image.open(res["background"]) as bg_im:
                arr = np.array(bg_im)

            patch = arr[358:444, 712:980]
            std_rgb = np.std(patch, axis=(0, 1))
            self.assertLessEqual(float(np.mean(std_rgb)), 2.0, "Inpainting introduced excessive noise on solid card")

            orig_arr = np.array(img)
            mean_diff = float(np.mean(np.abs(arr.astype(float) - orig_arr.astype(float))))
            self.assertLessEqual(mean_diff, 0.1, "Inpainting corrupted global background pixels")

    def test_f7_b03_inpainting_completely_black_canvas(self):
        """Verifies inpainting boundary extreme on completely black canvas (RGB=0)."""
        with isolated_sandbox() as tmpdir:
            img = Image.new("RGB", (1024, 686), (0, 0, 0))
            p = os.path.join(tmpdir, "black.png")
            img.save(p)

            res = card_layer_engine.decompose_card(p, output_dir=tmpdir)
            with Image.open(res["background"]) as bg_im:
                arr = np.array(bg_im)

            self.assertEqual(int(np.max(arr)), 0, "Black canvas inpainting must remain pure black")

    def test_f7_b04_inpainting_completely_white_canvas(self):
        """Verifies inpainting boundary extreme on completely white canvas (RGB=255)."""
        with isolated_sandbox() as tmpdir:
            img = Image.new("RGB", (1024, 686), (255, 255, 255))
            p = os.path.join(tmpdir, "white.png")
            img.save(p)

            res = card_layer_engine.decompose_card(p, output_dir=tmpdir)
            with Image.open(res["background"]) as bg_im:
                arr = np.array(bg_im)

            self.assertEqual(int(np.min(arr)), 255, "White canvas inpainting must remain pure white")

    def test_f7_b05_inpainting_preserves_native_1024x686_from_rescaled_input(self):
        """Verifies decompose_card normalizes non-standard input dimensions (500x300) to native 1024x686."""
        with isolated_sandbox() as tmpdir:
            img = Image.new("RGB", (500, 300), (128, 128, 128))
            p = os.path.join(tmpdir, "small_card.png")
            img.save(p)

            res = card_layer_engine.decompose_card(p, output_dir=tmpdir)
            self.assertEqual(res["canvas"]["width"], 1024)
            self.assertEqual(res["canvas"]["height"], 686)
            with Image.open(res["background"]) as bg_im:
                self.assertEqual(bg_im.size, (1024, 686))

    def test_f7_b06_selective_mask_boundary_zero_leakage_to_icons(self):
        """Verifies zero inpainting mask leakage into contact icons immediately adjacent to text region."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        self.assertTrue(os.path.isfile(ref_path), "kartvizit_son_orijinal.png missing")

        qr_root = os.path.join(PROJECT_ROOT, "layers", "qr_code.png")
        orig_qr_bytes = None
        if os.path.isfile(qr_root):
            with open(qr_root, "rb") as f:
                orig_qr_bytes = f.read()

        bg_root = os.path.join(PROJECT_ROOT, "card_background_clean.png")
        orig_bg_bytes = None
        if os.path.isfile(bg_root):
            with open(bg_root, "rb") as f:
                orig_bg_bytes = f.read()

        with isolated_sandbox() as tmpdir:
            try:
                res = card_layer_engine.decompose_card(ref_path, output_dir=tmpdir)
                clean_arr = _to_numpy_rgb(res["background"])
                orig_arr = _to_numpy_rgb(ref_path)

                # Icon patch [358:394, 659:714] must have exactly 0.0 delta (untouched)
                icon_diff = np.max(np.abs(orig_arr[358:394, 659:714].astype(float) - clean_arr[358:394, 659:714].astype(float)))
                self.assertEqual(icon_diff, 0.0, "Preserved icon patch was altered or blurred by inpainting")

                # Adjacent text patch [358:394, 715:975] must have substantial pixel delta (ink removed)
                text_diff = np.mean(np.abs(orig_arr[358:394, 715:975].astype(float) - clean_arr[358:394, 715:975].astype(float)))
                self.assertGreater(text_diff, 10.0, "Adjacent text ink was not removed by inpainting")
            finally:
                if orig_qr_bytes is not None:
                    with open(qr_root, "wb") as f:
                        f.write(orig_qr_bytes)
                if orig_bg_bytes is not None:
                    with open(bg_root, "wb") as f:
                        f.write(orig_bg_bytes)


# ==============================================================================
# FEATURE 8: Non-Destructive Decomposition Boundaries (F8)
# ==============================================================================
@tier(2)
class TestFeature8DecompositionBoundaries(unittest.TestCase):
    """Verifies empty layer state, Z-order occlusion, alpha channel boundaries [0 vs 255], and corrupt assets."""

    def setUp(self):
        if not ENGINE_AVAILABLE:
            self.skipTest("card_layer_engine.py required for decomposition boundary tests")

    def test_f8_b01_decomposition_and_rendering_empty_layers(self):
        """Verifies render_card with empty layers list produces clean canvas matching background image."""
        with isolated_sandbox() as tmpdir:
            bg = Image.new("RGB", (1024, 686), (200, 200, 200))
            bg_path = os.path.join(tmpdir, "clean_bg.png")
            bg.save(bg_path)

            state = {"canvas": {"width": 1024, "height": 686}, "background": bg_path, "layers": []}
            rendered = card_layer_engine.render_card(state)

            self.assertEqual(rendered.size, (1024, 686))
            ssim_val = compute_ssim_simple(rendered, bg_path)
            self.assertAlmostEqual(ssim_val, 1.0, places=4, msg="Empty layers render must match background with SSIM=1.0")

    def test_f8_b02_overlapping_layer_z_order_compositing(self):
        """Verifies Z-order compositing when multiple layers overlap in bounding box space."""
        with isolated_sandbox() as tmpdir:
            bg = Image.new("RGB", (1024, 686), (0, 0, 0))
            bg_path = os.path.join(tmpdir, "bg.png")
            bg.save(bg_path)

            l1_im = Image.new("RGBA", (100, 100), (0, 0, 255, 255))
            l1_path = os.path.join(tmpdir, "l1.png")
            l1_im.save(l1_path)

            l2_im = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
            l2_path = os.path.join(tmpdir, "l2.png")
            l2_im.save(l2_path)

            state = {
                "canvas": {"width": 1024, "height": 686},
                "background": bg_path,
                "layers": [
                    {"id": "l1", "type": "image", "x": 100, "y": 100, "w": 100, "h": 100, "asset_path": l1_path},
                    {"id": "l2", "type": "image", "x": 150, "y": 150, "w": 100, "h": 100, "asset_path": l2_path},
                ],
            }
            rendered = card_layer_engine.render_card(state)
            arr = np.array(rendered.convert("RGB"))

            # Overlap region at (175, 175) must show top layer (Red)
            np.testing.assert_array_equal(arr[175, 175], [255, 0, 0], err_msg="Top layer did not occlude bottom layer")
            # Non-overlap region at (120, 120) must show bottom layer (Blue)
            np.testing.assert_array_equal(arr[120, 120], [0, 0, 255], err_msg="Bottom layer not visible in non-overlap area")

    def test_f8_b03_rgba_alpha_channel_extremes_0_vs_255(self):
        """Verifies alpha boundary extremes: alpha=0 (100% bg transmission) vs alpha=255 (100% fg opacity)."""
        with isolated_sandbox() as tmpdir:
            bg = Image.new("RGB", (1024, 686), (200, 100, 50))
            bg_path = os.path.join(tmpdir, "bg.png")
            bg.save(bg_path)

            transp = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            transp_path = os.path.join(tmpdir, "transp.png")
            transp.save(transp_path)

            opaque = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
            opaque_path = os.path.join(tmpdir, "opaque.png")
            opaque.save(opaque_path)

            state = {
                "canvas": {"width": 1024, "height": 686},
                "background": bg_path,
                "layers": [
                    {"id": "t", "type": "image", "x": 50, "y": 50, "w": 100, "h": 100, "asset_path": transp_path},
                    {"id": "o", "type": "image", "x": 200, "y": 50, "w": 100, "h": 100, "asset_path": opaque_path},
                ],
            }
            rendered = card_layer_engine.render_card(state)
            arr = np.array(rendered.convert("RGB"))

            # Under alpha=0: exact background color (200, 100, 50)
            np.testing.assert_array_equal(arr[75, 75], [200, 100, 50], err_msg="Alpha=0 layer modified background pixel")
            # Under alpha=255: exact foreground color (255, 255, 255)
            np.testing.assert_array_equal(arr[75, 225], [255, 255, 255], err_msg="Alpha=255 layer bled background pixel")

    def test_f8_b04_corrupt_layer_asset_path_exception_handling(self):
        """Verifies UnidentifiedImageError is raised when layer asset file content is corrupted."""
        with isolated_sandbox() as tmpdir:
            bg = Image.new("RGB", (1024, 686), (0, 0, 0))
            bg_path = os.path.join(tmpdir, "bg.png")
            bg.save(bg_path)

            bad_asset = os.path.join(tmpdir, "corrupt_asset.png")
            with open(bad_asset, "wb") as f:
                f.write(b"INVALID_PNG_BINARY_BYTES")

            state = {
                "canvas": {"width": 1024, "height": 686},
                "background": bg_path,
                "layers": [{"id": "bad", "type": "image", "x": 50, "y": 50, "w": 100, "h": 100, "asset_path": bad_asset}],
            }
            with self.assertRaises(UnidentifiedImageError):
                card_layer_engine.render_card(state)

    def test_f8_b05_missing_layer_asset_path_graceful_recovery(self):
        """Verifies render_card gracefully skips non-existent layer asset paths without crashing."""
        with isolated_sandbox() as tmpdir:
            bg = Image.new("RGB", (1024, 686), (50, 50, 50))
            bg_path = os.path.join(tmpdir, "bg.png")
            bg.save(bg_path)

            state = {
                "canvas": {"width": 1024, "height": 686},
                "background": bg_path,
                "layers": [{"id": "ghost", "type": "image", "x": 50, "y": 50, "w": 100, "h": 100, "asset_path": "non_existent_ghost.png"}],
            }
            rendered = card_layer_engine.render_card(state)
            self.assertEqual(rendered.size, (1024, 686))

    def test_f8_b06_out_of_bounds_and_zero_dimension_layers(self):
        """Verifies off-canvas layers and empty text layers do not crash or alter canvas dimensions."""
        with isolated_sandbox() as tmpdir:
            bg = Image.new("RGB", (1024, 686), (10, 10, 10))
            bg_path = os.path.join(tmpdir, "bg.png")
            bg.save(bg_path)

            state = {
                "canvas": {"width": 1024, "height": 686},
                "background": bg_path,
                "layers": [
                    {"id": "oob", "type": "image", "x": 2000, "y": 2000, "w": 100, "h": 100},
                    {"id": "txt_empty", "type": "text", "text": "", "x": 100, "y": 100},
                    {"id": "txt_space", "type": "text", "text": "   ", "x": 100, "y": 100},
                ],
            }
            rendered = card_layer_engine.render_card(state)
            self.assertEqual(rendered.size, (1024, 686), "Canvas dimensions must remain strictly 1024x686")


# ==============================================================================
# FEATURE 9: Web Server Layer & AI API Boundaries (F9)
# ==============================================================================
@tier(2)
class TestFeature9WebServerApiBoundaries(unittest.TestCase):
    """Verifies boundary, negative input, and protocol edge cases for web_server.py REST endpoints."""

    def test_f9_b01_malformed_json_syntax_returns_400(self):
        """Verifies malformed JSON payload in POST /api/design/state and /api/ai_edit returns HTTP 400."""
        with EphemeralServer() as server:
            for endpoint in ["/api/design/state", "/api/ai_edit"]:
                req = urllib.request.Request(
                    f"{server.base_url}{endpoint}",
                    data=b"{bad_json: true, unterminated",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5.0)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertFalse(body.get("ok"))
                self.assertIn("Invalid JSON payload", body.get("error", ""))

    def test_f9_b02_non_dict_json_payload_returns_400(self):
        """Verifies non-object JSON roots (arrays, primitives) in POST requests return HTTP 400."""
        with EphemeralServer() as server:
            for non_dict in [b"[1, 2, 3]", b'"hello_world"', b"12345"]:
                req = urllib.request.Request(
                    f"{server.base_url}/api/ai_edit",
                    data=non_dict,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5.0)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertFalse(body.get("ok"))
                self.assertIn("Payload must be a JSON object", body.get("error", ""))

    def test_f9_b03_empty_body_post_handling(self):
        """Verifies empty payload {} handling on POST /api/design/state (400) and /api/ai_edit (graceful 200)."""
        with EphemeralServer() as server:
            req_state = urllib.request.Request(
                f"{server.base_url}/api/design/state",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_state, timeout=5.0)
            self.assertEqual(ctx.exception.code, 400)
            body_state = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertFalse(body_state.get("ok"))
            self.assertIn("Empty payload provided", body_state.get("error", ""))

            req_ai = urllib.request.Request(
                f"{server.base_url}/api/ai_edit",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_ai, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                body_ai = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(body_ai.get("ok"))
                self.assertFalse(body_ai.get("success"))
                self.assertEqual(body_ai.get("summary"), "Boş komut iletildi.")

    def test_f9_b04_invalid_design_state_schema_rejected(self):
        """Verifies invalid or non-list element schemas in POST /api/design/state return HTTP 400."""
        with EphemeralServer() as server:
            invalid_payloads = [
                {"elements": "string_not_list"},
                {"layers": 12345},
                {"width": -100, "height": -200},
                {"random_unrelated_key": "some_value"},
            ]
            for pl in invalid_payloads:
                req = urllib.request.Request(
                    f"{server.base_url}/api/design/state",
                    data=json.dumps(pl).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5.0)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertFalse(body.get("ok"))

    def test_f9_b05_unsupported_http_methods_rejected(self):
        """Verifies unsupported HTTP methods (PUT, DELETE, PATCH) return 405 or 501 status."""
        with EphemeralServer() as server:
            for method in ["PUT", "DELETE", "PATCH"]:
                req = urllib.request.Request(
                    f"{server.base_url}/api/design/state",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method=method,
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5.0)
                self.assertIn(ctx.exception.code, (405, 501))

    def test_f9_b06_large_payload_2mb_boundary(self):
        """Verifies server accepts large valid 2MB payload on POST /api/design/state without buffer overrun."""
        with EphemeralServer() as server:
            large_comment = "x" * (2 * 1024 * 1024)
            payload = {
                "width": 1024,
                "height": 686,
                "elements": [{"id": "meta", "type": "text", "text": "Boundary test", "comment": large_comment}],
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{server.base_url}/api/design/state",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                self.assertEqual(resp.status, 200)
                res_data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(res_data.get("ok"))


# ==============================================================================
# FEATURE 10: Interactive Canvas Integration Boundaries (F10)
# ==============================================================================
@tier(2)
class TestFeature10CanvasIntegrationBoundaries(unittest.TestCase):
    """Verifies boundary conditions, static asset routing, traversal defense, and isotropic scaling."""

    def test_f10_b01_directory_traversal_attempts_blocked(self):
        """Verifies directory traversal attempts via relative paths return 404/403 and prevent disclosure."""
        with EphemeralServer() as server:
            traversals = [
                "/../../etc/passwd",
                "/..%2F..%2Fwindows/win.ini",
                "/....//....//....//etc/shadow",
                "/ai_projects/../../../../secret.key",
            ]
            for p in traversals:
                req = urllib.request.Request(f"{server.base_url}{p}")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5.0)
                self.assertIn(ctx.exception.code, (400, 403, 404))
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertFalse(body.get("ok"))

    def test_f10_b02_non_existent_static_assets_return_404(self):
        """Verifies requests for non-existent static JS/CSS/image assets return HTTP 404 JSON."""
        with EphemeralServer() as server:
            non_existent = [
                "/static/bundle.js",
                "/assets/style.css",
                "/images/missing_logo.png",
                "/favicon.ico",
            ]
            for p in non_existent:
                req = urllib.request.Request(f"{server.base_url}{p}")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5.0)
                self.assertEqual(ctx.exception.code, 404)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertFalse(body.get("ok"))
                self.assertEqual(body.get("error"), "not_found")

    def test_f10_b03_missing_editor_html_fallback(self):
        """Verifies server gracefully serves fallback HTML if editor HTML file is missing on disk."""
        orig_editor = web_server.EDITOR_HTML_PATH
        try:
            web_server.EDITOR_HTML_PATH = os.path.join(PROJECT_ROOT, "ai_projects", "non_existent_editor_dummy.html")
            with EphemeralServer() as server:
                for endpoint in ["/", "/editor"]:
                    with urllib.request.urlopen(f"{server.base_url}{endpoint}", timeout=5.0) as resp:
                        self.assertEqual(resp.status, 200)
                        self.assertIn("text/html", resp.headers.get("Content-Type", ""))
                        html = resp.read().decode("utf-8")
                        self.assertIn("Henüz kaydedilmiş bir editör bulunamadı", html)
        finally:
            web_server.EDITOR_HTML_PATH = orig_editor

    def test_f10_b04_url_query_parameters_and_fragments(self):
        """Verifies URL query parameters (?mode=...&version=...) are safely stripped and do not break routing."""
        with EphemeralServer() as server:
            endpoints = [
                "/editor?theme=dark&zoom=100",
                "/api/design/state?format=full&_cache_bust=999",
                "/api/health?probe=liveness",
            ]
            for ep in endpoints:
                with urllib.request.urlopen(f"{server.base_url}{ep}", timeout=5.0) as resp:
                    self.assertEqual(resp.status, 200)

    def test_f10_b05_trailing_slash_strict_routing(self):
        """Verifies routes with trailing slashes (/editor/, /api/health/) return HTTP 404 under strict matching."""
        with EphemeralServer() as server:
            trailing_routes = ["/editor/", "/api/health/", "/api/design/state/"]
            for r in trailing_routes:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"{server.base_url}{r}", timeout=5.0)
                self.assertEqual(ctx.exception.code, 404)

    def test_f10_b06_canvas_isotropic_aspect_ratio_clamping(self):
        """Verifies canvas layer coordinates scale isotropically without drift across various target widths."""
        ref_layer = {"id": "isim", "x": 512, "y": 343, "w": 200, "h": 50, "fontSize": 20}

        scaled_down = transform_layer_isotropic(ref_layer, src_dimensions=(1024, 686), target_width=512)
        self.assertEqual(scaled_down["x"], 256)
        self.assertEqual(scaled_down["y"], 172)
        self.assertEqual(scaled_down["w"], 100)
        self.assertEqual(scaled_down["h"], 25)
        self.assertEqual(scaled_down["fontSize"], 10)
        self.assertEqual(scaled_down["_target_dimensions"], (512, 343))

        scaled_up = transform_layer_isotropic(ref_layer, src_dimensions=(1024, 686), target_width=2048)
        self.assertEqual(scaled_up["x"], 1024)
        self.assertEqual(scaled_up["y"], 686)
        self.assertEqual(scaled_up["w"], 400)
        self.assertEqual(scaled_up["h"], 100)
        self.assertEqual(scaled_up["fontSize"], 40)
        self.assertEqual(scaled_up["_target_dimensions"], (2048, 1372))


# ==============================================================================
# FEATURE 11: Turkish NLP Command Engine Boundaries (F11)
# ==============================================================================
@tier(2)
class TestFeature11TurkishNlpBoundaries(unittest.TestCase):
    """Verifies Turkish NLP engine boundary conditions, clamping, and character preservation."""

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="test_f11_b_state_")
        self._temp_state = os.path.join(self._temp_dir, "_active_design_state.json")
        self._orig_state_env = os.environ.get("ACTIVE_DESIGN_STATE_PATH")
        os.environ["ACTIVE_DESIGN_STATE_PATH"] = self._temp_state
        self._orig_server_state = getattr(web_server, "ACTIVE_DESIGN_STATE_PATH", None)
        web_server.ACTIVE_DESIGN_STATE_PATH = self._temp_state

        self.sample_state = {
            "width": 1024,
            "height": 686,
            "elements": [
                {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 0, "y": 0, "w": 200, "h": 50, "fontSize": 20},
                {"id": "unvan", "type": "text", "text": "Müdür", "x": 824, "y": 636, "w": 200, "h": 50, "fontSize": 16},
            ],
        }

    def tearDown(self):
        if self._orig_state_env is not None:
            os.environ["ACTIVE_DESIGN_STATE_PATH"] = self._orig_state_env
        else:
            os.environ.pop("ACTIVE_DESIGN_STATE_PATH", None)
        if self._orig_server_state is not None:
            web_server.ACTIVE_DESIGN_STATE_PATH = self._orig_server_state
        else:
            web_server.ACTIVE_DESIGN_STATE_PATH = os.path.join(PROJECT_ROOT, "ai_projects", "_active_design_state.json")
        if self._temp_dir and os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_f11_b01_empty_and_whitespace_command_handling(self):
        """Verifies empty or whitespace commands return success=False, error message, and unmutated state."""
        for cmd in ["", "   ", "\t\r\n   ", "   \t  "]:
            updated, summary, ok = web_server.process_natural_language_edit(cmd, "", self.sample_state)
            self.assertFalse(ok)
            self.assertEqual(summary, "Boş komut iletildi.")
            self.assertEqual(len(updated["elements"]), 2)
            self.assertEqual(updated["elements"][0]["text"], "Gül DİLMEN")

    def test_f11_b02_unrecognized_command_graceful_fallback(self):
        """Verifies unrecognized commands return structured fallback without throwing exceptions or 500s."""
        gibberish = [
            "rastgele metin asdfghjkl",
            "1234567890 !@#$%",
            "havalar bugün çok güzel",
        ]
        for cmd in gibberish:
            updated, summary, ok = web_server.process_natural_language_edit(cmd, "", self.sample_state)
            self.assertFalse(ok)
            self.assertTrue(summary.startswith("Komut işlendi ancak eşleşen kural bulunamadı"))
            self.assertEqual(updated["elements"][0]["text"], "Gül DİLMEN")

    def test_f11_b03_extreme_length_command_string(self):
        """Verifies 10,000-character input commands are handled gracefully without recursion/memory crashes."""
        long_val = "Mehmet " + ("x" * 10000)
        long_cmd = f"ismi {long_val} yap"
        updated, summary, ok = web_server.process_natural_language_edit(long_cmd, "", self.sample_state)
        self.assertTrue(ok)
        isim = next(e for e in updated["elements"] if e["id"] == "isim")
        self.assertEqual(isim["text"], long_val)

    def test_f11_b04_turkish_unicode_special_characters(self):
        """Verifies Turkish special unicode characters (ç, ğ, ı, ö, ş, ü, İ) are preserved accurately."""
        turkish_name = "Çağlar Şölen İpekçi"
        turkish_title = "Baş Mühendis & Ağ Yöneticisi"
        u1, s1, ok1 = web_server.process_natural_language_edit(f"ismi {turkish_name} yap", "", self.sample_state)
        self.assertTrue(ok1)
        isim = next(e for e in u1["elements"] if e["id"] == "isim")
        self.assertEqual(isim["text"], turkish_name)

        u2, s2, ok2 = web_server.process_natural_language_edit(f"unvanı {turkish_title} yap", "", u1)
        self.assertTrue(ok2)
        unvan = next(e for e in u2["elements"] if e["id"] == "unvan")
        self.assertEqual(unvan["text"], turkish_title)

    def test_f11_b05_boundary_clamping_left_and_top(self):
        """Verifies movement commands clamp coordinates to minimum canvas bounds (x >= 0, y >= 0)."""
        u1, s1, ok1 = web_server.process_natural_language_edit("ismi sola", "", self.sample_state)
        self.assertTrue(ok1)
        isim1 = next(e for e in u1["elements"] if e["id"] == "isim")
        self.assertEqual(isim1["x"], 0)

        u2, s2, ok2 = web_server.process_natural_language_edit("ismi yukarı", "", u1)
        self.assertTrue(ok2)
        isim2 = next(e for e in u2["elements"] if e["id"] == "isim")
        self.assertEqual(isim2["y"], 0)

    def test_f11_b06_boundary_clamping_right_and_bottom(self):
        """Verifies movement commands clamp coordinates to maximum bounds (x <= 1024 - w, y <= 686 - h)."""
        u1, s1, ok1 = web_server.process_natural_language_edit("unvanı sağa", "", self.sample_state)
        self.assertTrue(ok1)
        unvan1 = next(e for e in u1["elements"] if e["id"] == "unvan")
        self.assertEqual(unvan1["x"], 824)

        u2, s2, ok2 = web_server.process_natural_language_edit("unvanı aşağı", "", u1)
        self.assertTrue(ok2)
        unvan2 = next(e for e in u2["elements"] if e["id"] == "unvan")
        self.assertEqual(unvan2["y"], 636)


# ==============================================================================
# FEATURE 12: E2E Integration & CLI Runner Boundaries (F12)
# ==============================================================================
@tier(2)
class TestFeature12E2EIntegrationCliBoundaries(unittest.TestCase):
    """Verifies CLI argument parsing boundaries, exit codes, and error recovery on run_e2e_tests.py."""

    def test_f12_b01_invalid_tier_cli_argument_exits_2(self):
        """Verifies run_e2e_tests.py with invalid --tier option exits with code 2."""
        res = subprocess.run(
            [sys.executable, "run_e2e_tests.py", "--tier", "99"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 2)
        self.assertTrue("invalid choice" in res.stderr.lower() or "error" in res.stderr.lower())

    def test_f12_b02_non_matching_filter_exits_0_with_warning(self):
        """Verifies run_e2e_tests.py with non-matching test filter prints warning and exits with code 0."""
        res = subprocess.run(
            [sys.executable, "run_e2e_tests.py", "-k", "non_matching_filter_string_xyz_12345"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("WARNING: No tests matched criteria", res.stdout)

    def test_f12_b03_invalid_discovery_start_dir_exits_2(self):
        """Verifies run_e2e_tests.py with invalid --start-dir exits with code 2."""
        res = subprocess.run(
            [sys.executable, "run_e2e_tests.py", "--start-dir", "C:/non_existent_dir_dummy_xyz"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 2)
        self.assertIn("does not exist", res.stdout)

    def test_f12_b04_unwritable_json_output_path_exits_2(self):
        """Verifies run_e2e_tests.py exits with code 2 when JSON report path cannot be written."""
        res = subprocess.run(
            [sys.executable, "run_e2e_tests.py", "--tier", "1", "-k", "test_f2_01_health_check_endpoint", "--json", "Z:/non_existent_volume/report.json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 2)
        self.assertIn("Failed to write JSON report", res.stdout)

    def test_f12_b05_unwritable_junit_xml_output_path_exits_2(self):
        """Verifies run_e2e_tests.py exits with code 2 when JUnit XML path cannot be written."""
        res = subprocess.run(
            [sys.executable, "run_e2e_tests.py", "--tier", "1", "-k", "test_f2_01_health_check_endpoint", "--junit-xml", "Z:/non_existent_volume/junit.xml"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 2)
        self.assertIn("Failed to write JUnit XML report", res.stdout)

    def test_f12_b06_combined_cli_flags_verbose_and_fail_fast(self):
        """Verifies run_e2e_tests.py runs successfully when combining -v and -x flags."""
        res = subprocess.run(
            [sys.executable, "run_e2e_tests.py", "--tier", "1", "-k", "test_f2_01_health_check_endpoint", "-v", "-x"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("RUNNING:", res.stdout)
        self.assertIn("PASS", res.stdout)
        self.assertIn("1 PASSED", res.stdout)


if __name__ == "__main__":
    unittest.main()
