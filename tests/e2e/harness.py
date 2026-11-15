"""
tests/e2e/harness.py — Isolation harnesses, ephemeral test servers, and objective metrics.
"""

import contextlib
import gc
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, Optional, Tuple, Union

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Headless display enforcement
os.environ["MPLBACKEND"] = "Agg"
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def tier(level: int):
    """Decorator to assign an execution tier (1..5) to a TestCase or test method."""
    def decorator(obj):
        obj.__tier__ = level
        # Also attach pytest marker if pytest is installed/used
        try:
            import pytest
            marker = getattr(pytest.mark, f"tier{level}", None)
            if marker:
                obj = marker(obj)
        except Exception:
            pass
        return obj
    return decorator


class EphemeralServer:
    """Manages an isolated ThreadingHTTPServer on an OS-allocated ephemeral port with state sandboxing."""

    def __init__(self, handler_factory=None, initial_state: Optional[Dict[str, Any]] = None):
        if handler_factory is None:
            import web_server
            self.handler_factory = web_server.StitchWebHandler
        else:
            self.handler_factory = handler_factory
        self.initial_state = initial_state
        self.server = None
        self.thread = None
        self.port = 0
        self.base_url = ""
        self._temp_dir = None
        self._orig_state_env = None
        self._orig_server_state_path = None

    def __enter__(self):
        from http.server import ThreadingHTTPServer

        # Hermetic filesystem isolation: redirect active design state away from workspace root
        self._temp_dir = tempfile.mkdtemp(prefix="ephemeral_server_state_")
        self._temp_state = os.path.join(self._temp_dir, "_active_design_state.json")
        default_state_path = os.path.join(PROJECT_ROOT, "ai_projects", "_active_design_state.json")

        try:
            if self.initial_state is not None:
                with open(self._temp_state, "w", encoding="utf-8") as f:
                    json.dump(self.initial_state, f, ensure_ascii=False, indent=2)
            elif os.path.isfile(default_state_path):
                try:
                    with open(default_state_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        # Ensure canvas dimensions conform to native 1024x686
                        if data.get("width") == 1004 and data.get("height") == 650:
                            data["width"] = 1024
                            data["height"] = 686
                        with open(self._temp_state, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                    else:
                        shutil.copy2(default_state_path, self._temp_state)
                except Exception:
                    shutil.copy2(default_state_path, self._temp_state)
            else:
                try:
                    import web_server
                    default_data = web_server.get_default_design_state()
                except Exception:
                    default_data = {
                        "title": "Kartvizit Tasarımı",
                        "width": 1024,
                        "height": 686,
                        "background": "#0f1116",
                        "elements": [],
                        "updated_at": time.time(),
                    }
                with open(self._temp_state, "w", encoding="utf-8") as f:
                    json.dump(default_data, f, ensure_ascii=False, indent=2)

            self._orig_state_env = os.environ.get("ACTIVE_DESIGN_STATE_PATH")
            os.environ["ACTIVE_DESIGN_STATE_PATH"] = self._temp_state
            try:
                import web_server
                self._orig_server_state_path = getattr(web_server, "ACTIVE_DESIGN_STATE_PATH", None)
                web_server.ACTIVE_DESIGN_STATE_PATH = self._temp_state
            except Exception:
                pass

            # Port 0 instructs the OS kernel to allocate an unused ephemeral port
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_factory)
            self.port = self.server.server_address[1]
            self.base_url = f"http://127.0.0.1:{self.port}"

            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()

            # Health probe with 3.0s budget
            t_deadline = time.time() + 3.0
            healthy = False
            while time.time() < t_deadline:
                try:
                    with urllib.request.urlopen(f"{self.base_url}/api/health", timeout=0.5) as resp:
                        if resp.status == 200:
                            healthy = True
                            break
                except Exception:
                    time.sleep(0.05)
            return self
        except Exception:
            self._cleanup()
            raise

    def _cleanup(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            self.thread = None

        # Restore state path configuration
        if self._orig_state_env is not None:
            os.environ["ACTIVE_DESIGN_STATE_PATH"] = self._orig_state_env
        else:
            os.environ.pop("ACTIVE_DESIGN_STATE_PATH", None)

        try:
            import web_server
            if self._orig_server_state_path is not None:
                web_server.ACTIVE_DESIGN_STATE_PATH = self._orig_server_state_path
            else:
                web_server.ACTIVE_DESIGN_STATE_PATH = os.environ.get(
                    "ACTIVE_DESIGN_STATE_PATH",
                    os.path.join(PROJECT_ROOT, "ai_projects", "_active_design_state.json")
                )
        except Exception:
            pass

        # Cleanup temporary directory with Windows retry logic
        if self._temp_dir:
            gc.collect()
            for _ in range(5):
                try:
                    if os.path.exists(self._temp_dir):
                        shutil.rmtree(self._temp_dir, ignore_errors=True)
                    break
                except Exception:
                    time.sleep(0.05)
                    gc.collect()
            self._temp_dir = None

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cleanup()


@contextlib.contextmanager
def isolated_sandbox(prefix: str = "card_e2e_") -> Generator[str, None, None]:
    """Provides a fresh, isolated temporary directory with Windows-safe cleanup."""
    tmpdir = tempfile.mkdtemp(prefix=prefix)
    try:
        yield tmpdir
    finally:
        gc.collect()
        for _ in range(5):
            try:
                if os.path.exists(tmpdir):
                    shutil.rmtree(tmpdir)
                break
            except PermissionError:
                time.sleep(0.1)
                gc.collect()


@contextlib.contextmanager
def isolated_environ(**kwargs) -> Generator[None, None, None]:
    """Sandboxes os.environ, restoring original variables on exit."""
    original = os.environ.copy()
    os.environ.update(kwargs)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _to_numpy_rgb(img_input: Any):
    """Converts a file path, PIL Image, or numpy array to an RGB numpy array (uint8)."""
    import numpy as np
    from PIL import Image

    if isinstance(img_input, str):
        with Image.open(img_input) as pimg:
            return np.array(pimg.convert("RGB"), dtype=np.uint8)
    if hasattr(img_input, "convert"):
        return np.array(img_input.convert("RGB"), dtype=np.uint8)
    if isinstance(img_input, np.ndarray):
        if len(img_input.shape) == 2:
            import cv2
            return cv2.cvtColor(img_input, cv2.COLOR_GRAY2RGB)
        elif img_input.shape[2] == 4:
            import cv2
            return cv2.cvtColor(img_input, cv2.COLOR_RGBA2RGB)
        elif img_input.shape[2] == 3:
            return img_input.astype(np.uint8)
    raise TypeError(f"Unsupported image input type: {type(img_input)}")


def compute_dhash(img_input: Any) -> int:
    """Computes standard 64-bit difference hash for perceptual image matching."""
    import cv2
    import numpy as np

    arr = _to_numpy_rgb(img_input)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    return sum(1 << i for i, v in enumerate(diff.flatten()) if v)


def compute_dhash_distance(img1: Any, img2: Any) -> int:
    """Computes Hamming distance between two image dHashes (0-64 bits)."""
    h1 = compute_dhash(img1)
    h2 = compute_dhash(img2)
    return bin(h1 ^ h2).count("1")


def compute_ssim_simple(img1: Any, img2: Any) -> float:
    """Computes fast SSIM approximation between two RGB images (range -1.0 to 1.0)."""
    import cv2
    import numpy as np

    i1_arr = _to_numpy_rgb(img1)
    i2_arr = _to_numpy_rgb(img2)

    if i1_arr.shape != i2_arr.shape:
        i2_arr = cv2.resize(i2_arr, (i1_arr.shape[1], i1_arr.shape[0]))

    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    i1 = i1_arr.astype(np.float64)
    i2 = i2_arr.astype(np.float64)

    mu1 = cv2.GaussianBlur(i1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(i2, (11, 11), 1.5)

    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.GaussianBlur(i1 ** 2, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(i2 ** 2, (11, 11), 1.5) - mu2_sq
    sigma12 = cv2.GaussianBlur(i1 * i2, (11, 11), 1.5) - mu1_mu2

    ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))
    return float(np.mean(ssim_map))


def load_image_unicode_safe(path: str) -> "np.ndarray":
    """
    Loads an image safely on Windows even when path contains non-ASCII characters
    (such as Turkish characters in directory names). Returns RGB numpy array.
    """
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        return np.array(im.convert("RGB"), dtype=np.uint8)


def transform_layer_isotropic(
    layer: Dict[str, Any],
    src_dimensions: Tuple[int, int] = (1024, 686),
    target_width: int = 800,
) -> Dict[str, Any]:
    """
    Transforms a design state layer's coordinates isotropically to a target viewport width.
    Preserves exact aspect ratio and relative placement without coordinate drift.
    """
    import copy

    src_w, src_h = src_dimensions
    scale = float(target_width) / float(src_w)
    target_h = round(src_h * scale)

    scaled = copy.deepcopy(layer)
    scaled["x"] = round(layer["x"] * scale)
    scaled["y"] = round(layer["y"] * scale)

    w_key = "w" if "w" in layer else "width"
    h_key = "h" if "h" in layer else "height"
    if w_key in layer:
        scaled[w_key] = round(layer[w_key] * scale)
    if h_key in layer:
        scaled[h_key] = round(layer[h_key] * scale)

    if "fontSize" in layer:
        scaled["fontSize"] = round(layer["fontSize"] * scale)

    scaled["_target_dimensions"] = (target_width, target_h)
    scaled["_scale_factor"] = scale
    return scaled

