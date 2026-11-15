"""
Tests for Stitch AI+ Web Server (Milestone 1 Verification)
Verifies cloud runtime readiness, dynamic port binding, health checks, editor serving, and REST API.
"""

import importlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import web_server


def get_free_port() -> int:
    """Finds an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestWebServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = get_free_port()
        # Create isolated temporary directory for test design state
        cls.temp_dir = tempfile.mkdtemp(prefix="test_web_server_")
        cls.test_state_path = os.path.join(cls.temp_dir, "_active_design_state.json")
        # Initialize with standard 1024x686 default design state
        with open(cls.test_state_path, "w", encoding="utf-8") as f:
            json.dump(web_server.get_default_design_state(), f)

        cls.orig_env_state_path = os.environ.get("ACTIVE_DESIGN_STATE_PATH")
        os.environ["ACTIVE_DESIGN_STATE_PATH"] = cls.test_state_path
        web_server.ACTIVE_DESIGN_STATE_PATH = cls.test_state_path

        cls.server = web_server.ThreadingHTTPServer(("127.0.0.1", cls.port), web_server.StitchWebHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        # Small wait for thread startup
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.shutdown()
            cls.server.server_close()
        except Exception:
            pass
        # Clean up temporary directory
        try:
            shutil.rmtree(cls.temp_dir, ignore_errors=True)
        except Exception:
            pass
        # Restore original state path configuration
        if cls.orig_env_state_path is not None:
            os.environ["ACTIVE_DESIGN_STATE_PATH"] = cls.orig_env_state_path
            web_server.ACTIVE_DESIGN_STATE_PATH = cls.orig_env_state_path
        else:
            os.environ.pop("ACTIVE_DESIGN_STATE_PATH", None)
            web_server.ACTIVE_DESIGN_STATE_PATH = os.path.join(
                web_server.BASE_DIR, "ai_projects", "_active_design_state.json"
            )

    def test_health_endpoint(self):
        """Verifies GET /api/health returns HTTP 200 and expected schema."""
        url = f"{self.base_url}/api/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("application/json", resp.headers.get("Content-Type", ""))
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("service"), "stitch_ai_web")
            self.assertEqual(data.get("status"), "healthy")
            self.assertIn("port", data)

    def test_serve_editor_html_root(self):
        """Verifies GET / serves editor HTML with HTTP 200."""
        url = f"{self.base_url}/"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))
            content = resp.read().decode("utf-8", errors="ignore")
            self.assertIn("Stitch AI+", content)

    def test_serve_editor_html_editor_path(self):
        """Verifies GET /editor serves editor HTML with HTTP 200."""
        url = f"{self.base_url}/editor"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))
            content = resp.read().decode("utf-8", errors="ignore")
            self.assertIn("Stitch AI+", content)

    def test_ai_edit_post_request(self):
        """Verifies POST /api/ai_edit accepts prompt and updates design state."""
        url = f"{self.base_url}/api/ai_edit"
        payload = {
            "prompt": "telefonu 0532 555 44 33 yap",
            "state": {
                "width": 1024,
                "height": 686,
                "background": "#0f1116",
                "elements": [
                    {"id": "telefon", "label": "Telefon", "type": "text", "text": "0505 000 00 00", "x": 510, "y": 364}
                ],
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertTrue(data.get("success"))
            elements = data.get("state", {}).get("elements", [])
            tel_el = next((e for e in elements if e.get("id") == "telefon"), None)
            self.assertIsNotNone(tel_el)
            self.assertEqual(tel_el.get("text"), "0532 555 44 33")
            self.assertIn("0532 555 44 33", data.get("summary", ""))

    def test_ai_edit_nlp_scaling_bugfix(self):
        """Verifies 'ismi büyük yap' scales name rather than replacing text with 'büyük'."""
        url = f"{self.base_url}/api/ai_edit"
        payload = {
            "prompt": "ismi büyük yap",
            "state": {
                "width": 1024,
                "height": 686,
                "background": "#0f1116",
                "elements": [
                    {"id": "isim", "type": "text", "text": "Gül Dilmen", "fontSize": 20, "w": 200, "h": 50, "x": 500, "y": 100}
                ],
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            isim_el = next((e for e in data["state"]["elements"] if e.get("id") == "isim"), None)
            self.assertIsNotNone(isim_el)
            # Text must NOT be changed to "büyük"
            self.assertEqual(isim_el.get("text"), "Gül Dilmen")
            # FontSize must be scaled up
            self.assertGreater(isim_el.get("fontSize"), 20)

    def test_design_state_get_and_post(self):
        """Verifies GET and POST on /api/design/state."""
        get_url = f"{self.base_url}/api/design/state"
        req_get = urllib.request.Request(get_url)
        with urllib.request.urlopen(req_get, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertIn("canvas", data)

        # POST to save state
        test_state = {
            "title": "Test Card",
            "width": 1024,
            "height": 686,
            "background": "#112233",
            "elements": [{"id": "test_layer", "text": "Hello"}],
        }
        body = json.dumps({"state": test_state}).encode("utf-8")
        req_post = urllib.request.Request(get_url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_post, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            post_data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(post_data.get("ok"))
            self.assertTrue(post_data.get("success"))

    def test_options_cors_preflight(self):
        """Verifies OPTIONS request returns HTTP 204 with CORS headers."""
        url = f"{self.base_url}/api/ai_edit"
        req = urllib.request.Request(url, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
            self.assertIn("POST", resp.headers.get("Access-Control-Allow-Methods", ""))

    def test_not_found_endpoint(self):
        """Verifies undefined path returns HTTP 404 with JSON error."""
        url = f"{self.base_url}/api/non_existent_path"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 404)
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)
            data = json.loads(exc.read().decode("utf-8"))
            self.assertFalse(data.get("ok"))
            self.assertEqual(data.get("error"), "not_found")

    def test_port_environment_variable_binding(self):
        """Verifies PORT environment variable dynamically changes web_server.PORT."""
        test_port = "9123"
        os.environ["PORT"] = test_port
        importlib.reload(web_server)
        self.assertEqual(web_server.PORT, int(test_port))
        # Reset to default
        os.environ["PORT"] = "8080"
        importlib.reload(web_server)
        self.assertEqual(web_server.PORT, 8080)

    def test_non_dict_json_payloads_return_400(self):
        """Verifies posting non-dict JSON (list, string, int, null, bool) returns HTTP 400 Bad Request."""
        non_dict_samples = [
            b"[1, 2, 3]",
            b'"string value"',
            b"12345",
            b"null",
            b"true",
        ]
        endpoints = ["/api/ai_edit", "/api/design/state"]

        for endpoint in endpoints:
            url = f"{self.base_url}{endpoint}"
            for sample in non_dict_samples:
                req = urllib.request.Request(
                    url,
                    data=sample,
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError, msg=f"Failed for {endpoint} with {sample}") as ctx:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(ctx.exception.code, 400)
                err_data = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertFalse(err_data.get("ok"))
                self.assertIn("JSON object", err_data.get("error", ""))

    def test_post_malformed_state_rejected_with_400_and_state_preserved(self):
        """Verifies empty and malformed payloads are rejected with HTTP 400 without state corruption."""
        with open(self.test_state_path, "r", encoding="utf-8") as f:
            state_before = json.load(f)

        malformed_samples = [
            b"{}",
            b'{"elements": null}',
            b'{"state": {}}',
            b'{"state": {"elements": null}}',
            b'{"empty_test": true}',
            b'{"elements": "not_a_list"}',
        ]

        url = f"{self.base_url}/api/design/state"
        for sample in malformed_samples:
            req = urllib.request.Request(
                url,
                data=sample,
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError, msg=f"Failed to reject malformed payload: {sample}") as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 400)
            err_data = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertFalse(err_data.get("ok"))

        # Verify state file was NOT overwritten with corrupted or empty data
        with open(self.test_state_path, "r", encoding="utf-8") as f:
            state_after = json.load(f)
        self.assertEqual(state_after.get("width"), state_before.get("width", 1024))
        self.assertIsInstance(state_after.get("elements"), list)

    def test_subsequent_ai_edit_operates_reliably_after_malformed_requests(self):
        """Verifies server recovers immediately and subsequent /api/ai_edit succeeds without crashing."""
        url = f"{self.base_url}/api/ai_edit"
        payload = {
            "prompt": "yeni metin ekle 'Hata Sonrasi Dogrulama'",
            "state": {
                "width": 1024,
                "height": 686,
                "elements": [
                    {"id": "isim", "type": "text", "text": "Test Kisi"}
                ],
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertTrue(data.get("success"))
            elements = data.get("state", {}).get("elements", [])
            self.assertGreaterEqual(len(elements), 2)

    def test_configurable_state_path_env_variable(self):
        """Verifies ACTIVE_DESIGN_STATE_PATH env var redirects state persistence to custom path."""
        custom_state_file = os.path.join(self.temp_dir, "custom_sub_state.json")
        try:
            os.environ["ACTIVE_DESIGN_STATE_PATH"] = custom_state_file
            test_data = {
                "title": "Env Path Test",
                "width": 1024,
                "height": 686,
                "elements": [{"id": "env_el", "text": "Custom Env"}],
            }
            save_success = web_server.save_design_state(test_data)
            self.assertTrue(save_success)
            self.assertTrue(os.path.isfile(custom_state_file))

            loaded = web_server.load_design_state()
            self.assertEqual(loaded.get("title"), "Env Path Test")
            self.assertEqual(len(loaded.get("elements", [])), 1)
        finally:
            os.environ["ACTIVE_DESIGN_STATE_PATH"] = self.test_state_path

    def test_atomic_state_persistence_and_validation(self):
        """Verifies save_design_state performs atomic replacement and schema validation."""
        # Validation failures
        self.assertFalse(web_server.save_design_state({}))
        self.assertFalse(web_server.save_design_state({"elements": None}))
        self.assertFalse(web_server.save_design_state({"invalid_key": True}))

        # Valid save
        valid_state = {
            "title": "Atomic Card",
            "width": 1024,
            "height": 686,
            "elements": [{"id": "el1", "text": "Valid"}],
        }
        self.assertTrue(web_server.save_design_state(valid_state))
        # Ensure no leftover temp files in directory
        temp_files = [f for f in os.listdir(self.temp_dir) if f.startswith("_state_") and f.endswith(".tmp")]
        self.assertEqual(len(temp_files), 0)


if __name__ == "__main__":
    unittest.main()
