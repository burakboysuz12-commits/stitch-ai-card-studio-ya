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
    """Manages an isolated ThreadingHTTPServer on an OS-allocated ephemeral port."""

    def __init__(self, handler_factory=None):
        if handler_factory is None:
            import web_server
            self.handler_factory = web_server.StitchWebHandler
        else:
            self.handler_factory = handler_factory
        self.server = None
        self.thread = None
        self.port = 0
        self.base_url = ""

    def __enter__(self):
        from http.server import ThreadingHTTPServer
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

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)


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
