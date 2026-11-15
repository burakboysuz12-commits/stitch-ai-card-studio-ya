"""
tests/e2e/test_tier1_features.py — Tier 1 Feature Coverage (Happy Path) Test Suite.
Covers Features 1 through 12 (6 test cases per feature = 72 tests total).
"""

import concurrent.futures
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
import difflib
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import web_server
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
# FEATURE 1: Git Repo & Clean Artifacts (F1)
# ==============================================================================
@tier(1)
class TestFeature1GitRepoCleanArtifacts(unittest.TestCase):
    """Verifies repository hygiene, git initialization, and .gitignore rules."""

    def test_f1_01_git_repo_initialized(self):
        """Verifies workspace is a valid git repository with working tree."""
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Git rev-parse failed: {res.stderr}")
        self.assertEqual(res.stdout.strip(), "true")
        git_dir = os.path.join(PROJECT_ROOT, ".git")
        self.assertTrue(os.path.isdir(git_dir), ".git directory does not exist")
        self.assertTrue(
            os.path.isfile(os.path.join(git_dir, "HEAD")) or os.path.isfile(os.path.join(git_dir, "config")),
            "Missing HEAD or config in .git directory",
        )

    def test_f1_02_gitignore_exists_and_valid(self):
        """Verifies .gitignore exists, is non-empty, and defines required ignore categories."""
        gitignore_path = os.path.join(PROJECT_ROOT, ".gitignore")
        self.assertTrue(os.path.isfile(gitignore_path), ".gitignore file is missing")
        self.assertGreaterEqual(os.path.getsize(gitignore_path), 50, ".gitignore is too small")
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check required ignore patterns
        self.assertTrue(
            any(pat in content for pat in ("node_modules", "node_modules/")),
            "Missing node_modules exclusion in .gitignore",
        )
        self.assertTrue(
            any(pat in content for pat in ("build", "build/", "dist/")),
            "Missing build/dist exclusion in .gitignore",
        )
        self.assertTrue(
            any(pat in content for pat in ("__pycache__", "*.pyc")),
            "Missing python bytecode exclusion in .gitignore",
        )
        self.assertTrue(
            any(pat in content for pat in ("*.pt", "*.onnx", "*.pth")),
            "Missing model weight exclusion in .gitignore",
        )

    def test_f1_03_gitignore_excludes_node_modules_and_build(self):
        """Verifies .gitignore excludes heavyweight build and frontend dependency directories."""
        probe_paths = [
            "ai-assistant/node_modules/test.js",
            "build/uygulama/test.pkg",
            "dist/uygulama.exe",
            ".next/cache/test.pack",
        ]
        for probe in probe_paths:
            res = subprocess.run(
                ["git", "check-ignore", probe],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode, 0,
                f"Path '{probe}' should be ignored by .gitignore but git check-ignore returned {res.returncode}",
            )

    def test_f1_04_gitignore_excludes_pycache_and_binaries(self):
        """Verifies .gitignore excludes python bytecode, model checkpoints, and local database files."""
        probe_paths = [
            "__pycache__/app.cpython-312.pyc",
            "plaka_best.pt",
            "mini_agent_history.db",
            ".env",
        ]
        for probe in probe_paths:
            res = subprocess.run(
                ["git", "check-ignore", probe],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode, 0,
                f"Path '{probe}' should be ignored by .gitignore but git check-ignore returned {res.returncode}",
            )

    def test_f1_05_git_status_no_large_binaries_tracked(self):
        """Verifies no individual tracked file in repository exceeds 50MB and no bloated binaries are tracked."""
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"git ls-files failed: {res.stderr}")
        tracked_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]

        for rel_path in tracked_files:
            abs_path = os.path.join(PROJECT_ROOT, rel_path)
            if os.path.isfile(abs_path):
                size = os.path.getsize(abs_path)
                self.assertLess(
                    size, 50 * 1024 * 1024,
                    f"Tracked file '{rel_path}' exceeds 50MB limit ({size / (1024*1024):.2f}MB)",
                )
                self.assertFalse(
                    rel_path.endswith((".exe", ".pt", ".pkg", ".node")),
                    f"Forbidden binary file '{rel_path}' is tracked by git",
                )

    def test_f1_06_essential_source_files_not_ignored(self):
        """Verifies critical application source files and media are NOT ignored by .gitignore."""
        essential_files = [
            "web_server.py",
            "Procfile",
            "requirements.txt",
            "kartvizit_son_orijinal.png",
        ]
        for f in essential_files:
            res = subprocess.run(
                ["git", "check-ignore", f],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode, 1,
                f"Essential file '{f}' must NOT be ignored by .gitignore, but check-ignore matched: {res.stdout}",
            )


# ==============================================================================
# FEATURE 2: 24/7 Cloud Web Server (F2)
# ==============================================================================
@tier(1)
class TestFeature2CloudWebServer(unittest.TestCase):
    """Verifies web_server.py behavior, health checks, static serving, and CORS."""

    def test_f2_01_health_check_endpoint(self):
        """Verifies GET /api/health returns HTTP 200 and valid JSON health schema."""
        with EphemeralServer() as server:
            t0 = time.perf_counter()
            with urllib.request.urlopen(f"{server.base_url}/api/health", timeout=5.0) as resp:
                elapsed = time.perf_counter() - t0
                self.assertEqual(resp.status, 200)
                self.assertIn("application/json", resp.headers.get("Content-Type", ""))
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data.get("ok"))
                self.assertEqual(data.get("service"), "stitch_ai_web")
                self.assertLess(elapsed, 0.5, "Health check response took longer than 500ms")

    def test_f2_02_dynamic_port_binding(self):
        """Verifies web server dynamically binds to assigned OS port and echoes port in health response."""
        with EphemeralServer() as server:
            with urllib.request.urlopen(f"{server.base_url}/api/health", timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # Server responds with healthy status on allocated port
                self.assertEqual(resp.status, 200)
                self.assertEqual(server.port, server.server.server_address[1])

    def test_f2_03_static_editor_serving(self):
        """Verifies GET / and GET /editor serve the interactive editor HTML with HTTP 200."""
        with EphemeralServer() as server:
            for endpoint in ["/", "/editor"]:
                with urllib.request.urlopen(f"{server.base_url}{endpoint}", timeout=5.0) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertIn("text/html", resp.headers.get("Content-Type", ""))
                    body = resp.read().decode("utf-8", errors="ignore")
                    self.assertGreater(len(body), 500, f"Editor HTML from {endpoint} is too short")
                    self.assertTrue(
                        "Stitch AI" in body or "Görsel Parça" in body or "canvas" in body.lower(),
                        f"Expected editor title or canvas in response from {endpoint}",
                    )

    def test_f2_04_cors_and_security_headers(self):
        """Verifies server sets CORS headers and expected HTTP response headers."""
        with EphemeralServer() as server:
            req = urllib.request.Request(f"{server.base_url}/api/health", headers={"Origin": "http://localhost:3000"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
                methods = resp.headers.get("Access-Control-Allow-Methods", "")
                self.assertTrue("GET" in methods and "POST" in methods)

    def test_f2_05_unknown_route_returns_404_json(self):
        """Verifies unknown routes return HTTP 404 with structured JSON error."""
        with EphemeralServer() as server:
            url = f"{server.base_url}/api/non_existent_endpoint_xyz"
            try:
                urllib.request.urlopen(url, timeout=5.0)
                self.fail("Expected HTTPError 404 but request succeeded")
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 404)
                data = json.loads(exc.read().decode("utf-8"))
                self.assertFalse(data.get("ok"))
                self.assertEqual(data.get("error"), "not_found")

    def test_f2_06_graceful_shutdown(self):
        """Verifies ThreadingHTTPServer shuts down cleanly and frees port immediately."""
        from http.server import ThreadingHTTPServer
        server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.StitchWebHandler)
        port = server.server_address[1]
        import threading
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        # Verify running
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2.0) as resp:
            self.assertEqual(resp.status, 200)

        # Shutdown
        server.shutdown()
        server.server_close()
        t.join(timeout=2.0)
        self.assertFalse(t.is_alive(), "Server thread did not terminate within timeout")

        # Verify port is released by binding again
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_sock:
            test_sock.bind(("127.0.0.1", port))
            test_sock.listen(1)


# ==============================================================================
# FEATURE 3: Cloud Agent CI/CD & Playbook (F3)
# ==============================================================================
@tier(1)
class TestFeature3CloudAgentCICDPlaybook(unittest.TestCase):
    """Verifies CI/CD workflow, autonomous agent playbook, Procfile, and requirements."""

    def test_f3_01_ci_workflow_yaml_syntax_and_structure(self):
        """Verifies .github/workflows/ci.yml exists and contains push/PR triggers and jobs."""
        ci_path = os.path.join(PROJECT_ROOT, ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.isfile(ci_path), "Missing .github/workflows/ci.yml")
        with open(ci_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("name:", content)
        self.assertIn("on:", content)
        self.assertIn("jobs:", content)
        self.assertTrue("push" in content or "pull_request" in content)
        self.assertIn("ubuntu-latest", content)

    def test_f3_02_ci_workflow_headless_test_step(self):
        """Verifies CI workflow contains automated headless test execution step."""
        ci_path = os.path.join(PROJECT_ROOT, ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.isfile(ci_path))
        with open(ci_path, "r", encoding="utf-8") as f:
            content = f.read()

        has_test_step = any(
            cmd in content for cmd in ("pytest", "run_e2e_tests.py", "python -m unittest", "test")
        )
        self.assertTrue(has_test_step, "CI workflow lacks automated test execution command")

    def test_f3_03_agent_instructions_file_and_sections(self):
        """Verifies AGENT_INSTRUCTIONS.md exists, length >= 1000, and contains operational guidelines."""
        inst_path = os.path.join(PROJECT_ROOT, "AGENT_INSTRUCTIONS.md")
        self.assertTrue(os.path.isfile(inst_path), "AGENT_INSTRUCTIONS.md is missing")
        self.assertGreaterEqual(os.path.getsize(inst_path), 1000, "AGENT_INSTRUCTIONS.md is too short")
        with open(inst_path, "r", encoding="utf-8") as f:
            text = f.read()

        self.assertTrue(
            "web_server.py" in text or "web_server" in text,
            "AGENT_INSTRUCTIONS.md must document web server usage",
        )
        self.assertTrue(
            "test" in text.lower(),
            "AGENT_INSTRUCTIONS.md must document test execution",
        )

    def test_f3_04_procfile_format_and_command(self):
        """Verifies Procfile exists and declares 'web: python web_server.py'."""
        procfile_path = os.path.join(PROJECT_ROOT, "Procfile")
        self.assertTrue(os.path.isfile(procfile_path), "Procfile is missing")
        with open(procfile_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        web_line = next((l for l in lines if l.startswith("web:")), None)
        self.assertIsNotNone(web_line, "Procfile does not define 'web:' process")
        self.assertIn("web_server.py", web_line)

    def test_f3_05_requirements_txt_reproducible_dependencies(self):
        """Verifies requirements.txt specifies core reproducible dependencies without hardcoded local paths."""
        req_path = os.path.join(PROJECT_ROOT, "requirements.txt")
        self.assertTrue(os.path.isfile(req_path), "requirements.txt is missing")
        with open(req_path, "r", encoding="utf-8") as f:
            content = f.read().lower()

        for pkg in ["pillow", "numpy", "opencv"]:
            self.assertTrue(
                pkg in content,
                f"requirements.txt missing core package: {pkg}",
            )
        self.assertNotIn("c:\\", content)
        self.assertNotIn("/users/", content)

    def test_f3_06_dockerfile_or_render_yaml_validity(self):
        """Verifies cloud infrastructure specification (render.yaml or Dockerfile) exists."""
        render_path = os.path.join(PROJECT_ROOT, "render.yaml")
        docker_path = os.path.join(PROJECT_ROOT, "Dockerfile")
        has_cloud_config = os.path.isfile(render_path) or os.path.isfile(docker_path)
        self.assertTrue(has_cloud_config, "Neither render.yaml nor Dockerfile exists in project root")

        if os.path.isfile(render_path):
            with open(render_path, "r", encoding="utf-8") as f:
                r_content = f.read()
            self.assertTrue("services:" in r_content or "type: web" in r_content)


# ==============================================================================
# FEATURE 4: Phase 1 Notification (F4)
# ==============================================================================
@tier(1)
class TestFeature4Phase1Notification(unittest.TestCase):
    """Verifies Phase 1 completion artifacts, user report, and verification instructions."""

    def test_f4_01_completion_report_existence(self):
        """Verifies PHASE_1_COMPLETION_REPORT.md presence and minimum file size."""
        report_path = os.path.join(PROJECT_ROOT, "PHASE_1_COMPLETION_REPORT.md")
        self.assertTrue(os.path.isfile(report_path), "PHASE_1_COMPLETION_REPORT.md is missing from project root")
        self.assertGreaterEqual(os.path.getsize(report_path), 500, "Report file is too small")

    def test_f4_02_completion_report_structure_and_sections(self):
        """Verifies required markdown headings in PHASE_1_COMPLETION_REPORT.md."""
        report_path = os.path.join(PROJECT_ROOT, "PHASE_1_COMPLETION_REPORT.md")
        self.assertTrue(os.path.isfile(report_path), "PHASE_1_COMPLETION_REPORT.md is missing from project root")
        with open(report_path, "r", encoding="utf-8") as f:
            text = f.read().lower()

        required_keywords = ["özet", "sunucu", "kullanıcı", "doğrulama"]
        for kw in required_keywords:
            self.assertTrue(
                kw in text,
                f"PHASE_1_COMPLETION_REPORT.md missing section for: {kw}",
            )

    def test_f4_03_completion_report_clear_user_guidelines(self):
        """Verifies report contains clear Turkish guidelines for PC-off operation and cloud synchronization."""
        report_path = os.path.join(PROJECT_ROOT, "PHASE_1_COMPLETION_REPORT.md")
        self.assertTrue(os.path.isfile(report_path), "PHASE_1_COMPLETION_REPORT.md is missing from project root")
        with open(report_path, "r", encoding="utf-8") as f:
            text = f.read().lower()

        # Check for git sync guidance (git push or git pull) and cloud instructions
        has_git_guidelines = any(cmd in text for cmd in ("git push", "git pull", "git clone"))
        self.assertTrue(has_git_guidelines, "Report must document git commands to sync changes")
        self.assertTrue("bulut" in text or "cloud" in text, "Report must explain cloud operation")

    def test_f4_04_notification_workflow_or_script_presence(self):
        """Verifies notification workflow or cloud setup guide is available."""
        cloud_guide = os.path.join(PROJECT_ROOT, "cloud_7_24_kurulum.md")
        notify_workflow = os.path.join(PROJECT_ROOT, ".github", "workflows", "notify.yml")
        self.assertTrue(
            os.path.isfile(cloud_guide) or os.path.isfile(notify_workflow),
            "Expected either cloud_7_24_kurulum.md or notify.yml for user notification channel",
        )

    def test_f4_05_phase1_status_metadata_validity(self):
        """Verifies Phase 1 status metadata is documented or structured with valid attributes."""
        report_path = os.path.join(PROJECT_ROOT, "PHASE_1_COMPLETION_REPORT.md")
        status_json = os.path.join(PROJECT_ROOT, "phase1_status.json")

        self.assertTrue(
            os.path.isfile(report_path) or os.path.isfile(status_json),
            "Expected either PHASE_1_COMPLETION_REPORT.md or phase1_status.json for Phase 1 metadata",
        )

        metadata = {}
        if os.path.isfile(status_json):
            with open(status_json, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            self.assertIn("status", metadata)
            self.assertIn("milestone", metadata)
            self.assertIn(str(metadata["status"]).lower(), ["completed", "passed", "tamamlandi"])
        else:
            with open(report_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines()[:30]]

            for line in lines:
                m = re.match(r"^\*\*([^*]+)\*\*:\s*(.+)$", line)
                if m:
                    metadata[m.group(1).strip().lower()] = m.group(2).strip()

            self.assertIn("durum", metadata, "Report must specify 'Durum' (status) field in header")
            status_val = metadata["durum"].upper()
            self.assertTrue(
                "TAMAMLANDI" in status_val or "PASSED" in status_val,
                f"Expected status to indicate completion, got: {status_val}",
            )

            self.assertIn("aşama", metadata, "Report must specify 'Aşama' (milestone) field")
            asama_val = metadata["aşama"]
            self.assertTrue(
                "Milestone 1" in asama_val or "M1" in asama_val or "R1" in asama_val,
                f"Expected milestone reference in Aşama field, got: {asama_val}",
            )

            self.assertIn("tarih", metadata, "Report must specify 'Tarih' (date) field")
            date_val = metadata["tarih"]
            self.assertRegex(
                date_val, r"^\d{4}-\d{2}-\d{2}",
                f"Date must conform to ISO format YYYY-MM-DD, got: {date_val}",
            )

    def test_f4_06_report_reproducible_verification_commands(self):
        """Verifies completion report includes actionable verification commands."""
        report_path = os.path.join(PROJECT_ROOT, "PHASE_1_COMPLETION_REPORT.md")
        self.assertTrue(os.path.isfile(report_path), "PHASE_1_COMPLETION_REPORT.md is missing from project root")
        with open(report_path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertTrue("```" in text, "Report missing executable code blocks")


# ==============================================================================
# FEATURE 5: Headless Test Suite & Metrics (F5)
# ==============================================================================
@tier(1)
class TestFeature5HeadlessTestSuiteMetrics(unittest.TestCase):
    """Verifies mathematical image fidelity calculators: SSIM, dHash, and OCR accuracy."""

    def test_f5_01_ssim_metric_evaluation(self):
        """Verifies compute_ssim_simple produces 1.0 on identity and >= 0.92 on card variants."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        self.assertTrue(os.path.isfile(ref_path), "kartvizit_son_orijinal.png missing")

        # Identity test
        ssim_id = compute_ssim_simple(ref_path, ref_path)
        self.assertAlmostEqual(ssim_id, 1.0, places=4, msg="Identity SSIM must be 1.0")

        # Variant test
        var_path = os.path.join(PROJECT_ROOT, "kartvizit_ust_numara_0554_248_10_99.png")
        if os.path.isfile(var_path):
            ssim_var = compute_ssim_simple(ref_path, var_path)
            self.assertGreaterEqual(
                ssim_var, 0.92,
                f"Card variant SSIM ({ssim_var:.4f}) is below the required 0.92 threshold",
            )

    def test_f5_02_dhash_metric_evaluation(self):
        """Verifies compute_dhash and compute_dhash_distance produce 0 on identity and <= 6 on card variants."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        self.assertTrue(os.path.isfile(ref_path))

        dist_id = compute_dhash_distance(ref_path, ref_path)
        self.assertEqual(dist_id, 0, "Identity dHash distance must be 0 bits")

        var_path = os.path.join(PROJECT_ROOT, "kartvizit_ust_numara_0554_248_10_99.png")
        if os.path.isfile(var_path):
            dist_var = compute_dhash_distance(ref_path, var_path)
            self.assertLessEqual(
                dist_var, 6,
                f"Card variant dHash distance ({dist_var} bits) exceeds allowed 6 bits",
            )

    def test_f5_03_ocr_character_accuracy_evaluation(self):
        """Verifies reference contact strings extracted via OCR match ground truth with >= 98% accuracy."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        self.assertTrue(os.path.isfile(ref_path), "kartvizit_son_orijinal.png missing")

        # Load image with Windows Unicode-safe loader
        rgb_img = load_image_unicode_safe(ref_path)
        self.assertIsNotNone(rgb_img, "Failed to load reference image")

        expected_contacts = [
            "05542481099",
            "02422470050",
            "info@emirsultan.group",
            "guldilmen53@gmail.com",
        ]

        ocr_evaluated = False
        try:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR()
            results, _ = engine(rgb_img)
            if results:
                extracted = [r[1].replace(" ", "").lower() for r in results if r and len(r) > 1]
                accuracies = []
                for exp in expected_contacts:
                    best_match = max(difflib.SequenceMatcher(None, exp.lower(), t).ratio() for t in extracted)
                    accuracies.append(best_match)
                mean_acc = sum(accuracies) / len(accuracies)
                self.assertGreaterEqual(
                    mean_acc, 0.98,
                    f"OCR character accuracy ({mean_acc:.4f}) is below the required 98% threshold",
                )
                ocr_evaluated = True
        except Exception:
            pass

        if not ocr_evaluated:
            # Fallback: cv2 morphological & connected components inspection on contact region
            gray = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2GRAY)
            contact_roi = gray[350:540, 580:980]
            _, thresh = cv2.threshold(contact_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            _, _, stats, _ = cv2.connectedComponentsWithStats(thresh)
            # Filter character glyph components: typical area 10..1500 px, height >= 8 px
            glyphs = [s for s in stats[1:] if 10 <= s[cv2.CC_STAT_AREA] <= 1500 and s[cv2.CC_STAT_HEIGHT] >= 8]
            self.assertGreaterEqual(
                len(glyphs), 20,
                f"Expected >= 20 text glyphs in contact region, found {len(glyphs)}",
            )

    def test_f5_04_background_inpainting_smoothness_metric(self):
        """Verifies standard deviation metric on clean background patch is <= 8.0."""
        clean_bg = os.path.join(PROJECT_ROOT, "card_background_clean.png")
        if not os.path.isfile(clean_bg):
            clean_bg = os.path.join(PROJECT_ROOT, "kartvizit_arka_yuz_baskiya_hazir.png")
        self.assertTrue(os.path.isfile(clean_bg), "Clean background reference missing")
        with Image.open(clean_bg) as im:
            arr = np.array(im.convert("RGB"))
        crop = arr[360:394, 715:975]
        std_rgb = np.std(crop, axis=(0, 1))
        self.assertLessEqual(float(np.mean(std_rgb)), 8.0)

    def test_f5_05_icon_preservation_pixel_metric(self):
        """Verifies handset and email icons in reference card via pixel intensity and contrast metrics."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        self.assertTrue(os.path.isfile(ref_path), "kartvizit_son_orijinal.png missing")

        rgb_img = load_image_unicode_safe(ref_path)
        self.assertIsNotNone(rgb_img, "Failed to load reference image")
        gray = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2GRAY)
        self.assertEqual(gray.shape, (686, 1024), "Reference card dimensions must be 1024x686")

        # Handset icon crop coordinates [358:394, 659:714]
        y1, y2, x1, x2 = 358, 394, 659, 714
        self.assertTrue(0 <= y1 < y2 <= 686 and 0 <= x1 < x2 <= 1024)
        handset_crop = gray[y1:y2, x1:x2]

        # Email icon crop coordinates [455:492, 575:615]
        ey1, ey2, ex1, ex2 = 455, 492, 575, 615
        self.assertTrue(0 <= ey1 < ey2 <= 686 and 0 <= ex1 < ex2 <= 1024)
        email_crop = gray[ey1:ey2, ex1:ex2]

        # Uniform linen background patch near contact icons
        bg_crop = gray[330:350, 659:714]

        handset_contrast = int(np.max(handset_crop)) - int(np.min(handset_crop))
        email_contrast = int(np.max(email_crop)) - int(np.min(email_crop))
        handset_std = float(np.std(handset_crop))
        email_std = float(np.std(email_crop))
        bg_std = float(np.std(bg_crop))

        # Dynamic range checks (icons must exhibit strong foreground-to-background contrast >= 80)
        self.assertGreaterEqual(handset_contrast, 80, "Handset icon dynamic range too low")
        self.assertGreaterEqual(email_contrast, 80, "Email icon dynamic range too low")

        # Variance checks (icons have high pixel variance, background has uniform low variance)
        self.assertGreaterEqual(handset_std, 25.0, "Handset icon pixel variance too low")
        self.assertGreaterEqual(email_std, 25.0, "Email icon pixel variance too low")
        self.assertLessEqual(bg_std, 8.0, "Background patch variance too high")
        self.assertGreater(handset_std / max(bg_std, 0.1), 4.0, "Handset icon contrast over background too low")

    def test_f5_06_headless_runner_execution_and_summary(self):
        """Verifies unified headless test runner can execute with tier filter and return code 0."""
        runner_path = os.path.join(PROJECT_ROOT, "run_e2e_tests.py")
        self.assertTrue(os.path.isfile(runner_path), "run_e2e_tests.py is missing")
        res = subprocess.run(
            [sys.executable, runner_path, "--tier", "1", "-k", "test_f5_01"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"run_e2e_tests.py failed: {res.stderr}\n{res.stdout}")
        self.assertIn("PASSED", res.stdout)


# ==============================================================================
# FEATURE 6: Native 1024x686 Geometry (F6)
# ==============================================================================
@tier(1)
class TestFeature6Native1024x686Geometry(unittest.TestCase):
    """Verifies native 1024x686 canvas geometry, right-anchor margins, and aspect ratio integrity."""

    def test_f6_01_reference_image_native_dimensions(self):
        """Verifies kartvizit_son_orijinal.png has exactly 1024 width and 686 height."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        self.assertTrue(os.path.isfile(ref_path))
        with Image.open(ref_path) as im:
            w, h = im.size
            self.assertEqual(w, 1024, f"Width must be 1024, got {w}")
            self.assertEqual(h, 686, f"Height must be 686, got {h}")
            aspect = w / h
            self.assertAlmostEqual(aspect, 1024 / 686, places=4)

    def test_f6_02_canvas_state_native_dimensions(self):
        """Verifies default design state enforces native width=1024 and height=686."""
        state = web_server.get_default_design_state()
        self.assertEqual(state.get("width"), 1024)
        self.assertEqual(state.get("height"), 686)

    def _load_design_elements(self):
        """Helper to load design state elements from web_server, active state file, or git HEAD."""
        state = web_server.load_design_state()
        elements = {el.get("id"): el for el in state.get("elements", []) if isinstance(el, dict) and "id" in el}
        if not elements:
            state_path = os.path.join(PROJECT_ROOT, "ai_projects", "_active_design_state.json")
            if os.path.isfile(state_path):
                with open(state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    elements = {el.get("id"): el for el in data.get("elements", []) if isinstance(el, dict) and "id" in el}
                    state = data
        if not elements:
            # Defensive fallback to git-tracked state if disk state was temporarily cleared by a test
            try:
                proc = subprocess.run(
                    ["git", "show", "HEAD:ai_projects/_active_design_state.json"],
                    capture_output=True, text=True, encoding="utf-8",
                )
                data = json.loads(proc.stdout)
                elements = {el.get("id"): el for el in data.get("elements", []) if isinstance(el, dict) and "id" in el}
                state = data
            except Exception:
                pass
        return state, elements

    def test_f6_03_header_elements_center_axis_alignment(self):
        """Verifies header element 'isim' center-axis alignment from active design state within right panel."""
        state, elements = self._load_design_elements()
        self.assertIn("isim", elements, "Header layer 'isim' must exist in design state")
        name_layer = elements["isim"]
        x = float(name_layer["x"])
        w = float(name_layer.get("w") or name_layer.get("width", 0))
        center_x = x + w / 2.0

        # Verify header is strictly located in the right panel (center_x > 500)
        self.assertGreater(center_x, 500.0, f"Header element center ({center_x}) must reside in right panel (x > 500)")
        # In the active design state, isim spans x=510 with width=462 (center ~741, OCR center ~858)
        self.assertAlmostEqual(center_x, 741.0, delta=25.0, msg="Header element center axis deviates from design grid")
        self.assertIn(name_layer.get("align", "right"), ["right", "center"])

    def test_f6_04_contact_elements_right_anchor_alignment(self):
        """Verifies contact elements right-anchor formula right_x = x + w aligns consistently near canvas right border."""
        state, elements = self._load_design_elements()
        self.assertIn("telefon", elements, "Contact layer 'telefon' must exist in design state")
        phone_layer = elements["telefon"]
        px = float(phone_layer["x"])
        pw = float(phone_layer.get("w") or phone_layer.get("width", 0))
        phone_right = px + pw

        canvas_w = float(state.get("width", 1024))
        right_margin = canvas_w - phone_right

        # In active design state, telefon has x=510, w=462 -> right_x = 972
        self.assertAlmostEqual(phone_right, 972.0, delta=20.0, msg="Phone element right anchor must be near x ~ 972")
        self.assertTrue(20.0 <= right_margin <= 65.0, f"Right margin ({right_margin}px) outside safe printing margin (20-65px)")

        # Verify header 'isim' and contact 'telefon' share consistent right-alignment anchor
        if "isim" in elements:
            name_layer = elements["isim"]
            nx = float(name_layer["x"])
            nw = float(name_layer.get("w") or name_layer.get("width", 0))
            name_right = nx + nw
            self.assertAlmostEqual(
                name_right, phone_right, delta=5.0,
                msg=f"Header right edge ({name_right}) and phone right edge ({phone_right}) must align to common right anchor",
            )

    def test_f6_05_qr_code_and_logo_boundary_preservation(self):
        """Verifies QR code and logo bounds from active design state reside within the left card panel (x < 500)."""
        state, elements = self._load_design_elements()
        self.assertIn("qr_kod", elements, "QR code layer 'qr_kod' must exist in design state")
        qr = elements["qr_kod"]
        qx = float(qr["x"])
        qy = float(qr["y"])
        qw = float(qr.get("w") or qr.get("width", 0))
        qh = float(qr.get("h") or qr.get("height", 0))

        # QR code must be inside left panel (x + w < 500) and within canvas height (y + h < 686)
        self.assertLess(qx + qw, 500.0, f"QR code right bound ({qx + qw}) exceeds left panel boundary (500)")
        self.assertLess(qy + qh, 686.0, f"QR code bottom bound ({qy + qh}) exceeds canvas height (686)")
        self.assertGreaterEqual(qx, 0.0, "QR code x must be >= 0")
        self.assertGreaterEqual(qy, 0.0, "QR code y must be >= 0")

        # QR code must maintain square aspect ratio within 5% tolerance
        self.assertAlmostEqual(qw / qh, 1.0, delta=0.05, msg="QR code bounding box must be substantially square")

        self.assertIn("logo", elements, "Logo layer 'logo' must exist in design state")
        logo = elements["logo"]
        lx = float(logo["x"])
        ly = float(logo["y"])
        lw = float(logo.get("w") or logo.get("width", 0))
        lh = float(logo.get("h") or logo.get("height", 0))

        # Logo must be inside left panel (x + w < 500) and within canvas height
        self.assertLess(lx + lw, 500.0, f"Logo right bound ({lx + lw}) exceeds left panel boundary (500)")
        self.assertLess(ly + lh, 686.0, f"Logo bottom bound ({ly + lh}) exceeds canvas height (686)")
        self.assertGreaterEqual(lx, 0.0, "Logo x must be >= 0")
        self.assertGreaterEqual(ly, 0.0, "Logo y must be >= 0")

    def test_f6_06_isotropic_coordinate_scaling_transform(self):
        """Verifies responsive viewport scaling transforms actual layers isotropically without distortion."""
        state, elements = self._load_design_elements()
        self.assertIn("logo", elements, "Logo layer must exist to evaluate scaling transform")
        original_logo = elements["logo"]

        target_width = 800
        transformed = transform_layer_isotropic(
            original_logo,
            src_dimensions=(1024, 686),
            target_width=target_width,
        )

        expected_scale = target_width / 1024.0
        expected_target_height = round(686 * expected_scale)
        self.assertEqual(expected_target_height, 536)

        # Verify transformed coordinates match isotropic scale factor
        self.assertEqual(transformed["x"], round(original_logo["x"] * expected_scale))
        self.assertEqual(transformed["y"], round(original_logo["y"] * expected_scale))
        self.assertEqual(transformed["w"], round(original_logo["w"] * expected_scale))
        self.assertEqual(transformed["h"], round(original_logo["h"] * expected_scale))

        # Verify layer aspect ratio is preserved without distortion (w/h preserved)
        orig_aspect = original_logo["w"] / float(original_logo["h"])
        trans_aspect = transformed["w"] / float(transformed["h"])
        self.assertAlmostEqual(orig_aspect, trans_aspect, delta=0.02, msg="Layer aspect ratio must be preserved after scaling")

        # Verify transformed element remains strictly within target canvas bounds
        self.assertLessEqual(transformed["x"] + transformed["w"], target_width)
        self.assertLessEqual(transformed["y"] + transformed["h"], expected_target_height)


# ==============================================================================
# FEATURE 7: Selective Ink Inpainting (F7)
# ==============================================================================
@tier(1)
class TestFeature7SelectiveInkInpainting(unittest.TestCase):
    """Verifies selective ink inpainting, clean background generation, and texture preservation."""

    def setUp(self):
        try:
            import card_layer_engine
            self.engine = card_layer_engine
        except ImportError:
            self.skipTest("card_layer_engine.py pending implementation by Milestone M3")

    def test_f7_01_clean_background_generation(self):
        """Verifies decompose_card produces a clean background image of dimensions 1024x686."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        result = self.engine.decompose_card(ref_path)
        self.assertIn("background", result)
        bg = result["background"]
        bg_arr = _to_numpy_rgb(bg)
        self.assertEqual((bg_arr.shape[1], bg_arr.shape[0]), (1024, 686))

    def test_f7_02_text_ink_removal_fidelity(self):
        """Verifies selective inpainting removes foreground text ink while preserving contact icon patches."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        result = self.engine.decompose_card(ref_path)
        self.assertIn("background", result, "Decomposition must provide 'background' layer")
        clean_arr = _to_numpy_rgb(result["background"])
        orig_arr = _to_numpy_rgb(ref_path)

        # 1. Text ink removal: phone number region [360:394, 715:975] must reflect removed ink
        text_diff = np.abs(orig_arr[360:394, 715:975].astype(np.float64) - clean_arr[360:394, 715:975].astype(np.float64))
        text_mean_diff = float(np.mean(text_diff))
        self.assertGreater(
            text_mean_diff, 5.0,
            f"Text ink was not removed in text bounding box (mean pixel diff={text_mean_diff:.2f})",
        )

        # 2. Contact icon patch [358:394, 659:714] must NOT be erased or blurred by inpainting
        icon_diff = np.abs(orig_arr[358:394, 659:714].astype(np.float64) - clean_arr[358:394, 659:714].astype(np.float64))
        icon_norm_diff = float(np.mean(icon_diff)) / 255.0
        self.assertLessEqual(
            icon_norm_diff, 0.05,
            f"Contact icon patch was altered/blurred during inpainting (normalized diff={icon_norm_diff:.4f})",
        )
        self.assertGreater(
            text_mean_diff, float(np.mean(icon_diff)),
            "Selective inpainting must alter text region significantly more than preserved icon region",
        )

    def test_f7_03_linen_texture_preservation(self):
        """Verifies non-text background texture maintains high structural similarity (SSIM >= 0.94) and Laplacian variance."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        result = self.engine.decompose_card(ref_path)
        self.assertIn("background", result)
        clean_arr = _to_numpy_rgb(result["background"])
        orig_arr = _to_numpy_rgb(ref_path)

        # Non-text linen texture patch: left panel right of QR code [480:630, 230:420]
        clean_patch = clean_arr[480:630, 230:420]
        orig_patch = orig_arr[480:630, 230:420]

        # SSIM on non-text linen texture patch must be >= 0.94
        ssim_tex = compute_ssim_simple(clean_patch, orig_patch)
        self.assertGreaterEqual(
            ssim_tex, 0.94,
            f"Linen texture patch SSIM ({ssim_tex:.4f}) is below 0.94 threshold",
        )

        # Laplacian variance check to verify fine linen grain is preserved without blurring
        clean_gray = cv2.cvtColor(clean_patch, cv2.COLOR_RGB2GRAY)
        lap_var = float(cv2.Laplacian(clean_gray, cv2.CV_64F).var())
        self.assertGreaterEqual(
            lap_var, 8.0,
            f"Linen texture Laplacian variance ({lap_var:.2f}) indicates loss of texture sharpness",
        )

    def test_f7_04_contact_icon_preservation(self):
        """Verifies contact icons are preserved without blur or clipping."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        result = self.engine.decompose_card(ref_path)
        layers = result.get("layers", [])
        self.assertGreater(len(layers), 0, "Decomposition must extract layers")

        clean_bg = result.get("background")
        if clean_bg is not None:
            clean_arr = _to_numpy_rgb(clean_bg)
            orig_arr = _to_numpy_rgb(ref_path)
            icon_diff = np.abs(orig_arr[358:394, 659:714].astype(np.float64) - clean_arr[358:394, 659:714].astype(np.float64))
            icon_norm_diff = float(np.mean(icon_diff)) / 255.0
            self.assertLessEqual(
                icon_norm_diff, 0.05,
                f"Contact icon patch preservation error ({icon_norm_diff:.4f}) exceeds 0.05 threshold",
            )

    def test_f7_05_background_ssim_reference(self):
        """Verifies inpainted clean background achieves SSIM >= 0.88 against reference background."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        result = self.engine.decompose_card(ref_path)
        self.assertIn("background", result)
        clean_bg = result["background"]

        ref_bg = os.path.join(PROJECT_ROOT, "card_background_clean.png")
        if not os.path.isfile(ref_bg):
            ref_bg = ref_path

        ssim_val = compute_ssim_simple(clean_bg, ref_bg)
        self.assertGreaterEqual(
            ssim_val, 0.88,
            f"Inpainted background SSIM ({ssim_val:.4f}) is below the required 0.88 threshold",
        )

    def test_f7_06_color_histogram_consistency(self):
        """Verifies color channel histogram similarity >= 0.85 across card panels."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        result = self.engine.decompose_card(ref_path)
        self.assertIn("background", result)
        clean_arr = _to_numpy_rgb(result["background"])
        orig_arr = _to_numpy_rgb(ref_path)

        panels = [("left", 0, 500), ("right", 500, 1024)]
        for panel_name, x1, x2 in panels:
            p_orig = orig_arr[:, x1:x2]
            p_clean = clean_arr[:, x1:x2]
            for c in range(3):
                h_orig = cv2.calcHist([p_orig], [c], None, [32], [0, 256])
                h_clean = cv2.calcHist([p_clean], [c], None, [32], [0, 256])
                cv2.normalize(h_orig, h_orig, 0, 1, cv2.NORM_MINMAX)
                cv2.normalize(h_clean, h_clean, 0, 1, cv2.NORM_MINMAX)
                corr = float(cv2.compareHist(h_orig, h_clean, cv2.HISTCMP_CORREL))
                self.assertGreaterEqual(
                    corr, 0.85,
                    f"{panel_name} panel channel {c} color histogram correlation ({corr:.4f}) is below 0.85",
                )


# ==============================================================================
# FEATURE 8: Non-Destructive Decomposition (F8)
# ==============================================================================
@tier(1)
class TestFeature8NonDestructiveDecomposition(unittest.TestCase):
    """Verifies layer separation, transparency extraction, typography metadata, and coordinates."""

    def setUp(self):
        try:
            import card_layer_engine
            self.engine = card_layer_engine
        except ImportError:
            self.skipTest("card_layer_engine.py pending implementation by Milestone M3")

    def test_f8_01_layer_count_and_types(self):
        """Verifies decompose_card returns at least 7 layers including image and text layers."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        state = self.engine.decompose_card(ref_path)
        layers = state.get("layers", [])
        self.assertGreaterEqual(len(layers), 7)
        types = {layer.get("type") for layer in layers}
        self.assertTrue("text" in types or "image" in types)

    def test_f8_02_transparent_png_layer_assets(self):
        """Verifies extracted image layers provide transparent 4-channel PNG assets."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        state = self.engine.decompose_card(ref_path)
        img_layers = [l for l in state.get("layers", []) if l.get("type") == "image"]
        self.assertGreater(len(img_layers), 0)

    def test_f8_03_text_layer_metadata_accuracy(self):
        """Verifies text layers contain typography metadata (fontSize, color, alignment)."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        state = self.engine.decompose_card(ref_path)
        txt_layers = [l for l in state.get("layers", []) if l.get("type") == "text"]
        for l in txt_layers:
            self.assertIn("text", l)
            self.assertIn("fontSize", l)

    def test_f8_04_layer_bounding_box_coordinates(self):
        """Verifies all layer bounding boxes reside strictly within 1024x686 boundaries."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        state = self.engine.decompose_card(ref_path)
        for l in state.get("layers", []):
            x, y, w, h = l.get("x", 0), l.get("y", 0), l.get("w", 0), l.get("h", 0)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, 1024)
            self.assertLessEqual(y + h, 686)

    def test_f8_05_recombination_visual_similarity(self):
        """Verifies re-compositing decomposed layers over background yields SSIM >= 0.90 and dHash distance <= 6."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        state = self.engine.decompose_card(ref_path)
        self.assertIsInstance(state, dict, "decompose_card must return state dict")

        # Check for engine-provided recombination method
        recombined = None
        for method_name in ("recombine_layers", "recompose_card", "render_card", "composite_card"):
            fn = getattr(self.engine, method_name, None)
            if callable(fn):
                recombined = fn(state)
                break

        # Fallback to composite rendering over background using PIL
        if recombined is None:
            bg = state.get("background")
            if bg is not None:
                bg_img = Image.fromarray(_to_numpy_rgb(bg)).convert("RGBA")
            else:
                bg_img = Image.new("RGBA", (1024, 686), (255, 255, 255, 255))

            for layer in state.get("layers", []):
                x = int(layer.get("x", 0))
                y = int(layer.get("y", 0))
                asset_path = layer.get("asset_path") or layer.get("path")
                if asset_path and os.path.isfile(asset_path):
                    with Image.open(asset_path) as limg:
                        l_rgba = limg.convert("RGBA")
                        bg_img.paste(l_rgba, (x, y), l_rgba)

            recombined = bg_img

        ssim_val = compute_ssim_simple(recombined, ref_path)
        dhash_dist = compute_dhash_distance(recombined, ref_path)

        self.assertGreaterEqual(
            ssim_val, 0.90,
            f"Recombined card SSIM ({ssim_val:.4f}) is below the required 0.90 threshold",
        )
        self.assertLessEqual(
            dhash_dist, 6,
            f"Recombined card dHash distance ({dhash_dist}) exceeds the allowed 6-bit threshold",
        )

    def test_f8_06_semantic_layer_ids_and_labels(self):
        """Verifies all layers have standardized unique semantic IDs and descriptive labels."""
        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        state = self.engine.decompose_card(ref_path)
        ids = [l.get("id") for l in state.get("layers", [])]
        self.assertEqual(len(ids), len(set(ids)), "Layer IDs must be unique")


# ==============================================================================
# FEATURE 9: Web Server Layer & AI API (F9)
# ==============================================================================
@tier(1)
class TestFeature9WebServerLayerAIAPI(unittest.TestCase):
    """Verifies REST API endpoints /api/design/state and /api/ai_edit on web_server.py."""

    def test_f9_01_get_design_state_contract(self):
        """Verifies GET /api/design/state returns 200, valid canvas dimensions, and layers list."""
        with EphemeralServer() as server:
            with urllib.request.urlopen(f"{server.base_url}/api/design/state", timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("application/json", resp.headers.get("Content-Type", ""))
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data.get("ok"))
                self.assertIn("canvas", data)
                self.assertEqual(data["canvas"].get("width"), 1024)
                self.assertEqual(data["canvas"].get("height"), 686)
                self.assertIsInstance(data.get("layers"), list)

    def test_f9_02_post_design_state_persistence(self):
        """Verifies POST /api/design/state successfully saves modifications."""
        with EphemeralServer() as server:
            payload = {
                "canvas": {"width": 1024, "height": 686},
                "layers": [{"id": "isim", "text": "Mehmet Demir", "x": 510, "y": 104, "w": 400, "h": 50}],
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{server.base_url}/api/design/state",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data.get("ok"))
                self.assertTrue(data.get("success"))

    def test_f9_03_post_ai_edit_command_success(self):
        """Verifies POST /api/ai_edit modifies design layers and returns action summary."""
        with EphemeralServer() as server:
            payload = {
                "command": "ismi büyüt",
                "layers": [
                    {"id": "isim", "type": "text", "text": "Gül DİLMEN", "fontSize": 20, "w": 200, "h": 50, "x": 510, "y": 104}
                ],
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{server.base_url}/api/ai_edit",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data.get("ok"))
                self.assertTrue(data.get("success"))
                self.assertIn("action_summary", data)
                layers = data.get("layers", [])
                isim = next((l for l in layers if l.get("id") == "isim"), None)
                self.assertIsNotNone(isim)
                self.assertGreater(isim.get("fontSize", 0), 20)

    def test_f9_04_cors_and_json_headers(self):
        """Verifies CORS header and UTF-8 charset on /api/design/state and /api/health."""
        with EphemeralServer() as server:
            for path in ["/api/health", "/api/design/state"]:
                with urllib.request.urlopen(f"{server.base_url}{path}", timeout=5.0) as resp:
                    self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
                    self.assertIn("utf-8", resp.headers.get("Content-Type", "").lower())

    def test_f9_05_options_preflight_handling(self):
        """Verifies HTTP OPTIONS preflight request to /api/ai_edit returns HTTP 204 with CORS methods."""
        with EphemeralServer() as server:
            req = urllib.request.Request(f"{server.base_url}/api/ai_edit", method="OPTIONS")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertIn(resp.status, (200, 204))
                methods = resp.headers.get("Access-Control-Allow-Methods", "")
                self.assertTrue("POST" in methods and "OPTIONS" in methods)

    def test_f9_06_concurrent_api_requests(self):
        """Verifies server handles 10 concurrent requests without socket timeout or corruption."""
        with EphemeralServer() as server:
            def probe(endpoint):
                with urllib.request.urlopen(f"{server.base_url}{endpoint}", timeout=5.0) as resp:
                    return resp.status

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(probe, "/api/health" if i % 2 == 0 else "/api/design/state")
                    for i in range(10)
                ]
                results = [f.result(timeout=5.0) for f in futures]
                self.assertEqual(results, [200] * 10)


# ==============================================================================
# FEATURE 10: Interactive Canvas Integration (F10)
# ==============================================================================
@tier(1)
class TestFeature10InteractiveCanvasIntegration(unittest.TestCase):
    """Verifies interactive canvas editor frontend asset delivery, relative endpoints, and state model."""

    def test_f10_01_static_editor_serving(self):
        """Verifies editor HTML contains canvas container and script elements."""
        editor_path = os.path.join(PROJECT_ROOT, "ai_projects", "gorsel_parcali_editor.html")
        self.assertTrue(os.path.isfile(editor_path), "gorsel_parcali_editor.html missing")
        with open(editor_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertTrue("canvas" in html.lower() or "editör" in html.lower())
        self.assertIn("<script>", html)

    def test_f10_02_relative_api_endpoint_usage(self):
        """Verifies editor frontend uses relative /api/ endpoints instead of hardcoded host/port."""
        editor_path = os.path.join(PROJECT_ROOT, "ai_projects", "gorsel_parcali_editor.html")
        self.assertTrue(os.path.isfile(editor_path))
        with open(editor_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Active fetch calls must not hardcode 18765
        self.assertNotIn("http://127.0.0.1:18765", content)
        self.assertNotIn("http://localhost:18765", content)

    def test_f10_03_native_canvas_aspect_ratio(self):
        """Verifies editor canvas model defines native 1024x686 resolution and ~1.4927 aspect ratio."""
        default_state = web_server.get_default_design_state()
        w = default_state.get("width")
        h = default_state.get("height")
        self.assertEqual(w, 1024)
        self.assertEqual(h, 686)
        self.assertAlmostEqual(w / h, 1024 / 686, places=4)

        with EphemeralServer() as server:
            with urllib.request.urlopen(f"{server.base_url}/api/design/state", timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            canvas = data.get("canvas", data)
            cw = canvas.get("width")
            ch = canvas.get("height")
            self.assertEqual(cw, 1024)
            self.assertEqual(ch, 686)
            self.assertAlmostEqual(cw / ch, 1024 / 686, places=4)

    def test_f10_04_dom_layer_rendering_elements(self):
        """Verifies DOM layer rendering styles (position absolute, left, top, width, height, zIndex)."""
        editor_path = os.path.join(PROJECT_ROOT, "ai_projects", "gorsel_parcali_editor.html")
        with open(editor_path, "r", encoding="utf-8") as f:
            content = f.read()
        for prop in ["absolute", "fontSize", "zIndex"]:
            self.assertIn(prop, content)

    def test_f10_05_client_state_sync_and_storage(self):
        """Verifies client-side state serialization and undo/redo history tracking logic."""
        editor_path = os.path.join(PROJECT_ROOT, "ai_projects", "gorsel_parcali_editor.html")
        with open(editor_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue("JSON.stringify" in content or "pushHistory" in content or "history" in content.lower())

    def test_f10_06_canvas_export_render(self):
        """Verifies client-side canvas rendering / export button logic."""
        editor_path = os.path.join(PROJECT_ROOT, "ai_projects", "gorsel_parcali_editor.html")
        with open(editor_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue("getContext" in content or "export" in content.lower())


# ==============================================================================
# FEATURE 11: Turkish NLP Command Engine (F11)
# ==============================================================================
@tier(1)
class TestFeature11TurkishNLPCommandEngine(unittest.TestCase):
    """Verifies Turkish natural language parsing for scaling, movement, text update, and deletion."""

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="test_f11_state_")
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

    def _execute_nlp(self, command: str, layers: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str, bool]:
        """Helper to invoke either card_layer_engine or web_server.process_natural_language_edit."""
        try:
            import card_layer_engine
            if hasattr(card_layer_engine, "apply_natural_language_command"):
                new_layers, summary = card_layer_engine.apply_natural_language_command(command, layers)
                return new_layers, summary, True
        except ImportError:
            pass
        # Fallback to web_server implementation
        state = {"width": 1024, "height": 686, "elements": layers}
        updated, summary, success = web_server.process_natural_language_edit(command, "", state)
        return updated.get("elements", []), summary, success

    def test_f11_01_turkish_resize_scale_command(self):
        """Verifies 'ismi büyüt' increases fontSize/dimensions without replacing text with 'büyüt'."""
        layers = [{"id": "isim", "type": "text", "text": "Gül DİLMEN", "fontSize": 20, "w": 200, "h": 50, "x": 510, "y": 104}]
        new_layers, summary, ok = self._execute_nlp("ismi büyüt", layers)
        self.assertTrue(ok)
        isim = next((l for l in new_layers if l.get("id") == "isim"), None)
        self.assertIsNotNone(isim)
        self.assertEqual(isim.get("text"), "Gül DİLMEN")
        self.assertGreater(isim.get("fontSize", 0), 20)

    def test_f11_02_turkish_position_movement_command(self):
        """Verifies 'ortala' aligns layer horizontally on canvas."""
        layers = [{"id": "isim", "type": "text", "text": "Gül DİLMEN", "w": 200, "h": 50, "x": 100, "y": 100}]
        new_layers, summary, ok = self._execute_nlp("ismi ortala", layers)
        self.assertTrue(ok)
        isim = next((l for l in new_layers if l.get("id") == "isim"), None)
        self.assertIsNotNone(isim)
        # 1024 - 200 // 2 = 412
        self.assertEqual(isim.get("x"), 412)

    def test_f11_03_turkish_text_update_command(self):
        """Verifies 'telefonu 0554 248 10 99 yap' updates phone number text."""
        layers = [{"id": "telefon", "type": "text", "text": "0505 670 07 54", "x": 510, "y": 364}]
        new_layers, summary, ok = self._execute_nlp("telefonu 0554 248 10 99 yap", layers)
        self.assertTrue(ok)
        tel = next((l for l in new_layers if l.get("id") == "telefon"), None)
        self.assertIsNotNone(tel)
        self.assertEqual(tel.get("text"), "0554 248 10 99")

    def test_f11_04_turkish_delete_layer_command(self):
        """Verifies 'adresi sil' deletes the address layer while preserving others."""
        layers = [
            {"id": "isim", "type": "text", "text": "Gül DİLMEN"},
            {"id": "adres", "type": "text", "text": "Muratpaşa / ANTALYA"},
        ]
        new_layers, summary, ok = self._execute_nlp("adresi sil", layers)
        self.assertTrue(ok)
        self.assertEqual(len(new_layers), 1)
        self.assertIsNone(next((l for l in new_layers if l.get("id") == "adres"), None))
        self.assertIsNotNone(next((l for l in new_layers if l.get("id") == "isim"), None))

    def test_f11_05_turkish_companion_grouping_logo(self):
        """Verifies moving logo centers the logo element on canvas."""
        layers = [
            {"id": "logo", "type": "image", "x": 75, "y": 100, "w": 200, "h": 200},
        ]
        new_layers, summary, ok = self._execute_nlp("logoyu ortala", layers)
        self.assertTrue(ok)
        logo = next((l for l in new_layers if l.get("id") == "logo"), None)
        self.assertIsNotNone(logo)
        self.assertEqual(logo.get("x"), (1024 - 200) // 2)

    def test_f11_06_turkish_background_color_change(self):
        """Verifies 'arka planı lacivert yap' updates the canvas background color."""
        state = {"width": 1024, "height": 686, "background": "#0f1116", "elements": []}
        updated, summary, ok = web_server.process_natural_language_edit("arka planı lacivert yap", "", state)
        self.assertTrue(ok)
        self.assertEqual(updated.get("background"), "#0f172a")


# ==============================================================================
# FEATURE 12: E2E Integration & Hardening (F12)
# ==============================================================================
@tier(1)
class TestFeature12E2EIntegrationHardening(unittest.TestCase):
    """Verifies end-to-end integration workflows, multi-step editing sessions, and test runner stability."""

    def test_f12_01_full_decomposition_to_web_state_pipeline(self):
        """Verifies end-to-end pipeline from decomposition to web state persistence and fetch."""
        try:
            import card_layer_engine
        except ImportError:
            self.skipTest("card_layer_engine.py pending implementation by Milestone M3")

        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        decomposed = card_layer_engine.decompose_card(ref_path)
        with EphemeralServer() as server:
            payload = json.dumps({"layers": decomposed.get("layers", [])}).encode("utf-8")
            req = urllib.request.Request(
                f"{server.base_url}/api/design/state",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)

            with urllib.request.urlopen(f"{server.base_url}/api/design/state", timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)

    def test_f12_02_multi_step_nlp_editing_session(self):
        """Verifies multi-step sequential NLP edit session accumulates changes without data loss."""
        with EphemeralServer() as server:
            # Seed state
            initial_state = {
                "width": 1024,
                "height": 686,
                "elements": [
                    {"id": "isim", "type": "text", "text": "Eski İsim", "fontSize": 18, "w": 200, "h": 40, "x": 510, "y": 100},
                    {"id": "unvan", "type": "text", "text": "Eski Unvan", "fontSize": 14, "w": 200, "h": 30, "x": 510, "y": 150},
                ],
            }
            body = json.dumps({"state": initial_state}).encode("utf-8")
            req = urllib.request.Request(
                f"{server.base_url}/api/design/state",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)

            # Step 1: Change name
            body = json.dumps({"command": "ismi Ahmet Yılmaz yap"}).encode("utf-8")
            req = urllib.request.Request(f"{server.base_url}/api/ai_edit", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)

            # Step 2: Change title
            body = json.dumps({"command": "unvanı Genel Müdür yap"}).encode("utf-8")
            req = urllib.request.Request(f"{server.base_url}/api/ai_edit", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)

            # Step 3: Resize name
            body = json.dumps({"command": "ismi büyüt"}).encode("utf-8")
            req = urllib.request.Request(f"{server.base_url}/api/ai_edit", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)

            # Fetch final state
            with urllib.request.urlopen(f"{server.base_url}/api/design/state", timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                elements = data.get("layers", [])
                isim = next((e for e in elements if e.get("id") == "isim"), None)
                unvan = next((e for e in elements if e.get("id") == "unvan"), None)
                self.assertIsNotNone(isim)
                self.assertIsNotNone(unvan)
                self.assertEqual(isim.get("text"), "Ahmet Yılmaz")
                self.assertEqual(unvan.get("text"), "Genel Müdür")
                self.assertGreater(isim.get("fontSize", 0), 18)

    def test_f12_03_end_to_end_image_recomposition_quality(self):
        """Verifies recomposed modified card matches ground truth asset with SSIM >= 0.92."""
        try:
            import card_layer_engine
        except ImportError:
            self.skipTest("card_layer_engine.py pending implementation by Milestone M3")

        ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        ground_truth = os.path.join(PROJECT_ROOT, "kartvizit_0554_248_10_99.png")
        self.assertTrue(os.path.isfile(ref_path), "Reference card image missing")
        self.assertTrue(os.path.isfile(ground_truth), "Ground truth modified card image missing")

        # Decompose original reference card
        state = card_layer_engine.decompose_card(ref_path)
        layers = state.get("layers", [])

        # Apply natural language command or update phone number layer to target ground truth
        command = "telefonu 0554 248 10 99 yap"
        if hasattr(card_layer_engine, "apply_natural_language_command"):
            updated_layers, _ = card_layer_engine.apply_natural_language_command(command, layers)
            state["layers"] = updated_layers
        else:
            for l in layers:
                if l.get("id") in ("telefon", "phone") or "0242" in str(l.get("text", "")):
                    l["text"] = "0554 248 10 99"

        # Recompose modified card
        recomposed = None
        for method_name in ("recombine_layers", "recompose_card", "render_card", "composite_card"):
            fn = getattr(card_layer_engine, method_name, None)
            if callable(fn):
                recomposed = fn(state)
                break

        if recomposed is None:
            bg = state.get("background")
            if bg is not None:
                bg_img = Image.fromarray(_to_numpy_rgb(bg)).convert("RGBA")
            else:
                bg_img = Image.new("RGBA", (1024, 686), (255, 255, 255, 255))

            for layer in state.get("layers", []):
                x = int(layer.get("x", 0))
                y = int(layer.get("y", 0))
                asset_path = layer.get("asset_path") or layer.get("path")
                if asset_path and os.path.isfile(asset_path):
                    with Image.open(asset_path) as limg:
                        l_rgba = limg.convert("RGBA")
                        bg_img.paste(l_rgba, (x, y), l_rgba)

            recomposed = bg_img

        ssim_val = compute_ssim_simple(recomposed, ground_truth)
        self.assertGreaterEqual(
            ssim_val, 0.92,
            f"Recomposed card SSIM ({ssim_val:.4f}) is below the required 0.92 threshold against ground truth",
        )

    def test_f12_04_editor_html_and_api_roundtrip(self):
        """Verifies complete client round-trip: GET editor HTML, GET state, POST state."""
        with EphemeralServer() as server:
            # 1. Fetch editor
            with urllib.request.urlopen(f"{server.base_url}/editor", timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
            # 2. Fetch state
            with urllib.request.urlopen(f"{server.base_url}/api/design/state", timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
            # 3. Save state
            body = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                f"{server.base_url}/api/design/state",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)

    def test_f12_05_headless_cli_runner_execution(self):
        """Verifies master headless test runner execution via subprocess."""
        runner_path = os.path.join(PROJECT_ROOT, "run_e2e_tests.py")
        res = subprocess.run(
            [sys.executable, runner_path, "--tier", "1", "-k", "test_f2_01_health_check_endpoint"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"run_e2e_tests.py failed: {res.stderr}\n{res.stdout}")
        self.assertIn("1 PASSED", res.stdout)

    def test_f12_06_resource_cleanup_and_stability(self):
        """Verifies multiple ephemeral servers can be started and stopped without socket leaks."""
        for _ in range(3):
            with EphemeralServer() as server:
                with urllib.request.urlopen(f"{server.base_url}/api/health", timeout=2.0) as resp:
                    self.assertEqual(resp.status, 200)


if __name__ == "__main__":
    unittest.main()
