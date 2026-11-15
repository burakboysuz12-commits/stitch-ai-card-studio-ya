"""
Unit and Regression Test Suite for Card Layer Engine (Milestone 3 / R3)
Tests non-destructive business card decomposition, selective inpainting,
contact icon preservation, asset extraction, typography alignment, and NLP commands.
"""

import os
import sys
import unittest
import numpy as np
from PIL import Image

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import card_layer_engine
from tests.e2e.harness import compute_ssim_simple, compute_dhash_distance, _to_numpy_rgb


class TestCardDecomposition(unittest.TestCase):
    """Test suite for Milestone 3 Card Layer Engine."""

    @classmethod
    def setUpClass(cls):
        cls.ref_path = os.path.join(PROJECT_ROOT, "kartvizit_son_orijinal.png")
        cls.gt_path = os.path.join(PROJECT_ROOT, "kartvizit_0554_248_10_99.png")
        assert os.path.isfile(cls.ref_path), f"Reference card image not found: {cls.ref_path}"
        cls.state = card_layer_engine.decompose_card(cls.ref_path)

    def test_01_native_1024x686_resolution(self):
        """Verifies decomposition preserves native 1024x686 RGB geometry without squishing."""
        canvas = self.state.get("canvas", {})
        self.assertEqual(canvas.get("width"), 1024)
        self.assertEqual(canvas.get("height"), 686)

        bg_path = self.state.get("background")
        self.assertTrue(os.path.isfile(bg_path), f"Clean background file missing: {bg_path}")
        with Image.open(bg_path) as im:
            self.assertEqual(im.size, (1024, 686))

    def test_02_unicode_safe_path_handling(self):
        """Verifies unicode safe path I/O with Turkish/non-ASCII characters."""
        arr = card_layer_engine.load_image_unicode_safe(self.ref_path)
        self.assertEqual(arr.shape, (686, 1024, 3))
        self.assertEqual(arr.dtype, np.uint8)

    def test_03_contact_icon_preservation(self):
        """Verifies original contact icons are strictly preserved during inpainting."""
        orig_arr = _to_numpy_rgb(self.ref_path)
        clean_arr = _to_numpy_rgb(self.state["background"])

        # Phone 1 icon region [358:394, 659:714]
        diff_p1 = np.abs(orig_arr[358:394, 659:714].astype(float) - clean_arr[358:394, 659:714].astype(float))
        self.assertLessEqual(np.mean(diff_p1), 1.0)

        # Phone 2 icon region [406:440, 657:714]
        diff_p2 = np.abs(orig_arr[406:440, 657:714].astype(float) - clean_arr[406:440, 657:714].astype(float))
        self.assertLessEqual(np.mean(diff_p2), 1.0)

        # Email 1 icon region [459:487, 560:589]
        diff_e1 = np.abs(orig_arr[459:487, 560:589].astype(float) - clean_arr[459:487, 560:589].astype(float))
        self.assertLessEqual(np.mean(diff_e1), 1.0)

        # Email 2 icon region [502:533, 550:609]
        diff_e2 = np.abs(orig_arr[502:533, 550:609].astype(float) - clean_arr[502:533, 550:609].astype(float))
        self.assertLessEqual(np.mean(diff_e2), 1.0)

        # Address pin icon region [545:598, 557:599]
        diff_pin = np.abs(orig_arr[545:598, 557:599].astype(float) - clean_arr[545:598, 557:599].astype(float))
        self.assertLessEqual(np.mean(diff_pin), 1.0)

    def test_04_selective_ink_removal_fidelity(self):
        """Verifies text ink in phone numbers is cleanly removed while surrounding background is smooth."""
        orig_arr = _to_numpy_rgb(self.ref_path)
        clean_arr = _to_numpy_rgb(self.state["background"])

        text_diff = np.abs(orig_arr[360:394, 715:975].astype(float) - clean_arr[360:394, 715:975].astype(float))
        self.assertGreater(np.mean(text_diff), 5.0)

        # Background smoothness inside inpainted crimson patch
        crop = clean_arr[360:394, 715:975]
        std_rgb = np.std(crop, axis=(0, 1))
        self.assertLessEqual(float(np.mean(std_rgb)), 8.0)

    def test_05_layer_asset_extraction(self):
        """Verifies extracted transparent layer assets (logo.png, qr_code.png)."""
        logo_path = os.path.join(PROJECT_ROOT, "layers", "logo.png")
        self.assertTrue(os.path.isfile(logo_path), f"Extracted logo asset missing: {logo_path}")
        with Image.open(logo_path) as limg:
            self.assertEqual(limg.mode, "RGBA")
            self.assertEqual(limg.size, (385, 263))
            arr = np.array(limg)
            self.assertTrue(np.any(arr[:, :, 3] == 0), "Logo should have transparent background pixels")
            self.assertTrue(np.any(arr[:, :, 3] > 0), "Logo should have opaque emblem pixels")

        qr_path = os.path.join(PROJECT_ROOT, "layers", "qr_code.png")
        self.assertTrue(os.path.isfile(qr_path), f"Extracted QR asset missing: {qr_path}")
        with Image.open(qr_path) as qimg:
            self.assertEqual(qimg.size, (136, 138))

    def test_06_typography_and_coordinate_alignment(self):
        """Verifies header center axis x=858 and contact right anchor x=978."""
        layers = {l["id"]: l for l in self.state.get("layers", [])}
        self.assertIn("isim", layers)
        self.assertIn("unvan", layers)
        self.assertIn("telefon", layers)

        isim = layers["isim"]
        center_x = isim["x"] + isim["w"] / 2.0
        self.assertAlmostEqual(center_x, 858.0, delta=2.0)
        self.assertEqual(isim.get("align"), "center")

        unvan = layers["unvan"]
        unvan_center_x = unvan["x"] + unvan["w"] / 2.0
        self.assertAlmostEqual(unvan_center_x, 858.0, delta=2.0)
        self.assertEqual(unvan.get("align"), "center")

        telefon = layers["telefon"]
        right_x = telefon["x"] + telefon["w"]
        self.assertAlmostEqual(right_x, 978.0, delta=4.0)
        self.assertEqual(telefon.get("align"), "right")

    def test_07_natural_language_command_engine(self):
        """Verifies Turkish NLP commands for resizing, centering, text updating, and deleting."""
        layers = self.state.get("layers", [])

        # 1. Update text
        upd_layers, _ = card_layer_engine.apply_natural_language_command("telefonu 0554 248 10 99 yap", layers)
        tel = next((l for l in upd_layers if l.get("id") == "telefon"), None)
        self.assertIsNotNone(tel)
        self.assertEqual(tel.get("text"), "0554 248 10 99")

        # 2. Resize / enlarge
        upd_layers, _ = card_layer_engine.apply_natural_language_command("ismi büyüt", layers)
        isim = next((l for l in upd_layers if l.get("id") == "isim"), None)
        orig_isim = next((l for l in layers if l.get("id") == "isim"), None)
        self.assertGreater(isim.get("fontSize", 0), orig_isim.get("fontSize", 0))

        # 3. Center
        upd_layers, _ = card_layer_engine.apply_natural_language_command("logoyu ortala", layers)
        logo = next((l for l in upd_layers if l.get("id") == "logo"), None)
        self.assertEqual(logo.get("x"), (1024 - logo.get("w")) // 2)

        # 4. Delete
        upd_layers, _ = card_layer_engine.apply_natural_language_command("adresi sil", layers)
        self.assertIsNone(next((l for l in upd_layers if l.get("id") == "adres"), None))

    def test_08_recomposition_visual_similarity(self):
        """Verifies re-compositing decomposed layers yields SSIM >= 0.92 and dHash <= 6."""
        recomposed = card_layer_engine.render_card(self.state)
        ssim_val = compute_ssim_simple(recomposed, self.ref_path)
        dhash_dist = compute_dhash_distance(recomposed, self.ref_path)

        self.assertGreaterEqual(ssim_val, 0.92, f"SSIM ({ssim_val:.4f}) is below 0.92")
        self.assertLessEqual(dhash_dist, 6, f"dHash distance ({dhash_dist}) exceeds 6 bits")


if __name__ == "__main__":
    unittest.main()
