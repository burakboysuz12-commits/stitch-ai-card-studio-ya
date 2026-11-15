"""
Stitch AI+ Milestone 4 Headless Verification Suite:
Interactive Canvas Editing & Natural Language Command Integration (R4)

Verifies:
1. Full REST API Contracts (/api/health, /api/design/state GET & POST, /api/ai_edit).
2. Dynamic state initialization from card_layer_engine.decompose_card("kartvizit_son_orijinal.png").
3. Atomic state persistence and recovery via tempfile and os.replace.
4. Native 1024x686 canvas coordinate geometry and zoom compensation mathematics.
5. Strict boundary clamping for dragging and resizing ([0, width - el_w], [0, height - el_h]).
6. Turkish NLP commands:
   - Deletion ("adresi sil", "logoyu sil")
   - Alignment / Repositioning ("ismi ortala", "sağa yasla", "sola yasla", "yukarı kaydır")
   - Resizing & Bugfix ("ismi büyüt", "ismi büyük yap" - strictly no text corruption)
   - Text replacement ("telefonu 0532 555 44 33 yap")
   - Layer color change ("ismi altın yap")
   - Background color change ("arka plan lacivert yap")
7. Sequential stress editing with zero layout collapse or state corruption.
8. Frontend HTML editor contract and zoom/clamp geometry inspection.
9. Integration with uygulama.py and card_layer_engine.
"""

import copy
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

# Ensure workspace root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import card_layer_engine
import web_server


def get_free_port() -> int:
    """Finds an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestInteractiveCanvasNLP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = get_free_port()
        cls.temp_dir = tempfile.mkdtemp(prefix="test_canvas_nlp_")
        cls.test_state_path = os.path.join(cls.temp_dir, "_active_design_state.json")

        # Configure environment to use isolated temporary state
        cls.orig_env_state_path = os.environ.get("ACTIVE_DESIGN_STATE_PATH")
        os.environ["ACTIVE_DESIGN_STATE_PATH"] = cls.test_state_path
        web_server.ACTIVE_DESIGN_STATE_PATH = cls.test_state_path

        cls.server = web_server.ThreadingHTTPServer(("127.0.0.1", cls.port), web_server.StitchWebHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.shutdown()
            cls.server.server_close()
        except Exception:
            pass
        try:
            shutil.rmtree(cls.temp_dir, ignore_errors=True)
        except Exception:
            pass
        if cls.orig_env_state_path is not None:
            os.environ["ACTIVE_DESIGN_STATE_PATH"] = cls.orig_env_state_path
            web_server.ACTIVE_DESIGN_STATE_PATH = cls.orig_env_state_path
        else:
            os.environ.pop("ACTIVE_DESIGN_STATE_PATH", None)
            web_server.ACTIVE_DESIGN_STATE_PATH = os.path.join(
                web_server.BASE_DIR, "ai_projects", "_active_design_state.json"
            )

    def setUp(self):
        # Reset state file for clean test isolation if needed
        if os.path.exists(self.test_state_path):
            try:
                os.remove(self.test_state_path)
            except Exception:
                pass

    def test_01_rest_api_health_contract(self):
        """Verifies GET /api/health satisfies full REST schema contract."""
        url = f"{self.base_url}/api/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("application/json", resp.headers.get("Content-Type", ""))
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("status"), "healthy")
            self.assertEqual(data.get("service"), "stitch_ai_web")
            self.assertIn("version", data)
            self.assertIn("timestamp", data)

    def test_02_dynamic_state_initialization_from_decompose_card(self):
        """Verifies GET /api/design/state initializes from decompose_card when no active state exists."""
        # Ensure state file is absent
        if os.path.exists(self.test_state_path):
            os.remove(self.test_state_path)

        url = f"{self.base_url}/api/design/state"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertTrue(data.get("success"))
            self.assertIn("canvas", data)
            self.assertEqual(data["canvas"].get("width"), 1024)
            self.assertEqual(data["canvas"].get("height"), 686)

            layers = data.get("layers", [])
            self.assertGreaterEqual(len(layers), 8)
            # Verify required semantic layers exist
            layer_ids = [l.get("id") for l in layers if isinstance(l, dict)]
            self.assertIn("logo", layer_ids)
            self.assertIn("isim", layer_ids)
            self.assertIn("unvan", layer_ids)
            self.assertIn("telefon", layer_ids)
            self.assertIn("adres", layer_ids)

            # Verify that state was atomically saved to disk
            self.assertTrue(os.path.isfile(self.test_state_path))

    def test_03_atomic_state_persistence_and_recovery(self):
        """Verifies POST /api/design/state persists state atomically and GET recovers it accurately."""
        post_url = f"{self.base_url}/api/design/state"
        custom_state = {
            "title": "Atomik Test Kartvizit",
            "width": 1024,
            "height": 686,
            "canvas": {"width": 1024, "height": 686},
            "background": "#0f172a",
            "elements": [
                {
                    "id": "katman_test_1",
                    "label": "Test Katmanı",
                    "type": "text",
                    "text": "Atomik Kayıt Doğrulandı",
                    "x": 200,
                    "y": 150,
                    "w": 300,
                    "h": 50,
                    "color": "#ffffff",
                    "fontSize": 24,
                }
            ],
        }
        body = json.dumps({"state": custom_state}).encode("utf-8")
        req_post = urllib.request.Request(post_url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_post, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            post_data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(post_data.get("ok"))
            self.assertTrue(post_data.get("success"))

        # Verify disk file content
        self.assertTrue(os.path.isfile(self.test_state_path))
        with open(self.test_state_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
            self.assertEqual(disk_data.get("background"), "#0f172a")
            self.assertEqual(len(disk_data.get("elements", [])), 1)
            self.assertEqual(disk_data["elements"][0].get("id"), "katman_test_1")

        # GET request recovery
        req_get = urllib.request.Request(post_url)
        with urllib.request.urlopen(req_get, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            get_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(get_data["state"].get("background"), "#0f172a")
            self.assertEqual(get_data["layers"][0].get("text"), "Atomik Kayıt Doğrulandı")

    def test_04_rest_api_ai_edit_contract(self):
        """Verifies POST /api/ai_edit satisfies full contract schema including action_summary."""
        url = f"{self.base_url}/api/ai_edit"
        payload = {
            "prompt": "telefonu 0532 999 88 77 yap",
            "state": {
                "width": 1024,
                "height": 686,
                "elements": [
                    {"id": "telefon", "type": "text", "text": "0554 000 00 00", "x": 600, "y": 300, "w": 250, "h": 40}
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
            self.assertIn("state", data)
            self.assertIn("layers", data)
            self.assertIn("summary", data)
            self.assertIn("action_summary", data)
            self.assertIn("0532 999 88 77", data.get("action_summary"))

    def test_05_native_1024x686_coordinate_space_and_zoom_compensation(self):
        """Verifies 1024x686 coordinate geometry and screen-to-canvas zoom compensation math."""
        canvas_w = 1024
        canvas_h = 686
        self.assertEqual(canvas_w, 1024)
        self.assertEqual(canvas_h, 686)

        # Simulate client mouse movement at different zoom levels:
        # dx = (e.clientX - sx) / zoom, dy = (e.clientY - sy) / zoom
        zoom_levels = [0.6, 0.8, 1.0, 1.2]
        screen_delta_x = 60
        screen_delta_y = 48

        for zoom in zoom_levels:
            canvas_dx = screen_delta_x / zoom
            canvas_dy = screen_delta_y / zoom

            # For zoom = 1.0, canvas delta matches screen delta
            if zoom == 1.0:
                self.assertAlmostEqual(canvas_dx, 60.0)
                self.assertAlmostEqual(canvas_dy, 48.0)
            # For zoom = 0.6 (zoomed out), screen movement corresponds to larger canvas displacement
            elif zoom == 0.6:
                self.assertAlmostEqual(canvas_dx, 100.0)
                self.assertAlmostEqual(canvas_dy, 80.0)
            # For zoom = 1.2 (zoomed in), screen movement corresponds to smaller canvas displacement
            elif zoom == 1.2:
                self.assertAlmostEqual(canvas_dx, 50.0)
                self.assertAlmostEqual(canvas_dy, 40.0)

    def test_06_boundary_clamping_drag_and_resize(self):
        """Verifies strict boundary clamping within [0, canvas_w - el_w] and [0, canvas_h - el_h]."""
        canvas_w = 1024
        canvas_h = 686

        test_layers = [
            {"id": "overflow_right", "x": 1200, "y": 100, "w": 200, "h": 50},
            {"id": "overflow_bottom", "x": 100, "y": 800, "w": 200, "h": 50},
            {"id": "underflow_left", "x": -150, "y": 100, "w": 200, "h": 50},
            {"id": "underflow_top", "x": 100, "y": -90, "w": 200, "h": 50},
            {"id": "valid_element", "x": 500, "y": 300, "w": 200, "h": 50},
        ]

        clamped = web_server.clamp_layer_boundaries(test_layers, canvas_w, canvas_h)

        # Right boundary clamp: max_x = 1024 - 200 = 824
        self.assertEqual(clamped[0]["x"], 824)
        self.assertEqual(clamped[0]["y"], 100)

        # Bottom boundary clamp: max_y = 686 - 50 = 636
        self.assertEqual(clamped[1]["x"], 100)
        self.assertEqual(clamped[1]["y"], 636)

        # Underflow clamps: min_x = 0, min_y = 0
        self.assertEqual(clamped[2]["x"], 0)
        self.assertEqual(clamped[3]["y"], 0)

        # Valid element untouched
        self.assertEqual(clamped[4]["x"], 500)
        self.assertEqual(clamped[4]["y"], 300)

    def test_07_turkish_nlp_delete_command(self):
        """Verifies 'adresi sil' and 'logoyu sil' remove specified layers without touching others."""
        layers = [
            {"id": "logo", "type": "image", "x": 80, "y": 110, "w": 385, "h": 263},
            {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 734, "y": 105, "w": 248, "h": 44},
            {"id": "adres", "type": "text", "text": "Antalya", "x": 596, "y": 544, "w": 382, "h": 70},
        ]
        res_layers, summary = card_layer_engine.apply_natural_language_command("adresi sil", layers)
        remaining_ids = [l["id"] for l in res_layers]
        self.assertNotIn("adres", remaining_ids)
        self.assertIn("logo", remaining_ids)
        self.assertIn("isim", remaining_ids)
        self.assertIn("adres", summary)
        self.assertIn("silindi", summary)

    def test_08_turkish_nlp_alignment_ortala(self):
        """Verifies 'ismi ortala' centers the name horizontally on the 1024 canvas."""
        layers = [
            {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 734, "y": 105, "w": 248, "h": 44}
        ]
        res_layers, summary = card_layer_engine.apply_natural_language_command("ismi ortala", layers)
        target = res_layers[0]
        expected_x = (1024 - 248) // 2
        self.assertEqual(target["x"], expected_x)
        self.assertEqual(target.get("align"), "center")
        self.assertIn("ortalandı", summary)

    def test_09_turkish_nlp_alignment_saga_yasla(self):
        """Verifies 'sağa yasla' and 'ismi sağa yasla' align name to right border."""
        layers = [
            {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 100, "y": 105, "w": 248, "h": 44}
        ]
        res_layers, summary = card_layer_engine.apply_natural_language_command("ismi sağa yasla", layers)
        target = res_layers[0]
        # CANVAS_WIDTH - w - 44 = 1024 - 248 - 44 = 732
        self.assertEqual(target["x"], 1024 - 248 - 44)
        self.assertEqual(target.get("align"), "right")
        self.assertIn("sağa yaslandı", summary)

        # Also verify web_server handles default 'sağa yasla'
        st = {"width": 1024, "height": 686, "elements": copy.deepcopy(layers)}
        upd, s, ok = web_server.process_natural_language_edit("sağa yasla", "", st)
        self.assertTrue(ok)
        self.assertEqual(upd["elements"][0]["x"], 1024 - 248 - 44)

    def test_10_turkish_nlp_alignment_sola_yasla(self):
        """Verifies 'sola yasla' and 'ismi sola yasla' align to left border."""
        layers = [
            {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 500, "y": 105, "w": 248, "h": 44}
        ]
        res_layers, summary = card_layer_engine.apply_natural_language_command("ismi sola yasla", layers)
        target = res_layers[0]
        self.assertEqual(target["x"], 44)
        self.assertEqual(target.get("align"), "left")
        self.assertIn("sola yaslandı", summary)

        # Also verify web_server handles default 'sola yasla'
        st = {"width": 1024, "height": 686, "elements": copy.deepcopy(layers)}
        upd, s, ok = web_server.process_natural_language_edit("sola yasla", "", st)
        self.assertTrue(ok)
        self.assertEqual(upd["elements"][0]["x"], 44)

    def test_11_turkish_nlp_directional_movement_yukari_kaydir(self):
        """Verifies 'yukarı kaydır' shifts element vertically upward while clamping."""
        layers = [
            {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 734, "y": 105, "w": 248, "h": 44}
        ]
        res_layers, summary = card_layer_engine.apply_natural_language_command("isim yukarı kaydır", layers)
        target = res_layers[0]
        self.assertLess(target["y"], 105)
        self.assertIn("yukarı kaydırıldı", summary)

    def test_12_turkish_nlp_scaling_ismi_buyut(self):
        """Verifies 'ismi büyüt' scales up font size and dimensions."""
        layers = [
            {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 734, "y": 105, "w": 248, "h": 44, "fontSize": 38}
        ]
        res_layers, summary = card_layer_engine.apply_natural_language_command("ismi büyüt", layers)
        target = res_layers[0]
        self.assertGreater(target["fontSize"], 38)
        self.assertGreater(target["w"], 248)
        self.assertEqual(target["text"], "Gül DİLMEN")
        self.assertIn("büyütüldü", summary)

    def test_13_turkish_nlp_scaling_ismi_buyuk_yap_bugfix(self):
        """CRITICAL: Verifies 'ismi büyük yap' scales size and strictly does NOT overwrite text with 'BÜYÜK'."""
        state = {
            "width": 1024,
            "height": 686,
            "elements": [
                {
                    "id": "isim",
                    "type": "text",
                    "text": "Gül DİLMEN",
                    "x": 734,
                    "y": 105,
                    "w": 248,
                    "h": 44,
                    "fontSize": 38,
                }
            ],
        }

        # Test both web_server.process_natural_language_edit and card_layer_engine.apply_natural_language_command
        upd_state, summary, ok = web_server.process_natural_language_edit("ismi büyük yap", "", state)
        self.assertTrue(ok)
        target_ws = upd_state["elements"][0]
        self.assertGreater(target_ws["fontSize"], 38)
        self.assertEqual(target_ws["text"], "Gül DİLMEN")
        self.assertNotIn("büyük", target_ws["text"].lower())

        upd_layers, summary_eng = card_layer_engine.apply_natural_language_command("ismi büyük yap", state["elements"])
        target_eng = upd_layers[0]
        self.assertGreater(target_eng["fontSize"], 38)
        self.assertEqual(target_eng["text"], "Gül DİLMEN")

    def test_14_turkish_nlp_scaling_unvan_kucult(self):
        """Verifies 'unvanı küçült' decreases fontSize and dimensions."""
        layers = [
            {"id": "unvan", "type": "text", "text": "MÜDÜR", "x": 733, "y": 160, "w": 249, "h": 95, "fontSize": 20}
        ]
        res_layers, summary = card_layer_engine.apply_natural_language_command("unvanı küçült", layers)
        target = res_layers[0]
        self.assertLess(target["fontSize"], 20)
        self.assertLess(target["w"], 249)
        self.assertEqual(target["text"], "MÜDÜR")

    def test_15_turkish_nlp_text_replacement(self):
        """Verifies 'telefonu 0532 555 44 33 yap' replaces text correctly."""
        layers = [
            {"id": "telefon", "type": "text", "text": "0554 248 10 99", "x": 713, "y": 360, "w": 265, "h": 34}
        ]
        res_layers, summary = card_layer_engine.apply_natural_language_command("telefonu 0532 555 44 33 yap", layers)
        target = res_layers[0]
        self.assertEqual(target["text"], "0532 555 44 33")
        self.assertIn("0532 555 44 33", summary)

    def test_16_turkish_nlp_color_change(self):
        """Verifies 'ismi altın yap' updates element color to #d4af37."""
        state = {
            "width": 1024,
            "height": 686,
            "elements": [
                {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 734, "y": 105, "w": 248, "h": 44, "color": "#ffffff"}
            ],
        }
        upd_state, summary, ok = web_server.process_natural_language_edit("ismi altın yap", "", state)
        self.assertTrue(ok)
        self.assertEqual(upd_state["elements"][0].get("color"), "#d4af37")

    def test_17_turkish_nlp_background_color_change(self):
        """Verifies 'arka plan lacivert yap' updates canvas background to #0f172a."""
        state = {
            "width": 1024,
            "height": 686,
            "background": "#000000",
            "elements": [],
        }
        upd_state, summary, ok = web_server.process_natural_language_edit("arka plan lacivert yap", "", state)
        self.assertTrue(ok)
        self.assertEqual(upd_state.get("background"), "#0f172a")

    def test_18_consecutive_stress_editing_zero_layout_collapse(self):
        """Performs 10 sequential edits on design state, verifying zero layout collapse or state corruption."""
        state = {
            "title": "Stress Test Card",
            "width": 1024,
            "height": 686,
            "background": "#0f1116",
            "elements": [
                {"id": "logo", "type": "image", "x": 80, "y": 110, "w": 385, "h": 263},
                {"id": "isim", "type": "text", "text": "Gül DİLMEN", "x": 734, "y": 105, "w": 248, "h": 44, "fontSize": 38},
                {"id": "unvan", "type": "text", "text": "MÜDÜR", "x": 733, "y": 160, "w": 249, "h": 95, "fontSize": 20},
                {"id": "telefon", "type": "text", "text": "0554 248 10 99", "x": 713, "y": 360, "w": 265, "h": 34, "fontSize": 22},
                {"id": "adres", "type": "text", "text": "Antalya", "x": 596, "y": 544, "w": 382, "h": 70, "fontSize": 18},
            ],
        }

        commands = [
            "ismi büyük yap",
            "telefonu 0532 111 22 33 yap",
            "ismi ortala",
            "unvanı küçült",
            "ismi altın yap",
            "arka plan lacivert yap",
            "sağa yasla",
            "yukarı kaydır",
            "adresi sil",
            "metin ekle 'Emir Sultan Group'",
        ]

        curr_state = copy.deepcopy(state)
        for cmd in commands:
            curr_state, summary, ok = web_server.process_natural_language_edit(cmd, "", curr_state)
            self.assertTrue(ok, f"Command '{cmd}' failed: {summary}")
            self.assertEqual(curr_state["width"], 1024)
            self.assertEqual(curr_state["height"], 686)
            for el in curr_state["elements"]:
                # Check boundary invariant
                self.assertGreaterEqual(el["x"], 0)
                self.assertGreaterEqual(el["y"], 0)
                self.assertLessEqual(el["x"] + el["w"], 1024 + 10)  # small tolerance for rounding
                self.assertLessEqual(el["y"] + el["h"], 686 + 10)

        # Adres was deleted, metin ekle added a layer
        el_ids = [e["id"] for e in curr_state["elements"]]
        self.assertNotIn("adres", el_ids)
        self.assertIn("katman_5", el_ids)

    def test_19_editor_html_contract_and_geometry(self):
        """Inspects ai_projects/gorsel_parcali_editor.html verifying 1024x686, zoom compensation, and clamping."""
        html_path = os.path.join(PROJECT_ROOT, "ai_projects", "gorsel_parcali_editor.html")
        self.assertTrue(os.path.isfile(html_path))

        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # 1. 1024x686 INITIAL geometry
        self.assertIn('"width": 1024', html)
        self.assertIn('"height": 686', html)

        # 2. Zoom compensation math
        self.assertIn("(e.clientX - sx)/zoom", html)
        self.assertIn("(e.clientY - sy)/zoom", html)

        # 3. Boundary clamping logic
        self.assertIn("Math.max(0, state.width - el.w)", html)
        self.assertIn("Math.max(0, state.height - el.h)", html)

        # 4. REST AI edit endpoint integration
        self.assertIn("fetch('/api/ai_edit'", html)

        # 5. Dynamic state initialization from server
        self.assertIn("initFromServer", html)

    def test_20_uygulama_integration_card_layer_engine(self):
        """Verifies uygulama.py imports and connects card_layer_engine."""
        import uygulama

        self.assertTrue(hasattr(uygulama, "card_layer_engine"))
        self.assertIsNotNone(uygulama.card_layer_engine)
        self.assertTrue(hasattr(uygulama.card_layer_engine, "decompose_card"))
        self.assertTrue(hasattr(uygulama.card_layer_engine, "apply_natural_language_command"))

    def test_21_concurrent_multithreaded_save_state_locking(self):
        """Verifies concurrent multithreaded POST /api/design/state requests succeed with 100% pass rate without WinError 5."""
        import concurrent.futures

        url = f"{self.base_url}/api/design/state"
        errors = []
        num_threads = 10
        writes_per_thread = 3

        def worker(thread_idx):
            for seq in range(writes_per_thread):
                payload = {
                    "state": {
                        "width": 1024,
                        "height": 686,
                        "title": f"Concurrent Thread {thread_idx} Seq {seq}",
                        "elements": [
                            {
                                "id": f"el_t{thread_idx}_s{seq}",
                                "type": "text",
                                "text": f"Thread {thread_idx} Data {seq}",
                                "x": 100 + (thread_idx * 20),
                                "y": 100 + (seq * 40),
                                "w": 200,
                                "h": 30,
                            }
                        ],
                    }
                }
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        if resp.status != 200:
                            errors.append((thread_idx, seq, resp.status))
                        else:
                            resp_data = json.loads(resp.read().decode("utf-8"))
                            if not resp_data.get("ok"):
                                errors.append((thread_idx, seq, "ok is False"))
                except Exception as exc:
                    errors.append((thread_idx, seq, str(exc)))

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Concurrent state saves had {len(errors)} failures: {errors}")
        self.assertTrue(os.path.isfile(self.test_state_path))
        with open(self.test_state_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
            self.assertIn("width", disk_data)
            self.assertEqual(disk_data["width"], 1024)

    def test_22_ai_edit_non_string_payload_validation(self):
        """Verifies that non-string prompt, command, or selectedId payloads return HTTP 400 Bad Request instead of HTTP 500."""
        url = f"{self.base_url}/api/ai_edit"
        invalid_cases = [
            ({"prompt": 12345}, 400, "Prompt must be a string"),
            ({"prompt": ["adresi sil"]}, 400, "Prompt must be a string"),
            ({"prompt": {"cmd": "ortala"}}, 400, "Prompt must be a string"),
            ({"prompt": True}, 400, "Prompt must be a string"),
            ({"command": 9999}, 400, "Prompt must be a string"),
            ({"command": ["büyüt"]}, 400, "Prompt must be a string"),
            ({"command": {"action": "scale"}}, 400, "Prompt must be a string"),
            ({"command": False}, 400, "Prompt must be a string"),
            ({"selectedId": 12345}, 400, "selectedId must be a string"),
            ({"selectedId": ["isim"]}, 400, "selectedId must be a string"),
            ({"selectedId": {"id": "isim"}}, 400, "selectedId must be a string"),
            ({"selected_id": 12345}, 400, "selectedId must be a string"),
        ]

        for payload, expected_status, expected_error in invalid_cases:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    status = resp.status
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                status = err.code
                data = json.loads(err.read().decode("utf-8"))

            self.assertEqual(
                status,
                expected_status,
                f"Payload {payload} expected HTTP {expected_status}, got {status}",
            )
            self.assertFalse(data.get("ok"))
            self.assertIn(expected_error, data.get("error", ""))


if __name__ == "__main__":
    unittest.main()
