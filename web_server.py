"""
Stitch AI+ Cloud-Enabled Web Server
Provides 24/7 web hosting, interactive business card editor, and REST API for natural language design editing.
"""

import copy
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

PORT = int(os.environ.get("PORT", "8080"))
HOST = "0.0.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EDITOR_HTML_PATH = os.path.join(BASE_DIR, "ai_projects", "gorsel_parcali_editor.html")
ACTIVE_DESIGN_STATE_PATH = os.path.join(BASE_DIR, "ai_projects", "_active_design_state.json")

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


def get_default_design_state() -> Dict[str, Any]:
    """Returns a default 1024x686 card design state."""
    return {
        "title": "Kartvizit Tasarımı",
        "width": 1024,
        "height": 686,
        "background": "#0f1116",
        "elements": [],
        "updated_at": time.time(),
    }


def load_design_state() -> Dict[str, Any]:
    """Loads active design state from disk or returns default."""
    if os.path.isfile(ACTIVE_DESIGN_STATE_PATH):
        try:
            with open(ACTIVE_DESIGN_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return get_default_design_state()


def save_design_state(state: Dict[str, Any]) -> bool:
    """Saves active design state to disk."""
    try:
        os.makedirs(os.path.dirname(ACTIVE_DESIGN_STATE_PATH), exist_ok=True)
        state_copy = copy.deepcopy(state)
        state_copy["updated_at"] = time.time()
        with open(ACTIVE_DESIGN_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state_copy, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def process_natural_language_edit(
    prompt: str, selected_id: str, state: Dict[str, Any]
) -> Tuple[Dict[str, Any], str, bool]:
    """
    Applies natural language edit commands to design state.
    Returns (updated_state, summary_message, success).
    """
    prompt_raw = (prompt or "").strip()
    if not prompt_raw:
        return state, "Boş komut iletildi.", False

    pl = prompt_raw.lower()
    updated = copy.deepcopy(state)
    elements = updated.setdefault("elements", [])
    notes: List[str] = []

    # Find selected element
    sel_el = next((e for e in elements if str(e.get("id")) == str(selected_id)), None)

    # 1. Background color edit
    if any(k in pl for k in ("arka plan", "arkaplan", "zemin", "background")):
        c = resolve_color(pl)
        if c:
            updated["background"] = c
            notes.append(f"Arka plan rengi {c} yapıldı")
        elif "şeffaf" in pl or "transparent" in pl:
            updated["background"] = "transparent"
            notes.append("Arka plan şeffaf yapıldı")

    # 2. Identify target element (selected element or mentioned semantic layer)
    target_el = sel_el
    target_layer_id = None
    for layer_id, aliases in SEMANTIC_LAYER_ALIASES.items():
        if any(re.search(r"\b" + re.escape(alias) + r"\b", pl) for alias in aliases):
            found = next((e for e in elements if str(e.get("id")) == layer_id), None)
            if found:
                target_el = found
                target_layer_id = layer_id
                break

    # 3. Delete command
    if any(w in pl for w in ("sil", "kaldır", "kaldir", "yok et")):
        if target_el:
            elements[:] = [e for e in elements if e.get("id") != target_el.get("id")]
            notes.append(f"#{target_el.get('id')} katmanı silindi")
            target_el = None

    # 4. Scaling (büyüt / büyük yap / küçült / küçük yap) - evaluated before text replacement to fix "ismi büyük yap"
    if target_el and not notes:
        if any(w in pl for w in ("büyüt", "buyut", "daha büyük", "büyük yap", "büyük olsun")):
            if "fontSize" in target_el:
                target_el["fontSize"] = int(target_el.get("fontSize", 16) * 1.25)
            target_el["w"] = int(target_el.get("w", 100) * 1.2)
            target_el["h"] = int(target_el.get("h", 40) * 1.2)
            notes.append(f"#{target_el.get('id')} boyutu büyütüldü")
        elif any(w in pl for w in ("küçült", "kucult", "daha küçük", "küçük yap", "küçük olsun")):
            if "fontSize" in target_el:
                target_el["fontSize"] = max(10, int(target_el.get("fontSize", 16) * 0.8))
            target_el["w"] = max(20, int(target_el.get("w", 100) * 0.8))
            target_el["h"] = max(15, int(target_el.get("h", 40) * 0.8))
            notes.append(f"#{target_el.get('id')} boyutu küçültüldü")

    # 5. Alignment / Movement
    if target_el and not notes:
        canvas_w = int(updated.get("width", 1024))
        canvas_h = int(updated.get("height", 686))
        el_w = int(target_el.get("w", 100))
        el_h = int(target_el.get("h", 40))
        if "ortala" in pl:
            target_el["x"] = max(0, (canvas_w - el_w) // 2)
            notes.append(f"#{target_el.get('id')} yatayda ortalandı")
        elif any(w in pl for w in ("sağa", "saga")):
            target_el["x"] = min(canvas_w - el_w, int(target_el.get("x", 0)) + 30)
            notes.append(f"#{target_el.get('id')} sağa kaydırıldı")
        elif any(w in pl for w in ("sola",)):
            target_el["x"] = max(0, int(target_el.get("x", 0)) - 30)
            notes.append(f"#{target_el.get('id')} sola kaydırıldı")
        elif any(w in pl for w in ("yukarı", "yukari")):
            target_el["y"] = max(0, int(target_el.get("y", 0)) - 30)
            notes.append(f"#{target_el.get('id')} yukarı alındı")
        elif any(w in pl for w in ("aşağı", "asagi")):
            target_el["y"] = min(canvas_h - el_h, int(target_el.get("y", 0)) + 30)
            notes.append(f"#{target_el.get('id')} aşağı alındı")

    # 6. Color change for target element
    if target_el and not notes:
        color = resolve_color(pl)
        if color and any(w in pl for w in ("renk", "rengi", "boya", "yap", "olsun", "ton")):
            target_el["color"] = color
            notes.append(f"#{target_el.get('id')} rengi {color} yapıldı")

    # 7. Text content replacement
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

    # 8. Add element command (e.g. "metin ekle 'Yeni Metin'")
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

    def do_GET(self):
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
            self._send_json(
                200,
                {
                    "ok": True,
                    "success": True,
                    "state": state,
                    "layers": state.get("elements", []),
                    "canvas": {
                        "width": state.get("width", 1024),
                        "height": state.get("height", 686),
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

        # 1. AI natural language editing endpoint
        if path == "/api/ai_edit":
            prompt = payload.get("prompt") or payload.get("command") or ""
            selected_id = payload.get("selectedId") or ""
            client_state = payload.get("state")

            if not client_state:
                # If caller provided `layers` directly
                layers = payload.get("layers")
                if isinstance(layers, list):
                    client_state = get_default_design_state()
                    client_state["elements"] = layers
                else:
                    client_state = load_design_state()

            updated_state, summary, success = process_natural_language_edit(
                prompt=prompt, selected_id=selected_id, state=client_state
            )

            self._send_json(
                200,
                {
                    "ok": True,
                    "success": success,
                    "state": updated_state,
                    "layers": updated_state.get("elements", []),
                    "summary": summary,
                    "action_summary": summary,
                },
            )
            return

        # 2. Design state save endpoint (POST)
        if path in ("/api/design/state", "/api/state"):
            new_state = payload.get("state")
            if not new_state and ("elements" in payload or "layers" in payload):
                new_state = payload.get("state") or load_design_state()
                if "layers" in payload:
                    new_state["elements"] = payload["layers"]
                elif "elements" in payload:
                    new_state["elements"] = payload["elements"]
            elif not new_state:
                new_state = payload

            saved = save_design_state(new_state)
            self._send_json(
                200,
                {
                    "ok": saved,
                    "success": saved,
                    "message": "Design state saved successfully" if saved else "Failed to save state",
                    "layers": new_state.get("elements", []),
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
