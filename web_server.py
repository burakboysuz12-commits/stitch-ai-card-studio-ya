"""
Stitch AI+ Cloud-Enabled Web Server
Provides 24/7 web hosting, interactive business card editor, and REST API for natural language design editing.
"""

import copy
import json
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

PORT = int(os.environ.get("PORT", "8080"))
HOST = "0.0.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EDITOR_HTML_PATH = os.path.join(BASE_DIR, "ai_projects", "gorsel_parcali_editor.html")
ACTIVE_DESIGN_STATE_PATH = os.environ.get(
    "ACTIVE_DESIGN_STATE_PATH",
    os.path.join(BASE_DIR, "ai_projects", "_active_design_state.json")
)

_STATE_WRITE_LOCK = threading.Lock()


def get_active_design_state_path() -> str:
    """Returns active design state path, allowing runtime environment overrides."""
    return os.environ.get("ACTIVE_DESIGN_STATE_PATH", ACTIVE_DESIGN_STATE_PATH)

# Turkish color keyword mapping
TR_COLORS = {
    "altın": "#d4af37",
    "altin": "#d4af37",
    "gold": "#d4af37",
    "gümüş": "#c0c0c0",
    "gumus": "#c0c0c0",
    "silver": "#c0c0c0",
    "bakır": "#b87333",
    "bakir": "#b87333",
    "lacivert": "#0f172a",
    "koyu mavi": "#1e3a8a",
    "mavi": "#2563eb",
    "turkuaz": "#06b6d4",
    "cyan": "#06b6d4",
    "kırmızı": "#dc2626",
    "kirmizi": "#dc2626",
    "bordo": "#7f1d1d",
    "yeşil": "#16a34a",
    "yesil": "#16a34a",
    "zümrüt": "#059669",
    "siyah": "#0f1116",
    "beyaz": "#ffffff",
    "gri": "#6b7280",
    "koyu gri": "#374151",
    "açık gri": "#e5e7eb",
    "mor": "#7c3aed",
    "turuncu": "#ea580c",
    "sarı": "#eab308",
    "sari": "#eab308",
}

SEMANTIC_LAYER_ALIASES = {
    "isim": ["isim", "ismi", "ismini", "ad", "adı", "adını", "ad soyad", "kişi", "name"],
    "unvan": ["unvan", "unvanı", "unvanını", "ünvan", "ünvanı", "ünvanını", "meslek", "pozisyon", "görev", "title"],
    "telefon": ["telefon", "telefonu", "telefonunu", "tel", "cep", "numara", "numarası", "numarasını", "phone"],
    "telefon_2": ["telefon 2", "telefonu 2", "ikinci telefon", "sabit hat", "tel2"],
    "eposta": ["eposta", "epostayı", "e-posta", "e-postayı", "mail", "maili", "email"],
    "eposta_2": ["eposta 2", "ikinci mail", "ikinci eposta", "email2"],
    "adres": ["adres", "adresi", "adresini", "konum", "yer", "address"],
    "slogan": ["slogan", "sloganı", "alt metin", "açıklama"],
    "logo": ["logo", "logoyu", "amblem", "ikon", "görsel"],
    "qr_kod": ["qr", "qr kod", "karekod"],
}


def resolve_color(text: str) -> Optional[str]:
    """Resolves hex or Turkish color name from text."""
    hex_m = re.search(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", text)
    if hex_m:
        return "#" + hex_m.group(1).lower()
    text_lower = text.lower()
    for name, hex_val in TR_COLORS.items():
        if re.search(r"\b" + re.escape(name) + r"\b", text_lower):
            return hex_val
    return None


def is_valid_design_state(state: Any) -> bool:
    """Validates that state is a valid dictionary with canvas dimensions or elements."""
    if not isinstance(state, dict) or not state:
        return False

    # If elements is present, it must be a list
    if "elements" in state and not isinstance(state["elements"], list):
        return False

    # If layers is present, it must be a list
    if "layers" in state and not isinstance(state["layers"], list):
        return False

    has_dimensions = (
        ("width" in state and isinstance(state["width"], (int, float)) and state["width"] > 0)
        or ("height" in state and isinstance(state["height"], (int, float)) and state["height"] > 0)
        or ("canvas" in state and isinstance(state.get("canvas"), dict))
    )
    has_elements = "elements" in state and isinstance(state["elements"], list)
    has_layers = "layers" in state and isinstance(state["layers"], list)

    return has_dimensions or has_elements or has_layers


def get_default_design_state() -> Dict[str, Any]:
    """Returns a default 1024x686 card design state."""
    return {
        "title": "Kartvizit Tasarımı",
        "width": 1024,
        "height": 686,
        "canvas": {"width": 1024, "height": 686},
        "background": "#0f1116",
        "elements": [],
        "layers": [],
        "updated_at": time.time(),
    }


def clamp_layer_boundaries(
    layers: List[Dict[str, Any]], canvas_w: int = 1024, canvas_h: int = 686
) -> List[Dict[str, Any]]:
    """Strictly clamps all element coordinates to [0, canvas_w - el_w] and [0, canvas_h - el_h]."""
    for el in layers:
        if not isinstance(el, dict):
            continue
        try:
            el_w = int(float(el.get("w", el.get("width", 100))))
        except (ValueError, TypeError):
            el_w = 100
        try:
            el_h = int(float(el.get("h", el.get("height", 40))))
        except (ValueError, TypeError):
            el_h = 40
        max_x = max(0, canvas_w - el_w)
        max_y = max(0, canvas_h - el_h)
        if "x" in el:
            try:
                el["x"] = max(0, min(int(float(el["x"])), max_x))
            except (ValueError, TypeError):
                el["x"] = 0
        if "y" in el:
            try:
                el["y"] = max(0, min(int(float(el["y"])), max_y))
            except (ValueError, TypeError):
                el["y"] = 0
    return layers


def load_design_state() -> Dict[str, Any]:
    """Loads active design state from disk or initializes from card_layer_engine if absent."""
    state_path = get_active_design_state_path()
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "elements" not in data and "layers" in data:
                        data["elements"] = data["layers"]
                    elif "layers" not in data and "elements" in data:
                        data["layers"] = data["elements"]
                    if not isinstance(data.get("elements"), list):
                        data["elements"] = []
                    if not isinstance(data.get("layers"), list):
                        data["layers"] = data.get("elements", [])
                    return data
        except Exception:
            pass

    # If no active state file exists, initialize from card_layer_engine.decompose_card
    try:
        import card_layer_engine
        image_candidates = [
            os.path.join(BASE_DIR, "kartvizit_son_orijinal.png"),
            os.path.join(os.getcwd(), "kartvizit_son_orijinal.png"),
            "kartvizit_son_orijinal.png",
        ]
        target_img = next((p for p in image_candidates if os.path.isfile(p)), None)
        if target_img:
            decomp = card_layer_engine.decompose_card(target_img)
            if decomp and isinstance(decomp.get("layers"), list) and decomp["layers"]:
                bg_path = decomp.get("background") or decomp.get("background_image") or "#0f1116"
                initial_state = {
                    "title": "Görsel Parça Editörü (kartvizit_son_orijinal.png)",
                    "width": 1024,
                    "height": 686,
                    "canvas": {"width": 1024, "height": 686},
                    "background": bg_path,
                    "background_image": decomp.get("background_image", bg_path),
                    "elements": decomp.get("layers", []),
                    "layers": decomp.get("layers", []),
                    "updated_at": time.time(),
                }
                save_design_state(initial_state)
                return initial_state
    except Exception:
        pass

    return get_default_design_state()


def save_design_state(state: Dict[str, Any]) -> bool:
    """Saves active design state to disk atomically with concurrency locking and retry on Windows."""
    if not is_valid_design_state(state):
        return False
    try:
        state_path = get_active_design_state_path()
        dir_name = os.path.dirname(os.path.abspath(state_path))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        state_copy = copy.deepcopy(state)
        # Ensure elements and layers are always lists
        if not isinstance(state_copy.get("elements"), list):
            if isinstance(state_copy.get("layers"), list):
                state_copy["elements"] = state_copy["layers"]
            else:
                state_copy["elements"] = []
        if not isinstance(state_copy.get("layers"), list):
            state_copy["layers"] = state_copy["elements"]

        state_copy["updated_at"] = time.time()

        with _STATE_WRITE_LOCK:
            temp_fd, temp_path = tempfile.mkstemp(dir=dir_name or None, prefix="_state_", suffix=".tmp")
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(state_copy, f, ensure_ascii=False, indent=2)

                # Retry loop up to 5 attempts with 0.02s sleep catching PermissionError (WinError 5)
                for attempt in range(5):
                    try:
                        os.replace(temp_path, state_path)
                        return True
                    except PermissionError:
                        if attempt < 4:
                            time.sleep(0.02)
                        else:
                            raise
                return True
            except Exception:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                raise
    except Exception:
        return False


_NLP_RECURSION_GUARD = False


def process_natural_language_edit(
    prompt: str, selected_id: str, state: Dict[str, Any]
) -> Tuple[Dict[str, Any], str, bool]:
    """
    Applies natural language edit commands to design state.
    Delegates to card_layer_engine.apply_natural_language_command when appropriate.
    Returns (updated_state, summary_message, success).
    """
    global _NLP_RECURSION_GUARD

    if not isinstance(state, dict):
        state = get_default_design_state()

    prompt_raw = (prompt if isinstance(prompt, str) else str(prompt or "")).strip()
    if not prompt_raw:
        return state, "Boş komut iletildi.", False

    selected_id = str(selected_id) if selected_id is not None else ""
    pl = prompt_raw.lower()
    updated = copy.deepcopy(state)
    elements = updated.get("elements")
    if not isinstance(elements, list):
        if isinstance(updated.get("layers"), list):
            elements = updated["layers"]
        else:
            elements = []
        updated["elements"] = elements
    updated["layers"] = elements

    canvas_w = int(updated.get("width", 1024))
    canvas_h = int(updated.get("height", 686))
    notes: List[str] = []

    # 1. Background color edit
    if any(k in pl for k in ("arka plan", "arkaplan", "zemin", "background")):
        c = resolve_color(pl)
        if c:
            updated["background"] = c
            updated["background_image"] = c
            notes.append(f"Arka plan rengi {c} yapıldı")
        elif "şeffaf" in pl or "transparent" in pl:
            updated["background"] = "transparent"
            updated["background_image"] = "transparent"
            notes.append("Arka plan şeffaf yapıldı")
        if notes:
            summary = "; ".join(notes)
            save_design_state(updated)
            return updated, summary, True

    # 2. Element color edit (evaluated before engine to prevent engine interpreting color as text replacement)
    elem_color = resolve_color(pl)
    if elem_color and any(w in pl for w in ("renk", "rengi", "boya", "yap", "olsun", "ton")):
        # Find target element (from selected_id or semantic layer aliases or default to isim)
        sel_el = next((e for e in elements if isinstance(e, dict) and str(e.get("id")) == str(selected_id)), None)
        target_el = sel_el
        for layer_id, aliases in SEMANTIC_LAYER_ALIASES.items():
            if any(re.search(r"\b" + re.escape(alias) + r"\b", pl) for alias in aliases):
                found = next((e for e in elements if isinstance(e, dict) and str(e.get("id")) == layer_id), None)
                if found:
                    target_el = found
                    break
        if not target_el:
            target_el = next((e for e in elements if isinstance(e, dict) and str(e.get("id")) == "isim"), elements[0] if elements else None)

        if target_el:
            target_el["color"] = elem_color
            notes.append(f"#{target_el.get('id')} rengi {elem_color} yapıldı")
            clamp_layer_boundaries(elements, canvas_w, canvas_h)
            updated["elements"] = elements
            updated["layers"] = elements
            summary = "; ".join(notes)
            save_design_state(updated)
            return updated, summary, True

    # 3. Delegate to card_layer_engine.apply_natural_language_command if not in recursion guard
    if not _NLP_RECURSION_GUARD:
        _NLP_RECURSION_GUARD = True
        try:
            import card_layer_engine
            target_cmd = prompt_raw
            if not any(kw in pl for kw in ("isim", "unvan", "ünvan", "telefon", "adres", "eposta", "logo", "qr", "slogan")):
                target_name = selected_id if selected_id else "isim"
                target_cmd = f"{target_name} {prompt_raw}"

            layers_in = copy.deepcopy(elements)
            updated_layers, engine_summary = card_layer_engine.apply_natural_language_command(target_cmd, layers_in)
            if updated_layers != layers_in or any(kw in engine_summary for kw in ("başarıyla", "ortalandı", "yaslandı", "kaydırıldı", "büyütüldü", "küçültüldü", "güncellendi", "rengi")):
                elements[:] = clamp_layer_boundaries(updated_layers, canvas_w, canvas_h)
                updated["elements"] = elements
                updated["layers"] = elements
                save_design_state(updated)
                return updated, engine_summary, True
        except Exception:
            pass
        finally:
            _NLP_RECURSION_GUARD = False

    # 4. Identify target element (selected element or mentioned semantic layer or fallback to isim)
    sel_el = next((e for e in elements if isinstance(e, dict) and str(e.get("id")) == str(selected_id)), None)
    target_el = sel_el
    target_layer_id = None
    for layer_id, aliases in SEMANTIC_LAYER_ALIASES.items():
        if any(re.search(r"\b" + re.escape(alias) + r"\b", pl) for alias in aliases):
            found = next((e for e in elements if isinstance(e, dict) and str(e.get("id")) == layer_id), None)
            if found:
                target_el = found
                target_layer_id = layer_id
                break

    if not target_el:
        target_el = next((e for e in elements if isinstance(e, dict) and str(e.get("id")) == "isim"), elements[0] if elements else None)

    # 5. Delete command
    if any(w in pl for w in ("sil", "kaldır", "kaldir", "yok et")):
        if target_el:
            elements[:] = [e for e in elements if isinstance(e, dict) and e.get("id") != target_el.get("id")]
            notes.append(f"#{target_el.get('id')} katmanı silindi")
            target_el = None

    def _to_num(val, default):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _to_int(val, default):
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    # 6. Scaling (büyüt / büyük yap / küçült / küçük yap) - evaluated before text replacement to fix "ismi büyük yap"
    if target_el and not notes:
        if any(w in pl for w in ("büyüt", "buyut", "daha büyük", "büyük yap", "büyük olsun")):
            if "fontSize" in target_el:
                target_el["fontSize"] = int(_to_num(target_el.get("fontSize"), 16) * 1.25)
            target_el["w"] = int(_to_num(target_el.get("w"), 100) * 1.2)
            target_el["h"] = int(_to_num(target_el.get("h"), 40) * 1.2)
            notes.append(f"#{target_el.get('id')} boyutu büyütüldü")
        elif any(w in pl for w in ("küçült", "kucult", "daha küçük", "küçük yap", "küçük olsun")):
            if "fontSize" in target_el:
                target_el["fontSize"] = max(10, int(_to_num(target_el.get("fontSize"), 16) * 0.8))
            target_el["w"] = max(20, int(_to_num(target_el.get("w"), 100) * 0.8))
            target_el["h"] = max(15, int(_to_num(target_el.get("h"), 40) * 0.8))
            notes.append(f"#{target_el.get('id')} boyutu küçültüldü")

    # 6. Alignment / Movement
    if target_el and not notes:
        el_w = _to_int(target_el.get("w"), 100)
        el_h = _to_int(target_el.get("h"), 40)
        if "ortala" in pl:
            target_el["x"] = max(0, (canvas_w - el_w) // 2)
            notes.append(f"#{target_el.get('id')} yatayda ortalandı")
        elif any(w in pl for w in ("sağa", "saga")):
            target_el["x"] = min(canvas_w - el_w, _to_int(target_el.get("x"), 0) + 30)
            notes.append(f"#{target_el.get('id')} sağa kaydırıldı")
        elif any(w in pl for w in ("sola",)):
            target_el["x"] = max(0, _to_int(target_el.get("x"), 0) - 30)
            notes.append(f"#{target_el.get('id')} sola kaydırıldı")
        elif any(w in pl for w in ("yukarı", "yukari")):
            target_el["y"] = max(0, _to_int(target_el.get("y"), 0) - 30)
            notes.append(f"#{target_el.get('id')} yukarı alındı")
        elif any(w in pl for w in ("aşağı", "asagi")):
            target_el["y"] = min(canvas_h - el_h, _to_int(target_el.get("y"), 0) + 30)
            notes.append(f"#{target_el.get('id')} aşağı alındı")

    # 7. Color change for target element
    if target_el and not notes:
        color = resolve_color(pl)
        if color and any(w in pl for w in ("renk", "rengi", "boya", "yap", "olsun", "ton")):
            target_el["color"] = color
            notes.append(f"#{target_el.get('id')} rengi {color} yapıldı")

    # 8. Text content replacement
    if target_el and not notes:
        m_yap = re.search(r"['\"]?([^'\"]+?)['\"]?\s*(?:yap|olsun|olarak değiştir)$", prompt_raw, re.IGNORECASE)
        if m_yap:
            new_val = m_yap.group(1).strip()
            # Strip target keyword prefix if captured
            for k in (
                "telefonu", "telefon", "telefonunu", "numarayı", "numara",
                "ismi", "isim", "ismini", "adını", "adı", "ad",
                "unvanı", "unvan", "ünvanı", "ünvan", "mesleği",
                "adresi", "adres", "adresini",
                "epostayı", "eposta", "maili", "mail", "e-postayı", "e-posta",
                "metni", "metin", "yazıyı", "yazı", "sloganı", "slogan",
            ):
                if new_val.lower().startswith(k + " "):
                    new_val = new_val[len(k) + 1:].strip()
            color_check = resolve_color(new_val)
            if color_check and len(new_val.split()) <= 2:
                target_el["color"] = color_check
                notes.append(f"#{target_el.get('id')} rengi {color_check} yapıldı")
            elif len(new_val) >= 1:
                target_el["text"] = new_val
                notes.append(f"#{target_el.get('id')} metni güncellendi: {new_val}")

    # 9. Add element command (e.g. "metin ekle 'Yeni Metin'")
    if not notes and any(w in pl for w in ("ekle", "yeni metin", "yazı ekle")):
        m_txt = re.search(r"['\"]([^'\"]+)['\"]", prompt_raw)
        txt = m_txt.group(1) if m_txt else "Yeni Metin"
        new_id = f"katman_{len(elements) + 1}"
        new_el = {
            "id": new_id,
            "label": txt,
            "type": "text",
            "text": txt,
            "x": 100,
            "y": 100 + len(elements) * 30,
            "w": 250,
            "h": 40,
            "color": "#ffffff",
            "fontSize": 18,
            "bg": "transparent",
        }
        elements.append(new_el)
        notes.append(f"Yeni #{new_id} katmanı eklendi: '{txt}'")

    clamp_layer_boundaries(elements, canvas_w, canvas_h)
    updated["elements"] = elements
    updated["layers"] = elements

    if notes:
        summary = "; ".join(notes)
        save_design_state(updated)
        return updated, summary, True
    else:
        summary = f"Komut işlendi ancak eşleşen kural bulunamadı: '{prompt_raw}'"
        return updated, summary, False


class StitchWebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep logs clean; un-comment for local debugging if desired
        return

    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.end_headers()

    def _reject_unsupported_method(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                self.rfile.read(min(content_length, 1024 * 1024))
        except Exception:
            pass
        self._send_json(405, {"ok": False, "error": "Method Not Allowed"})

    def do_PUT(self):
        self._reject_unsupported_method()

    def do_DELETE(self):
        self._reject_unsupported_method()

    def do_PATCH(self):
        self._reject_unsupported_method()

    def do_GET(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                self.rfile.read(min(content_length, 16 * 1024 * 1024))
        except Exception:
            pass

        path = urlparse(self.path).path

        # 1. Health check endpoint
        if path == "/api/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "stitch_ai_web",
                    "port": PORT,
                    "status": "healthy",
                    "version": "1.0.0",
                    "timestamp": time.time(),
                },
            )
            return

        # 2. Design state endpoint (GET)
        if path in ("/api/design/state", "/api/state"):
            state = load_design_state()
            layers = state.get("elements") if isinstance(state.get("elements"), list) else state.get("layers", [])
            canvas_w = state.get("width", 1024)
            canvas_h = state.get("height", 686)
            if isinstance(state.get("canvas"), dict):
                canvas_w = state["canvas"].get("width", canvas_w)
                canvas_h = state["canvas"].get("height", canvas_h)
            self._send_json(
                200,
                {
                    "ok": True,
                    "success": True,
                    "state": state,
                    "layers": layers,
                    "canvas": {
                        "width": canvas_w,
                        "height": canvas_h,
                    },
                },
            )
            return

        # 3. Editor frontend
        if path in ("/", "/editor"):
            if os.path.isfile(EDITOR_HTML_PATH):
                with open(EDITOR_HTML_PATH, "rb") as f:
                    html = f.read()
            else:
                html = (
                    "<!doctype html><html lang='tr'><meta charset='utf-8'>"
                    "<body style='background:#0f1116;color:#f3f4f6;font-family:sans-serif;padding:40px'>"
                    "<h2>Stitch AI+ Web Sunucusu Aktif</h2>"
                    "<p>Henüz kaydedilmiş bir editör bulunamadı.</p>"
                    "</body></html>"
                ).encode("utf-8")
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        self._send_json(404, {"ok": False, "error": "not_found", "path": path})

    def do_POST(self):
        path = urlparse(self.path).path

        # Parse request body safely
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(min(content_length, 16 * 1024 * 1024))
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": f"Invalid JSON payload: {exc}"})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"ok": False, "error": "Payload must be a JSON object"})
            return

        # 1. AI natural language editing endpoint
        if path == "/api/ai_edit":
            if "prompt" in payload and not isinstance(payload["prompt"], str):
                self._send_json(400, {"ok": False, "error": "Prompt must be a string"})
                return
            if "command" in payload and not isinstance(payload["command"], str):
                self._send_json(400, {"ok": False, "error": "Prompt must be a string"})
                return
            if "selectedId" in payload and not isinstance(payload["selectedId"], str):
                self._send_json(400, {"ok": False, "error": "selectedId must be a string"})
                return
            if "selected_id" in payload and not isinstance(payload["selected_id"], str):
                self._send_json(400, {"ok": False, "error": "selectedId must be a string"})
                return

            prompt = payload.get("prompt") or payload.get("command") or ""
            selected_id = payload.get("selectedId") or payload.get("selected_id") or ""
            client_state = payload.get("state")

            if not isinstance(client_state, dict):
                # If caller provided `layers` directly
                layers = payload.get("layers")
                if isinstance(layers, list):
                    client_state = get_default_design_state()
                    client_state["elements"] = layers
                else:
                    client_state = load_design_state()

            try:
                updated_state, summary, success = process_natural_language_edit(
                    prompt=prompt, selected_id=selected_id, state=client_state
                )
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"Error processing edit: {exc}"})
                return

            self._send_json(
                200,
                {
                    "ok": True,
                    "success": success,
                    "state": updated_state,
                    "layers": updated_state.get("elements", []) if isinstance(updated_state.get("elements"), list) else [],
                    "summary": summary,
                    "action_summary": summary,
                },
            )
            return

        # 2. Design state save endpoint (POST)
        if path in ("/api/design/state", "/api/state"):
            if not payload:
                self._send_json(400, {"ok": False, "error": "Empty payload provided"})
                return

            new_state = payload.get("state")
            if new_state is None and ("elements" in payload or "layers" in payload):
                layers_val = payload.get("layers") if "layers" in payload else payload.get("elements")
                if not isinstance(layers_val, list):
                    self._send_json(400, {"ok": False, "error": "Malformed elements: must be a list"})
                    return
                new_state = load_design_state()
                new_state["elements"] = layers_val
            elif new_state is None:
                new_state = payload

            if not is_valid_design_state(new_state):
                self._send_json(400, {"ok": False, "error": "Invalid or malformed design state schema"})
                return

            saved = save_design_state(new_state)
            if not saved:
                self._send_json(400, {"ok": False, "error": "Failed to validate or save design state"})
                return

            layers_out = new_state.get("elements") if isinstance(new_state.get("elements"), list) else new_state.get("layers", [])
            self._send_json(
                200,
                {
                    "ok": True,
                    "success": True,
                    "message": "Design state saved successfully",
                    "state": new_state,
                    "layers": layers_out,
                },
            )
            return

        self._send_json(404, {"ok": False, "error": "not_found", "path": path})


def run_server(port: int = PORT, host: str = HOST):
    server = ThreadingHTTPServer((host, port), StitchWebHandler)
    print(f"Stitch AI+ Web Server running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()


if __name__ == "__main__":
    run_server()
