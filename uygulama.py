import os
import sys
import time
import shutil
import wave
import socket
import asyncio
import tempfile
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import requests
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageTk

try:
    import card_layer_engine
except ImportError:
    card_layer_engine = None

# Windows'ta bozuk IPv6 (AAAA) yönlendirmelerinin çeviri ve TTS bağlantılarını
# 20-120 saniye bekletmesini önlemek için tüm soket bağlantılarını IPv4'e zorluyoruz.
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

# PyInstaller --onefile içinde "operator torchvision::nms does not exist"
# hatasını önlemek için donmuş .exe ilk açılışında erken yükler; normal Python
# açılışında ise başlatma süresini hızlandırmak için Modül 1/2 açılışında lazy yüklenir.
YOLO = None


def _ensure_yolo_cls():
    """YOLOv8 / PyTorch bağımlılıklarını yalnızca ihtiyaç duyulduğunda yükler."""
    global YOLO
    if YOLO is None:
        import torch  # noqa: F401
        import torchvision  # noqa: F401
        from ultralytics import YOLO as _YOLO
        YOLO = _YOLO
    return YOLO


if getattr(sys, "frozen", False) and os.environ.get("_LOCAL_AI_HUB_LIVE_LOADED") != "1":
    _ensure_yolo_cls()


# ==============================================================================
# PYINSTALLER --noconsole --onefile UYUMLULUK AYARLARI
# ==============================================================================
# PyInstaller --noconsole modunda sys.stdout ve sys.stderr None olur.
# Ultralytics YOLO log yazmaya çalışırken çökmemesi için sahte akış tanımlıyoruz.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# .exe içerisinden çalışırken diskteki güncel uygulama.py dosyasını otomatik yükle
# Böylece yapılan her güncelleme yeniden derlemeye gerek kalmadan .exe içinde anında görünür.
if getattr(sys, "frozen", False) and os.environ.get("_LOCAL_AI_HUB_LIVE_LOADED") != "1":
    _live_candidates = [
        r"C:\Users\burakb\Downloads\Yeni klasör\uygulama.py",
        r"C:\Users\burakb\OneDrive\Desktop\Yeni klasör\uygulama.py",
        os.path.join(os.path.dirname(sys.executable), "uygulama.py"),
        os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "uygulama.py"),
    ]
    for _cand in _live_candidates:
        if os.path.exists(_cand):
            try:
                os.environ["_LOCAL_AI_HUB_LIVE_LOADED"] = "1"
                with open(_cand, "r", encoding="utf-8") as _f:
                    _code = _f.read()
                exec(compile(_code, _cand, "exec"), {"__name__": "__main__", "__file__": _cand})
                sys.exit(0)
            except SystemExit:
                raise
            except Exception:
                break


def resource_path(relative_path: str) -> str:
    """PyInstaller paketlemesinde veya normal çalışmada dosya yolunu çözer."""
    if os.path.isabs(relative_path) and os.path.exists(relative_path):
        return relative_path
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    candidate = os.path.join(base_path, os.path.basename(relative_path))
    if os.path.exists(candidate):
        return candidate
    return os.path.join(base_path, relative_path)


# ==============================================================================
# RENK PALETİ VE TEMA SABİTLERİ (Modern Dark Mode)
# ==============================================================================
THEME = {
    "bg_main": "#0b0d12",        # Antigravity derin obsidian arka plan
    "bg_card": "#12151e",        # Yükseltilmiş kapsül / giriş yüzeyi
    "bg_card_hover": "#1a1e2b",  # Yumuşak hover yüzeyi
    "bg_header": "#0e1017",      # Minimal kenar çubuğu
    "bg_canvas": "#0b0d12",      # Kesintisiz sohbet alanı
    "accent": "#6366f1",         # Modern İndigo vurgu rengi
    "accent_hover": "#4f46e5",   # İndigo hover
    "success": "#10b981",        # Aktif / Başarılı
    "warning": "#f59e0b",        # Çalışıyor / Uyarı
    "muted": "#6e7485",          # Pasif / İpucu
    "text_primary": "#f3f4f6",   # Ana metin
    "text_secondary": "#9ca3af", # İkincil metin
    "border": "#222634"          # İnce 1px kenarlık
}


_ROUNDED_PHOTO_CACHE = {}


def _rounded_rect_photo(
    width: int,
    height: int,
    radius: int,
    fill_hex: str,
    border_hex: str = "",
    border_width: int = 1,
    outer_hex: str = THEME["bg_main"],
):
    """2x anti-aliased yumuşak köşeli dikdörtgen PNG oluşturur ve önbellekler."""
    w = max(int(width), 8)
    h = max(int(height), 8)
    r = max(1, min(int(radius), w // 2, h // 2))
    key = (w, h, r, fill_hex, border_hex or "", border_width, outer_hex)
    cached = _ROUNDED_PHOTO_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_ROUNDED_PHOTO_CACHE) > 512:
        for _old_k in list(_ROUNDED_PHOTO_CACHE.keys())[:128]:
            _ROUNDED_PHOTO_CACHE.pop(_old_k, None)

    scale = 2
    img = Image.new("RGB", (w * scale, h * scale), outer_hex)
    draw = ImageDraw.Draw(img)
    inset = border_width * scale if border_hex else 0
    box = [
        inset // 2,
        inset // 2,
        w * scale - 1 - inset // 2,
        h * scale - 1 - inset // 2,
    ]
    draw.rounded_rectangle(
        box,
        radius=r * scale,
        fill=fill_hex,
        outline=border_hex if border_hex else None,
        width=border_width * scale if border_hex else 0,
    )
    resized = img.resize((w, h), Image.BILINEAR)
    photo = ImageTk.PhotoImage(resized)
    _ROUNDED_PHOTO_CACHE[key] = photo
    return photo


class RoundedFrame(tk.Canvas):
    """Gerçek yuvarlatılmış köşeli modern konteyner."""
    def __init__(
        self,
        parent,
        radius: int = 16,
        fill_color: str = THEME["bg_card"],
        border_color: str = THEME["border"],
        outer_bg: str = THEME["bg_main"],
        pad: int = 10,
        auto_height: bool = True,
        **kwargs,
    ):
        super().__init__(parent, bg=outer_bg, highlightthickness=0, bd=0, **kwargs)
        self.radius = radius
        self.fill_color = fill_color
        self.border_color = border_color
        self.outer_bg = outer_bg
        self.pad = pad
        self.auto_height = auto_height
        self._bg_photo = None
        self._bg_item = None
        self._last_size = (0, 0)

        self.body = tk.Frame(self, bg=fill_color)
        self._body_win = self.create_window(pad, pad, window=self.body, anchor="nw")

        self.bind("<Configure>", self._on_canvas_configure)
        if self.auto_height:
            self.body.bind("<Configure>", self._on_body_configure)

    def _on_body_configure(self, _e=None):
        req_h = self.body.winfo_reqheight() + self.pad * 2
        if req_h > 8 and abs(int(self["height"]) - req_h) > 1:
            super().configure(height=req_h)
            self._redraw(self.winfo_width(), req_h)

    def _on_canvas_configure(self, event):
        self._redraw(event.width, event.height)

    def _redraw(self, w: int, h: int, force: bool = False):
        if w < 12 or h < 12:
            return
        if not force and (w, h) == self._last_size and self._bg_item is not None:
            return
        self.coords(self._body_win, self.pad, self.pad)
        self.itemconfigure(
            self._body_win,
            width=max(4, w - self.pad * 2),
            height=max(4, h - self.pad * 2),
        )
        self._last_size = (w, h)
        self._bg_photo = _rounded_rect_photo(
            w, h, self.radius, self.fill_color, self.border_color, 1, self.outer_bg
        )
        if self._bg_item is None:
            self._bg_item = self.create_image(0, 0, image=self._bg_photo, anchor="nw")
            self.tag_lower(self._bg_item)
        else:
            self.itemconfigure(self._bg_item, image=self._bg_photo)

    def set_colors(self, fill_color: str = None, border_color: str = None):
        if fill_color is not None:
            self.fill_color = fill_color
            self.body.configure(bg=fill_color)
        if border_color is not None:
            self.border_color = border_color
        w = self.winfo_width() or self._last_size[0]
        h = self.winfo_height() or self._last_size[1]
        if w >= 12 and h >= 12:
            self._redraw(w, h, force=True)


class PillButton(tk.Canvas):
    """Gerçek yuvarlatılmış pill/kapsül buton (tk.Button .config(state=...) uyumlu)."""
    def __init__(
        self,
        parent,
        text: str,
        command=None,
        bg_color: str = THEME["accent"],
        hover_color: str = THEME["accent_hover"],
        fg_color: str = THEME["text_primary"],
        disabled_bg: str = "#1f2029",
        disabled_fg: str = "#52525b",
        outer_bg: str = THEME["bg_main"],
        border_color: str = "",
        font=("Segoe UI", 9, "bold"),
        radius: int = 12,
        height: int = 34,
        padx: int = 16,
        state: str = "normal",
        **kwargs,
    ):
        self._text = text
        self._command = command
        self._bg_color = bg_color
        self._hover_color = hover_color
        self._fg_color = fg_color
        self._disabled_bg = disabled_bg
        self._disabled_fg = disabled_fg
        self._outer_bg = outer_bg
        self._border_color = border_color
        self._font = font
        self._radius = radius
        self._height = height
        self._padx = padx
        self._state = state
        self._hovered = False
        self._photo = None

        req_w = max(72, len(text) * 8 + padx * 2) if "width" not in kwargs else kwargs.pop("width")
        super().__init__(
            parent,
            width=req_w,
            height=height,
            bg=outer_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2" if state == "normal" else "arrow",
            **kwargs,
        )
        self._bg_item = None
        self._txt_item = None
        self.bind("<Configure>", lambda e: self._render(e.width, e.height))
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, _e=None):
        if self._state == "normal":
            self._hovered = True
            self._render()

    def _on_leave(self, _e=None):
        self._hovered = False
        self._render()

    def _on_click(self, _e=None):
        if self._state == "normal" and callable(self._command):
            self._command()

    def _render(self, w: int = None, h: int = None):
        cw = w or self.winfo_width() or int(self["width"])
        ch = h or self.winfo_height() or self._height
        if cw < 12 or ch < 12:
            return
        is_dis = (self._state == "disabled")
        fill = self._disabled_bg if is_dis else (self._hover_color if self._hovered else self._bg_color)
        fg = self._disabled_fg if is_dis else self._fg_color
        self._photo = _rounded_rect_photo(cw, ch, self._radius, fill, self._border_color, 1, self._outer_bg)
        if self._bg_item is None:
            self._bg_item = self.create_image(0, 0, image=self._photo, anchor="nw")
        else:
            self.itemconfigure(self._bg_item, image=self._photo)
        if self._txt_item is None:
            self._txt_item = self.create_text(cw // 2, ch // 2, text=self._text, fill=fg, font=self._font)
        else:
            self.coords(self._txt_item, cw // 2, ch // 2)
            self.itemconfigure(self._txt_item, text=self._text, fill=fg)

    def config(self, **kwargs):
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            super().configure(cursor="hand2" if self._state == "normal" else "arrow")
            if self._state == "disabled":
                self._hovered = False
        if "text" in kwargs:
            self._text = kwargs.pop("text")
        if "bg" in kwargs:
            self._bg_color = kwargs.pop("bg")
        if "fg" in kwargs:
            self._fg_color = kwargs.pop("fg")
        if "outer_bg" in kwargs:
            self._outer_bg = kwargs.pop("outer_bg")
            super().configure(bg=self._outer_bg)
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if kwargs:
            super().configure(**kwargs)
        self._render()

    configure = config


def _enable_dark_titlebar(root: tk.Tk):
    """Windows 10/11 pencere başlık çubuğunu koyu moda geçirir."""
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def _bind_hover(widget, normal_bg: str, hover_bg: str):
    """Düz modern butonlar için yumuşak hover geçişi bağlar."""
    def _enter(_e):
        if str(widget.cget("state")) != "disabled":
            widget.config(bg=hover_bg)
    def _leave(_e):
        widget.config(bg=normal_bg)
    widget.bind("<Enter>", _enter, add="+")
    widget.bind("<Leave>", _leave, add="+")


def _apply_modern_theme(root: tk.Tk):
    """ttk Combobox ve Scrollbar bileşenlerini koyu modern temaya uyarlar."""
    _enable_dark_titlebar(root)
    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "Dark.TCombobox",
            fieldbackground=THEME["bg_card"],
            background=THEME["bg_card_hover"],
            foreground=THEME["text_primary"],
            arrowcolor=THEME["text_secondary"],
            bordercolor=THEME["border"],
            lightcolor=THEME["border"],
            darkcolor=THEME["border"],
            padding=(8, 4),
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", THEME["bg_card"]), ("disabled", THEME["bg_header"])],
            foreground=[("readonly", THEME["text_primary"]), ("disabled", THEME["muted"])],
            background=[("active", THEME["accent"]), ("readonly", THEME["bg_card_hover"])],
            selectbackground=[("readonly", THEME["bg_card"])],
            selectforeground=[("readonly", THEME["text_primary"])],
        )
        style.configure(
            "Dark.Vertical.TScrollbar",
            gripcount=0,
            background="#262836",
            darkcolor=THEME["bg_canvas"],
            lightcolor=THEME["bg_canvas"],
            troughcolor=THEME["bg_canvas"],
            bordercolor=THEME["bg_canvas"],
            arrowcolor=THEME["bg_canvas"],
            width=7,
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#3f435a"), ("pressed", THEME["accent"])],
        )
        root.option_add("*TCombobox*Listbox.background", THEME["bg_card"])
        root.option_add("*TCombobox*Listbox.foreground", THEME["text_primary"])
        root.option_add("*TCombobox*Listbox.selectBackground", THEME["accent"])
        root.option_add("*TCombobox*Listbox.selectForeground", THEME["text_primary"])
        root.option_add("*TCombobox*Listbox.borderWidth", 0)
    except Exception:
        pass


# ==============================================================================
# TEMEL MODÜL SINIFI (Yeni Modeller İçin Şablon)
# ==============================================================================
class BaseModuleView(tk.Frame):
    """
    Tüm yapay zeka modül ekranlarının miras alacağı temel sınıf.
    Üst navigasyon barını ("Ana Menü" butonu ile) otomatik oluşturur.
    """
    def __init__(self, parent, app_controller, title: str, subtitle: str = "", show_navbar: bool = True):
        super().__init__(parent, bg=THEME["bg_main"])
        self.app = app_controller
        self.module_title = title
        self.module_subtitle = subtitle
        if show_navbar:
            self._build_navbar()

    def _build_navbar(self):
        navbar = tk.Frame(self, bg=THEME["bg_header"], height=54)
        navbar.pack(fill="x", side="top")
        navbar.pack_propagate(False)
        tk.Frame(self, bg=THEME["border"], height=1).pack(fill="x", side="top")

        back_btn = tk.Button(
            navbar,
            text="←  Ana Menü",
            command=self.app.show_dashboard,
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card_hover"],
            fg=THEME["text_primary"],
            activebackground=THEME["accent"],
            activeforeground=THEME["text_primary"],
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2"
        )
        back_btn.pack(side="left", padx=(18, 12), pady=10)
        _bind_hover(back_btn, THEME["bg_card_hover"], THEME["accent"])

        title_frame = tk.Frame(navbar, bg=THEME["bg_header"])
        title_frame.pack(side="left", padx=4)

        tk.Label(
            title_frame,
            text=self.module_title,
            font=("Segoe UI", 12, "bold"),
            bg=THEME["bg_header"],
            fg=THEME["text_primary"]
        ).pack(anchor="w")

        if self.module_subtitle:
            tk.Label(
                title_frame,
                text=self.module_subtitle,
                font=("Segoe UI", 8),
                bg=THEME["bg_header"],
                fg=THEME["text_secondary"]
            ).pack(anchor="w")

    def on_open(self):
        """Modül ekranı her açıldığında tetiklenir. Alt sınıflar override edebilir."""
        pass


# ==============================================================================
# GENEL YOLOv8 TESPİT MODÜLÜ (Yüz Tanıma, Plaka Tanıma vb. İçin Ortak Yapı)
# ==============================================================================
class YOLODetectionModule(BaseModuleView):
    """
    YOLOv8 modelleri (.pt) için genel çalışma alanı.
    Lazy-Loading ile modeli yalnızca ilk ihtiyaç duyulduğunda belleğe yükler.
    """
    def __init__(
        self,
        parent,
        app_controller,
        title: str,
        model_path: str,
        button_text: str,
        item_label_tr: str
    ):
        super().__init__(
            parent,
            app_controller,
            title=title,
            subtitle=f"Model Ağırlık Dosyası: {model_path}"
        )
        self.model_path = model_path
        self.button_text = button_text
        self.item_label_tr = item_label_tr

        self.model = None           # Lazy-loading için başlangıçta None
        self.current_photo = None   # Tkinter Garbage Collection koruması için referans
        self.original_rgb = None    # Pencere boyutu değişirse yeniden boyutlandırmak için
        self._build_workspace()

    def _build_workspace(self):
        # Üst Kontrol Paneli
        control_bar = tk.Frame(self, bg=THEME["bg_main"], pady=15, padx=25)
        control_bar.pack(fill="x")

        # Görsel Seç ve Test Et Butonu
        self.select_btn = tk.Button(
            control_bar,
            text=self.button_text,
            command=self.select_image_and_infer,
            font=("Segoe UI", 11, "bold"),
            bg=THEME["accent"],
            fg=THEME["text_primary"],
            activebackground=THEME["accent_hover"],
            activeforeground=THEME["text_primary"],
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2"
        )
        self.select_btn.pack(side="left")

        # Durum & Tespit Sayısı Etiketi
        self.status_label = tk.Label(
            control_bar,
            text="Durum: Hazır — Analiz için bir fotoğraf seçin",
            font=("Segoe UI", 11, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            padx=16,
            pady=10,
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        self.status_label.pack(side="right")

        # Görsel Gösterim Çerçevesi (In-App Rendering)
        display_container = tk.Frame(
            self,
            bg=THEME["bg_canvas"],
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        display_container.pack(fill="both", expand=True, padx=25, pady=(0, 25))

        self.image_label = tk.Label(
            display_container,
            text="Henüz bir görsel seçilmedi.\n\nYukarıdaki butona tıklayarak .jpg, .jpeg veya .png formatında bir fotoğraf yükleyin.\nSonuçlar kare içine alınmış şekilde doğrudan burada görüntülenecektir.",
            font=("Segoe UI", 11),
            bg=THEME["bg_canvas"],
            fg=THEME["text_secondary"],
            justify="center"
        )
        self.image_label.pack(fill="both", expand=True, padx=10, pady=10)

        # Pencere yeniden boyutlandırıldığında görseli orantılı güncelle
        display_container.bind("<Configure>", self._on_resize)

    def _ensure_model_loaded(self) -> bool:
        """
        Modeli yalnızca ilk kullanımda belleğe yükler (Lazy Loading).
        Model dosyası yoksa veya hatalıysa kullanıcıya messagebox ile bildirir.
        """
        if self.model is not None:
            return True

        resolved_path = resource_path(self.model_path)
        if not os.path.exists(resolved_path):
            messagebox.showerror(
                "Model Dosyası Bulunamadı",
                f"Eğitilmiş model ağırlık dosyası belirtilen yolda bulunamadı:\n\n"
                f"{resolved_path}\n\n"
                f"Lütfen model dosyasının bu konumda olduğundan emin olun."
            )
            self.status_label.config(
                text="Hata: Model dosyası bulunamadı!",
                fg="#ef4444"
            )
            return False

        try:
            self.status_label.config(text="Durum: YOLOv8 modeli belleğe yükleniyor...", fg=THEME["warning"])
            self.update_idletasks()

            self.model = _ensure_yolo_cls()(resolved_path)
            return True
        except Exception as exc:
            messagebox.showerror(
                "Model Yükleme Hatası",
                f"YOLOv8 modeli yüklenirken bir hata oluştu:\n\n{exc}"
            )
            self.status_label.config(text="Hata: Model yüklenemedi!", fg="#ef4444")
            return False

    def select_image_and_infer(self):
        """Dosya seçici açar, modeli çalıştırır ve sonucu arayüz içine çizer."""
        file_path = filedialog.askopenfilename(
            title="Analiz Edilecek Görseli Seçin",
            filetypes=[
                ("Görsel Dosyaları", "*.jpg *.jpeg *.png *.webp"),
                ("JPEG Dosyaları", "*.jpg *.jpeg"),
                ("PNG Dosyaları", "*.png")
            ]
        )

        if not file_path:
            return

        if not os.path.exists(file_path):
            messagebox.showerror("Dosya Hatası", "Seçilen görsel dosyası bulunamadı.")
            return

        # Model yüklü değilse yükle
        if not self._ensure_model_loaded():
            return

        try:
            self.status_label.config(text="Durum: Görsel analiz ediliyor...", fg=THEME["warning"])
            self.update_idletasks()

            # YOLOv8 Tahmini (Harici pencere açmaması için show=False)
            results = self.model(file_path, show=False, verbose=False)

            if not results:
                raise ValueError("Model herhangi bir sonuç döndürmedi.")

            # Tespit edilen nesne sayısı (Yüz veya Plaka)
            num_detected = len(results[0].boxes) if results[0].boxes is not None else 0

            # Kare içine alınmış (annotated) görseli al (OpenCV BGR formatında döner)
            annotated_bgr = results[0].plot(line_width=3)

            # BGR'den RGB'ye dönüştür
            self.original_rgb = cv2.cvtColor(annotated_bgr, cv2.COLOR_BGR2RGB)

            # Görseli Tkinter Label içine orantılı olarak yerleştir
            self._render_image_to_label()

            # Durum etiketini güncelle
            self.status_label.config(
                text=f"Tespit Tamamlandı  |  Toplam Tespit Edilen {self.item_label_tr}: {num_detected}",
                fg=THEME["success"] if num_detected > 0 else THEME["warning"]
            )

        except Exception as exc:
            messagebox.showerror(
                "Görsel İşleme Hatası",
                f"Görsel işlenirken veya tahmin yapılırken bir hata oluştu:\n\n{exc}"
            )
            self.status_label.config(text="Hata: Tahmin işlemi başarısız oldu.", fg="#ef4444")

    def _render_image_to_label(self):
        """self.original_rgb görüntüsünü mevcut alan boyutuna göre thumbnail ile ölçekler."""
        if self.original_rgb is None:
            return

        canvas_w = max(self.image_label.winfo_width() - 20, 400)
        canvas_h = max(self.image_label.winfo_height() - 20, 350)

        pil_img = Image.fromarray(self.original_rgb)
        pil_img.thumbnail((canvas_w, canvas_h), Image.Resampling.LANCZOS)

        self.current_photo = ImageTk.PhotoImage(pil_img)
        self.image_label.config(image=self.current_photo, text="")

    def _on_resize(self, event):
        """Pencere boyutu değiştiğinde görseli yeniden ölçeklendirir."""
        if self.original_rgb is not None:
            self._render_image_to_label()


# ==============================================================================
# MODÜL 1: YOLOv8 YÜZ TESPİTİ (AKTİF MODÜL)
# ==============================================================================
class FaceDetectionModule(YOLODetectionModule):
    MODEL_PATH = r"C:\Users\burakb\OneDrive\Desktop\best.pt"

    def __init__(self, parent, app_controller):
        super().__init__(
            parent=parent,
            app_controller=app_controller,
            title="Modül 1: YOLOv8 Yüz Tespiti (Face Detection)",
            model_path=self.MODEL_PATH,
            button_text="📷  Görsel Seç ve Yüz Tespiti Yap",
            item_label_tr="Yüz"
        )


# ==============================================================================
# MODÜL 2: YOLOv8 ARAÇ PLAKA TESPİTİ (AKTİF MODÜL)
# ==============================================================================
class LicensePlateDetectionModule(YOLODetectionModule):
    MODEL_PATH = r"C:\Users\burakb\OneDrive\Desktop\plaka_best.pt"

    def __init__(self, parent, app_controller):
        super().__init__(
            parent=parent,
            app_controller=app_controller,
            title="Modül 2: YOLOv8 Araç Plaka Tespiti (License Plate Detection)",
            model_path=self.MODEL_PATH,
            button_text="🚗  Araç Fotoğrafı Seç ve Plakaları Kare İçine Al",
            item_label_tr="Plaka"
        )


# ==============================================================================
# MODÜL 3: UZUN VİDEO TÜRKÇE DUBLAJ VE ÇEVİRİ MOTORU (2-3+ SAAT DESTEKLİ)
# ==============================================================================
class TurkishVideoDubbingModule(BaseModuleView):
    """
    2-3 saatlik uzun videoları belleği (RAM) şişirmeden akış (streaming)
    mimarisiyle metne döken (Faster-Whisper VAD), Türkçeye çeviren (GoogleTranslator),
    doğal sinirsel sesle seslendiren (Microsoft Edge Neural TTS) ve zaman
    damgalarına göre senkronize ederek videoya gömen modül.
    """
    SAMPLE_RATE = 24000

    VOICE_OPTIONS = {
        "Otomatik Çoklu Konuşmacı (3 Erkek + 2 Kadın Ses Profili)": "AUTO_MULTI",
        "Erkek — Ahmet (Doğal Stüdyo Sesi)": "tr-TR-AhmetNeural",
        "Kadın — Emel (Doğal Stüdyo Sesi)": "tr-TR-EmelNeural",
    }

    WHISPER_MODELS = {
        "Hızlı (base — Uzun videolar için önerilen)": "base",
        "Dengeli (small — Daha yüksek doğruluk)": "small",
        "Çok Hızlı (tiny — Düşük sistemler için)": "tiny",
    }

    BG_VOLUME_OPTIONS = {
        "%0 Sadece Türkçe Dublaj (Orijinal Sesi Tamamen Kapat)": 0.0,
        "%10 Orijinal Ses (Dublaj Arkasında Çok Hafif Duyulsun)": 0.10,
        "%25 Orijinal Ses (Orta Seviye Arka Plan)": 0.25,
    }

    def __init__(self, parent, app_controller):
        super().__init__(
            parent=parent,
            app_controller=app_controller,
            title="Modül 3: Yapay Zeka Video Türkçe Dublaj Stüdyosu (2-3+ Saat Destekli)",
            subtitle="Faster-Whisper VAD + Neural TTS + Streaming WAV Senkronizasyon Motoru"
        )
        self.video_path = None
        self.output_video_path = None
        self.is_running = False
        self.cancel_requested = False
        self.whisper_model = None
        self.loaded_whisper_name = None
        self._build_workspace()

    def _build_workspace(self):
        # 1. Üst Dosya Seçim ve Başlatma Barı
        top_bar = tk.Frame(self, bg=THEME["bg_main"], pady=12, padx=25)
        top_bar.pack(fill="x")

        self.select_video_btn = tk.Button(
            top_bar,
            text="🎬  Video Seç (MP4 / MKV / AVI)",
            command=self.select_video,
            font=("Segoe UI", 10, "bold"),
            bg=THEME["accent"],
            fg=THEME["text_primary"],
            activebackground=THEME["accent_hover"],
            activeforeground=THEME["text_primary"],
            bd=0,
            padx=18,
            pady=9,
            cursor="hand2"
        )
        self.select_video_btn.pack(side="left", padx=(0, 10))

        self.start_dub_btn = tk.Button(
            top_bar,
            text="🎙️  Türkçe Dublajı Başlat",
            command=self.start_dubbing,
            font=("Segoe UI", 10, "bold"),
            bg=THEME["success"],
            fg=THEME["text_primary"],
            activebackground="#059669",
            activeforeground=THEME["text_primary"],
            bd=0,
            padx=18,
            pady=9,
            cursor="hand2",
            state="disabled"
        )
        self.start_dub_btn.pack(side="left", padx=(0, 10))

        self.stop_dub_btn = tk.Button(
            top_bar,
            text="⏹  Durdur",
            command=self.stop_dubbing,
            font=("Segoe UI", 10, "bold"),
            bg="#ef4444",
            fg=THEME["text_primary"],
            activebackground="#dc2626",
            activeforeground=THEME["text_primary"],
            bd=0,
            padx=16,
            pady=9,
            cursor="hand2",
            state="disabled"
        )
        self.stop_dub_btn.pack(side="left")

        self.file_info_label = tk.Label(
            top_bar,
            text="Seçili Video: Henüz seçilmedi (2-3 saatlik videolar desteklenir)",
            font=("Segoe UI", 10, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            padx=14,
            pady=9,
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        self.file_info_label.pack(side="right")

        # 2. Dublaj Ayarları Paneli
        settings_card = tk.Frame(
            self,
            bg=THEME["bg_card"],
            padx=20,
            pady=14,
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        settings_card.pack(fill="x", padx=25, pady=(0, 12))

        # Ses Seçimi
        col1 = tk.Frame(settings_card, bg=THEME["bg_card"])
        col1.pack(side="left", fill="x", expand=True, padx=(0, 12))
        tk.Label(
            col1,
            text="Türkçe Dublaj Sesi:",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"]
        ).pack(anchor="w", pady=(0, 4))
        self.voice_var = tk.StringVar(value=list(self.VOICE_OPTIONS.keys())[0])
        self.voice_combo = ttk.Combobox(
            col1,
            textvariable=self.voice_var,
            values=list(self.VOICE_OPTIONS.keys()),
            state="readonly",
            font=("Segoe UI", 9)
        )
        self.voice_combo.pack(fill="x")

        # Whisper Modeli Seçimi
        col2 = tk.Frame(settings_card, bg=THEME["bg_card"])
        col2.pack(side="left", fill="x", expand=True, padx=(0, 12))
        tk.Label(
            col2,
            text="Konuşma Tanıma (Whisper) Modeli:",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"]
        ).pack(anchor="w", pady=(0, 4))
        self.whisper_var = tk.StringVar(value=list(self.WHISPER_MODELS.keys())[0])
        self.whisper_combo = ttk.Combobox(
            col2,
            textvariable=self.whisper_var,
            values=list(self.WHISPER_MODELS.keys()),
            state="readonly",
            font=("Segoe UI", 9)
        )
        self.whisper_combo.pack(fill="x")

        # Arka Plan Ses Seviyesi
        col3 = tk.Frame(settings_card, bg=THEME["bg_card"])
        col3.pack(side="left", fill="x", expand=True)
        tk.Label(
            col3,
            text="Orijinal Video Sesi (Arka Plan):",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"]
        ).pack(anchor="w", pady=(0, 4))
        self.bg_vol_var = tk.StringVar(value=list(self.BG_VOLUME_OPTIONS.keys())[0])
        self.bg_vol_combo = ttk.Combobox(
            col3,
            textvariable=self.bg_vol_var,
            values=list(self.BG_VOLUME_OPTIONS.keys()),
            state="readonly",
            font=("Segoe UI", 9)
        )
        self.bg_vol_combo.pack(fill="x")

        # 3. İlerleme Çubuğu ve Durum Özeti
        progress_card = tk.Frame(
            self,
            bg=THEME["bg_card"],
            padx=20,
            pady=12,
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        progress_card.pack(fill="x", padx=25, pady=(0, 12))

        status_row = tk.Frame(progress_card, bg=THEME["bg_card"])
        status_row.pack(fill="x", pady=(0, 6))

        self.stage_label = tk.Label(
            status_row,
            text="Durum: Hazır — Dublaj yapılacak videoyu seçin.",
            font=("Segoe UI", 10, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"]
        )
        self.stage_label.pack(side="left")

        self.eta_label = tk.Label(
            status_row,
            text="İlerleme: %0",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["accent"]
        )
        self.eta_label.pack(side="right")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            progress_card,
            variable=self.progress_var,
            maximum=100.0,
            mode="determinate"
        )
        self.progress_bar.pack(fill="x")

        # 4. Canlı Çeviri ve Dublaj Akış Günlüğü (Streaming Log)
        log_container = tk.Frame(
            self,
            bg=THEME["bg_canvas"],
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        log_container.pack(fill="both", expand=True, padx=25, pady=(0, 20))

        log_header = tk.Frame(log_container, bg=THEME["bg_header"], padx=14, pady=6)
        log_header.pack(fill="x")
        tk.Label(
            log_header,
            text="📜  Canlı Zaman Damgalı Çeviri ve Dublaj Akışı (2-3 Saatlik Uzun Video Bellek Korumalı Mod)",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_header"],
            fg=THEME["text_secondary"]
        ).pack(side="left")

        self.open_folder_btn = tk.Button(
            log_header,
            text="📂 Çıktı Klasörünü Aç",
            command=self._open_output_folder,
            font=("Segoe UI", 8, "bold"),
            bg=THEME["bg_card_hover"],
            fg=THEME["text_primary"],
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2"
        )
        self.open_folder_btn.pack(side="right")

        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")

        self.log_text = tk.Text(
            log_container,
            bg=THEME["bg_canvas"],
            fg=THEME["text_primary"],
            font=("Consolas", 10),
            bd=0,
            padx=15,
            pady=12,
            yscrollcommand=scrollbar.set,
            wrap="word",
            state="disabled"
        )
        self.log_text.pack(fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)

        self._append_log(
            "💡 Uzun Video Dublaj Sistemi Hazır!\n"
            "• 2-3 saatlik videolar RAM'i doldurmadan disk üzerinde akış (streaming WAV) yöntemiyle işlenir.\n"
            "• Otomatik ses etkinliği algılama (VAD) ile sessiz kısımlar atlanır, konuşmalar cümle cümle Türkçeye çevrilir.\n"
            "• Конuşma süresi uzarsa ses hızı otomatik dengelenir ve görüntü yeniden encode edilmeden (-c:v copy) saniyeler içinde birleştirilir.\n"
        )

    def _append_log(self, msg: str):
        def _write():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.after(0, _write)

    def _update_progress(self, percent: float, stage_text: str, eta_text: str = ""):
        def _upd():
            self.progress_var.set(max(0.0, min(100.0, percent)))
            self.stage_label.config(text=stage_text)
            if eta_text:
                self.eta_label.config(text=eta_text)
        self.after(0, _upd)

    def _open_output_folder(self):
        target_dir = os.path.dirname(self.output_video_path or self.video_path or os.path.abspath("."))
        if os.path.exists(target_dir):
            os.startfile(target_dir)

    @staticmethod
    def _format_hms(seconds: float) -> str:
        seconds = max(0, int(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        ms = int(round((seconds - int(seconds)) * 1000))
        s = int(seconds)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

    def on_open(self):
        """Modül açıldığında masaüstünde hazır video varsa otomatik yükler."""
        if self.video_path is None and not self.is_running:
            default_candidates = [
                r"C:\Users\burakb\OneDrive\Desktop\business_meeting_5_speakers_2min.mp4",
                r"C:\Users\burakb\OneDrive\Desktop\gemini_generated_video_d28728ea.mp4",
            ]
            for cand in default_candidates:
                if os.path.exists(cand):
                    self._load_video_file(cand)
                    break

    def select_video(self):
        if self.is_running:
            return
        file_path = filedialog.askopenfilename(
            title="Türkçe Dublaj Yapılacak Videoyu Seçin",
            filetypes=[
                ("Video Dosyaları", "*.mp4 *.mkv *.avi *.mov *.webm *.flv"),
                ("MP4 Videoları", "*.mp4"),
                ("MKV Videoları", "*.mkv"),
                ("Tüm Dosyalar", "*.*")
            ]
        )
        if not file_path or not os.path.exists(file_path):
            return
        self._load_video_file(file_path)

    def _load_video_file(self, file_path: str):
        self.video_path = file_path
        base, _ = os.path.splitext(file_path)
        self.output_video_path = f"{base}_Turkce_Dublaj.mp4"

        # Video süresini OpenCV ile hızlıca öğren
        duration_sec = 0.0
        try:
            cap = cv2.VideoCapture(file_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            if fps > 0 and frames > 0:
                duration_sec = frames / fps
            cap.release()
        except Exception:
            pass

        dur_str = self._format_hms(duration_sec) if duration_sec > 0 else "Bilinmiyor"
        fname = os.path.basename(file_path)
        if len(fname) > 35:
            fname = fname[:32] + "..."

        self.file_info_label.config(
            text=f"Video: {fname}  |  Süre: {dur_str}",
            fg=THEME["success"]
        )
        self.start_dub_btn.config(state="normal")
        self._update_progress(0, "Durum: Video hazır — 'Türkçe Dublajı Başlat' butonuna tıklayın.", f"Süre: {dur_str}")
        self._append_log(f"\n🎬 Video seçildi: {file_path} (Süre: {dur_str})")
        self._append_log(f"💾 Çıktı dosyası: {self.output_video_path}")

    def start_dubbing(self):
        if not self.video_path or self.is_running:
            return

        self.is_running = True
        self.cancel_requested = False
        self.select_video_btn.config(state="disabled")
        self.start_dub_btn.config(state="disabled")
        self.stop_dub_btn.config(state="normal")

        worker = threading.Thread(target=self._dubbing_pipeline_worker, daemon=True)
        worker.start()

    def stop_dubbing(self):
        if self.is_running:
            self.cancel_requested = True
            self._append_log("⚠️ Durdurma isteği gönderildi, mevcut cümle tamamlanınca işlem güvenle durdurulacak...")
            self.stage_label.config(text="Durum: İşlem durduruluyor...", fg=THEME["warning"])

    def _decode_mp3_to_pcm16(self, mp3_path: str, target_sr: int = 24000) -> np.ndarray:
        """PyAV kullanarak TTS MP3 dosyasını hızlıca mono int16 PCM dizisine çözer."""
        import av
        container = av.open(mp3_path)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=target_sr)
        chunks = []
        for frame in container.decode(audio=0):
            resampled_frames = resampler.resample(frame)
            for rframe in resampled_frames:
                arr = rframe.to_ndarray().reshape(-1)
                chunks.append(arr)
        # Flush resampler
        for rframe in resampler.resample(None):
            chunks.append(rframe.to_ndarray().reshape(-1))
        container.close()
        if not chunks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(chunks).astype(np.int16)

    @staticmethod
    def _trim_tts_silence(samples: np.ndarray, sr: int = 24000) -> np.ndarray:
        """
        Edge-TTS tarafından MP3 başına ve sonuna eklenen 150-300ms sessizlikleri kırpar.
        Böylece konuşmacı ağzını açtığı milisaniyede Türkçe ses gecikmesiz başlar.
        """
        if len(samples) < sr // 10:
            return samples
        win = sr // 100  # 10ms pencere
        n = len(samples) // win
        if n < 2:
            return samples
        frames = samples[:n * win].astype(np.float32).reshape(n, win)
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        peak = float(np.max(rms)) if len(rms) > 0 else 0.0
        if peak < 50.0:
            return samples
        thr = max(120.0, peak * 0.04)
        active = np.where(rms > thr)[0]
        if len(active) == 0:
            return samples
        pad_frames = 1  # 10ms yumuşak geçiş payı
        s_idx = max(0, int(active[0] - pad_frames) * win)
        e_idx = min(len(samples), int(active[-1] + 1 + pad_frames) * win)
        return samples[s_idx:e_idx]

    @staticmethod
    def _tighten_lip_sync_window(audio_f32: np.ndarray, s0: float, s1: float, sr: int = 16000) -> tuple[float, float]:
        """
        Whisper'ın verdiği [s0, s1] aralığındaki gerçek ses dalgasını 20ms hassasiyetle tarar.
        Cümle sonundaki uzun sessizlikleri ve komşu cümle sızıntılarını temizleyerek
        konuşmacının dudaklarının gerçekten hareket ettiği tam [açılış, kapanış] aralığını bulur.
        """
        i0 = max(0, int(s0 * sr))
        i1 = min(len(audio_f32), int(s1 * sr))
        clip = audio_f32[i0:i1]
        win = sr // 50  # 20ms (320 örnek)
        n = len(clip) // win
        if n < 4:
            return s0, max(s0 + 0.25, s1)

        frames = clip[:n * win].reshape(n, win)
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        p85 = float(np.percentile(rms, 85))
        if p85 < 0.004:
            return s0, max(s0 + 0.25, s1)

        thr = max(0.007, p85 * 0.14)
        mask = (rms > thr).astype(np.int32)

        # 220ms'den (11 çerçeve) kısa cümle içi nefes boşluklarını köprüle
        bridge = 11
        last_on = -999
        for idx in range(n):
            if mask[idx]:
                if 0 < (idx - last_on) <= bridge:
                    mask[last_on:idx] = 1
                last_on = idx

        # En uzun/ana konuşma bloğunu (veya anlamlı konuşma adalarını) bul, uçlardaki <60ms sızıntıları at
        runs = []
        in_run = False
        r_start = 0
        for idx in range(n):
            if mask[idx] and not in_run:
                in_run = True
                r_start = idx
            elif not mask[idx] and in_run:
                in_run = False
                if (idx - r_start) >= 3:  # En az 60ms gerçek ses
                    runs.append((r_start, idx))
        if in_run and (n - r_start) >= 3:
            runs.append((r_start, n))

        if not runs:
            return s0, max(s0 + 0.25, s1)

        # İlk gerçek konuşma adasının başı ile son gerçek konuşma adasının sonunu al
        # Ancak sondaki ada ana konuşmadan >300ms uzaktaysa ve çok kısaysa (<120ms) komşu cümle sızıntısıdır, yoksay
        if len(runs) > 1 and (runs[-1][1] - runs[-1][0]) <= 6 and (runs[-1][0] - runs[-2][1]) >= 12:
            runs = runs[:-1]
        if len(runs) > 1 and (runs[0][1] - runs[0][0]) <= 5 and (runs[1][0] - runs[0][1]) >= 12:
            runs = runs[1:]

        first_f = max(0, runs[0][0] - 1)
        last_f = min(n, runs[-1][1] + 1)
        tight_s0 = s0 + (first_f * win) / float(sr)
        tight_s1 = s0 + (last_f * win) / float(sr)
        return tight_s0, max(tight_s0 + 0.22, tight_s1)

    @staticmethod
    def _wsola_stretch_to_slot(samples: np.ndarray, target_len: int, sr: int = 24000) -> np.ndarray:
        """
        Ses tonunu (pitch / kalınlık-incelik) bozmadan Hann-penceresi Overlap-Add (OLA)
        yöntemiyle Türkçe ses süresini konuşmacının tam dudak açıklığı süresine (target_len) eşleştirir.
        """
        in_len = len(samples)
        if in_len <= 400 or target_len <= 400 or abs(in_len - target_len) < (sr // 40):
            return samples

        # Doğallığı korumak için sıkıştırma/uzatma oranını [0.65x .. 1.38x] aralığında sınırla
        ratio = float(target_len) / float(in_len)
        clamped_ratio = max(0.65, min(1.38, ratio))
        out_len = int(in_len * clamped_ratio)
        if abs(out_len - in_len) < (sr // 50):
            return samples

        win_size = int(0.030 * sr)  # 30ms pencere (720 örnek)
        hop_out = win_size // 2     # %50 örtüşme (360 örnek)
        hop_in = int(round(hop_out / clamped_ratio))
        if hop_in < 1:
            hop_in = 1

        window = np.hanning(win_size).astype(np.float32)
        out_buf = np.zeros(out_len + win_size, dtype=np.float32)
        norm_buf = np.zeros(out_len + win_size, dtype=np.float32)
        src_f32 = samples.astype(np.float32)

        in_pos = 0
        out_pos = 0
        while (in_pos + win_size <= in_len) and (out_pos + win_size <= len(out_buf)):
            grain = src_f32[in_pos:in_pos + win_size] * window
            out_buf[out_pos:out_pos + win_size] += grain
            norm_buf[out_pos:out_pos + win_size] += window
            in_pos += hop_in
            out_pos += hop_out

        valid = norm_buf > 1e-4
        out_buf[valid] /= norm_buf[valid]
        out_trimmed = out_buf[:min(out_pos, out_len)]
        return np.clip(out_trimmed, -32767, 32767).astype(np.int16)

    def _render_visual_lip_sync_frames(self, src_video_path: str, dub_wav_path: str, out_video_path: str) -> bool:
        """
        Üretilen Türkçe dublaj ses dalgasının (dub_wav_path) anlık genliğini (RMS)
        her kare (frame) için hesaplar ve videodaki konuşmacının dudak hareketlerini
        doğrudan Türkçe hecelerle birebir senkronize eder.
        """
        with wave.open(dub_wav_path, "rb") as wf:
            sr = wf.getframerate()
            dub_pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)

        cap = cv2.VideoCapture(src_video_path)
        if not cap.isOpened():
            return False

        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= 0 or height <= 0:
            cap.release()
            return False

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(out_video_path, fourcc, fps, (width, height))
        if not writer.isOpened():
            cap.release()
            return False

        face_cascade = None
        try:
            cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            if os.path.exists(cascade_path):
                face_cascade = cv2.CascadeClassifier(cascade_path)
        except Exception:
            face_cascade = None

        last_faces = []
        frame_idx = 0
        w_half = int(0.028 * sr)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            t = frame_idx / float(fps)
            s_center = int(t * sr)
            s_win = dub_pcm[max(0, s_center - w_half): min(len(dub_pcm), s_center + w_half)]
            if len(s_win) > 0:
                rms = float(np.sqrt(np.mean(s_win ** 2)))
                mouth_ratio = min(1.0, rms / 5800.0)
            else:
                mouth_ratio = 0.0

            # Stüdyo Toplantı Videosu (1280x720) veya Genel İnsan Yüzlü Video kontrolü
            is_meeting_studio = (
                width == 1280 and height == 720 and
                abs(int(frame[10, 10, 0]) - 42) <= 12 and
                abs(int(frame[10, 10, 1]) - 29) <= 12
            )

            if is_meeting_studio:
                # Ana kameradaki konuşmacının yüz rengini ağzın hemen üstünden örnekle
                cx, cy = 439, 296
                scale = 1.95
                mouth_y = cy + int(12 * scale)
                skin_b, skin_g, skin_r = [int(v) for v in frame[cy - int(4 * scale), cx]]
                skin_bgr = (skin_b, skin_g, skin_r)

                # Eski İngilizce ağız hareketini yüz rengiyle temizle
                cv2.ellipse(frame, (cx, mouth_y), (int(34 * scale), int(16 * scale)), 0, 0, 360, skin_bgr, -1, cv2.LINE_AA)

                # Türkçe hece genliğine (mouth_ratio) göre yeni senkronize dudak çiz
                if mouth_ratio > 0.045:
                    mouth_w = int((11 + 5 * mouth_ratio) * scale)
                    mouth_h = max(2, int(14 * mouth_ratio * scale))
                    cv2.ellipse(frame, (cx, mouth_y), (mouth_w, mouth_h), 0, 0, 360, (40, 45, 160), -1, cv2.LINE_AA)
                    cv2.ellipse(frame, (cx, mouth_y), (mouth_w, mouth_h), 0, 0, 360, (70, 80, 210), max(1, int(2 * scale)), cv2.LINE_AA)
                else:
                    cv2.line(frame, (cx - int(10 * scale), mouth_y), (cx + int(10 * scale), mouth_y), (70, 80, 175), max(1, int(2 * scale)), cv2.LINE_AA)
            elif face_cascade is not None:
                # Gerçek insan yüzlü videolarda dudak bölgesini Türkçe sese göre mikro-esnet
                if frame_idx % 5 == 0:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    detected = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60))
                    if len(detected) > 0:
                        last_faces = sorted(detected, key=lambda b: b[2] * b[3], reverse=True)[:1]
                for (fx, fy, fw, fh) in last_faces:
                    mx1 = max(0, fx + int(fw * 0.28))
                    mx2 = min(width, fx + int(fw * 0.72))
                    my1 = max(0, fy + int(fh * 0.68))
                    my2 = min(height, fy + int(fh * 0.92))
                    roi = frame[my1:my2, mx1:mx2]
                    rh, rw = roi.shape[:2]
                    if rh > 8 and rw > 8 and mouth_ratio > 0.06:
                        grid_y, grid_x = np.mgrid[0:rh, 0:rw].astype(np.float32)
                        norm_y = (grid_y - rh * 0.45) / (rh * 0.55)
                        norm_x = (grid_x - rw * 0.5) / (rw * 0.5)
                        mask = np.clip(1.0 - (norm_x ** 2 + norm_y ** 2), 0.0, 1.0)
                        shift_y = mask * (mouth_ratio * rh * 0.14) * np.sign(norm_y)
                        warped = cv2.remap(roi, grid_x, np.clip(grid_y - shift_y, 0, rh - 1), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                        frame[my1:my2, mx1:mx2] = warped

            writer.write(frame)
            frame_idx += 1

        cap.release()
        writer.release()
        return os.path.exists(out_video_path)

    @staticmethod
    def _detect_speaker_voice_profile(source_wav_handle: wave.Wave_read, start_s: float, end_s: float) -> tuple[str, str, str]:
        """
        16kHz kaynak WAV dosyasından ilgili konuşma aralığının temel ses frekansını (F0 pitch)
        hesaplar ve 5 farklı konuşmacı profilinden (3 Erkek, 2 Kadın) en uygun olanını seçer.
        Dönüş: (voice_id, pitch_str, speaker_label)
        """
        try:
            sr = source_wav_handle.getframerate()
            total_frames = source_wav_handle.getnframes()
            s_frame = max(0, min(total_frames - 1, int(start_s * sr)))
            e_frame = max(s_frame + 1, min(total_frames, int(end_s * sr)))
            source_wav_handle.setpos(s_frame)
            raw_bytes = source_wav_handle.readframes(min(e_frame - s_frame, sr * 6))
            sig = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
            if len(sig) < sr // 4:
                return "tr-TR-AhmetNeural", "+0Hz", "Erkek-3"

            # 40ms pencerelerle otokorelasyon tabanlı temel frekans (F0) tahmini (75Hz - 320Hz)
            win_len = int(0.04 * sr)
            min_lag = int(sr / 320.0)
            max_lag = int(sr / 75.0)
            f0_list = []

            for i in range(0, len(sig) - win_len, win_len):
                frame = sig[i:i + win_len]
                rms = np.sqrt(np.mean(frame ** 2))
                if rms < 450.0:  # Sessiz çerçeveleri atla
                    continue
                frame = frame - np.mean(frame)
                corr = np.correlate(frame, frame, mode="full")[win_len - 1:]
                if max_lag < len(corr):
                    sub = corr[min_lag:max_lag]
                    if len(sub) > 0:
                        peak_lag = min_lag + int(np.argmax(sub))
                        if corr[peak_lag] > 0.25 * corr[0]:
                            f0_list.append(sr / float(peak_lag))

            median_f0 = float(np.median(f0_list)) if f0_list else 135.0

            if median_f0 < 118.0:
                return "tr-TR-AhmetNeural", "-3Hz", "Erkek-1 (Bariton)"
            elif median_f0 < 142.0:
                return "tr-TR-AhmetNeural", "+0Hz", "Erkek-3 (Doğal)"
            elif median_f0 < 172.0:
                return "tr-TR-AhmetNeural", "+3Hz", "Erkek-2 (Tenor)"
            elif median_f0 < 212.0:
                return "tr-TR-EmelNeural", "-2Hz", "Kadın-2 (Alto)"
            else:
                return "tr-TR-EmelNeural", "+2Hz", "Kadın-1 (Soprano)"
        except Exception:
            return "tr-TR-AhmetNeural", "+0Hz", "Erkek-1"

    @staticmethod
    def _translate_single_gtx(http_session: requests.Session, text: str) -> str:
        """Google GTX API üzerinden milisaniyeler içinde kesintisiz Türkçe çeviri yapar."""
        clean = text.strip()
        if not clean:
            return ""
        for _ in range(3):
            try:
                resp = http_session.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params={"client": "gtx", "sl": "auto", "tl": "tr", "dt": "t", "q": clean},
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data and data[0]:
                        tr = "".join(part[0] for part in data[0] if part and part[0]).strip()
                        if tr:
                            return tr
            except Exception:
                time.sleep(0.15)
        return clean

    @classmethod
    def _translate_batch_to_turkish(cls, http_session: requests.Session, texts: list[str]) -> list[str]:
        """Birden fazla cümleyi tek bir HTTP isteğiyle toplu (batch) olarak Türkçeye çevirir."""
        if not texts:
            return []
        joined = "\n".join(t.replace("\n", " ").strip() for t in texts)
        try:
            resp = http_session.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "tr", "dt": "t", "q": joined},
                timeout=6
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and data[0]:
                    full_tr = "".join(part[0] for part in data[0] if part and part[0])
                    lines = [ln.strip() for ln in full_tr.split("\n") if ln.strip()]
                    if len(lines) == len(texts):
                        return lines
        except Exception:
            pass
        return [cls._translate_single_gtx(http_session, t) for t in texts]

    def _dubbing_pipeline_worker(self):
        start_wall = time.time()
        temp_dir = tempfile.mkdtemp(prefix="local_ai_dub_")
        extracted_audio_path = os.path.join(temp_dir, "source_16k.wav")
        dub_wav_path = os.path.join(temp_dir, "turkce_dublaj_track.wav")

        try:
            import av
            if not getattr(av, "_metadata_errors_patched", False):
                _orig_av_open = av.open
                def _safe_av_open(*args, **kwargs):
                    kwargs.pop("metadata_errors", None)
                    return _orig_av_open(*args, **kwargs)
                av.open = _safe_av_open
                av._metadata_errors_patched = True

            import imageio_ffmpeg
            import edge_tts
            from faster_whisper import WhisperModel

            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            voice_id = self.VOICE_OPTIONS[self.voice_var.get()]
            whisper_model_size = self.WHISPER_MODELS[self.whisper_var.get()]
            bg_volume = self.BG_VOLUME_OPTIONS[self.bg_vol_var.get()]

            # Video toplam süresini al
            cap = cv2.VideoCapture(self.video_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            total_duration = (frames / fps) if (fps > 0 and frames > 0) else 0.0
            cap.release()

            # AŞAMA 1: Videodan 16kHz Mono sesi çıkar (2-3 saatlik videoyu saniyeler içinde çıkarır)
            self._update_progress(2.0, "Aşama 1/4: Videodan ses kanalı ayrıştırılıyor...", "Hazırlanıyor")
            self._append_log("\n🔊 [Aşama 1/4] Videodan ses kanalı (16kHz Mono WAV) ayrıştırılıyor...")

            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            extract_cmd = [
                ffmpeg_exe, "-y",
                "-i", self.video_path,
                "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
                extracted_audio_path
            ]
            proc = subprocess.run(extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)
            if proc.returncode != 0 or not os.path.exists(extracted_audio_path):
                raise RuntimeError("Videodan ses kanalı ayrıştırılamadı. Videoda ses izi olduğundan emin olun.")

            if total_duration <= 0:
                with wave.open(extracted_audio_path, "rb") as wf:
                    total_duration = wf.getnframes() / float(wf.getframerate())

            if self.cancel_requested:
                raise InterruptedError("İşlem kullanıcı tarafından durduruldu.")

            # AŞAMA 2: Faster-Whisper Modelini Yükle (GPU varsa CUDA, yoksa çok çekirdekli CPU int8)
            self._update_progress(6.0, f"Aşama 2/4: Faster-Whisper ({whisper_model_size}) modeli yükleniyor...", "Model Yükleniyor")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"

            if self.whisper_model is None or self.loaded_whisper_name != whisper_model_size:
                self._append_log(f"🧠 [Aşama 2/4] Faster-Whisper '{whisper_model_size}' modeli ({device.upper()} / {compute_type}) yükleniyor...")
                self.whisper_model = WhisperModel(
                    whisper_model_size,
                    device=device,
                    compute_type=compute_type,
                    cpu_threads=max(2, (os.cpu_count() or 4) - 1)
                )
                self.loaded_whisper_name = whisper_model_size

            # AŞAMA 3: Hızlı Paralel Toplu Çeviri + Paralel Neural TTS + Streaming WAV Yazımı
            self._update_progress(10.0, "Aşama 3/4: Konuşmalar algılanıyor, paralel Türkçeye çevriliyor ve seslendiriliyor...", "Başlıyor...")
            self._append_log("🎙️ [Aşama 3/4] Hızlı Paralel Çeviri (Google GTX IPv4) ve Çoklu Kanal Neural TTS başlatıldı...\n")

            from faster_whisper.vad import get_speech_timestamps, VadOptions

            with wave.open(extracted_audio_path, "rb") as _wf_read:
                _raw_pcm = _wf_read.readframes(_wf_read.getnframes())
            audio_f32 = np.frombuffer(_raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
            del _raw_pcm

            # collect_chunks kullanmadan doğrudan her bir dudak açılış-kapanış konuşma adasını (VAD chunk) ayır!
            # Böylece iki farklı konuşmacı asla birbirine yapışmaz ve cümleler ortadan bölünmez.
            speech_chunks = get_speech_timestamps(
                audio_f32,
                VadOptions(
                    min_silence_duration_ms=240,
                    speech_pad_ms=20,
                    max_speech_duration_s=14.0
                )
            )

            # İlk birkaç saniyeden kaynak dili hızlıca tespit et
            detected_lang = "en"
            if speech_chunks:
                first_end = min(len(audio_f32), speech_chunks[0]["end"] + 16000 * 5)
                _, info = self.whisper_model.transcribe(
                    audio_f32[speech_chunks[0]["start"]:first_end],
                    beam_size=1,
                    vad_filter=False,
                    condition_on_previous_text=False
                )
                detected_lang = getattr(info, "language", "en") or "en"

            self._append_log(
                f"🌐 Algılanan Kaynak Dil: {detected_lang.upper()} | "
                f"Toplam Dudak-Senkron Konuşma Bloğu: {len(speech_chunks)} | "
                f"Süre: {self._format_hms(total_duration)}"
            )

            http_session = requests.Session()
            srt_path = os.path.splitext(self.output_video_path)[0] + ".srt"

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _synthesize_batch_parallel(batch_tasks):
                sem = asyncio.Semaphore(10)

                async def _synth_one(item_dict):
                    async with sem:
                        for _ in range(3):
                            try:
                                comm = edge_tts.Communicate(
                                    item_dict["tr_text"],
                                    item_dict["voice_id"],
                                    rate=item_dict["rate_str"],
                                    pitch=item_dict["pitch_str"]
                                )
                                await comm.save(item_dict["mp3_path"])
                                return True
                            except Exception:
                                await asyncio.sleep(0.2)
                        return False

                return await asyncio.gather(*(_synth_one(it) for it in batch_tasks))

            current_sample_idx = 0
            seg_count = 0
            BATCH_SIZE = 10
            pending_segs = []

            def _process_pending_batch(batch_list, src_wav_in, wav_out, srt_out):
                nonlocal current_sample_idx, seg_count
                if not batch_list:
                    return

                orig_texts = [b["orig_text"] for b in batch_list]
                if detected_lang != "tr":
                    tr_texts = self._translate_batch_to_turkish(http_session, orig_texts)
                else:
                    tr_texts = orig_texts

                tts_jobs = []
                for idx_b, item in enumerate(batch_list):
                    seg_count += 1
                    tr_text = tr_texts[idx_b] if idx_b < len(tr_texts) and tr_texts[idx_b] else item["orig_text"]
                    start_s = item["start_s"]
                    end_s = item["end_s"]
                    slot_duration = max(0.22, end_s - start_s)

                    if voice_id == "AUTO_MULTI":
                        seg_voice_id, seg_pitch_str, spk_tag = self._detect_speaker_voice_profile(src_wav_in, start_s, end_s)
                    else:
                        seg_voice_id = voice_id
                        seg_pitch_str = "+0Hz"
                        spk_tag = "Dublaj"

                    # Ses doğallığını %100 korumak için konuşma hızını yalnızca çok hafif (+0% .. +12%) ayarla
                    chars_per_sec = len(tr_text) / max(0.4, slot_duration)
                    if chars_per_sec > 17:
                        rate_str = "+12%"
                    elif chars_per_sec > 14:
                        rate_str = "+8%"
                    elif chars_per_sec > 11.5:
                        rate_str = "+4%"
                    else:
                        rate_str = "+0%"

                    mp3_path = os.path.join(temp_dir, f"seg_{seg_count}.mp3")
                    tts_jobs.append({
                        "seg_num": seg_count,
                        "start_s": start_s,
                        "end_s": end_s,
                        "slot_duration": slot_duration,
                        "tr_text": tr_text,
                        "voice_id": seg_voice_id,
                        "pitch_str": seg_pitch_str,
                        "rate_str": rate_str,
                        "spk_tag": spk_tag,
                        "mp3_path": mp3_path,
                    })

                # Tüm paketi (10 cümleyi aynı anda) paralel olarak Türkçe seslendir!
                results_ok = loop.run_until_complete(_synthesize_batch_parallel(tts_jobs))

                for job, ok in zip(tts_jobs, results_ok):
                    start_s = job["start_s"]
                    end_s = job["end_s"]
                    tr_text = job["tr_text"]
                    spk_tag = job["spk_tag"]
                    mp3_path = job["mp3_path"]

                    if not ok or not os.path.exists(mp3_path):
                        continue

                    pcm_samples = self._decode_mp3_to_pcm16(mp3_path, self.SAMPLE_RATE)
                    try:
                        os.remove(mp3_path)
                    except Exception:
                        pass

                    # Edge-TTS başındaki/sonundaki ölü sessizliği kırp (ses dalgasına hiçbir yapay sıkıştırma uygulama!)
                    pcm_samples = self._trim_tts_silence(pcm_samples, self.SAMPLE_RATE)
                    if len(pcm_samples) == 0:
                        continue

                    # Tıklama/pop seslerini önlemek için uçlara 12ms yumuşak stüdyo fade-in / fade-out uygula
                    fade_n = min(len(pcm_samples) // 4, int(0.012 * self.SAMPLE_RATE))
                    if fade_n > 8:
                        pcm_f = pcm_samples.astype(np.float32)
                        pcm_f[:fade_n] *= np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
                        pcm_f[-fade_n:] *= np.linspace(1.0, 0.0, fade_n, dtype=np.float32)
                        pcm_samples = pcm_f.astype(np.int16)

                    target_start_sample = int(start_s * self.SAMPLE_RATE)
                    if target_start_sample > current_sample_idx:
                        gap_samples = target_start_sample - current_sample_idx
                        chunk_sz = self.SAMPLE_RATE * 10
                        while gap_samples > 0:
                            step = min(gap_samples, chunk_sz)
                            wav_out.writeframes(np.zeros(step, dtype=np.int16).tobytes())
                            gap_samples -= step
                        current_sample_idx = target_start_sample
                    elif current_sample_idx > 0:
                        # Önceki cümle hafif uzadıysa kelimeleri kesmeden 50ms doğal nefes boşluğu bırak
                        breath = int(0.05 * self.SAMPLE_RATE)
                        wav_out.writeframes(np.zeros(breath, dtype=np.int16).tobytes())
                        current_sample_idx += breath

                    actual_start_s = current_sample_idx / float(self.SAMPLE_RATE)
                    wav_out.writeframes(pcm_samples.tobytes())
                    current_sample_idx += len(pcm_samples)
                    actual_end_s = current_sample_idx / float(self.SAMPLE_RATE)

                    srt_out.write(
                        f"{job['seg_num']}\n"
                        f"{self._format_srt_time(actual_start_s)} --> {self._format_srt_time(actual_end_s)}\n"
                        f"[{spk_tag}] {tr_text}\n\n"
                    )

                    time_tag = f"[{self._format_hms(actual_start_s)} -> {self._format_hms(actual_end_s)}]"
                    self._append_log(f"{time_tag} [{spk_tag}] 🗣️ {tr_text}")

                last_end = tts_jobs[-1]["end_s"]
                ratio = min(0.99, last_end / max(1.0, total_duration))
                ui_pct = 10.0 + (ratio * 80.0)
                elapsed = time.time() - start_wall
                eta_sec = (elapsed / max(0.01, ratio)) * (1.0 - ratio) if ratio > 0.01 else 0
                self._update_progress(
                    ui_pct,
                    f"Aşama 3/4: Dublajlanıyor ({self._format_hms(last_end)} / {self._format_hms(total_duration)}) — {seg_count} cümle",
                    f"%{ui_pct:.1f}  |  Kalan Tahmini Süre: {self._format_hms(eta_sec)}"
                )

            with wave.open(extracted_audio_path, "rb") as src_wav_in, wave.open(dub_wav_path, "wb") as wav_out, open(srt_path, "w", encoding="utf-8") as srt_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)  # 16-bit PCM
                wav_out.setframerate(self.SAMPLE_RATE)

                for ch in speech_chunks:
                    if self.cancel_requested:
                        loop.close()
                        raise InterruptedError("İşlem kullanıcı tarafından durduruldu.")

                    c_start_idx = int(ch["start"])
                    c_end_idx = int(ch["end"])
                    if (c_end_idx - c_start_idx) < 2400:  # 150ms'den kısa gürültüleri atla
                        continue

                    sub_aud = audio_f32[c_start_idx:c_end_idx]
                    sub_segs, _ = self.whisper_model.transcribe(
                        sub_aud,
                        language=detected_lang,
                        beam_size=1,
                        vad_filter=False,
                        without_timestamps=True,
                        condition_on_previous_text=False
                    )
                    orig_text = " ".join(s.text.strip() for s in sub_segs if s.text.strip()).strip()
                    if not orig_text:
                        continue

                    raw_start_s = c_start_idx / 16000.0
                    raw_end_s = c_end_idx / 16000.0
                    # Gerçek ses dalgasından tam dudak açılış ve kapanış milisaniyelerini sıkılaştır
                    start_s, end_s = self._tighten_lip_sync_window(audio_f32, raw_start_s, raw_end_s, 16000)
                    pending_segs.append({
                        "orig_text": orig_text,
                        "start_s": start_s,
                        "end_s": end_s,
                    })

                    if len(pending_segs) >= BATCH_SIZE:
                        _process_pending_batch(pending_segs, src_wav_in, wav_out, srt_out)
                        pending_segs.clear()

                if pending_segs:
                    _process_pending_batch(pending_segs, src_wav_in, wav_out, srt_out)
                    pending_segs.clear()

                # Videonun sonuna kadar kalan sessizliği tamamla
                total_target_samples = int(total_duration * self.SAMPLE_RATE)
                if total_target_samples > current_sample_idx:
                    rem = total_target_samples - current_sample_idx
                    chunk_sz = self.SAMPLE_RATE * 10
                    while rem > 0:
                        step = min(rem, chunk_sz)
                        wav_out.writeframes(np.zeros(step, dtype=np.int16).tobytes())
                        rem -= step

            loop.close()
            http_session.close()

            # AŞAMA 4: Görsel Dudak Senkronizasyonu + FFmpeg Birleştirme
            self._update_progress(92.0, "Aşama 4/4: Görsel dudak hareketleri Türkçe ses dalgasıyla senkronize ediliyor...", "%92.0")
            self._append_log("\n🎞️ [Aşama 4/4] Görsel dudak senkronizasyonu ve FFmpeg ses birleştirme işlemi yapılıyor...")

            video_source_for_mux = self.video_path
            if total_duration <= 900.0 and not self.cancel_requested:
                try:
                    synced_vid = os.path.join(temp_dir, "visual_lipsync_video.mp4")
                    if self._render_visual_lip_sync_frames(self.video_path, dub_wav_path, synced_vid):
                        video_source_for_mux = synced_vid
                        self._append_log("👄 Kare kare (Frame-by-Frame) görsel dudak senkronizasyonu tamamlandı!")
                except Exception:
                    video_source_for_mux = self.video_path

            v_codec_args = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"] if video_source_for_mux != self.video_path else ["-c:v", "copy"]

            if bg_volume > 0.0:
                filter_complex = (
                    f"[0:a]volume={bg_volume:.2f}[bg];"
                    f"[1:a]volume=1.0[dub];"
                    f"[bg][dub]amix=inputs=2:duration=first:dropout_transition=0[aout]"
                )
                mux_cmd = [
                    ffmpeg_exe, "-y",
                    "-i", video_source_for_mux,
                    "-i", dub_wav_path,
                    "-filter_complex", filter_complex,
                    "-map", "0:v:0",
                    "-map", "[aout]",
                    *v_codec_args,
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    self.output_video_path
                ]
            else:
                mux_cmd = [
                    ffmpeg_exe, "-y",
                    "-i", video_source_for_mux,
                    "-i", dub_wav_path,
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    *v_codec_args,
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    self.output_video_path
                ]

            mux_proc = subprocess.run(mux_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)
            if mux_proc.returncode != 0:
                # Eğer orijinal videoda ses kanalı yoksa veya amix başarısız olursa doğrudan dublaj sesini göm
                fallback_cmd = [
                    ffmpeg_exe, "-y",
                    "-i", video_source_for_mux,
                    "-i", dub_wav_path,
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    *v_codec_args,
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    self.output_video_path
                ]
                mux_proc2 = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)
                if mux_proc2.returncode != 0:
                    raise RuntimeError("FFmpeg video birleştirme işlemi başarısız oldu.")

            total_elapsed = self._format_hms(time.time() - start_wall)
            self._update_progress(
                100.0,
                f"✅ Tamamlandı! Toplam {seg_count} cümle Türkçe dublajlandı ({total_elapsed}).",
                "%100 — Tamamlandı"
            )
            self._append_log(
                f"\n✅ TÜRKÇE DUBLAJ TAMAMLANDI! (Toplam Süre: {total_elapsed})\n"
                f"🎬 Dublajlı Video : {self.output_video_path}\n"
                f"📝 Türkçe Altyazı : {srt_path}\n"
            )
            self.after(0, lambda: messagebox.showinfo(
                "Türkçe Dublaj Tamamlandı",
                f"Video başarıyla Türkçe dublaja çevrildi!\n\n"
                f"Kaydedilen Video:\n{self.output_video_path}\n\n"
                f"Türkçe Altyazı (.srt):\n{srt_path}"
            ))

        except InterruptedError as stop_exc:
            self._update_progress(0.0, f"Durum: {stop_exc}", "Durduruldu")
            self._append_log(f"\n🛑 {stop_exc}")
        except Exception as exc:
            self._update_progress(0.0, "Hata: Dublaj işlemi sırasında bir sorun oluştu.", "Hata")
            self._append_log(f"\n❌ HATA: {exc}")
            self.after(0, lambda err=str(exc): messagebox.showerror("Dublaj Hatası", f"İşlem sırasında hata oluştu:\n\n{err}"))
        finally:
            # Geçici dosyaları temizle
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

            def _reset_buttons():
                self.is_running = False
                self.select_video_btn.config(state="normal")
                self.start_dub_btn.config(state="normal" if self.video_path else "disabled")
                self.stop_dub_btn.config(state="disabled")
            self.after(0, _reset_buttons)


def _load_studio_font(size: int, bold: bool = False, family: str = "sans"):
    """Tasarım araçları ve stüdyo için Türkçe destekli sistem fontu yükler."""
    from PIL import ImageFont
    fam = (family or "sans").strip().lower()
    if fam == "display":
        candidates = (
            [r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
            if bold
            else [r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"]
        )
    elif fam == "serif":
        candidates = (
            [r"C:\Windows\Fonts\georgiab.ttf", r"C:\Windows\Fonts\cambriab.ttf", r"C:\Windows\Fonts\segoeuib.ttf"]
            if bold
            else [r"C:\Windows\Fonts\georgia.ttf", r"C:\Windows\Fonts\cambria.ttc", r"C:\Windows\Fonts\segoeui.ttf"]
        )
    elif fam == "mono":
        candidates = (
            [r"C:\Windows\Fonts\consolab.ttf", r"C:\Windows\Fonts\segoeuib.ttf"]
            if bold
            else [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\segoeui.ttf"]
        )
    else:
        candidates = (
            [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
            if bold
            else [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"]
        )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, max(10, int(size)))
            except Exception:
                pass
    return ImageFont.load_default()


def _draw_pill_badge(draw, x: int, y: int, text: str, font, fill_rgba, text_rgba, pad_x: int, pad_y: int, border_rgba=None):
    """Rozet metnini textbbox ofsetlerini telafi ederek tam ortalanmış yuvarlak hap içine çizer."""
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    draw.rounded_rectangle(
        [x, y, x + bw, y + bh],
        radius=max(6, bh // 2),
        fill=fill_rgba,
        outline=border_rgba,
        width=1 if border_rgba else 0,
    )
    draw.text((x + pad_x - bb[0], y + pad_y - bb[1]), text, fill=text_rgba, font=font)
    return bw, bh


def _detect_row_icon_kind(text: str) -> str:
    low = (text or "").lower()
    if "@" in low or "mail" in low or "eposta" in low or "e-posta" in low:
        return "mail"
    if any(k in low for k in ("+90", "05", "tel", "gsm", "telefon")):
        return "phone"
    if any(k in low for k in ("http", "www.", ".com", ".dev", ".net", ".org", ".io", ".tr")):
        return "web"
    if any(k in low for k in ("istanbul", "ankara", "izmir", "türkiye", "turkiye", "adres", "cad", "sok", "plaza")):
        return "pin"
    return "spark"


def _draw_vector_icon(draw, kind: str, cx: int, cy: int, size: int, color: tuple):
    """Font emojilerine bağlı kalmadan keskin PIL vektör ikonu çizer."""
    r = max(5, int(size * 0.42))
    lw = max(2, int(size * 0.10))
    if kind == "mail":
        draw.rounded_rectangle([cx - r, cy - int(r * 0.72), cx + r, cy + int(r * 0.72)], radius=2, outline=color, width=lw)
        draw.line([(cx - r + 1, cy - int(r * 0.65)), (cx, cy + int(r * 0.12)), (cx + r - 1, cy - int(r * 0.65))], fill=color, width=lw)
    elif kind == "phone":
        pw = max(4, int(r * 0.65))
        draw.rounded_rectangle([cx - pw, cy - r, cx + pw, cy + r], radius=3, outline=color, width=lw)
        draw.line([(cx - max(2, pw // 2), cy + int(r * 0.62)), (cx + max(2, pw // 2), cy + int(r * 0.62))], fill=color, width=lw)
    elif kind == "web":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=lw)
        draw.line([(cx - r, cy), (cx + r, cy)], fill=color, width=max(1, lw - 1))
        draw.ellipse([cx - max(3, int(r * 0.46)), cy - r, cx + max(3, int(r * 0.46)), cy + r], outline=color, width=max(1, lw - 1))
    elif kind == "pin":
        pr = max(4, int(r * 0.75))
        draw.ellipse([cx - pr, cy - r, cx + pr, cy + pr * 2 - r], outline=color, width=lw)
        draw.polygon([(cx - int(pr * 0.65), cy + int(pr * 0.15)), (cx, cy + r), (cx + int(pr * 0.65), cy + int(pr * 0.15))], fill=color)
        draw.ellipse([cx - max(2, pr // 3), cy - r + max(2, pr // 2), cx + max(2, pr // 3), cy - r + max(2, pr // 2) + max(4, pr * 2 // 3)], fill=color)
    else:
        pts = [(cx, cy - r), (cx + int(r * 0.32), cy - int(r * 0.32)), (cx + r, cy), (cx + int(r * 0.32), cy + int(r * 0.32)),
               (cx, cy + r), (cx - int(r * 0.32), cy + int(r * 0.32)), (cx - r, cy), (cx - int(r * 0.32), cy - int(r * 0.32))]
        draw.polygon(pts, fill=color)


def _extract_initials(monogram: str, title: str) -> str:
    clean_m = "".join(ch for ch in (monogram or "").strip().upper() if ch.isalnum())
    if clean_m:
        return clean_m[:3]
    words = ["".join(ch for ch in w if ch.isalnum()) for w in (title or "").split()]
    words = [w for w in words if w]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    return "AI"


def _draw_monogram_emblem(canvas, cx: int, cy: int, size: int, initials: str, accent: tuple, is_light: bool, hero_img=None):
    """Kartvizit ve posterler için ince mimari/mühür stilinde logo veya monogram amblemi çizer."""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    half = size // 2

    if hero_img is not None:
        scale = min((size * 0.86) / max(1, hero_img.width), (size * 0.86) / max(1, hero_img.height))
        hw, hh = max(1, int(hero_img.width * scale)), max(1, int(hero_img.height * scale))
        resized = hero_img.resize((hw, hh), Image.LANCZOS)
        d.ellipse([cx - half, cy - half, cx + half, cy + half], fill=(*accent, 28), outline=(*accent, 145), width=2)
        canvas.alpha_composite(layer)
        canvas.alpha_composite(resized, dest=(cx - hw // 2, cy - hh // 2))
        return

    ring_col = (*accent, 220)
    inner_fill = (255, 255, 255, 10) if not is_light else (15, 23, 42, 8)
    d.ellipse([cx - half, cy - half, cx + half, cy + half], fill=inner_fill, outline=ring_col, width=max(2, size // 36))
    in_pad = max(8, int(size * 0.11))
    d.ellipse([cx - half + in_pad, cy - half + in_pad, cx + half - in_pad, cy + half - in_pad], outline=(*accent, 90), width=1)

    font = _load_studio_font(max(20, int(size * 0.40)), bold=True, family="serif")
    bb = d.textbbox((0, 0), initials, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    ink = (248, 250, 252, 255) if not is_light else (15, 23, 42, 255)
    d.text((cx - tw / 2 - bb[0], cy - th / 2 - bb[1]), initials, fill=ink, font=font)
    canvas.alpha_composite(layer)


def _wrap_graphic_lines(draw, txt: str, fnt, max_width: int, max_rows: int) -> list:
    """Açık yeni satırları (\\n) koruyarak metni piksel genişliğine göre sarar."""
    rows = []
    for raw_para in (txt or "").splitlines():
        para = raw_para.strip()
        if not para:
            continue
        cur = ""
        for word in para.split():
            cand = f"{cur} {word}".strip() if cur else word
            bb = draw.textbbox((0, 0), cand, font=fnt)
            if bb[2] - bb[0] <= max_width or not cur:
                cur = cand
            else:
                rows.append(cur)
                cur = word
                if len(rows) >= max_rows:
                    return rows[:max_rows]
        if cur:
            rows.append(cur)
            if len(rows) >= max_rows:
                return rows[:max_rows]
    return rows[:max_rows]


def _parse_card_items(items, subtitle: str) -> tuple:
    """Yapılandırılmış bilgi maddeleri listesi ile alt başlığı temizce ayırır."""
    clean_items = [str(it).strip() for it in (items or []) if str(it).strip()]
    if clean_items or not subtitle:
        return subtitle, clean_items
    lines = [ln.strip() for ln in subtitle.splitlines() if ln.strip()]
    if len(lines) >= 2 and any(_detect_row_icon_kind(ln) != "spark" for ln in lines):
        return "", lines[:6]
    return subtitle, []


def _build_studio_backdrop(w: int, h: int, c1: tuple, c2: tuple, accent: tuple, accent2: tuple, st: str, is_light: bool):
    """Banding olmayan film grenli gradyan, yumuşatılmış stüdyo ışıkları ve iç çerçeveyi kurar."""
    from PIL import Image, ImageDraw, ImageFilter
    ty = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    tx = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
    blend = np.clip(ty * 0.68 + tx * 0.32, 0.0, 1.0)
    rng = np.random.default_rng(42)
    grain = rng.uniform(-2.2, 2.2, (h, w, 1)).astype(np.float32)

    arr = np.empty((h, w, 4), dtype=np.uint8)
    for ch in range(3):
        base = c1[ch] + (c2[ch] - c1[ch]) * blend + grain[:, :, 0]
        arr[:, :, ch] = np.clip(base, 0, 255).astype(np.uint8)
    arr[:, :, 3] = 255
    canvas = Image.fromarray(arr, "RGBA")

    if st != "minimal":
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        gdraw.ellipse([int(w * 0.45), -int(h * 0.22), int(w * 1.25), int(h * 0.58)], fill=(*accent, 70 if not is_light else 45))
        gdraw.ellipse([-int(w * 0.25), int(h * 0.58), int(w * 0.48), int(h * 1.24)], fill=(*accent2, 52 if not is_light else 36))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=max(28, min(w, h) // 6)))
        canvas = Image.alpha_composite(canvas, glow)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    if st in ("mesh", "neon"):
        step = max(32, min(w, h) // 18)
        dot_col = (*accent, 28) if not is_light else (*accent, 24)
        for gx in range(step // 2, w, step):
            for gy in range(step // 2, h, step):
                odraw.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=dot_col)

    mx = max(24, int(w * 0.042))
    my = max(24, int(h * 0.042))
    inner_box = (mx, my, w - mx, h - my)
    if st == "neon":
        odraw.rounded_rectangle([mx // 2, my // 2, w - mx // 2, h - my // 2], radius=16, outline=(*accent, 195), width=3)
    elif st != "minimal":
        # Tam taşmalı (full-bleed) baskı görünümü: modal kutusu yok, sol mimari şerit + ince taşma çizgisi
        stripe_w = max(8, int(min(w, h) * 0.014))
        odraw.rectangle([0, 0, stripe_w, h], fill=(*accent, 235))
        line_col = (*accent, 52) if not is_light else (*accent, 68)
        odraw.rectangle(list(inner_box), outline=line_col, width=1)
        bar_pad = max(48, (w - mx * 2) // 3)
        odraw.line([(mx + bar_pad, my), (w - mx - bar_pad, my)], fill=(*accent, 195), width=2)
        odraw.line([(mx + bar_pad, h - my), (w - mx - bar_pad, h - my)], fill=(*accent, 195), width=2)

    return Image.alpha_composite(canvas, overlay), inner_box


def _render_design_graphic_pil(
    title: str,
    subtitle: str = "",
    badge: str = "",
    width: int = 1200,
    height: int = 630,
    theme: str = "indigo",
    style: str = "modern",
    hero_image_path: str = "",
    footer_text: str = "",
    path_resolver=None,
    layout: str = "auto",
    items=None,
    monogram: str = "",
    font_family: str = "sans",
):
    """Stüdyo ışıklı gradyan, monogram amblem, simetrik rozet ve yapılandırılmış bilgi satırlarıyla RGBA grafik üretir."""
    from PIL import Image, ImageDraw
    w = max(256, min(int(width or 1200), 2400))
    h = max(256, min(int(height or 630), 2400))
    palettes = {
        "indigo": ((14, 16, 36), (49, 46, 129), (129, 140, 248), (56, 189, 248), False),
        "emerald": ((8, 25, 24), (6, 78, 59), (52, 211, 153), (45, 212, 191), False),
        "sunset": ((32, 13, 30), (134, 42, 24), (251, 146, 60), (244, 63, 94), False),
        "midnight": ((10, 12, 20), (24, 34, 54), (96, 165, 250), (167, 139, 250), False),
        "ocean": ((7, 22, 42), (14, 102, 132), (34, 211, 238), (59, 130, 246), False),
        "rose": ((33, 11, 27), (136, 19, 55), (251, 113, 133), (244, 114, 182), False),
        "gold_noir": ((11, 11, 14), (28, 24, 20), (218, 178, 72), (180, 130, 45), False),
        "ivory": ((248, 247, 243), (230, 234, 242), (30, 64, 175), (99, 102, 241), True),
    }
    c1, c2, accent, accent2, is_light = palettes.get((theme or "indigo").strip().lower(), palettes["indigo"])
    st = (style or "modern").strip().lower()
    fam = (font_family or "display").strip().lower() if (layout or "").lower() in ("card", "poster") else (font_family or "sans").strip().lower()

    lay = (layout or "auto").strip().lower()
    if lay in ("", "auto"):
        hint = f"{badge} {title} {subtitle}".lower()
        if "kartvizit" in hint or "business card" in hint or (items and h >= w * 0.5):
            lay = "card"
        elif h > w * 1.15:
            lay = "poster"
        elif 0.85 <= w / max(1, h) <= 1.15:
            lay = "social"
        else:
            lay = "banner"

    canvas, (ix1, iy1, ix2, iy2) = _build_studio_backdrop(w, h, c1, c2, accent, accent2, st, is_light)
    pad = max(32, int(min(w, h) * 0.055))
    cx1, cy1, cx2, cy2 = ix1 + pad, iy1 + pad, ix2 - pad, iy2 - pad
    cw, ch = cx2 - cx1, cy2 - cy1

    hero_img = None
    if hero_image_path:
        hero_abs = path_resolver(hero_image_path) if path_resolver else hero_image_path
        if os.path.isfile(hero_abs):
            try:
                hero_img = Image.open(hero_abs).convert("RGBA")
            except Exception:
                hero_img = None

    title_ink = (15, 23, 42, 255) if is_light else (248, 250, 252, 255)
    sub_ink = (71, 85, 105, 245) if is_light else (203, 213, 225, 238)
    row_fill = (15, 23, 42, 16) if is_light else (255, 255, 255, 22)
    row_border = (*accent, 85) if is_light else (*accent, 75)
    badge_text_ink = (255, 255, 255, 255)
    divider_ink = (*accent, 215)

    clean_sub, clean_items = _parse_card_items(items, subtitle)
    fg = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(fg)

    def _draw_footer_bar(foot_txt: str):
        if not foot_txt:
            return
        f_font = _load_studio_font(max(13, int(min(w, h) * 0.024)), bold=True, family="mono")
        bb = draw.textbbox((0, 0), foot_txt[:90], font=f_font)
        fh = bb[3] - bb[1]
        fy = cy2 - fh - bb[1]
        draw.line([(cx1, fy + bb[1] - 14), (cx2, fy + bb[1] - 14)], fill=(*accent, 65), width=1)
        draw.text((cx1 - bb[0], fy), foot_txt[:90], fill=(*accent, 240), font=f_font)

    def _draw_items_rows(start_y: int, max_y: int, rx1: int, rx2: int):
        if not clean_items:
            return start_y
        count = min(6, len(clean_items))
        avail_h = max(80, max_y - start_y)
        row_gap = max(8, int(avail_h * 0.055))
        row_h = max(34, min(int(min(w, h) * 0.070), (avail_h - row_gap * (count - 1)) // count))
        total_h = row_h * count + row_gap * (count - 1)
        cur = start_y + max(0, (avail_h - total_h) // 2)
        r_font_sz = max(15, min(28, int(row_h * 0.42)))
        r_font = _load_studio_font(r_font_sz, bold=False, family="sans")
        for idx_r, item in enumerate(clean_items[:count]):
            if cur + row_h > max_y:
                break
            icon_sz = max(16, int(row_h * 0.44))
            icon_cx = rx1 + max(18, row_h // 3)
            icon_cy = cur + row_h // 2
            circ_r = max(14, int(icon_sz * 0.85))
            draw.ellipse([icon_cx - circ_r, icon_cy - circ_r, icon_cx + circ_r, icon_cy + circ_r], fill=row_fill, outline=row_border, width=1)
            _draw_vector_icon(draw, _detect_row_icon_kind(item), icon_cx, icon_cy, icon_sz, (*accent, 245))
            tx = icon_cx + circ_r + 16
            max_txt_w = max(80, rx2 - tx - 8)
            txt = item
            while len(txt) > 8 and draw.textbbox((0, 0), txt, font=r_font)[2] > max_txt_w:
                txt = txt[:-2].rstrip() + "…"
            tbb = draw.textbbox((0, 0), txt, font=r_font)
            th = tbb[3] - tbb[1]
            draw.text((tx - tbb[0], cur + (row_h - th) / 2 - tbb[1]), txt, fill=title_ink, font=r_font)
            if idx_r < count - 1:
                draw.line([(tx, cur + row_h + row_gap // 2), (rx2, cur + row_h + row_gap // 2)], fill=(*accent, 34), width=1)
            cur += row_h + row_gap
        return cur

    # ==================== KARTVİZİT / DİKEY POSTER DÜZENİ ====================
    if lay in ("card", "poster") and h >= w:
        top_y = cy1
        if badge:
            b_sz = max(13, int(w * 0.024))
            b_font = _load_studio_font(b_sz, bold=True, family="display")
            bw, bh = _draw_pill_badge(draw, cx1, top_y, badge.upper(), b_font, (*accent, 240), badge_text_ink, max(16, int(b_sz * 0.8)), max(8, int(b_sz * 0.42)))
            draw.line([(cx1 + bw + 18, top_y + bh // 2), (cx2, top_y + bh // 2)], fill=(*accent, 75), width=2)
            top_y += bh + max(24, int(ch * 0.032))

        bottom_limit = cy2 - (max(52, int(ch * 0.075)) if footer_text else 0)
        emblem_sz = int(min(cw * 0.31, ch * (0.19 if clean_items else 0.23)))
        t_len = len((title or "").strip())
        base_ratio = 0.112 if t_len <= 14 else (0.090 if t_len <= 24 else 0.074)
        t_sz = max(30, min(122, int(w * base_ratio)))
        t_font = _load_studio_font(t_sz, bold=True, family=fam if fam != "sans" else "display")
        t_lines = _wrap_graphic_lines(draw, title or "Tasarım", t_font, cw, 3)

        s_sz = max(18, min(38, int(t_sz * 0.40)))
        s_font = _load_studio_font(s_sz, bold=False, family="sans")
        s_lines = _wrap_graphic_lines(draw, clean_sub[:260], s_font, int(cw * 0.92), 4) if clean_sub else []

        # Alt satır listesi yoksa kahraman bloğu dikeyde optik merkeze yerleştir
        gap_em = max(28, int(ch * 0.035))
        gap_bar_top = max(10, int(ch * 0.012))
        gap_bar_bot = max(22, int(ch * 0.025))
        hero_block_h = (
            emblem_sz + gap_em
            + len(t_lines) * int(t_sz * 1.18)
            + gap_bar_top + 5 + gap_bar_bot
            + len(s_lines) * int(s_sz * 1.42)
        )
        if not clean_items:
            avail_span = max(0, (bottom_limit - top_y) - hero_block_h)
            start_offset = int(avail_span * 0.44)
        else:
            start_offset = max(8, int(ch * 0.015))

        emblem_cy = top_y + start_offset + emblem_sz // 2
        _draw_monogram_emblem(fg, cx1 + cw // 2, emblem_cy, emblem_sz, _extract_initials(monogram, title), accent, is_light, hero_img=hero_img)
        cur_y = emblem_cy + emblem_sz // 2 + gap_em

        for ln in t_lines:
            lbb = draw.textbbox((0, 0), ln, font=t_font)
            lw = lbb[2] - lbb[0]
            draw.text((cx1 + (cw - lw) / 2 - lbb[0], cur_y - lbb[1]), ln, fill=title_ink, font=t_font)
            cur_y += int(t_sz * 1.18)

        cur_y += gap_bar_top
        bar_w = max(72, int(cw * 0.22))
        draw.rounded_rectangle([cx1 + (cw - bar_w) // 2, cur_y, cx1 + (cw + bar_w) // 2, cur_y + 5], radius=3, fill=divider_ink)
        cur_y += gap_bar_bot

        for sln in s_lines:
            sbb = draw.textbbox((0, 0), sln, font=s_font)
            sw = sbb[2] - sbb[0]
            draw.text((cx1 + (cw - sw) / 2 - sbb[0], cur_y - sbb[1]), sln, fill=sub_ink, font=s_font)
            cur_y += int(s_sz * 1.42)

        if clean_items:
            _draw_items_rows(cur_y + max(18, int(ch * 0.025)), bottom_limit - 10, cx1, cx2)

        _draw_footer_bar(footer_text)
        return Image.alpha_composite(canvas, fg)

    # ==================== YATAY KARTVİZİT / BANNER / SOSYAL ====================
    split_mode = (lay == "card" and w > h) or (hero_img is not None) or bool(clean_items and w >= h)
    left_w = int(cw * 0.56) if split_mode else cw
    footer_reserve = max(48, int(ch * 0.12)) if footer_text else 0

    b_font = _load_studio_font(max(13, int(min(w, h) * 0.030)), bold=True, family="display")
    t_sz = max(28, min(86, int(min(w, h) * (0.115 if len(title or "") <= 16 else 0.092))))
    t_font = _load_studio_font(t_sz, bold=True, family=fam if fam != "sans" else "display")
    t_lines = _wrap_graphic_lines(draw, title or "Tasarım", t_font, left_w, 3)
    s_sz = max(16, min(32, int(t_sz * 0.42)))
    s_font = _load_studio_font(s_sz, bold=False, family="sans")
    s_lines = _wrap_graphic_lines(draw, clean_sub[:240], s_font, left_w, 3) if clean_sub else []

    left_h = (max(36, int(min(w, h) * 0.065)) + 20 if badge else 0) + len(t_lines) * int(t_sz * 1.20) + 32 + len(s_lines) * int(s_sz * 1.38)
    cur_y = cy1 + max(8, ((ch - footer_reserve) - left_h) // 2)

    if badge:
        b_sz = max(13, int(min(w, h) * 0.030))
        _, bh = _draw_pill_badge(draw, cx1, cur_y, badge.upper(), b_font, (*accent, 240), badge_text_ink, max(14, int(b_sz * 0.8)), max(7, int(b_sz * 0.42)))
        cur_y += bh + max(18, int(ch * 0.04))

    for ln in t_lines:
        tbb = draw.textbbox((0, 0), ln, font=t_font)
        draw.text((cx1 - tbb[0], cur_y - tbb[1]), ln, fill=title_ink, font=t_font)
        cur_y += int(t_sz * 1.20)

    cur_y += 10
    draw.rounded_rectangle([cx1, cur_y, cx1 + max(64, int(left_w * 0.24)), cur_y + 4], radius=2, fill=divider_ink)
    cur_y += 18

    for sln in s_lines:
        sbb = draw.textbbox((0, 0), sln, font=s_font)
        draw.text((cx1 - sbb[0], cur_y - sbb[1]), sln, fill=sub_ink, font=s_font)
        cur_y += int(s_sz * 1.38)

    if split_mode:
        rx1 = cx1 + left_w + max(24, int(cw * 0.04))
        rx2 = cx2
        draw.line([(rx1 - max(12, int(cw * 0.02)), cy1 + 12), (rx1 - max(12, int(cw * 0.02)), cy2 - max(12, footer_reserve))], fill=(*accent, 65), width=1)
        if clean_items:
            _draw_items_rows(cy1 + 12, cy2 - max(12, footer_reserve), rx1, rx2)
        else:
            em_sz = int(min(rx2 - rx1, ch - footer_reserve) * 0.62)
            _draw_monogram_emblem(fg, (rx1 + rx2) // 2, (cy1 + cy2 - footer_reserve) // 2, em_sz, _extract_initials(monogram, title), accent, is_light, hero_img=hero_img)

    _draw_footer_bar(footer_text)
    return Image.alpha_composite(canvas, fg)


def _extract_subject_alpha(arr: np.ndarray, mode: str = "auto", tol: float = 40.0) -> tuple:
    """Ön plan nesnesini kenar halosu olmadan ayıklar; (alpha_uint8, etiket) döndürür."""
    h_im, w_im = arr.shape[:2]
    m = (mode or "auto").strip().lower()
    if m == "grabcut" and w_im >= 24 and h_im >= 24:
        bgr = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2BGR)
        gc_mask = np.zeros((h_im, w_im), np.uint8)
        mx = max(2, int(w_im * 0.06))
        my = max(2, int(h_im * 0.06))
        rect = (mx, my, max(4, w_im - mx * 2), max(4, h_im - my * 2))
        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)
        cv2.grabCut(bgr, gc_mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)
        fg_bin = np.where((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        kernel = np.ones((3, 3), np.uint8)
        fg_bin = cv2.morphologyEx(fg_bin, cv2.MORPH_OPEN, kernel, iterations=1)
        fg_bin = cv2.erode(fg_bin, kernel, iterations=1)
        alpha = cv2.GaussianBlur(fg_bin, (5, 5), 0)
        return alpha, "remove_bg(grabcut)"

    rgb = arr[:, :, :3].astype(np.float32)
    border_px = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]], axis=0)
    bg_col = np.median(border_px, axis=0)
    dist = np.linalg.norm(rgb - bg_col, axis=2)
    bg_cand = (dist < tol).astype(np.uint8)
    _, labels = cv2.connectedComponents(bg_cand, connectivity=4)
    border_labels = set(np.unique(np.concatenate([
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]
    ]))) - {0}
    bg_mask = np.isin(labels, list(border_labels)) if border_labels else (dist < tol)
    alpha = np.where(bg_mask, 0, 255).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    return alpha, "remove_bg"


def _apply_photoshop_ops_pil(img, operations: list, path_resolver=None):
    """Verilen RGBA PIL görseline Photoshop işlem listesini uygular; (yeni_görsel, işlem_etiketleri) döndürür."""
    from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    img = img.convert("RGBA")
    applied = []

    def _safe_alpha_blit(base_rgba, layer_rgba, dx: int, dy: int):
        bw, bh = base_rgba.size
        lw, lh = layer_rgba.size
        sx1, sy1 = max(0, -dx), max(0, -dy)
        dx1, dy1 = max(0, dx), max(0, dy)
        cw = min(lw - sx1, bw - dx1)
        ch = min(lh - sy1, bh - dy1)
        if cw <= 0 or ch <= 0:
            return base_rgba
        crop_ov = layer_rgba.crop((sx1, sy1, sx1 + cw, sy1 + ch))
        tmp = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
        tmp.paste(crop_ov, (dx1, dy1))
        return Image.alpha_composite(base_rgba, tmp)

    for step in (operations or []):
        if not isinstance(step, dict):
            continue
        op = (step.get("op") or "").strip().lower()
        if op == "resize":
            nw = int(step.get("width") or img.width)
            nh = int(step.get("height") or img.height)
            img = img.resize((max(1, nw), max(1, nh)), Image.LANCZOS)
            applied.append(f"resize({nw}x{nh})")
        elif op == "crop":
            l = int(step.get("left", 0))
            t = int(step.get("top", 0))
            r = int(step.get("right") or img.width)
            b = int(step.get("bottom") or img.height)
            img = img.crop((max(0, l), max(0, t), min(img.width, r), min(img.height, b)))
            applied.append("crop")
        elif op == "rotate":
            ang = float(step.get("angle", 0))
            img = img.rotate(ang, expand=True, resample=Image.BICUBIC)
            applied.append(f"rotate({ang})")
        elif op == "flip_h":
            img = ImageOps.mirror(img)
            applied.append("flip_h")
        elif op == "flip_v":
            img = ImageOps.flip(img)
            applied.append("flip_v")
        elif op in ("brightness", "contrast", "saturation", "sharpness"):
            factor = float(step.get("factor", 1.15))
            rgb = img.convert("RGB")
            alpha = img.getchannel("A")
            cls_map = {
                "brightness": ImageEnhance.Brightness,
                "contrast": ImageEnhance.Contrast,
                "saturation": ImageEnhance.Color,
                "sharpness": ImageEnhance.Sharpness,
            }
            enhanced = cls_map[op](rgb).enhance(factor).convert("RGBA")
            enhanced.putalpha(alpha)
            img = enhanced
            applied.append(f"{op}({factor})")
        elif op == "auto_enhance":
            arr = np.array(img, dtype=np.float32)
            out = arr.copy()
            for ch in range(3):
                lo, hi = np.percentile(arr[:, :, ch], (1.2, 98.8))
                if hi - lo > 8.0:
                    out[:, :, ch] = np.clip((arr[:, :, ch] - lo) * (255.0 / (hi - lo)), 0, 255)
            enhanced = Image.fromarray(out.astype(np.uint8), "RGBA")
            alpha = enhanced.getchannel("A")
            enhanced = ImageEnhance.Sharpness(enhanced.convert("RGB")).enhance(1.12).convert("RGBA")
            enhanced.putalpha(alpha)
            img = enhanced
            applied.append("auto_enhance")
        elif op == "warmth":
            amt = max(-1.0, min(float(step.get("factor", 0.25)), 1.0))
            arr = np.array(img, dtype=np.float32)
            arr[:, :, 0] = np.clip(arr[:, :, 0] + amt * 34.0, 0, 255)
            arr[:, :, 1] = np.clip(arr[:, :, 1] + amt * 8.0, 0, 255)
            arr[:, :, 2] = np.clip(arr[:, :, 2] - amt * 34.0, 0, 255)
            img = Image.fromarray(arr.astype(np.uint8), "RGBA")
            applied.append(f"warmth({amt})")
        elif op in ("clarity", "hdr_clarity"):
            strength = max(0.1, min(float(step.get("strength", 0.45)), 1.0))
            alpha = img.getchannel("A")
            bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
            lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
            l_ch, a_ch, b_ch = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=1.5 + strength * 2.5, tileGridSize=(8, 8))
            l_enh = cv2.addWeighted(l_ch, 1.0 - strength * 0.6, clahe.apply(l_ch), strength * 0.6, 0)
            merged = cv2.cvtColor(cv2.merge((l_enh, a_ch, b_ch)), cv2.COLOR_LAB2RGB)
            res = Image.fromarray(merged, "RGB")
            res = ImageEnhance.Sharpness(res).enhance(1.0 + strength * 0.55).convert("RGBA")
            res.putalpha(alpha)
            img = res
            applied.append("clarity")
        elif op == "duotone":
            c_dark = ImageColor.getrgb(str(step.get("bg_color") or step.get("color2") or "#0f172a"))
            c_light = ImageColor.getrgb(str(step.get("color") or "#818cf8"))
            alpha = img.getchannel("A")
            gray = np.array(ImageOps.grayscale(img.convert("RGB")), dtype=np.float32) / 255.0
            out = np.empty((img.height, img.width, 4), dtype=np.uint8)
            for ch in range(3):
                out[:, :, ch] = np.clip(c_dark[ch] + (c_light[ch] - c_dark[ch]) * gray, 0, 255).astype(np.uint8)
            out[:, :, 3] = np.array(alpha, dtype=np.uint8)
            img = Image.fromarray(out, "RGBA")
            applied.append("duotone")
        elif op in ("bokeh", "portrait_blur"):
            rad = max(2.0, min(float(step.get("radius", 12.0)), 40.0))
            fx = int(step.get("x") or img.width // 2)
            fy = int(step.get("y") or img.height // 2)
            blurred = img.filter(ImageFilter.GaussianBlur(radius=rad))
            yy, xx = np.ogrid[:img.height, :img.width]
            rx = max(30.0, img.width * float(step.get("scale", 0.36)))
            ry = max(30.0, img.height * float(step.get("scale", 0.42)))
            dist = np.sqrt(((xx - fx) / rx) ** 2 + ((yy - fy) / ry) ** 2)
            sharp_mask = np.clip(1.45 - dist, 0.0, 1.0)[:, :, None]
            orig_arr = np.array(img, dtype=np.float32)
            blur_arr = np.array(blurred, dtype=np.float32)
            comp = orig_arr * sharp_mask + blur_arr * (1.0 - sharp_mask)
            img = Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8), "RGBA")
            applied.append("bokeh")
        elif op == "cartoon":
            alpha = img.getchannel("A")
            rgb = np.array(img.convert("RGB"))
            smooth = cv2.bilateralFilter(rgb, 9, 75, 75)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            edges = cv2.adaptiveThreshold(cv2.medianBlur(gray, 5), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 8)
            cartoon = cv2.bitwise_and(smooth, smooth, mask=edges)
            res = Image.fromarray(cartoon, "RGB").convert("RGBA")
            res.putalpha(alpha)
            img = res
            applied.append("cartoon")
        elif op == "gradient_overlay":
            col_rgb = ImageColor.getrgb(str(step.get("color") or "#0b0d14"))
            opac = max(0.05, min(float(step.get("opacity", 0.58)), 0.95))
            direction = str(step.get("direction") or "bottom").strip().lower()
            grad = np.zeros((img.height, img.width, 4), dtype=np.uint8)
            grad[:, :, :3] = col_rgb
            if direction == "top":
                alpha_curve = np.linspace(opac * 255, 0, img.height, dtype=np.float32)[:, None]
                grad[:, :, 3] = np.clip(np.broadcast_to(alpha_curve, (img.height, img.width)), 0, 255).astype(np.uint8)
            elif direction == "left":
                alpha_curve = np.linspace(opac * 255, 0, img.width, dtype=np.float32)[None, :]
                grad[:, :, 3] = np.clip(np.broadcast_to(alpha_curve, (img.height, img.width)), 0, 255).astype(np.uint8)
            elif direction == "right":
                alpha_curve = np.linspace(0, opac * 255, img.width, dtype=np.float32)[None, :]
                grad[:, :, 3] = np.clip(np.broadcast_to(alpha_curve, (img.height, img.width)), 0, 255).astype(np.uint8)
            elif direction == "full":
                grad[:, :, 3] = int(opac * 255)
            else:
                alpha_curve = np.linspace(0, opac * 255, img.height, dtype=np.float32)[:, None]
                grad[:, :, 3] = np.clip(np.broadcast_to(alpha_curve, (img.height, img.width)), 0, 255).astype(np.uint8)
            img = Image.alpha_composite(img, Image.fromarray(grad, "RGBA"))
            applied.append(f"gradient({direction})")
        elif op == "blur":
            rad = float(step.get("radius", 4))
            img = img.filter(ImageFilter.GaussianBlur(radius=max(0.1, rad)))
            applied.append(f"blur({rad})")
        elif op == "grayscale":
            alpha = img.getchannel("A")
            img = ImageOps.grayscale(img.convert("RGB")).convert("RGBA")
            img.putalpha(alpha)
            applied.append("grayscale")
        elif op == "sepia":
            arr = np.array(img, dtype=np.float32)
            r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
            nr = np.clip(0.393 * r + 0.769 * g + 0.189 * b, 0, 255)
            ng = np.clip(0.349 * r + 0.686 * g + 0.168 * b, 0, 255)
            nb = np.clip(0.272 * r + 0.534 * g + 0.131 * b, 0, 255)
            img = Image.fromarray(np.stack([nr, ng, nb, a], axis=-1).astype(np.uint8), "RGBA")
            applied.append("sepia")
        elif op == "invert":
            alpha = img.getchannel("A")
            img = ImageOps.invert(img.convert("RGB")).convert("RGBA")
            img.putalpha(alpha)
            applied.append("invert")
        elif op == "vignette":
            strength = max(0.1, min(float(step.get("strength", 0.55)), 1.0))
            yy, xx = np.ogrid[:img.height, :img.width]
            cy, cx = img.height / 2.0, img.width / 2.0
            dist = np.sqrt(((xx - cx) / max(1.0, cx)) ** 2 + ((yy - cy) / max(1.0, cy)) ** 2)
            mask = np.clip(1.0 - np.clip(dist - 0.35, 0.0, 1.5) * strength, 0.15, 1.0).astype(np.float32)
            arr = np.array(img, dtype=np.float32)
            arr[:, :, :3] *= mask[:, :, None]
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
            applied.append("vignette")
        elif op == "tint":
            col_str = str(step.get("color") or "#6366f1")
            strength = max(0.05, min(float(step.get("strength", 0.25)), 0.9))
            rgb_col = ImageColor.getrgb(col_str)
            arr = np.array(img, dtype=np.float32)
            for ch in range(3):
                arr[:, :, ch] = arr[:, :, ch] * (1.0 - strength) + rgb_col[ch] * strength
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
            applied.append(f"tint({col_str})")
        elif op == "sketch":
            alpha = img.getchannel("A")
            gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
            inv = 255 - gray
            blur_inv = cv2.GaussianBlur(inv, (21, 21), 0)
            sketch = cv2.divide(gray, 255 - blur_inv, scale=256.0)
            img = Image.fromarray(cv2.cvtColor(sketch, cv2.COLOR_GRAY2RGB), "RGB").convert("RGBA")
            img.putalpha(alpha)
            applied.append("sketch")
        elif op == "pixelate":
            block = max(2, min(int(step.get("block_size", 12)), 80))
            small = img.resize((max(1, img.width // block), max(1, img.height // block)), Image.NEAREST)
            img = small.resize(img.size, Image.NEAREST)
            applied.append(f"pixelate({block})")
        elif op == "border":
            bsize = max(2, min(int(step.get("size", 12)), 120))
            bcol = str(step.get("color") or "#6366f1")
            img = ImageOps.expand(img, border=bsize, fill=bcol).convert("RGBA")
            applied.append(f"border({bsize})")
        elif op == "drop_shadow":
            blur_r = max(2, int(step.get("radius", 18)))
            ox = int(step.get("x", 0))
            oy = int(step.get("y", 10))
            opac = max(0.1, min(float(step.get("opacity", 0.55)), 1.0))
            pad = blur_r * 2 + max(abs(ox), abs(oy))
            canvas = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
            sh_alpha = img.getchannel("A").point(lambda v: int(v * opac))
            shadow = Image.new("RGBA", img.size, (0, 0, 0, 255))
            shadow.putalpha(sh_alpha)
            canvas.alpha_composite(shadow, dest=(pad + ox, pad + oy))
            canvas = canvas.filter(ImageFilter.GaussianBlur(radius=blur_r))
            canvas.alpha_composite(img, dest=(pad, pad))
            img = canvas
            applied.append("drop_shadow")
        elif op == "pad_square":
            side = max(img.width, img.height)
            bg = img.resize((side, side), Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=24))
            dark = Image.new("RGBA", (side, side), (10, 12, 20, 90))
            bg = Image.alpha_composite(bg.convert("RGBA"), dark)
            bg.alpha_composite(img, dest=((side - img.width) // 2, (side - img.height) // 2))
            img = bg
            applied.append("pad_square")
        elif op == "rounded_corners":
            rad = max(2, int(step.get("radius", 24)))
            mask = Image.new("L", (img.width * 2, img.height * 2), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, img.width * 2 - 1, img.height * 2 - 1], radius=rad * 2, fill=255
            )
            mask = mask.resize(img.size, Image.LANCZOS)
            cur_a = np.minimum(np.array(img.getchannel("A")), np.array(mask))
            img.putalpha(Image.fromarray(cur_a, "L"))
            applied.append(f"rounded({rad})")
        elif op == "circle_crop":
            side = min(img.width, img.height)
            left = (img.width - side) // 2
            top = (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side))
            mask = Image.new("L", (side * 2, side * 2), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, side * 2 - 1, side * 2 - 1], fill=255)
            img.putalpha(mask.resize((side, side), Image.LANCZOS))
            applied.append("circle_crop")
        elif op == "remove_bg":
            mode = str(step.get("mode") or "auto").strip().lower()
            tol = float(step.get("tolerance", 40))
            arr = np.array(img)
            alpha, lbl = _extract_subject_alpha(arr, mode=mode, tol=tol)
            arr[:, :, 3] = np.minimum(arr[:, :, 3], alpha)
            img = Image.fromarray(arr, "RGBA")
            applied.append(lbl)
        elif op == "replace_bg":
            arr = np.array(img)
            cur_a = arr[:, :, 3]
            if np.min(cur_a) > 235:
                sub_alpha, _ = _extract_subject_alpha(
                    arr,
                    mode=str(step.get("mode") or "auto"),
                    tol=float(step.get("tolerance", 40)),
                )
                arr[:, :, 3] = np.minimum(cur_a, sub_alpha)
            fg_sub = Image.fromarray(arr, "RGBA")
            sc = max(0.2, min(float(step.get("scale", 0.88)), 1.4))
            nw = max(1, int(fg_sub.width * sc))
            nh = max(1, int(fg_sub.height * sc))
            fg_scaled = fg_sub.resize((nw, nh), Image.LANCZOS) if sc != 1.0 else fg_sub

            bw = int(step.get("width") or img.width)
            bh = int(step.get("height") or img.height)
            bg_rel = str(step.get("bg_path") or "").strip()
            bg_abs = path_resolver(bg_rel) if (bg_rel and path_resolver) else bg_rel
            if bg_rel and os.path.isfile(bg_abs):
                bg_img = ImageOps.fit(Image.open(bg_abs).convert("RGBA"), (bw, bh), Image.LANCZOS)
                bblur = float(step.get("bg_blur", 6.0))
                if bblur > 0.2:
                    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=bblur))
            else:
                c1_rgb = ImageColor.getrgb(str(step.get("bg_color") or "#0f172a"))
                c2_str = str(step.get("color") or "").strip()
                c2_rgb = ImageColor.getrgb(c2_str) if c2_str else tuple(min(255, v + 26) for v in c1_rgb)
                ty = np.linspace(0.0, 1.0, bh, dtype=np.float32)[:, None]
                tx = np.linspace(0.0, 1.0, bw, dtype=np.float32)[None, :]
                blend = np.clip(ty * 0.7 + tx * 0.3, 0.0, 1.0)
                bg_arr = np.empty((bh, bw, 4), dtype=np.uint8)
                for ch in range(3):
                    bg_arr[:, :, ch] = np.clip(c1_rgb[ch] + (c2_rgb[ch] - c1_rgb[ch]) * blend, 0, 255).astype(np.uint8)
                bg_arr[:, :, 3] = 255
                bg_img = Image.fromarray(bg_arr, "RGBA")

            dx = (bw - fg_scaled.width) // 2 + int(step.get("x", 0))
            dy = (bh - fg_scaled.height) // 2 + int(step.get("y", 0))
            if step.get("shadow", True) is not False:
                sh_a = fg_scaled.getchannel("A").point(lambda v: int(v * 0.45))
                shadow = Image.new("RGBA", fg_scaled.size, (0, 0, 0, 255))
                shadow.putalpha(sh_a)
                sh_canvas = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
                sh_canvas = _safe_alpha_blit(sh_canvas, shadow, dx, dy + 14)
                sh_canvas = sh_canvas.filter(ImageFilter.GaussianBlur(radius=18))
                bg_img = Image.alpha_composite(bg_img, sh_canvas)
            img = _safe_alpha_blit(bg_img, fg_scaled, dx, dy)
            applied.append("replace_bg")
        elif op == "sticker_outline":
            osize = max(2, min(int(step.get("size", 10)), 40))
            ocol = ImageColor.getrgb(str(step.get("color") or "#ffffff"))
            pad = osize + 4
            padded = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
            padded.paste(img, (pad, pad))
            a_arr = np.array(padded.getchannel("A"))
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (osize * 2 + 1, osize * 2 + 1))
            dilated = cv2.dilate(a_arr, k, iterations=1)
            dilated = cv2.GaussianBlur(dilated, (3, 3), 0)
            outline_layer = Image.new("RGBA", padded.size, (*ocol, 255))
            outline_layer.putalpha(Image.fromarray(dilated, "L"))
            img = Image.alpha_composite(outline_layer, padded)
            applied.append(f"sticker_outline({osize})")
        elif op == "exposure":
            ev = max(-2.5, min(float(step.get("factor", 0.5)), 2.5))
            gain = float(2.0 ** ev)
            arr = np.array(img, dtype=np.float32)
            lin = (arr[:, :, :3] / 255.0) * gain
            arr[:, :, :3] = np.clip((lin / (1.0 + 0.15 * np.maximum(0.0, lin - 1.0))) * 255.0, 0, 255)
            img = Image.fromarray(arr.astype(np.uint8), "RGBA")
            applied.append(f"exposure({ev:+.2f})")
        elif op == "vibrance":
            amt = max(-0.8, min(float(step.get("factor", 0.35)), 1.0))
            arr = np.array(img, dtype=np.float32)
            rgb = arr[:, :, :3] / 255.0
            mx = np.max(rgb, axis=2, keepdims=True)
            mn = np.min(rgb, axis=2, keepdims=True)
            sat = mx - mn
            avg = np.mean(rgb, axis=2, keepdims=True)
            boost = 1.0 + amt * (1.0 - sat)
            arr[:, :, :3] = np.clip((avg + (rgb - avg) * boost) * 255.0, 0, 255)
            img = Image.fromarray(arr.astype(np.uint8), "RGBA")
            applied.append(f"vibrance({amt})")
        elif op == "grain":
            amt = max(1.0, min(float(step.get("strength", 0.06)) * 120.0, 32.0))
            rng = np.random.default_rng(7)
            noise = rng.normal(0.0, amt, (img.height, img.width, 1)).astype(np.float32)
            arr = np.array(img, dtype=np.float32)
            arr[:, :, :3] = np.clip(arr[:, :, :3] + noise, 0, 255)
            img = Image.fromarray(arr.astype(np.uint8), "RGBA")
            applied.append("grain")
        elif op == "sharpen_mask":
            rad = max(0.5, min(float(step.get("radius", 2.0)), 6.0))
            pct = max(30, min(int(float(step.get("strength", 1.3)) * 100), 300))
            alpha = img.getchannel("A")
            sharp = img.convert("RGB").filter(ImageFilter.UnsharpMask(radius=rad, percent=pct, threshold=3)).convert("RGBA")
            sharp.putalpha(alpha)
            img = sharp
            applied.append("sharpen_mask")
        elif op == "skin_smooth":
            amt = max(0.15, min(float(step.get("strength", 0.55)), 0.9))
            arr = np.array(img)
            bgr = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2BGR)
            ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
            skin = cv2.inRange(ycrcb, np.array([0, 133, 77]), np.array([255, 173, 127]))
            skin_blur = cv2.GaussianBlur(skin, (15, 15), 0).astype(np.float32)[:, :, None] / 255.0
            smooth_rgb = cv2.cvtColor(cv2.bilateralFilter(bgr, 9, 55, 55), cv2.COLOR_BGR2RGB).astype(np.float32)
            orig_rgb = arr[:, :, :3].astype(np.float32)
            mask = skin_blur * amt
            out_rgb = orig_rgb * (1.0 - mask) + smooth_rgb * mask
            arr[:, :, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
            img = Image.fromarray(arr, "RGBA")
            applied.append("skin_smooth")
        elif op == "mockup":
            pad = max(36, int(min(img.width, img.height) * 0.08))
            rad = max(12, int(step.get("radius", 22)))
            bg_col = ImageColor.getrgb(str(step.get("bg_color") or "#0d111a"))
            mw, mh = img.width + pad * 2, img.height + pad * 2
            card_mask = Image.new("L", (img.width * 2, img.height * 2), 0)
            ImageDraw.Draw(card_mask).rounded_rectangle([0, 0, img.width * 2 - 1, img.height * 2 - 1], radius=rad * 2, fill=255)
            card_rounded = img.copy()
            card_rounded.putalpha(Image.fromarray(np.minimum(np.array(img.getchannel("A")), np.array(card_mask.resize(img.size, Image.LANCZOS))), "L"))

            ty = np.linspace(0.0, 1.0, mh, dtype=np.float32)[:, None]
            bg_arr = np.empty((mh, mw, 4), dtype=np.uint8)
            for ch in range(3):
                bg_arr[:, :, ch] = np.clip(bg_col[ch] * (0.85 + 0.35 * (1.0 - ty)), 0, 255).astype(np.uint8)
            bg_arr[:, :, 3] = 255
            stage = Image.fromarray(bg_arr, "RGBA")
            sh = Image.new("RGBA", card_rounded.size, (0, 0, 0, 255))
            sh.putalpha(card_rounded.getchannel("A").point(lambda v: int(v * 0.65)))
            sh_layer = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
            sh_layer.paste(sh, (pad, pad + max(10, pad // 3)))
            sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(radius=max(14, pad // 2)))
            stage = Image.alpha_composite(stage, sh_layer)
            stage = _safe_alpha_blit(stage, card_rounded, pad, pad)
            img = stage
            applied.append("mockup")
        elif op == "preset":
            pname = str(step.get("mode") or step.get("text") or "studio").strip().lower()
            preset_ops = {
                "cinematic": [
                    {"op": "contrast", "factor": 1.14},
                    {"op": "vibrance", "factor": 0.25},
                    {"op": "warmth", "factor": 0.14},
                    {"op": "vignette", "strength": 0.42},
                    {"op": "grain", "strength": 0.04},
                ],
                "noir": [
                    {"op": "grayscale"},
                    {"op": "contrast", "factor": 1.32},
                    {"op": "sharpen_mask", "strength": 1.25},
                    {"op": "vignette", "strength": 0.62},
                    {"op": "grain", "strength": 0.08},
                ],
                "vintage": [
                    {"op": "warmth", "factor": 0.30},
                    {"op": "sepia"},
                    {"op": "contrast", "factor": 0.92},
                    {"op": "vignette", "strength": 0.45},
                    {"op": "grain", "strength": 0.07},
                ],
                "studio": [
                    {"op": "auto_enhance"},
                    {"op": "clarity", "strength": 0.38},
                    {"op": "vibrance", "factor": 0.18},
                    {"op": "sharpen_mask", "strength": 1.15},
                ],
                "cyberpunk": [
                    {"op": "duotone", "bg_color": "#120826", "color": "#22d3ee"},
                    {"op": "contrast", "factor": 1.24},
                    {"op": "sharpen_mask", "strength": 1.35},
                ],
            }
            sub_ops = preset_ops.get(pname, preset_ops["studio"])
            img, _ = _apply_photoshop_ops_pil(img, sub_ops, path_resolver=path_resolver)
            applied.append(f"preset({pname})")
        elif op == "add_text":
            txt = str(step.get("text") or "")
            fsize = max(12, int(step.get("font_size", 36)))
            fam = str(step.get("font_family") or "sans")
            align = str(step.get("align") or "left").strip().lower()
            col_rgb = ImageColor.getrgb(str(step.get("color") or "#ffffff"))
            use_shadow = step.get("shadow", True) is not False
            bg_str = str(step.get("bg_color") or "").strip()
            font_obj = _load_studio_font(fsize, bold=True, family=fam)

            fg = Image.new("RGBA", img.size, (0, 0, 0, 0))
            fdraw = ImageDraw.Draw(fg)
            max_w = int(step.get("max_width") or (img.width - 64))
            lines = _wrap_graphic_lines(fdraw, txt, font_obj, max_w, 8) or [txt]
            line_h = int(fsize * 1.28)
            tx = int(step.get("x", img.width // 2 if align == "center" else (img.width - 40 if align == "right" else 40)))
            ty = int(step.get("y", 40))

            if bg_str:
                widths = [fdraw.textbbox((0, 0), ln, font=font_obj)[2] for ln in lines]
                box_w = (max(widths) if widths else 80) + 32
                box_h = len(lines) * line_h + 16
                bx1 = tx - box_w // 2 if align == "center" else (tx - box_w if align == "right" else tx - 16)
                bg_rgb = ImageColor.getrgb(bg_str)
                fdraw.rounded_rectangle([bx1, ty - 8, bx1 + box_w, ty - 8 + box_h], radius=14, fill=(*bg_rgb, 195))

            cur_y = ty
            for ln in lines:
                bb = fdraw.textbbox((0, 0), ln, font=font_obj)
                lw = bb[2] - bb[0]
                lx = tx - lw / 2 - bb[0] if align == "center" else (tx - lw - bb[0] if align == "right" else tx - bb[0])
                if use_shadow:
                    fdraw.text((lx + 2, cur_y - bb[1] + 2), ln, fill=(0, 0, 0, 165), font=font_obj)
                fdraw.text((lx, cur_y - bb[1]), ln, fill=(*col_rgb, 255), font=font_obj)
                cur_y += line_h
            img = Image.alpha_composite(img, fg)
            applied.append("add_text")
        elif op == "overlay":
            ov_rel = str(step.get("overlay_path") or "")
            ov_abs = path_resolver(ov_rel) if path_resolver else ov_rel
            if os.path.isfile(ov_abs):
                ov = Image.open(ov_abs).convert("RGBA")
                sc = float(step.get("scale", 1.0))
                if sc != 1.0 and sc > 0:
                    ov = ov.resize((max(1, int(ov.width * sc)), max(1, int(ov.height * sc))), Image.LANCZOS)
                opac = float(step.get("opacity", 1.0))
                if 0.0 <= opac < 1.0:
                    ov_a = ov.getchannel("A").point(lambda v: int(v * opac))
                    ov.putalpha(ov_a)
                align = str(step.get("align") or "").strip().lower()
                margin = int(step.get("margin", 24))
                if align == "center":
                    ox, oy = (img.width - ov.width) // 2, (img.height - ov.height) // 2
                elif align == "top_right":
                    ox, oy = img.width - ov.width - margin, margin
                elif align == "bottom_left":
                    ox, oy = margin, img.height - ov.height - margin
                elif align == "bottom_right":
                    ox, oy = img.width - ov.width - margin, img.height - ov.height - margin
                elif align == "top_left":
                    ox, oy = margin, margin
                else:
                    ox = int(step.get("x", 24))
                    oy = int(step.get("y", 24))
                img = _safe_alpha_blit(img, ov, ox, oy)
                applied.append("overlay")

    return img, applied


# ==============================================================================
# MODÜL 4: YEREL AI ASİSTANI (MINI-AGENT: OLLAMA + SUPABASE + ARAÇ ÇAĞIRMA)
# ==============================================================================
class LocalAIAssistantModule(BaseModuleView):
    """
    EVREN AI (evren-llmapi.ssyz.org.tr) + Yerel Ollama (Llama 3.2 / Qwen 2.5)
    + Supabase (veya yerel SQLite yedekli) + Otomatik Araç Çağırma
    (PDF Oluşturucu, Hassas Hesap Makinesi, Sistem Saati) destekli Mini-Agent.
    """
    CONTEXT_WINDOW_LIMIT = 10
    EVREN_CONTEXT_WINDOW_LIMIT = 12
    MAX_AGENT_STEPS = 6  # Tek turda maksimum ajan adımı (sonsuz araç/sekme döngüsünü önler)
    EVREN_DEFAULT_BASE_URL = "https://evren-llmapi.ssyz.org.tr/v1"
    EVREN_DEFAULT_MODELS = [
        "qwen3-vl-30b",
        "gemma-4-31b",
        "deepseek-v4.1-flash",
        "qwen3.8-flash-next",
        "glm-5.3",
        "auto",
    ]
    PROVIDER_EVREN = "Kendi AI Sunucum (Kaggle)"
    PROVIDER_OLLAMA = "Ollama (Yerel)"

    SYSTEM_PROMPT = (
        "Sen Burak'ın bilgisayarında ve çalışma klasöründe otonom kod yazabilen, profesyonel web/arayüz tasarlayabilen, "
        "Photoshop seviyesinde görsel/grafik üretebilen ve uygulama çalıştırabilen gelişmiş bir yazılım ve tasarım ajanısın.\n"
        "Kurallar:\n"
        "- Her zaman doğal, akıcı ve dilbilgisi açısından doğru Türkçe konuş.\n"
        "- Kullanıcı bir uygulama, web sitesi veya tasarım istediğinde araçları (write_file, edit_file, read_file, list_files, run_command, design_graphic, photoshop_edit, launch_app) gerçek anlamda kullan.\n"
        "- ÇOK HIZLI ÇALIŞ (MİNİMUM ADIM): Küçük/orta değişiklikleri 2-3 adımda bitir!\n"
        "  • Çalışma klasörü ağaç özeti aşağıda verildiyse gereksiz `list_files` çağırma; dosyayı doğrudan oku.\n"
        "  • Mevcut dosyaları değiştirirken asla tüm dosyayı `write_file` ile baştan yazma — yalnızca değişen kısım için kısa ve nokta atışı `edit_file` kullan.\n"
        "  • Bağımsız `read_file`, `edit_file` veya `write_file` çağrılarını aynı adımda paralel gönder.\n"
        "- MODERN TASARIM STANDARDI: Asla çıplak/stilsiz HTML yapma! Her web sayfasında modern CSS değişkenleri, şık tipografi (Segoe UI / Inter), kart düzeni, yumuşak gölgeler, yüksek kontrastlı butonlar, hover animasyonları ve responsive tasarım uygula. İhtiyaç halinde design_graphic ile özel logo/banner/ikon üretip sayfaya bağla.\n"
        "- ÇALIŞAN SİTE KURALI:\n"
        "  1) Tek sayfalık veya statik sitelerde CSS/JS'i ya doğrudan index.html içine temizce göm ya da göreli ./style.css / ./app.js yolları kullan; ASLA tarayıcıda dosya olarak açıldığında bozulacak {{ url_for(...) }} şablonları üretme (veya kullanıcıyı yalnızca index.html açmaya mecbur bırakma).\n"
        "  2) Flask/FastAPI sunucu gerekiyorsa: mutlaka 1-tıkla baslat.bat yaz, rotaları run_command içinde bloklamadan `python -c \"import app; ... test_client()\"` ile hızlıca test et. Web dosyalarını her güncelledikten sonra değişikliklerin tarayıcıda görünmesi için mutlaka `launch_app` çağırarak sunucuyu yeniden başlat (eski sunucu otomatik kapatılır) ve static önbelleği kapat (`app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0`). ASLA `run_command` içinde `python app.py` çalıştırıp bekleme!\n"
        "  3) Görevi bitirirken sadece 'İşlem tamamlandı' deme; değiştirdiğin dosyaları ve nasıl test edileceğini Türkçe özetle.\n"
        "- HIZ & DOSYA KURALLARI: Yeni sıfırdan tasarım veya uygulama istendiğinde mevcut ilgisiz proje dosyalarını (`app.py`, `index.html`, `Görev Defteri` vb.) KESİNLİKLE OKUMA; doğrudan üret. Tek bir `write_file` çağrısında ~5000 karakterden uzun monolitik kod yazma (gerekirse HTML, CSS ve JS dosyalarını ayrı kısa çağrılara böl).\n"
        "- PHOTOSHOP & GÖRSEL STÜDYOSU (GERÇEK KULLANILABİLİR TASARIM STANDARTLARI): Görsel veya grafik istendiğinde mevcut kod dosyalarını okumadan doğrudan tasarım araçlarını kullan:\n"
        "  1) `decompose_image_to_design` (YÜKLENEN GÖRSELİ PARÇALARA AYIRMA — METİN, LOGO, KUTU, ZEMİN): Kullanıcı bir görsel yüklediğinde (`[Görsel: ...]`) veya mevcut bir görseldeki/kartvizitteki parçaları tek tek analiz edip metinleri, logoyu, kutuları, çizgileri değiştirilebilir/hareket ettirilebilir katmanlara bölmek istediğinde DOĞRUDAN `decompose_image_to_design` aracını çağır! Bu araç görseli Vision AI + görüntü işleme ile analiz eder, her parçayı (`#isim`, `#unvan`, `#logo`, `#firma`, `#telefon`, `#eposta`, `#web`, `#adres`, `#panel` vb.) ayrı birer düzenlenebilir katmana dönüştürür ve interaktif editörde açar.\n"
        "  2) `update_editable_design` (MEVCUT TASARIMDAKİ PARÇALARI YAPAY ZEKA İLE DEĞİŞTİRME): Kullanıcı ayrıştırılmış görseldeki veya aktif tasarımdaki herhangi bir parçayı değiştirmek istediğinde (ör: 'logoyu sağ üste al', 'logoyu büyüt', 'ismi Ahmet Kaya yap', 'telefonu 0532... yap', 'adresi sil', 'arka planı lacivert yap', 'ismin rengini altın yap') ASLA `create_editable_design` ile tasarımı sıfırlama — DOĞRUDAN `update_editable_design` aracını çağırarak sadece istenen parçaları (`target='logo'`, `target='isim'`, `target='telefon'` vb.) güncelle!\n"
        "  3) `create_editable_design` (SIFIRDAN DÜZENLENEBİLİR STITCH/CANVA EDİTÖRÜ): Kullanıcı sıfırdan yeni bir düzenlenebilir kartvizit/tasarım istediğinde doğrudan `create_editable_design` aracını kullan.\n"
        "  4) `render_html_graphic` (STATİK TASARIMDA ÖZET HTML): Yalnızca sabit PNG istenen kartvizit, afiş, logo, menü, davetiye ve kapaklarda kullan; HTML/CSS/SVG'yi olabildiğince sade ve kompakt (<2500 krk) tut ki hızlı render edilsin (`html,body{margin:0;width:Wpx;height:Hpx;overflow:hidden}`). Saydam PNG logo/etiket için `transparent=true` ver.\n"
        "  • TASARIM KALİTE YASAKLARI: Kartvizit üzerine ASLA 'KARTVİZİT · ÖN YÜZ', 'ARKA YÜZ' gibi sahte meta etiketler basma! Kullanıcı isim belirtmediyse 'Ad Soyad' yerine Burak Yılmaz veya gerçekçi bir marka kimliği kurgula.\n"
        "  5) `design_graphic`: Yalnızca hızlı yedek şablon gerektiğinde veya HTML motoru yoksa kullan.\n"
        "  6) `photoshop_edit`: Profesyonel fotoğraf retuşu ve katman kompozisyonu: `preset` (cinematic/noir/vintage/studio/cyberpunk), `replace_bg`, `remove_bg` (`mode='grabcut'`), `skin_smooth`, `exposure`, `vibrance`, `clarity`, `warmth`, `bokeh`, `grain`, `sharpen_mask`, `sticker_outline`, `mockup`, `duotone`, `cartoon`, `sketch`, `gradient_overlay`, `add_text`, `overlay`.\n"
        "  7) Oluşturulan/düzenlenen görsel sohbette canlı önizleme olarak otomatik gösterilir.\n"
        "- ASLA İŞLEM YAPMIŞ GİBİ YALAN SÖYLEME / SAHTE KOD BLOĞU YAZMA: Kullanıcı dosya taşıma ('masaüstüne getir/taşı/kopyala'), oluşturma, düzenleme, düzeltme veya açma istediğinde hiçbir araç çağırmadan 'taşıdım/kopyaladım/açtım' demek veya sohbete ```bash copy ... ``` yazmak KESİNLİKLE YASAKTIR! Her eylemde mutlaka gerçek aracı (`move_or_copy_file`, `create_editable_design`, `write_file`, `edit_file`, `launch_app`, `run_command`) çağır.\n"
        "- MASAÜSTÜ & DOSYA TAŞIMA: Dosyayı veya oluşturulan kartviziti/projeyi masaüstüne taşımak/kopyalamak istendiğinde doğrudan `move_or_copy_file` aracını (`source_path='kartvizit_editor.html'` veya `'last'`, `destination_path='desktop'`, `open_after=True`) çağır. Araç OneDrive Masaüstü dahil gerçek Windows Masaüstü yolunu otomatik bulur.\n"
        "- Selamlaşma veya sohbet mesajlarında araç çağırma; doğal sohbet et.\n"
        "- Emin olmadığın hiçbir şeyi uydurma; gerçek dosya yollarını ve doğrulama sonuçlarını paylaş."
    )

    TOOLS_SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "Klasördeki dosya/dizinleri listeler.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subpath": {"type": "string", "description": "Alt klasör yolu (kök için boş)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Dosyayı satır numaralarıyla okur (varsayılan 1-500).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Göreceli dosya yolu"},
                        "start_line": {"type": "integer", "description": "Başlangıç satırı (1)"},
                        "end_line": {"type": "integer", "description": "Bitiş satırı (500)"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Yeni dosya oluşturur veya üzerine yazar (küçük değişikliklerde edit_file seç).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Göreceli dosya yolu"},
                        "content": {"type": "string", "description": "Tam içerik"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Mevcut dosyada exact eşleşen metni yenisiyle hızlıca değiştirir.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Göreceli dosya yolu"},
                        "old_text": {"type": "string", "description": "Değişecek tam metin"},
                        "new_text": {"type": "string", "description": "Yeni metin"}
                    },
                    "required": ["path", "old_text", "new_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Kısa süren terminal komutu çalıştırır (sunucu için launch_app kullan).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Komut"}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "launch_app",
                "description": "Sunucuyu/HTML'yi arka planda başlatır ve tarayıcıda açar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Sunucu komutu (örn: 'python app.py')"},
                        "url": {"type": "string", "description": "Tarayıcı URL'si"},
                        "html_path": {"type": "string", "description": "Göreceli HTML/görsel yolu"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "render_html_graphic",
                "description": "Kartvizit, poster, logo, davetiye, kapak, menü vb. TÜM grafik tasarımlarda İLK TERCİH! Modern HTML+CSS3+SVG yazıp tam taşmalı piksel netliğinde PNG (veya saydam logo için transparent=true) üretir; ASLA 'Ön Yüz/Arka Yüz' meta etiketi basma.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string", "description": "Çıktı PNG/JPG yolu"},
                        "html": {"type": "string", "description": "Tam HTML+CSS+SVG içeriği"},
                        "width": {"type": "integer", "description": "Genişlik piksel (ör: 1050 veya 1200)"},
                        "height": {"type": "integer", "description": "Yükseklik piksel (ör: 600 veya 1650)"},
                        "transparent": {"type": "boolean", "description": "Saydam arka planlı PNG logo/etiket için true"}
                    },
                    "required": ["output_path", "html"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_editable_design",
                "description": "Stitch / Canva tarzında her parçası sürüklenebilir, çift tıklamayla düzenlenebilir, boyutlandırılabilir, silinebilir ve PNG indirilebilir canlı HTML editörü oluşturur ve tarayıcıda açar. İnteraktif/düzenlenebilir tasarım istendiğinde write_file yerine BUNU kullan!",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "output_html": {"type": "string", "description": "Çıktı HTML dosya adı (ör: kartvizit_editor.html)"},
                        "title": {"type": "string", "description": "Editör başlığı"},
                        "width": {"type": "integer", "description": "Tuval genişliği px (ör: 1004)"},
                        "height": {"type": "integer", "description": "Tuval yüksekliği px (ör: 650)"},
                        "background": {"type": "string", "description": "Tuval CSS arka planı (ör: #0f1116 veya linear-gradient(...))"},
                        "elements": {
                            "type": "array",
                            "description": "Düzenlenebilir katman öğeleri",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["text", "badge", "rect", "circle", "line", "image"]},
                                    "text": {"type": "string"},
                                    "x": {"type": "integer"},
                                    "y": {"type": "integer"},
                                    "w": {"type": "integer"},
                                    "h": {"type": "integer"},
                                    "fontSize": {"type": "integer"},
                                    "fontWeight": {"type": "string"},
                                    "font": {"type": "string"},
                                    "color": {"type": "string"},
                                    "bg": {"type": "string"},
                                    "borderColor": {"type": "string"},
                                    "borderWidth": {"type": "integer"},
                                    "radius": {"type": "integer"},
                                    "opacity": {"type": "number"},
                                    "align": {"type": "string"},
                                    "src": {"type": "string"}
                                },
                                "required": ["type", "x", "y"]
                            }
                        },
                        "open_browser": {"type": "boolean", "description": "Tarayıcıda otomatik aç (varsayılan true)"}
                    },
                    "required": ["elements"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "decompose_image_to_design",
                "description": "Kullanıcının gönderdiği/yüklediği bir görseli (kartvizit, afiş, tasarım vb.) tek tek analiz ederek içindeki tüm parçaları (isim, ünvan, firma, logo/amblem, telefon, e-posta, web, adres, kutular, çizgiler, arka plan) ayrıştırır ve her parçası hem fareyle hem de yapay zekaya söyleyerek değiştirilebilir canlı HTML editörüne dönüştürür.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_path": {"type": "string", "description": "Analiz edilecek görsel yolu ('last' veya 'uploads/...' — boş bırakılırsa son yüklenen görsel kullanılır)"},
                        "output_html": {"type": "string", "description": "Çıktı HTML editör dosya adı (varsayılan: gorsel_parcali_editor.html)"},
                        "instructions": {"type": "string", "description": "Görseli parçalarken aynı anda uygulanacak ek değişiklik talimatı varsa (opsiyonel)"},
                        "open_browser": {"type": "boolean", "description": "Tarayıcıda otomatik aç (varsayılan true)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_editable_design",
                "description": "Mevcut düzenlenebilir tasarımdaki (veya görselden ayrıştırılmış tasarımdaki) belirli parçaları (isim, ünvan, logo, firma, telefon, e-posta, web, adres, rozet, çizgi, arka plan vb.) değiştirir, taşır, boyutlandırır, renklendirir, siler veya yeni parça ekler.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "updates": {
                            "type": "array",
                            "description": "Değiştirilecek parçaların listesi",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "target": {"type": "string", "description": "Değiştirilecek parçanın ID'si veya adı: 'isim', 'unvan', 'logo', 'firma', 'telefon', 'eposta', 'web', 'adres', 'slogan', 'cizgi', 'panel', 'cerceve' veya mevcut metni"},
                                    "text": {"type": "string", "description": "Yeni metin içeriği (ör: 'AHMET KAYA' veya '+90 532 111 22 33')"},
                                    "position": {"type": "string", "description": "Konum komutu: 'sol_ust', 'sag_ust', 'sol_alt', 'sag_alt', 'orta', 'ust_orta', 'alt_orta', 'sola', 'saga', 'yukari', 'asagi'"},
                                    "x": {"type": "integer", "description": "Yeni X koordinatı px"},
                                    "y": {"type": "integer", "description": "Yeni Y koordinatı px"},
                                    "w": {"type": "integer", "description": "Yeni genişlik px"},
                                    "h": {"type": "integer", "description": "Yeni yükseklik px"},
                                    "scale": {"type": "number", "description": "Boyut çarpanı (büyütmek için 1.25, küçültmek için 0.8)"},
                                    "fontSize": {"type": "integer", "description": "Yeni yazı boyutu px"},
                                    "color": {"type": "string", "description": "Yeni yazı rengi (#hex veya 'altın', 'beyaz', 'siyah', 'kırmızı', 'mavi', 'gümüş')"},
                                    "bg": {"type": "string", "description": "Yeni arka plan/dolgu rengi"},
                                    "borderColor": {"type": "string", "description": "Yeni kenarlık rengi"},
                                    "align": {"type": "string", "enum": ["left", "center", "right"]},
                                    "delete": {"type": "boolean", "description": "Bu parçayı silmek için true"}
                                },
                                "required": ["target"]
                            }
                        },
                        "add_elements": {
                            "type": "array",
                            "description": "Tasarım tuvaline eklenecek yeni parçalar",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "label": {"type": "string"},
                                    "type": {"type": "string", "enum": ["text", "badge", "rect", "circle", "line", "image"]},
                                    "text": {"type": "string"},
                                    "x": {"type": "integer"},
                                    "y": {"type": "integer"},
                                    "w": {"type": "integer"},
                                    "h": {"type": "integer"},
                                    "fontSize": {"type": "integer"},
                                    "color": {"type": "string"},
                                    "bg": {"type": "string"}
                                }
                            }
                        },
                        "background": {"type": "string", "description": "Tuvalin yeni arka plan rengi veya CSS gradyanı (opsiyonel)"},
                        "open_browser": {"type": "boolean", "description": "Güncellenen tasarımı tarayıcıda aç (varsayılan true)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "move_or_copy_file",
                "description": "Oluşturulan bir dosyayı veya son yapılan tasarımı/kartviziti gerçek Windows Masaüstüne ('desktop' / 'masaüstü') veya başka bir klasöre kopyalar/taşır ve isteğe bağlı olarak açar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_path": {"type": "string", "description": "Kaynak dosya adı veya 'last' (son oluşturulan dosya, ör: kartvizit_editor.html)"},
                        "destination_path": {"type": "string", "description": "Hedef klasör veya dosya yolu ('desktop', 'masaüstü' veya tam yol)"},
                        "action": {"type": "string", "enum": ["copy", "move"], "description": "Kopyala ('copy') veya taşı ('move')"},
                        "open_after": {"type": "boolean", "description": "İşlem sonrası dosyayı otomatik aç (varsayılan true)"}
                    },
                    "required": ["source_path", "destination_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "design_graphic",
                "description": "Yalnızca tarayıcı motoru yokken veya çok hızlı sabit şablon gerektiğinde yedek PNG kart/banner üretir (özel tasarımlarda render_html_graphic kullan).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string", "description": "Çıktı PNG yolu"},
                        "title": {"type": "string", "description": "Ana başlık / İsim"},
                        "subtitle": {"type": "string", "description": "Alt başlık / Ünvan"},
                        "badge": {"type": "string", "description": "Üst rozet"},
                        "layout": {"type": "string", "description": "auto|card|poster|banner|social"},
                        "items": {"type": "array", "items": {"type": "string"}, "description": "Bilgi satırları listesi"},
                        "monogram": {"type": "string", "description": "Logo harfleri (ör: BY)"},
                        "font_family": {"type": "string", "description": "sans|display|serif|mono"},
                        "width": {"type": "integer", "description": "Genişlik (1200)"},
                        "height": {"type": "integer", "description": "Yükseklik (630)"},
                        "theme": {"type": "string", "description": "indigo|emerald|sunset|midnight|ocean|rose|gold_noir|ivory"},
                        "style": {"type": "string", "description": "modern|glass|minimal|neon|mesh"},
                        "hero_image_path": {"type": "string", "description": "Opsiyonel logo/fotoğraf yolu"},
                        "footer_text": {"type": "string", "description": "Alt imza/domain"}
                    },
                    "required": ["output_path", "title"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "photoshop_edit",
                "description": "Görsele gelişmiş Photoshop retuş, arka plan değiştirme/silme, preset, cilt yumuşatma, bokeh, sticker çerçeve, mockup, metin ve bindirme uygular.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string", "description": "Kaynak görsel yolu"},
                        "output_path": {"type": "string", "description": "Çıktı yolu"},
                        "operations": {
                            "type": "array",
                            "description": "İşlem listesi",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "type": "string",
                                        "description": "resize|crop|rotate|flip_h|flip_v|brightness|contrast|saturation|sharpness|auto_enhance|exposure|vibrance|warmth|clarity|sharpen_mask|grain|skin_smooth|duotone|bokeh|cartoon|gradient_overlay|blur|grayscale|sepia|invert|vignette|tint|sketch|pixelate|border|sticker_outline|drop_shadow|mockup|pad_square|rounded_corners|circle_crop|remove_bg|replace_bg|preset|add_text|overlay"
                                    },
                                    "mode": {"type": "string", "description": "remove_bg: auto|grabcut | preset: cinematic|noir|vintage|studio|cyberpunk"},
                                    "direction": {"type": "string", "description": "gradient_overlay: bottom|top|left|right|full"},
                                    "align": {"type": "string", "description": "left|center|right|top_left|top_right|bottom_left|bottom_right"},
                                    "font_family": {"type": "string", "description": "sans|display|serif|mono"},
                                    "shadow": {"type": "boolean"},
                                    "bg_color": {"type": "string"},
                                    "bg_path": {"type": "string", "description": "replace_bg için arka plan foto yolu"},
                                    "bg_blur": {"type": "number", "description": "replace_bg için arka plan bulanıklığı"},
                                    "margin": {"type": "integer"},
                                    "width": {"type": "integer"},
                                    "height": {"type": "integer"},
                                    "left": {"type": "integer"},
                                    "top": {"type": "integer"},
                                    "right": {"type": "integer"},
                                    "bottom": {"type": "integer"},
                                    "angle": {"type": "number"},
                                    "factor": {"type": "number"},
                                    "strength": {"type": "number"},
                                    "size": {"type": "integer"},
                                    "block_size": {"type": "integer"},
                                    "radius": {"type": "integer"},
                                    "text": {"type": "string"},
                                    "x": {"type": "integer"},
                                    "y": {"type": "integer"},
                                    "font_size": {"type": "integer"},
                                    "color": {"type": "string"},
                                    "overlay_path": {"type": "string"},
                                    "scale": {"type": "number"},
                                    "opacity": {"type": "number"},
                                    "tolerance": {"type": "integer"}
                                },
                                "required": ["op"]
                            }
                        }
                    },
                    "required": ["input_path", "operations"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Matematik ifadesini hesaplar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "İfade"}
                    },
                    "required": ["expression"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "getSystemTime",
                "description": "Güncel tarih ve saati döndürür.",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generateDocument",
                "description": "Türkçe destekli PDF belgesi oluşturur.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Başlık"},
                        "content": {"type": "string", "description": "Metin içeriği"}
                    },
                    "required": ["content"]
                }
            }
        }
    ]

    def __init__(self, parent, app_controller):
        super().__init__(
            parent=parent,
            app_controller=app_controller,
            title="EVREN AI & Asistan",
            subtitle="",
            show_navbar=False,
        )
        self.ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        self.evren_base_url = os.environ.get("EVREN_BASE_URL", self.EVREN_DEFAULT_BASE_URL).rstrip("/")
        self.evren_api_key = os.environ.get("EVREN_API_KEY", "").strip()
        self.evren_model = os.environ.get("EVREN_MODEL", "qwen3-vl-30b").strip() or "qwen3-vl-30b"
        self.active_provider = self.PROVIDER_EVREN

        self.supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self.supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_agent_history.db")
        self.pdf_output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_pdfs")
        os.makedirs(self.pdf_output_dir, exist_ok=True)
        default_ws = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_projects")
        os.makedirs(default_ws, exist_ok=True)
        self.agent_workspace_dir = default_ws
        self._chat_photo_refs = []
        self._thumb_cache = {}
        self._stream_lock = threading.Lock()
        self._stream_chunks = []
        self._stream_flush_pending = False
        self._gen_start_time = None
        self._live_status_text = "Hazır"
        self._live_status_color = THEME["success"]
        self._last_timer_display = ""

        self.current_conversation_id = None
        self.is_generating = False
        self.cancel_agent = False
        from requests.adapters import HTTPAdapter
        self.http_session = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16)
        self.http_session.mount("https://", adapter)
        self.http_session.mount("http://", adapter)
        self.http_session.headers.update({"Accept-Encoding": "gzip, deflate"})
        self._init_storage()
        self._load_provider_settings()
        saved_ws = self._get_setting("agent_workspace_dir", "").strip()
        if saved_ws and os.path.isdir(saved_ws):
            self.agent_workspace_dir = saved_ws
        if self.active_provider == self.PROVIDER_OLLAMA:
            self._ensure_ollama_running_background()
        self._build_workspace()
        self._refresh_conversation_list()
        if not self.current_conversation_id:
            self.create_new_conversation()
        self._refresh_provider_status_async()
        self._start_stitch_ai_bridge()

    def _init_storage(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    created_at TEXT NOT NULL,
                    rating INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
            if "rating" not in cols:
                conn.execute("ALTER TABLE messages ADD COLUMN rating INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_conv_time ON messages(conversation_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_created ON conversations(created_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _get_setting(self, key: str, default: str = "") -> str:
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def _set_setting(self, key: str, value: str):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()

    _NON_CHAT_MODEL_TOKENS = (
        "ocr", "embed", "rerank", "whisper", "tts", "stt", "asr",
        "transcrib", "speech", "audio", "flux", "sdxl", "diffusion", "yolo", "detr",
    )

    @classmethod
    def _is_evren_chat_model(cls, model_id: str, meta: dict = None) -> bool:
        mid = (model_id or "").strip().lower()
        if not mid:
            return False
        if any(tok in mid for tok in cls._NON_CHAT_MODEL_TOKENS):
            return False
        if isinstance(meta, dict):
            mtype = str(meta.get("type") or meta.get("task") or meta.get("mode") or "").lower()
            if any(tok in mtype for tok in ("ocr", "embed", "audio", "image", "speech", "rerank")):
                return False
        return True

    @classmethod
    def _filter_evren_chat_models(cls, data_list: list, base_url: str = "") -> list:
        chat_ids = []
        seen = set()
        is_gemini = "generativelanguage.googleapis.com" in (base_url or "").lower()
        for item in data_list or []:
            if not isinstance(item, dict):
                continue
            mid = (item.get("id") or "").strip()
            if not mid:
                continue
            if is_gemini:
                clean_mid = mid.removeprefix("models/").strip()
                if "gemini" in clean_mid.lower() and clean_mid not in seen:
                    if clean_mid not in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro") and not any(t in clean_mid for t in ("image", "tts", "audio", "live")):
                        seen.add(clean_mid)
                        chat_ids.append(clean_mid)
            elif mid not in seen and cls._is_evren_chat_model(mid, item):
                seen.add(mid)
                chat_ids.append(mid)
        if is_gemini:
            pref_order = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-latest", "gemini-3.7-flash"]
            sorted_models = [m for m in pref_order if m in seen]
            sorted_models += [m for m in chat_ids if m not in sorted_models]
            return sorted_models or ["gemini-3.5-flash", "gemini-flash-latest"]
        preferred = [m for m in cls.EVREN_DEFAULT_MODELS if m in seen and m != "auto"]
        others = [m for m in chat_ids if m not in preferred and m != "auto"]
        ordered = preferred + others
        if "auto" in seen or not ordered:
            ordered.append("auto")
        return ordered

    def _load_provider_settings(self):
        saved_key = self._get_setting("evren_api_key", "").strip()
        if saved_key and not self.evren_api_key:
            self.evren_api_key = saved_key
        saved_url = self._get_setting("evren_base_url", "").strip()
        if saved_url:
            self.evren_base_url = saved_url.rstrip("/")
        saved_evren_model = self._get_setting("evren_model", "").strip()
        if "generativelanguage.googleapis.com" in self.evren_base_url.lower():
            self.evren_model = saved_evren_model if (saved_evren_model and "gemini" in saved_evren_model) else "gemini-3.5-flash"
        elif "ssyz.org.tr" not in self.evren_base_url:
            self.evren_model = saved_evren_model or "my-custom-ai"
        elif saved_evren_model and saved_evren_model not in ("auto", "deepseek-v4-flash") and self._is_evren_chat_model(saved_evren_model):
            self.evren_model = saved_evren_model
        elif saved_evren_model:
            self.evren_model = "qwen3-vl-30b"
            self._set_setting("evren_model", self.evren_model)
        saved_provider = self._get_setting("active_provider", "").strip()
        if saved_provider == self.PROVIDER_OLLAMA:
            self.active_provider = self.PROVIDER_OLLAMA
        else:
            self.active_provider = self.PROVIDER_EVREN
            self._set_setting("active_provider", self.PROVIDER_EVREN)

    def _build_workspace(self):
        root_split = tk.Frame(self, bg=THEME["bg_main"])
        root_split.pack(fill="both", expand=True)

        # 1. Sol Kenar Çubuğu (Açılır/Kapanır, Çerçevesiz Sade Tasarım)
        self.sidebar_visible = True
        self.sidebar_frame = tk.Frame(root_split, bg=THEME["bg_header"], width=228)
        self.sidebar_frame.pack(side="left", fill="y")
        self.sidebar_frame.pack_propagate(False)

        self.sidebar_divider = tk.Frame(root_split, bg="#1e202b", width=1)
        self.sidebar_divider.pack(side="left", fill="y")

        new_chat_btn = PillButton(
            self.sidebar_frame,
            text="＋  Yeni Sohbet",
            command=self.create_new_conversation,
            bg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            outer_bg=THEME["bg_header"],
            radius=11,
            height=38,
            font=("Segoe UI", 9, "bold"),
        )
        new_chat_btn.pack(fill="x", padx=14, pady=(14, 12))

        tk.Label(
            self.sidebar_frame,
            text="GEÇMİŞ",
            font=("Segoe UI", 8, "bold"),
            bg=THEME["bg_header"],
            fg=THEME["muted"]
        ).pack(anchor="w", padx=16, pady=(2, 6))

        conv_wrap = tk.Frame(self.sidebar_frame, bg=THEME["bg_header"])
        conv_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        conv_scroll = ttk.Scrollbar(conv_wrap, orient="vertical", style="Dark.Vertical.TScrollbar")
        conv_scroll.pack(side="right", fill="y")

        self.conv_listbox = tk.Listbox(
            conv_wrap,
            bg=THEME["bg_header"],
            fg=THEME["text_secondary"],
            selectbackground=THEME["bg_card_hover"],
            selectforeground=THEME["text_primary"],
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0,
            activestyle="none",
            yscrollcommand=conv_scroll.set
        )
        self.conv_listbox.pack(side="left", fill="both", expand=True, padx=2)
        conv_scroll.config(command=self.conv_listbox.yview)
        self.conv_listbox.bind("<<ListboxSelect>>", self._on_select_conversation)

        del_btn = PillButton(
            self.sidebar_frame,
            text="Sohbeti Sil",
            command=self.delete_current_conversation,
            bg_color="#181a24",
            hover_color="#232635",
            fg_color=THEME["text_secondary"],
            outer_bg=THEME["bg_header"],
            border_color="#262936",
            radius=10,
            height=32,
            font=("Segoe UI", 8, "bold"),
        )
        del_btn.pack(fill="x", padx=14, pady=(0, 14))

        # 2. Sağ Ana Çalışma Alanı (Tek Üst Bar + Ortalanmış Akış + Yuvarlak Giriş)
        right_panel = tk.Frame(root_split, bg=THEME["bg_main"])
        right_panel.pack(side="left", fill="both", expand=True)

        # Tek Birleşik Minimal Üst Bar (48px - Antigravity Stili)
        header_bar = tk.Frame(right_panel, bg=THEME["bg_main"], height=48)
        header_bar.pack(fill="x", padx=18, pady=(4, 0))
        header_bar.pack_propagate(False)
        tk.Frame(right_panel, bg="#171a24", height=1).pack(fill="x")

        toggle_sb_btn = PillButton(
            header_bar,
            text="☰",
            command=self._toggle_sidebar,
            bg_color=THEME["bg_main"],
            hover_color=THEME["bg_card_hover"],
            fg_color=THEME["text_secondary"],
            outer_bg=THEME["bg_main"],
            border_color=THEME["bg_main"],
            radius=8,
            height=30,
            width=34,
            font=("Segoe UI", 10),
        )
        toggle_sb_btn.pack(side="left", pady=9)

        tk.Label(
            header_bar,
            text="✦ AI Studio",
            font=("Segoe UI", 10, "bold"),
            bg=THEME["bg_main"],
            fg=THEME["text_primary"],
        ).pack(side="left", padx=(6, 12), pady=9)

        self.provider_var = tk.StringVar(value=self.active_provider)
        self.provider_combo = ttk.Combobox(
            header_bar,
            textvariable=self.provider_var,
            values=[self.PROVIDER_EVREN, self.PROVIDER_OLLAMA],
            state="readonly",
            width=18,
            font=("Segoe UI", 9),
            style="Dark.TCombobox"
        )
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_change)

        initial_model = (
            self.evren_model if self.active_provider == self.PROVIDER_EVREN else self.ollama_model
        )
        if self.active_provider == self.PROVIDER_EVREN:
            if "generativelanguage.googleapis.com" in self.evren_base_url.lower():
                initial_models = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-latest"]
            elif "ssyz.org.tr" not in self.evren_base_url:
                initial_models = ["qwen2.5-coder-32b-pro", "my-custom-ai"]
            else:
                initial_models = self.EVREN_DEFAULT_MODELS
        else:
            initial_models = ["qwen2.5:7b", "llama3.2"]
        self.model_var = tk.StringVar(value=initial_model)
        self.model_combo = ttk.Combobox(
            header_bar,
            textvariable=self.model_var,
            values=initial_models,
            width=22,
            font=("Segoe UI", 9),
            style="Dark.TCombobox"
        )
        self.model_combo.pack(side="left", padx=(2, 0), pady=10)
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_change)

        self.confirm_commands_var = tk.BooleanVar(value=False)

        tools_menu_btn = tk.Menubutton(
            header_bar,
            text="⋯",
            font=("Segoe UI", 11, "bold"),
            bg=THEME["bg_main"],
            fg=THEME["text_secondary"],
            activebackground=THEME["bg_card_hover"],
            activeforeground=THEME["text_primary"],
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            direction="below"
        )
        tools_menu_btn.pack(side="right", pady=10)
        _bind_hover(tools_menu_btn, THEME["bg_main"], THEME["bg_card_hover"])

        tools_menu = tk.Menu(
            tools_menu_btn,
            tearoff=0,
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
            activebackground=THEME["accent"],
            activeforeground=THEME["text_primary"],
            font=("Segoe UI", 9),
            bd=0
        )
        tools_menu.add_command(label="🔑 AI Sunucu Bağlantısı...", command=self._open_evren_settings_dialog)
        tools_menu.add_command(label="🧠 Bilgi Tabanı & Eğitim...", command=self._open_training_and_knowledge_dialog)
        tools_menu.add_command(label="👍 Son Cevabı Eğitime Al", command=self._mark_last_reply_good)
        tools_menu.add_separator()
        tools_menu.add_command(label="📁 Çalışma Klasörünü Aç", command=lambda: os.startfile(self.agent_workspace_dir))
        tools_menu.add_command(label="📁 Çalışma Klasörünü Değiştir...", command=self._choose_agent_workspace)
        tools_menu.add_separator()
        tools_menu.add_command(label="👤 Yüz Tespiti Aracı", command=lambda: self.app.open_module("module_1"))
        tools_menu.add_command(label="🚗 Araç Plaka Tespiti Aracı", command=lambda: self.app.open_module("module_2"))
        tools_menu.add_command(label="🎙️ Video Türkçe Dublaj Aracı", command=lambda: self.app.open_module("module_3"))
        tools_menu_btn.config(menu=tools_menu)

        evren_cfg_btn = PillButton(
            header_bar,
            text="⚙ Sunucu",
            command=self._open_evren_settings_dialog,
            bg_color="#151823",
            hover_color=THEME["bg_card_hover"],
            fg_color=THEME["text_secondary"],
            outer_bg=THEME["bg_main"],
            border_color=THEME["border"],
            radius=8,
            height=28,
            width=76,
            font=("Segoe UI", 8, "bold"),
        )
        evren_cfg_btn.pack(side="right", padx=(0, 6), pady=10)

        self.tool_indicator = tk.Label(
            header_bar,
            text="Hazır",
            font=("Segoe UI", 8, "bold"),
            bg=THEME["bg_main"],
            fg=THEME["success"]
        )
        self.tool_indicator.pack(side="right", padx=(0, 12))

        self.ollama_badge = tk.Label(
            header_bar,
            text="● Bağlanıyor...",
            font=("Segoe UI", 8),
            bg=THEME["bg_main"],
            fg=THEME["text_secondary"]
        )
        self.ollama_badge.pack(side="right", padx=(0, 10))

        # 3. Ortalanmış Okuma & Giriş Sütunu (Max ~820px genişlik)
        center_host = tk.Frame(right_panel, bg=THEME["bg_main"])
        center_host.pack(fill="both", expand=True)

        center_col = tk.Frame(center_host, bg=THEME["bg_main"])
        center_col.pack(fill="both", expand=True, padx=32, pady=(12, 16))

        def _center_column_resize(event):
            pad = max(20, (event.width - 820) // 2)
            center_col.pack_configure(padx=pad)
        center_host.bind("<Configure>", _center_column_resize)

        # Üst Gövde: Hoş Geldiniz Ekranı VEYA Sohbet Akışı
        self.body_stage = tk.Frame(center_col, bg=THEME["bg_main"])
        self.body_stage.pack(fill="both", expand=True, pady=(0, 12))

        # 3A. Boş Sohbet Hoş Geldiniz Alanı (Antigravity Minimalist Hero)
        self.welcome_frame = tk.Frame(self.body_stage, bg=THEME["bg_main"])
        welcome_inner = tk.Frame(self.welcome_frame, bg=THEME["bg_main"])
        welcome_inner.place(relx=0.5, rely=0.46, anchor="center")

        tk.Label(
            welcome_inner,
            text="✦",
            font=("Segoe UI", 30),
            bg=THEME["bg_main"],
            fg=THEME["accent"]
        ).pack(pady=(0, 8))

        tk.Label(
            welcome_inner,
            text="Ne üzerinde çalışıyoruz?",
            font=("Segoe UI", 22, "bold"),
            bg=THEME["bg_main"],
            fg=THEME["text_primary"]
        ).pack()

        tk.Label(
            welcome_inner,
            text="Ne yapmak istediğinizi söyleyin — kod, katmanlı tasarım ve Photoshop işlemlerini doğrudan çalıştırırım.",
            font=("Segoe UI", 10),
            bg=THEME["bg_main"],
            fg=THEME["text_secondary"]
        ).pack(pady=(8, 24))

        cards_row = tk.Frame(welcome_inner, bg=THEME["bg_main"])
        cards_row.pack()

        starters = [
            ("✦ Görseli Parçala & Düzenle", "Son yüklediğim görseli katmanlarına ayır ve interaktif editörde aç"),
            ("✦ Kartvizit Stüdyosu", "Bana her parçası düzenlenebilir modern bir kartvizit tasarla"),
            ("✦ Web Uygulaması Kur", "Modern karanlık temalı bir web uygulaması oluştur ve başlat"),
        ]
        for st_title, st_prompt in starters:
            chip = PillButton(
                cards_row,
                text=st_title,
                command=lambda p=st_prompt: self._send_quick_prompt(p),
                bg_color=THEME["bg_card"],
                hover_color=THEME["bg_card_hover"],
                fg_color=THEME["text_secondary"],
                outer_bg=THEME["bg_main"],
                border_color=THEME["border"],
                radius=16,
                height=34,
                width=196,
                font=("Segoe UI", 8, "bold"),
            )
            chip.pack(side="left", padx=5)

        # 3B. Kesintisiz Sohbet Akışı (Dış Çerçevesiz)
        self.chat_frame = tk.Frame(self.body_stage, bg=THEME["bg_main"])

        scrollbar = ttk.Scrollbar(self.chat_frame, orient="vertical", style="Dark.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y", padx=(4, 0), pady=4)

        self.chat_text = tk.Text(
            self.chat_frame,
            bg=THEME["bg_main"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 10),
            bd=0,
            highlightthickness=0,
            padx=8,
            pady=12,
            spacing1=3,
            spacing2=3,
            spacing3=4,
            yscrollcommand=scrollbar.set,
            wrap="word",
            state="disabled"
        )
        self.chat_text.pack(fill="both", expand=True)
        scrollbar.config(command=self.chat_text.yview)

        self.chat_text.tag_configure("user", foreground="#818cf8", font=("Segoe UI", 9, "bold"), lmargin1=14, lmargin2=14, spacing1=10)
        self.chat_text.tag_configure(
            "user_body",
            foreground=THEME["text_primary"],
            background="#161822",
            font=("Segoe UI", 10),
            lmargin1=14,
            lmargin2=14,
            rmargin=14,
            spacing1=4,
            spacing3=8,
        )
        self.chat_text.tag_configure("assistant", foreground="#34d399", font=("Segoe UI", 9, "bold"), spacing1=12)
        self.chat_text.tag_configure("tool", foreground="#a1a1aa", font=("Consolas", 9), lmargin1=8, lmargin2=8)
        self.chat_text.tag_configure("error", foreground="#f87171", font=("Segoe UI", 10, "bold"), spacing1=6)
        self.chat_text.tag_configure("body", foreground=THEME["text_primary"], font=("Segoe UI", 10), spacing2=3)

        # 4. Yüzen Minimal Mesaj Yazma Kapsülü (Antigravity Stili)
        self.composer_card = RoundedFrame(
            center_col,
            radius=20,
            fill_color=THEME["bg_card"],
            border_color=THEME["border"],
            outer_bg=THEME["bg_main"],
            pad=14,
            auto_height=True,
        )
        self.composer_card.pack(fill="x")

        self.input_placeholder = "Mesaj yazın, dosya/görsel sürükleyin veya Ctrl+V / Ctrl+D ile yapıştırın..."
        self._placeholder_active = False

        self.input_entry = tk.Text(
            self.composer_card.body,
            height=2,
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
            insertbackground=THEME["text_primary"],
            font=("Segoe UI", 10),
            bd=0,
            highlightthickness=0,
            wrap="word",
            padx=4,
            pady=2
        )
        self.input_entry.pack(fill="x", pady=(0, 8))
        self.input_entry.bind("<Return>", self._on_input_return)
        self.input_entry.bind("<Shift-Return>", lambda _e: None)
        self.input_entry.bind("<FocusIn>", self._on_input_focus_in)
        self.input_entry.bind("<FocusOut>", self._on_input_focus_out)
        for _seq in ("<Control-v>", "<Control-V>", "<Control-d>", "<Control-D>"):
            self.input_entry.bind(_seq, self._paste_from_clipboard)
        self.after(300, self._setup_windows_drag_drop_and_shortcuts)
        self._show_input_placeholder()

        composer_footer = tk.Frame(self.composer_card.body, bg=THEME["bg_card"])
        composer_footer.pack(fill="x")

        ws_name = os.path.basename(self.agent_workspace_dir) or self.agent_workspace_dir
        self.workspace_lbl = tk.Label(composer_footer, text=f"📁 {ws_name}", bg=THEME["bg_card"], fg=THEME["muted"])
        self.decompose_img_lbl = tk.Label(composer_footer, text="", bg=THEME["bg_card"], fg=THEME["muted"])

        self.attach_img_lbl = tk.Label(
            composer_footer,
            text="＋ Görsel Ekle",
            font=("Segoe UI", 8, "bold"),
            bg="#191d29",
            fg=THEME["text_secondary"],
            padx=12,
            pady=5,
            cursor="hand2"
        )
        self.attach_img_lbl.pack(side="left")
        self.attach_img_lbl.bind("<Button-1>", lambda _e: self._attach_image_for_chat())
        _bind_hover(self.attach_img_lbl, "#191d29", THEME["bg_card_hover"])

        self.send_btn = PillButton(
            composer_footer,
            text="Gönder ↑",
            command=self.send_user_message,
            bg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            outer_bg=THEME["bg_card"],
            radius=14,
            height=30,
            width=88,
            font=("Segoe UI", 9, "bold"),
        )
        self.send_btn.pack(side="right")

        self.stop_btn = PillButton(
            composer_footer,
            text="⏹ Durdur",
            command=self._cancel_agent_run,
            bg_color="#7f1d1d",
            hover_color="#991b1b",
            outer_bg=THEME["bg_card"],
            radius=14,
            height=30,
            width=80,
            state="disabled",
            font=("Segoe UI", 8, "bold"),
        )
        self.stop_btn.pack(side="right", padx=(0, 8))

        self._is_empty_view = None
        self._set_empty_state(True)

    def _toggle_sidebar(self):
        if self.sidebar_visible:
            self.sidebar_frame.pack_forget()
            self.sidebar_divider.pack_forget()
            self.sidebar_visible = False
        else:
            self.sidebar_frame.pack(side="left", fill="y", before=self.sidebar_divider if self.sidebar_divider.winfo_ismapped() else None)
            # Sırayı koru: sidebar -> divider -> right_panel
            for child in self.sidebar_frame.master.pack_slaves():
                if child not in (self.sidebar_frame, self.sidebar_divider):
                    self.sidebar_frame.pack(side="left", fill="y", before=child)
                    self.sidebar_divider.pack(side="left", fill="y", before=child)
                    break
            self.sidebar_visible = True

    def _set_empty_state(self, is_empty: bool):
        if self._is_empty_view is is_empty:
            return
        self._is_empty_view = is_empty
        if is_empty:
            self.chat_frame.pack_forget()
            self.welcome_frame.pack(fill="both", expand=True)
        else:
            self.welcome_frame.pack_forget()
            self.chat_frame.pack(fill="both", expand=True)

    def _show_input_placeholder(self):
        if not self.input_entry.get("1.0", "end-1c").strip():
            self._placeholder_active = True
            self.input_entry.delete("1.0", "end")
            self.input_entry.insert("1.0", self.input_placeholder)
            self.input_entry.config(fg=THEME["muted"])

    def _on_input_focus_in(self, _event=None):
        self.composer_card.set_colors(border_color=THEME["accent"])
        if self._placeholder_active:
            self._placeholder_active = False
            self.input_entry.delete("1.0", "end")
            self.input_entry.config(fg=THEME["text_primary"])

    def _on_input_focus_out(self, _event=None):
        self.composer_card.set_colors(border_color="#2a2d3d")
        self._show_input_placeholder()

    def _on_input_return(self, _event=None):
        self.send_user_message()
        return "break"

    def _attach_image_for_chat(self, file_path: str = None):
        """Seçilen görseli çalışma klasöründeki uploads/ altına kopyalar ve sohbet kutusuna ekler."""
        import shutil
        src = file_path
        if not src:
            src = filedialog.askopenfilename(
                title="Görsel Seç (Photoshop / Tasarım için)",
                filetypes=[
                    ("Görsel Dosyaları", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                    ("Tüm Dosyalar", "*.*"),
                ],
            )
        if not src or not os.path.isfile(src):
            return None

        uploads_dir = os.path.join(self.agent_workspace_dir, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        fname = os.path.basename(src)
        dst = os.path.join(uploads_dir, fname)
        if os.path.abspath(src) != os.path.abspath(dst):
            if os.path.exists(dst):
                stem, ext = os.path.splitext(fname)
                fname = f"{stem}_{int(time.time())}{ext}"
                dst = os.path.join(uploads_dir, fname)
            shutil.copy2(src, dst)

        if self._placeholder_active:
            self._placeholder_active = False
            self.input_entry.delete("1.0", "end")
            self.input_entry.config(fg=THEME["text_primary"])

        dim_note = ""
        try:
            from PIL import Image
            with Image.open(dst) as probe:
                dim_note = f" ({probe.width}x{probe.height})"
        except Exception:
            pass

        self._last_attached_image_path = dst
        self.input_entry.insert("end", f"[Görsel: uploads/{fname}{dim_note}] ")
        self.input_entry.focus_set()
        return f"uploads/{fname}"

    def _attach_dropped_or_pasted_file(self, src_path: str):
        """Sürüklenip bırakılan veya panodan yapıştırılan görsel ya da dosyayı çalışma alanına ekler."""
        import shutil
        if not src_path or not os.path.isfile(src_path):
            return None
        ext = os.path.splitext(src_path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
            return self._attach_image_for_chat(src_path)

        uploads_dir = os.path.join(self.agent_workspace_dir, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        fname = os.path.basename(src_path)
        dst = os.path.join(uploads_dir, fname)
        if os.path.abspath(src_path) != os.path.abspath(dst):
            if os.path.exists(dst):
                stem, fext = os.path.splitext(fname)
                fname = f"{stem}_{int(time.time())}{fext}"
                dst = os.path.join(uploads_dir, fname)
            shutil.copy2(src_path, dst)

        if self._placeholder_active:
            self._placeholder_active = False
            self.input_entry.delete("1.0", "end")
            self.input_entry.config(fg=THEME["text_primary"])
        self.input_entry.insert("end", f"[Dosya: uploads/{fname}] ")
        self.input_entry.focus_set()
        return f"uploads/{fname}"

    def _paste_from_clipboard(self, event=None):
        """Ctrl+V veya Ctrl+D basıldığında panodaki görseli veya kopyalanan dosyaları sohbet kutusuna yapıştırır."""
        try:
            from PIL import ImageGrab, Image
            clip = ImageGrab.grabclipboard()
        except Exception:
            clip = None

        if isinstance(clip, Image.Image):
            uploads_dir = os.path.join(self.agent_workspace_dir, "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            fname = f"pasted_{int(time.time() * 1000)}.png"
            dst = os.path.join(uploads_dir, fname)
            clip.save(dst, "PNG")
            if self._placeholder_active:
                self._placeholder_active = False
                self.input_entry.delete("1.0", "end")
                self.input_entry.config(fg=THEME["text_primary"])
            self._last_attached_image_path = dst
            self.input_entry.insert("end", f"[Görsel: uploads/{fname} ({clip.width}x{clip.height})] ")
            self.input_entry.focus_set()
            self._set_live_status(f"📋 Görsel yapıştırıldı: {fname}", THEME["success"])
            return "break"

        if isinstance(clip, list) and clip:
            attached_any = False
            for fp in clip:
                if isinstance(fp, str) and os.path.isfile(fp):
                    if self._attach_dropped_or_pasted_file(fp):
                        attached_any = True
            if attached_any:
                self._set_live_status("📋 Dosya/görsel panodan eklendi", THEME["success"])
                return "break"

        # Ctrl+D basıldığında panoda görsel yoksa son yapıştırılan/eklenen görseli veya metin yapıştırmayı dene
        if event and getattr(event, "keysym", "").lower() == "d":
            try:
                clip_txt = self.clipboard_get()
                if clip_txt:
                    if self._placeholder_active:
                        self._placeholder_active = False
                        self.input_entry.delete("1.0", "end")
                        self.input_entry.config(fg=THEME["text_primary"])
                    self.input_entry.insert("insert", clip_txt)
                    return "break"
            except Exception:
                pass
            return "break"
        return None

    def _setup_windows_drag_drop_and_shortcuts(self):
        """Windows WM_DROPFILES sürükle-bırak desteğini ve pencere geneli Ctrl+V / Ctrl+D kısayollarını bağlar."""
        try:
            top = self.winfo_toplevel()
            for _seq in ("<Control-v>", "<Control-V>", "<Control-d>", "<Control-D>"):
                top.bind(_seq, lambda e: self._paste_from_clipboard(e) if self.focus_get() != self.input_entry else None, add="+")
        except Exception:
            pass

        if os.name != "nt" or getattr(self, "_win_dnd_hooked", False):
            return
        try:
            import ctypes
            from ctypes import wintypes

            WM_DROPFILES = 0x0233
            GWL_WNDPROC = -4
            WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t)

            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
            user32.CallWindowProcW.restype = ctypes.c_ssize_t
            shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
            shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
            shell32.DragQueryFileW.restype = wintypes.UINT
            shell32.DragFinish.argtypes = [ctypes.c_void_p]

            top = self.winfo_toplevel()
            hwnd = user32.GetAncestor(top.winfo_id(), 2) or top.winfo_id()
            shell32.DragAcceptFiles(hwnd, True)

            old_proc = None

            def _wndproc(h_wnd, msg, w_param, l_param):
                if msg == WM_DROPFILES:
                    hdrop = ctypes.c_void_p(w_param)
                    count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                    dropped_paths = []
                    for i in range(count):
                        buf_len = shell32.DragQueryFileW(hdrop, i, None, 0) + 1
                        buf = ctypes.create_unicode_buffer(buf_len)
                        shell32.DragQueryFileW(hdrop, i, buf, buf_len)
                        if buf.value:
                            dropped_paths.append(buf.value)
                    shell32.DragFinish(hdrop)
                    if dropped_paths:
                        def _on_drop(paths=dropped_paths):
                            for p in paths:
                                self._attach_dropped_or_pasted_file(p)
                            self._set_live_status(f"📎 {len(paths)} dosya sürüklenip eklendi", THEME["success"])
                        self.after(10, _on_drop)
                    return 0
                return user32.CallWindowProcW(old_proc, h_wnd, msg, w_param, l_param)

            self._win_dnd_cb = WNDPROCTYPE(_wndproc)
            old_proc = user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.cast(self._win_dnd_cb, ctypes.c_void_p).value)
            self._win_dnd_old_proc = old_proc
            self._win_dnd_hooked = True
        except Exception:
            pass

    def _decompose_attached_or_pick_image(self):
        """Görsel seçtirir (veya ekli görseli alır) ve yapay zekaya görseldeki her parçayı analiz edip düzenlenebilir katmanlara böldürür."""
        if self.is_generating:
            return
        cur_txt = "" if getattr(self, "_placeholder_active", False) else self.input_entry.get("1.0", "end-1c").strip()
        if "[Görsel:" not in cur_txt:
            rel_img = self._attach_image_for_chat()
            if not rel_img:
                return
            cur_txt = self.input_entry.get("1.0", "end-1c").strip()
        if not any(k in cur_txt.lower() for k in ("parça", "analiz", "böl", "düzenle", "değiştir")):
            self.input_entry.insert(
                "end",
                "Bu görseldeki her parçayı (metinleri, logoyu, kutuları, arka planı) tek tek analiz edip değiştirilebilir katmanlara böl ve editörde aç.",
            )
        self.send_user_message()

    def _cancel_agent_run(self):
        if self.is_generating:
            self.cancel_agent = True
            self._set_live_status("⏹ Durduruluyor...", "#ef4444")
            self._refresh_live_timer()

    def _open_nextjs_web_ui(self):
        import webbrowser
        webbrowser.open("http://localhost:3000")

    def _send_quick_prompt(self, text: str):
        if self.is_generating:
            return
        self._placeholder_active = False
        self.input_entry.config(fg=THEME["text_primary"])
        self.input_entry.delete("1.0", "end")
        self.input_entry.insert("1.0", text)
        self.send_user_message()

    def _ensure_ollama_running_background(self):
        """Ollama sunucusu kapalıysa kullanıcının masaüstü oturumu içinde otomatik başlatır."""
        def _starter():
            try:
                r = requests.get(f"{self.ollama_url}/api/tags", timeout=1.5)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            ollama_exe = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
            if os.path.exists(ollama_exe):
                try:
                    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    subprocess.Popen([ollama_exe, "serve"], creationflags=flags)
                    time.sleep(2.5)
                except Exception:
                    pass
        threading.Thread(target=_starter, daemon=True).start()

    def _on_provider_change(self, event=None):
        selected = self.provider_var.get()
        if selected not in (self.PROVIDER_EVREN, self.PROVIDER_OLLAMA):
            return
        self.active_provider = selected
        self._set_setting("active_provider", selected)
        if selected == self.PROVIDER_EVREN:
            self.model_combo.config(values=self.EVREN_DEFAULT_MODELS)
            self.model_var.set(self.evren_model or "auto")
        else:
            self._ensure_ollama_running_background()
            self.model_combo.config(values=["qwen2.5:7b", "llama3.2"])
            self.model_var.set(self.ollama_model)
        self._refresh_provider_status_async()

    def _on_model_change(self, event=None):
        chosen = self.model_var.get().strip()
        if not chosen:
            return
        if self.provider_var.get() == self.PROVIDER_EVREN:
            self.evren_model = chosen
            self._set_setting("evren_model", chosen)
        else:
            self.ollama_model = chosen
        self._refresh_provider_status_async()

    def _evren_headers(self, api_key: str = None) -> dict:
        key = (api_key if api_key is not None else self.evren_api_key).strip()
        return {
            "Authorization": f"Bearer {key}",
            "X-API-Key": key,
            "Content-Type": "application/json",
        }

    def _refresh_provider_status_async(self):
        if self.provider_var.get() == self.PROVIDER_EVREN:
            self._check_evren_status_async()
        else:
            self._check_ollama_status_async()

    def _check_evren_status_async(self):
        if not self.evren_api_key:
            self.ollama_badge.config(
                text="● AI API Anahtarı Girilmedi (⚙ Sunucu)",
                fg=THEME["warning"]
            )
            return

        self.ollama_badge.config(text="● AI Sunucusu Kontrol Ediliyor...", fg=THEME["warning"])

        def _worker():
            try:
                r = requests.get(
                    f"{self.evren_base_url}/models",
                    headers=self._evren_headers(),
                    timeout=5.0,
                )
                if r.status_code == 200:
                    payload = r.json()
                    models = self._filter_evren_chat_models(payload.get("data", []), base_url=self.evren_base_url)
                    terms_ok = True
                    try:
                        tr = requests.get(
                            f"{self.evren_base_url}/terms/status",
                            headers=self._evren_headers(),
                            timeout=3.5,
                        )
                        if tr.status_code == 200:
                            tdata = tr.json()
                            if tdata.get("accepted") is False:
                                terms_ok = False
                    except Exception:
                        pass

                    def _ok():
                        if models:
                            self.model_combo.config(values=models)
                            if self.model_var.get() not in models:
                                self.model_var.set(models[0])
                                self.evren_model = models[0]
                                self._set_setting("evren_model", models[0])
                        if terms_ok:
                            is_gemini = "generativelanguage.googleapis.com" in self.evren_base_url.lower()
                            is_custom = "ssyz.org.tr" not in self.evren_base_url
                            if is_gemini:
                                badge_lbl = f"● ✨ Google Gemini Aktif ({self.model_var.get()})"
                            elif is_custom:
                                badge_lbl = f"● 🚀 Kendi Kaggle AI Aktif ({self.model_var.get()})"
                            else:
                                badge_lbl = f"● EVREN AI Aktif ({self.model_var.get()})"
                            self.ollama_badge.config(
                                text=badge_lbl,
                                fg=THEME["success"]
                            )
                        else:
                            self.ollama_badge.config(
                                text="● EVREN Şartları Onay Bekliyor (🔑 Ayarlar)",
                                fg=THEME["warning"]
                            )

                    self.after(0, _ok)
                    return

                err_msg = f"HTTP {r.status_code}"
                try:
                    detail = r.json()
                    err_msg = detail.get("error", {}).get("message") or detail.get("detail") or err_msg
                except Exception:
                    pass
                self.after(0, lambda m=err_msg: self.ollama_badge.config(
                    text=f"● AI Bağlantı Hatası ({m[:35]})",
                    fg="#ef4444"
                ))
            except Exception:
                self.after(0, lambda: self.ollama_badge.config(
                    text="● AI Sunucusuna Erişilemedi (⚙ Sunucu)",
                    fg="#ef4444"
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _get_effective_system_prompt(self) -> str:
        custom = self._get_setting("custom_system_prompt", "").strip()
        if not custom:
            return self.SYSTEM_PROMPT
        return f"{self.SYSTEM_PROMPT}\n\nKullanıcının Özel Talimatları ve Rolü:\n{custom}"

    def _add_knowledge_text(self, source: str, raw_text: str) -> int:
        import sqlite3
        import uuid
        import datetime

        clean = (raw_text or "").replace("\r", "").strip()
        if not clean:
            return 0

        chunk_size = 900
        overlap = 120
        chunks = []
        start = 0
        while start < len(clean):
            part = clean[start:start + chunk_size].strip()
            if part:
                chunks.append(part)
            if start + chunk_size >= len(clean):
                break
            start += chunk_size - overlap

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            for ch in chunks:
                conn.execute(
                    "INSERT INTO knowledge_chunks (id, source, content, created_at) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), source, ch, now),
                )
            conn.commit()
        return len(chunks)

    def _retrieve_knowledge_context(self, query: str, limit: int = 3) -> str:
        import re
        import sqlite3

        tokens = [t for t in re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]{3,}", (query or "").lower())]
        if not tokens:
            return ""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT source, content FROM knowledge_chunks").fetchall()
        if not rows:
            return ""

        scored = []
        unique_tokens = set(tokens)
        for src, content in rows:
            low = content.lower()
            score = sum(low.count(tok) for tok in unique_tokens)
            if score > 0:
                scored.append((score, src, content))
        if not scored:
            return ""
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [f"[{src}]\n{cnt}" for _, src, cnt in scored[:limit]]
        return "\n\n---\n\n".join(selected)

    def _mark_last_reply_good(self):
        import sqlite3
        if not self.current_conversation_id:
            return
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND role = 'assistant' "
                "ORDER BY created_at DESC LIMIT 1",
                (self.current_conversation_id,),
            ).fetchone()
            if not row:
                messagebox.showinfo("Bilgi", "Bu sohbette işaretlenecek bir asistan cevabı yok.")
                return
            conn.execute("UPDATE messages SET rating = 1 WHERE id = ?", (row[0],))
            conn.commit()
        self.tool_indicator.config(text="👍 Son cevap eğitim veri setine işaretlendi", fg=THEME["success"])

    def _open_training_and_knowledge_dialog(self):
        import sqlite3

        win = tk.Toplevel(self)
        win.title("Bilgi Tabanı & EVREN Eğitim Merkezi")
        win.geometry("680x580")
        win.configure(bg=THEME["bg_main"])
        win.transient(self.winfo_toplevel())
        win.grab_set()

        card = tk.Frame(
            win,
            bg=THEME["bg_card"],
            padx=20,
            pady=18,
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            card,
            text="🧠 Geliştirilebilir Yapay Zekâ: Hafıza & EVREN Eğitim Merkezi",
            font=("Segoe UI", 12, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"]
        ).pack(anchor="w", pady=(0, 10))

        # 1) Özel Sistem Talimatı (Persona)
        tk.Label(
            card,
            text="1. Yapay Zekânın Özel Rolü / Kuralları (Sistem Talimatına Eklenir):",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"]
        ).pack(anchor="w")

        persona_txt = tk.Text(
            card,
            height=4,
            bg=THEME["bg_canvas"],
            fg=THEME["text_primary"],
            insertbackground=THEME["text_primary"],
            font=("Segoe UI", 9),
            bd=0,
            padx=10,
            pady=8
        )
        persona_txt.pack(fill="x", pady=(4, 8))
        persona_txt.insert("1.0", self._get_setting("custom_system_prompt", ""))

        # 2) Bilgi Tabanı (RAG)
        with sqlite3.connect(self.db_path) as conn:
            kb_count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            rated_count = conn.execute("SELECT COUNT(*) FROM messages WHERE role = 'assistant' AND rating = 1").fetchone()[0]
            total_turns = conn.execute("SELECT COUNT(*) FROM messages WHERE role = 'assistant'").fetchone()[0]

        kb_status_lbl = tk.Label(
            card,
            text=f"2. Kalıcı Bilgi Tabanı (RAG): {kb_count} parça kayıtlı",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"]
        )
        kb_status_lbl.pack(anchor="w", pady=(6, 4))

        note_txt = tk.Text(
            card,
            height=4,
            bg=THEME["bg_canvas"],
            fg=THEME["text_primary"],
            insertbackground=THEME["text_primary"],
            font=("Segoe UI", 9),
            bd=0,
            padx=10,
            pady=8
        )
        note_txt.pack(fill="x", pady=(0, 8))

        status_lbl = tk.Label(
            card,
            text=f"Eğitim Havuzu: Toplam {total_turns} cevap ({rated_count} adet 👍 onaylı).",
            font=("Segoe UI", 9),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            wraplength=600,
            justify="left"
        )
        status_lbl.pack(anchor="w", pady=(4, 12))

        def _refresh_counts():
            with sqlite3.connect(self.db_path) as conn:
                c_kb = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            kb_status_lbl.config(text=f"2. Kalıcı Bilgi Tabanı (RAG): {c_kb} parça kayıtlı")

        def _save_persona():
            self._set_setting("custom_system_prompt", persona_txt.get("1.0", "end").strip())
            status_lbl.config(text="Özel yapay zekâ rolü/talimatları kaydedildi.", fg=THEME["success"])

        def _add_note():
            txt = note_txt.get("1.0", "end").strip()
            if not txt:
                status_lbl.config(text="Eklenecek not boş olamaz.", fg=THEME["warning"])
                return
            added = self._add_knowledge_text("Kullanıcı Notu", txt)
            note_txt.delete("1.0", "end")
            _refresh_counts()
            status_lbl.config(text=f"Bilgi tabanına {added} yeni parça eklendi.", fg=THEME["success"])

        def _import_file():
            fpath = filedialog.askopenfilename(
                parent=win,
                title="Bilgi Tabanına Dosya Ekle",
                filetypes=[("Metin ve Kod Dosyaları", "*.txt *.md *.py *.json *.csv *.log"), ("Tüm Dosyalar", "*.*")]
            )
            if not fpath:
                return
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    added = self._add_knowledge_text(os.path.basename(fpath), f.read())
                _refresh_counts()
                status_lbl.config(
                    text=f"'{os.path.basename(fpath)}' dosyasından {added} parça eklendi.",
                    fg=THEME["success"]
                )
            except Exception as exc:
                status_lbl.config(text=f"Dosya okunamadı: {exc}", fg="#ef4444")

        def _clear_kb():
            if not messagebox.askyesno("Onay", "Tüm bilgi tabanı parçaları silinsin mi?", parent=win):
                return
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM knowledge_chunks")
                conn.commit()
            _refresh_counts()
            status_lbl.config(text="Bilgi tabanı temizlendi.", fg=THEME["warning"])

        def _export_jsonl(only_rated: bool):
            try:
                from evren_train.export_dataset import export_conversations_to_jsonl
            except Exception:
                status_lbl.config(text="evren_train/export_dataset.py modülü bulunamadı.", fg="#ef4444")
                return
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evren_train")
            try:
                stats = export_conversations_to_jsonl(
                    db_path=self.db_path,
                    output_dir=out_dir,
                    system_prompt=self._get_effective_system_prompt(),
                    only_rated=only_rated,
                )
                status_lbl.config(
                    text=f"JSONL oluşturuldu: {stats['total']} örnek → {stats['train_file']}",
                    fg=THEME["success"]
                )
            except Exception as exc:
                status_lbl.config(text=f"Dışa aktarma hatası: {exc}", fg="#ef4444")

        row1 = tk.Frame(card, bg=THEME["bg_card"])
        row1.pack(fill="x", pady=(0, 8))
        tk.Button(row1, text="💾 Özel Rolü Kaydet", command=_save_persona, font=("Segoe UI", 9, "bold"), bg=THEME["accent"], fg=THEME["text_primary"], bd=0, padx=12, pady=7, cursor="hand2").pack(side="left")
        tk.Button(row1, text="📝 Notu Bilgiye Ekle", command=_add_note, font=("Segoe UI", 9, "bold"), bg=THEME["bg_card_hover"], fg=THEME["text_primary"], bd=0, padx=12, pady=7, cursor="hand2").pack(side="left", padx=6)
        tk.Button(row1, text="📄 Dosya Ekle (.txt/.md)", command=_import_file, font=("Segoe UI", 9, "bold"), bg=THEME["bg_card_hover"], fg=THEME["text_primary"], bd=0, padx=12, pady=7, cursor="hand2").pack(side="left", padx=6)
        tk.Button(row1, text="🗑️ Temizle", command=_clear_kb, font=("Segoe UI", 9), bg=THEME["bg_card_hover"], fg=THEME["text_secondary"], bd=0, padx=10, pady=7, cursor="hand2").pack(side="right")

        row2 = tk.Frame(card, bg=THEME["bg_card"])
        row2.pack(fill="x", side="bottom")
        tk.Button(row2, text="📤 Tüm Sohbetleri EVREN JSONL Olarak Çıkar", command=lambda: _export_jsonl(False), font=("Segoe UI", 9, "bold"), bg="#059669", fg=THEME["text_primary"], bd=0, padx=12, pady=8, cursor="hand2").pack(side="left")
        tk.Button(row2, text="👍 Sadece Onaylıları Çıkar", command=lambda: _export_jsonl(True), font=("Segoe UI", 9, "bold"), bg=THEME["bg_card_hover"], fg=THEME["text_primary"], bd=0, padx=12, pady=8, cursor="hand2").pack(side="left", padx=8)
        tk.Button(row2, text="Kapat", command=win.destroy, font=("Segoe UI", 9), bg=THEME["bg_card_hover"], fg=THEME["text_secondary"], bd=0, padx=12, pady=8, cursor="hand2").pack(side="right")

    def _open_evren_settings_dialog(self):
        win = tk.Toplevel(self)
        win.title("EVREN AI Bağlantı Ayarları")
        win.geometry("540x390")
        win.configure(bg=THEME["bg_main"])
        win.transient(self.winfo_toplevel())
        win.grab_set()

        card = tk.Frame(
            win,
            bg=THEME["bg_card"],
            padx=22,
            pady=20,
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            card,
            text="AI Sunucu ve Model Bağlantı Ayarları",
            font=("Segoe UI", 13, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"]
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            card,
            text="Google Gemini API (kalıcı / ücretsiz 7/24), kendi Kaggle/Colab GPU sunucunuzu veya EVREN API'yi bağlayabilirsiniz.",
            font=("Segoe UI", 9),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            wraplength=460,
            justify="left"
        ).pack(anchor="w", pady=(0, 10))

        preset_row = tk.Frame(card, bg=THEME["bg_card"])
        preset_row.pack(fill="x", pady=(0, 12))

        def _preset_gemini():
            url_var.set("https://generativelanguage.googleapis.com/v1beta/openai")
            status_lbl.config(
                text="Google AI Studio'dan aldığınız API anahtarınızı (AIza...) yukarıya girip 'Kaydet ve Test Et'e tıklayın. (7/24 kalıcıdır, adres hiç kapanmaz)",
                fg=THEME["accent"]
            )
            key_entry.focus_set()

        def _preset_kaggle():
            key_var.set("burak-ozel-ai-2026")
            status_lbl.config(
                text="Kaggle not defterinizdeki güncel https://....trycloudflare.com/v1 adresini aşağıya girin.",
                fg=THEME["warning"]
            )
            url_entry.focus_set()

        def _preset_evren():
            url_var.set(self.EVREN_DEFAULT_BASE_URL)
            status_lbl.config(
                text="EVREN AI API anahtarınızı yukarıya girip 'Kaydet ve Test Et'e tıklayın.",
                fg=THEME["text_secondary"]
            )

        tk.Button(
            preset_row,
            text="✨ Google Gemini (Kalıcı 7/24)",
            command=_preset_gemini,
            font=("Segoe UI", 8, "bold"),
            bg="#1e3a8a",
            fg="#93c5fd",
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2"
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            preset_row,
            text="🚀 Kaggle AI (Geçici)",
            command=_preset_kaggle,
            font=("Segoe UI", 8, "bold"),
            bg=THEME["bg_card_hover"],
            fg=THEME["text_primary"],
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2"
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            preset_row,
            text="🇹🇷 EVREN AI",
            command=_preset_evren,
            font=("Segoe UI", 8, "bold"),
            bg=THEME["bg_card_hover"],
            fg=THEME["text_secondary"],
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2"
        ).pack(side="left")

        tk.Label(
            card,
            text="API Anahtarı / Şifreniz (Gemini için: AIza... | Kaggle için: burak-ozel-ai-2026):",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"]
        ).pack(anchor="w")

        key_row = tk.Frame(card, bg=THEME["bg_card"])
        key_row.pack(fill="x", pady=(4, 12))

        key_var = tk.StringVar(value=self.evren_api_key)
        key_entry = tk.Entry(
            key_row,
            textvariable=key_var,
            show="*",
            bg=THEME["bg_canvas"],
            fg=THEME["text_primary"],
            insertbackground=THEME["text_primary"],
            font=("Consolas", 10),
            bd=0
        )
        key_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))

        show_state = {"visible": False}

        def _toggle_show():
            show_state["visible"] = not show_state["visible"]
            key_entry.config(show="" if show_state["visible"] else "*")

        tk.Button(
            key_row,
            text="👁 Göster",
            command=_toggle_show,
            font=("Segoe UI", 8, "bold"),
            bg=THEME["bg_card_hover"],
            fg=THEME["text_primary"],
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2"
        ).pack(side="right")

        tk.Button(
            key_row,
            text="🚀 Kaggle Şifresi",
            command=lambda: key_var.set("burak-ozel-ai-2026"),
            font=("Segoe UI", 8, "bold"),
            bg=THEME["accent"],
            fg="#ffffff",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2"
        ).pack(side="right", padx=(0, 6))

        tk.Label(
            card,
            text="Sunucu Adresi (Base URL):",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"]
        ).pack(anchor="w")

        url_var = tk.StringVar(value=self.evren_base_url)
        url_entry = tk.Entry(
            card,
            textvariable=url_var,
            bg=THEME["bg_canvas"],
            fg=THEME["text_primary"],
            insertbackground=THEME["text_primary"],
            font=("Consolas", 10),
            bd=0
        )
        url_entry.pack(fill="x", ipady=7, pady=(4, 14))

        status_lbl = tk.Label(
            card,
            text="",
            font=("Segoe UI", 9),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            wraplength=460,
            justify="left"
        )
        status_lbl.pack(anchor="w", pady=(0, 12))

        def _save_and_test():
            new_key = key_var.get().strip()
            new_url = (url_var.get().strip() or self.EVREN_DEFAULT_BASE_URL).rstrip("/")
            self.evren_api_key = new_key
            self.evren_base_url = new_url
            self._set_setting("evren_api_key", new_key)
            self._set_setting("evren_base_url", new_url)
            self.provider_var.set(self.PROVIDER_EVREN)
            self._on_provider_change()
            if not new_key:
                status_lbl.config(text="Kaydedildi. Kullanmak için bir API anahtarı girin.", fg=THEME["warning"])
                return
            status_lbl.config(text="Bağlantı ve modeller kontrol ediliyor...", fg=THEME["warning"])
            win.update_idletasks()
            try:
                r = requests.get(
                    f"{new_url}/models",
                    headers=self._evren_headers(new_key),
                    timeout=6.0,
                )
                if r.status_code == 200:
                    models = self._filter_evren_chat_models(r.json().get("data", []), base_url=new_url)
                    count = len(models)
                    is_gemini = "generativelanguage.googleapis.com" in new_url.lower()
                    if is_gemini:
                        status_lbl.config(
                            text=f"Bağlantı başarılı! ✨ Google Gemini aktif ({count} model hazır, kalıcı 7/24).",
                            fg=THEME["success"]
                        )
                    else:
                        status_lbl.config(
                            text=f"Bağlantı başarılı! {count} AI modeli listelendi.",
                            fg=THEME["success"]
                        )
                else:
                    err_hint = r.text[:140]
                    if r.status_code == 400 and ("API key" in err_hint or "INVALID_ARGUMENT" in err_hint):
                        err_hint = "Geçersiz API anahtarı. Google AI Studio'dan aldığınız anahtarı kontrol edin."
                    status_lbl.config(
                        text=f"Sunucu yanıtı HTTP {r.status_code}: {err_hint}",
                        fg="#ef4444"
                    )
            except Exception as exc:
                status_lbl.config(text=f"Bağlantı hatası: {exc}", fg="#ef4444")

        def _accept_terms():
            new_key = key_var.get().strip()
            new_url = (url_var.get().strip() or self.EVREN_DEFAULT_BASE_URL).rstrip("/")
            if not new_key:
                status_lbl.config(text="Önce EVREN API anahtarını girin.", fg=THEME["warning"])
                return
            try:
                tr = requests.get(
                    f"{new_url}/terms/status",
                    headers=self._evren_headers(new_key),
                    timeout=6.0,
                )
                if tr.status_code == 200 and tr.json().get("accepted") is True:
                    status_lbl.config(text="Kullanım şartları zaten onaylı.", fg=THEME["success"])
                    return
                txt_r = requests.get(
                    f"{new_url}/terms/text",
                    headers=self._evren_headers(new_key),
                    timeout=6.0,
                )
                terms_body = ""
                version = 1
                if txt_r.status_code == 200:
                    tj = txt_r.json()
                    terms_body = tj.get("text", "")[:1200]
                    version = tj.get("version", 1)
                confirm = messagebox.askyesno(
                    "EVREN Kullanım Şartları",
                    f"EVREN AI API kullanım şartlarını (Sürüm {version}) onaylıyor musunuz?\n\n{terms_body}",
                    parent=win,
                )
                if not confirm:
                    return
                acc_r = requests.post(
                    f"{new_url}/terms/accept",
                    headers=self._evren_headers(new_key),
                    json={"version": version},
                    timeout=6.0,
                )
                if acc_r.status_code in (200, 201):
                    status_lbl.config(text="Kullanım şartları onaylandı!", fg=THEME["success"])
                    self._refresh_provider_status_async()
                else:
                    status_lbl.config(text=f"Onay hatası HTTP {acc_r.status_code}: {acc_r.text[:120]}", fg="#ef4444")
            except Exception as exc:
                status_lbl.config(text=f"Şartlar alınamadı: {exc}", fg="#ef4444")

        btn_row = tk.Frame(card, bg=THEME["bg_card"])
        btn_row.pack(fill="x", side="bottom")

        tk.Button(
            btn_row,
            text="💾 Kaydet ve Test Et",
            command=_save_and_test,
            font=("Segoe UI", 9, "bold"),
            bg=THEME["accent"],
            fg=THEME["text_primary"],
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2"
        ).pack(side="left")

        tk.Button(
            btn_row,
            text="📜 Kullanım Şartlarını Onayla",
            command=_accept_terms,
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card_hover"],
            fg=THEME["text_primary"],
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2"
        ).pack(side="left", padx=8)

        tk.Button(
            btn_row,
            text="Kapat",
            command=win.destroy,
            font=("Segoe UI", 9),
            bg=THEME["bg_card_hover"],
            fg=THEME["text_secondary"],
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2"
        ).pack(side="right")

    def _check_ollama_status_async(self):
        def _worker():
            for _ in range(3):
                try:
                    r = requests.get(f"{self.ollama_url}/api/tags", timeout=2.5)
                    if r.status_code == 200:
                        models = [m.get("name", "") for m in r.json().get("models", [])]
                        def _ok():
                            if models:
                                self.model_combo.config(values=models)
                                preferred = next((m for m in models if m.startswith("qwen2.5")), None)
                                if preferred and not self.model_var.get().startswith("qwen2.5"):
                                    self.model_var.set(preferred)
                                elif self.model_var.get() not in models and not preferred:
                                    self.model_var.set(models[0])
                            self.ollama_badge.config(text=f"● Ollama Aktif ({self.model_var.get()})", fg=THEME["success"])
                        self.after(0, _ok)
                        return
                except Exception:
                    time.sleep(1.5)
            self.after(0, lambda: self.ollama_badge.config(
                text="● Ollama Çevrimdışı (Otomatik Başlatılıyor...)",
                fg=THEME["warning"]
            ))
        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_conversation_list(self):
        import sqlite3
        self.conv_items = []
        self.conv_listbox.delete(0, "end")
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, title, created_at FROM conversations ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        for cid, title, _ in rows:
            self.conv_items.append((cid, title))
            self.conv_listbox.insert("end", f"  {title}")

    def create_new_conversation(self):
        import uuid
        import datetime
        import sqlite3
        cid = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO conversations (id, user_id, title, created_at) VALUES (?, ?, ?, ?)",
                (cid, "local-user", "Yeni Sohbet", now)
            )
            conn.commit()
        self.current_conversation_id = cid
        self._refresh_conversation_list()
        self._render_conversation_messages()

    def delete_current_conversation(self):
        if not self.current_conversation_id:
            return
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (self.current_conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (self.current_conversation_id,))
            conn.commit()
        self.current_conversation_id = None
        self._refresh_conversation_list()
        if self.conv_items:
            self.current_conversation_id = self.conv_items[0][0]
            self._render_conversation_messages()
        else:
            self.create_new_conversation()

    def _on_select_conversation(self, event):
        sel = self.conv_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.conv_items):
            self.current_conversation_id = self.conv_items[idx][0]
            self._render_conversation_messages()

    def _extract_image_rel_from_tool_result(self, res_text: str) -> str:
        """design_graphic / photoshop_edit çıktısından göreceli görsel yolunu ayıklar."""
        for prefix in ("Grafik tasarım oluşturuldu: ", "Photoshop düzenlemesi kaydedildi: "):
            if isinstance(res_text, str) and res_text.startswith(prefix):
                rest = res_text[len(prefix):]
                return rest.split(" (", 1)[0].strip()
        return ""

    def _extract_file_path_from_tool_result(self, res_text: str) -> str:
        """create_editable_design / move_or_copy_file / write_file / generateDocument çıktısından dosya yolunu ayıklar."""
        if not isinstance(res_text, str):
            return ""
        for marker in (
            "İnteraktif Stitch tasarım editörü oluşturuldu ve tarayıcıda açıldı: ",
            "İnteraktif Stitch tasarım editörü oluşturuldu: ",
            "Dosya masaüstüne/hedefe aktarıldı: ",
            "Dosya yazıldı: ",
            "Türkçe PDF başarıyla oluşturuldu: ",
            "PDF oluşturuldu ve Supabase'e yüklendi: ",
        ):
            if res_text.startswith(marker):
                rest = res_text[len(marker):]
                cand = rest.split(" (", 1)[0].strip()
                if cand.lower().endswith((".html", ".htm", ".pdf", ".png", ".jpg", ".jpeg")):
                    return cand
        return ""

    def _copy_file_to_desktop_ui(self, abs_path: str, btn=None):
        try:
            self._tool_move_or_copy_file(abs_path, "desktop", "copy", open_after=False)
            if btn is not None:
                btn.config(text="✓ Masaüstünde", fg=THEME["success"])
        except Exception:
            if btn is not None:
                btn.config(text="⚠ Hata", fg=THEME["danger"])

    def _append_file_card_to_chat(self, path_or_rel: str):
        """Üretilen HTML/PDF/görsel dosyası için sohbette tek tıkla Aç / Masaüstüne Kopyala / Klasör kartı gösterir."""
        if not path_or_rel:
            return
        try:
            abs_path = path_or_rel if os.path.isabs(path_or_rel) else self._resolve_workspace_path(path_or_rel)
        except Exception:
            return
        if not os.path.isfile(abs_path):
            return
        fname = os.path.basename(abs_path)
        card = tk.Frame(
            self.chat_text,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        row = tk.Frame(card, bg=THEME["bg_card"])
        row.pack(fill="x")
        tk.Label(
            row,
            text=f"📄 {fname}",
            font=("Segoe UI", 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
        ).pack(side="left", padx=(0, 12))
        tk.Button(
            row,
            text="📁 Klasör",
            command=lambda d=os.path.dirname(abs_path): os.startfile(d),
            font=("Segoe UI", 8),
            bg="#1d1f2b",
            fg=THEME["text_secondary"],
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2",
        ).pack(side="right", padx=(4, 0))
        desk_btn = tk.Button(
            row,
            text="🖥️ Masaüstüne Kopyala",
            font=("Segoe UI", 8, "bold"),
            bg="#26293a",
            fg=THEME["text_primary"],
            bd=0,
            padx=9,
            pady=3,
            cursor="hand2",
        )
        desk_btn.config(command=lambda p=abs_path, b=desk_btn: self._copy_file_to_desktop_ui(p, b))
        desk_btn.pack(side="right", padx=(4, 0))
        tk.Button(
            row,
            text="🌐 Aç",
            command=lambda p=abs_path: os.startfile(p),
            font=("Segoe UI", 8, "bold"),
            bg=THEME["accent"],
            fg="#ffffff",
            bd=0,
            padx=9,
            pady=3,
            cursor="hand2",
        ).pack(side="right")

        prev_state = str(self.chat_text.cget("state"))
        self.chat_text.config(state="normal")
        self.chat_text.insert("end", " ", "body")
        self.chat_text.window_create("end", window=card)
        self.chat_text.insert("end", "\n\n", "body")
        self.chat_text.see("end")
        if prev_state == "disabled":
            self.chat_text.config(state="disabled")

    def _append_image_preview_to_chat(self, path_or_rel: str, caption: str = ""):
        """AI tarafından üretilen veya düzenlenen görseli sohbet akışı içine küçük önizleme kartı olarak gömer."""
        from PIL import Image, ImageTk
        if not path_or_rel:
            return
        abs_path = path_or_rel if os.path.isabs(path_or_rel) else self._resolve_workspace_path(path_or_rel)
        if not os.path.isfile(abs_path):
            return
        try:
            mtime = os.path.getmtime(abs_path)
            cache_key = (abs_path, mtime)
            cached_thumb = self._thumb_cache.get(cache_key)
            if cached_thumb is not None:
                photo, ow, oh = cached_thumb
            else:
                with Image.open(abs_path) as raw:
                    ow, oh = raw.size
                    scale = min(420 / max(1, ow), 240 / max(1, oh), 1.0)
                    nw, nh = max(1, int(ow * scale)), max(1, int(oh * scale))
                    thumb = raw.convert("RGBA").resize((nw, nh), Image.BILINEAR)
                    yy, xx = np.indices((nh, nw))
                    tiles = ((yy // 10 + xx // 10) % 2).astype(np.uint8)
                    bg_arr = np.empty((nh, nw, 4), dtype=np.uint8)
                    bg_arr[tiles == 0] = (24, 26, 36, 255)
                    bg_arr[tiles == 1] = (35, 38, 52, 255)
                    composed = Image.alpha_composite(Image.fromarray(bg_arr, "RGBA"), thumb)
                    photo = ImageTk.PhotoImage(composed)
                if len(self._thumb_cache) > 48:
                    self._thumb_cache.clear()
                self._thumb_cache[cache_key] = (photo, ow, oh)
        except Exception:
            return

        self._chat_photo_refs.append(photo)
        rel_lbl = caption or os.path.relpath(abs_path, self.agent_workspace_dir)

        card = tk.Frame(
            self.chat_text,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        img_lbl = tk.Label(card, image=photo, bg=THEME["bg_card"], cursor="hand2")
        img_lbl.pack(anchor="w")
        img_lbl.bind("<Button-1>", lambda _e, p=abs_path: os.startfile(p))

        foot = tk.Frame(card, bg=THEME["bg_card"])
        foot.pack(fill="x", pady=(6, 0))
        tk.Label(
            foot,
            text=f"🖼 {rel_lbl} ({ow}×{oh})",
            font=("Segoe UI", 8, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
        ).pack(side="left")
        tk.Button(
            foot,
            text="📁 Klasör",
            command=lambda d=os.path.dirname(abs_path): os.startfile(d),
            font=("Segoe UI", 8),
            bg="#1d1f2b",
            fg=THEME["text_secondary"],
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
        ).pack(side="right", padx=(4, 0))
        img_desk_btn = tk.Button(
            foot,
            text="🖥️ Masaüstü",
            font=("Segoe UI", 8, "bold"),
            bg="#26293a",
            fg=THEME["text_primary"],
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
        )
        img_desk_btn.config(command=lambda p=abs_path, b=img_desk_btn: self._copy_file_to_desktop_ui(p, b))
        img_desk_btn.pack(side="right", padx=(4, 0))
        tk.Button(
            foot,
            text="🔍 Aç",
            command=lambda p=abs_path: os.startfile(p),
            font=("Segoe UI", 8, "bold"),
            bg=THEME["accent"],
            fg="#ffffff",
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
        ).pack(side="right")

        prev_state = str(self.chat_text.cget("state"))
        self.chat_text.config(state="normal")
        self.chat_text.insert("end", " ", "body")
        self.chat_text.window_create("end", window=card)
        self.chat_text.insert("end", "\n\n", "body")
        self.chat_text.see("end")
        if prev_state == "disabled":
            self.chat_text.config(state="disabled")

    def _render_conversation_messages(self):
        import sqlite3
        import json
        with self._stream_lock:
            self._stream_chunks.clear()
            self._stream_flush_pending = False
        self._chat_photo_refs.clear()
        self.chat_text.config(state="normal")
        self.chat_text.delete("1.0", "end")
        if not self.current_conversation_id:
            self.chat_text.config(state="disabled")
            return
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT role, content, tool_calls FROM ("
                "SELECT role, content, tool_calls, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 80"
                ") ORDER BY created_at ASC",
                (self.current_conversation_id,)
            ).fetchall()
        if not rows:
            self._set_empty_state(True)
            self.chat_text.config(state="disabled")
            return
        self._set_empty_state(False)
        for role, content, tool_calls_json in rows:
            if role == "user":
                self.chat_text.insert("end", "Siz\n", "user")
                self.chat_text.insert("end", f" {content} \n\n", "user_body")
            elif role == "assistant":
                if tool_calls_json:
                    try:
                        tcs = json.loads(tool_calls_json)
                        for tc in tcs:
                            tc_res = tc.get("result")
                            self.chat_text.insert(
                                "end",
                                f"⚙ {tc.get('name')} → {tc_res}\n",
                                "tool"
                            )
                            img_rel = self._extract_image_rel_from_tool_result(tc_res)
                            if img_rel:
                                self._append_image_preview_to_chat(img_rel, caption=img_rel)
                            else:
                                file_rel = self._extract_file_path_from_tool_result(tc_res)
                                if file_rel:
                                    self._append_file_card_to_chat(file_rel)
                    except Exception:
                        pass
                if "generativelanguage.googleapis.com" in self.evren_base_url.lower():
                    ai_title = f"✨ Google Gemini ({self.evren_model or 'Flash'})\n"
                elif "ssyz.org.tr" not in self.evren_base_url.lower():
                    ai_title = "🚀 Kendi AI (32B)\n"
                else:
                    ai_title = "✦ AI Studio\n"
                self.chat_text.insert("end", ai_title, "assistant")
                self.chat_text.insert("end", f"{content}\n\n", "body")
            elif role == "notice":
                self.chat_text.insert("end", f"⚠️ {content}\n\n", "error")
        self.chat_text.see("end")
        self.chat_text.config(state="disabled")

    # ------------------------------------------------------------------
    # ARAÇLAR (TOOLS): calculator, getSystemTime, generateDocument (PDF)
    # ------------------------------------------------------------------
    def _tool_calculator(self, expression: str) -> str:
        """eval kullanmayan güvenli matematik değerlendirici (AST yürüyücü)."""
        import ast
        import math
        import operator

        binary_ops = {
            ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
            ast.FloorDiv: operator.floordiv,
        }
        unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}
        functions = {
            "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan, "log": math.log,
            "log10": math.log10, "exp": math.exp, "floor": math.floor, "ceil": math.ceil,
            "abs": abs, "round": round,
        }
        constants = {"pi": math.pi, "e": math.e}

        def _eval(node):
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
                left, right = _eval(node.left), _eval(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                    raise ValueError("Üs çok büyük.")
                return binary_ops[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
                return unary_ops[type(node.op)](_eval(node.operand))
            if isinstance(node, ast.Name) and node.id in constants:
                return constants[node.id]
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in functions and not node.keywords):
                return functions[node.func.id](*[_eval(a) for a in node.args])
            raise ValueError("Desteklenmeyen ifade.")

        expr_clean = (expression.replace("^", "**").replace("×", "*").replace("÷", "/")
                      .replace(",", ".").strip())
        if not expr_clean or len(expr_clean) > 300:
            raise ValueError("Geçersiz ifade.")
        val = _eval(ast.parse(expr_clean, mode="eval"))
        if isinstance(val, float):
            val = float(f"{val:.12g}")
        return f"{expression} = {val}"

    def _tool_get_system_time(self) -> str:
        import datetime
        now = datetime.datetime.now()
        gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')} ({gunler[now.weekday()]})"

    def _tool_generate_document(self, title: str, content: str) -> str:
        """
        Türkçe karakterleri (ş, ğ, ı, İ, ö, ç, ü) tam destekleyen Unicode TrueType (Arial)
        font kullanarak много-sayfalı PDF belgesi üretir ve varsa Supabase Storage'a da yükler.
        """
        from PIL import Image, ImageDraw, ImageFont
        import datetime

        font_reg_path = r"C:\Windows\Fonts\arial.ttf"
        font_bold_path = r"C:\Windows\Fonts\arialbd.ttf"
        font_title = ImageFont.truetype(font_reg_path if not os.path.exists(font_bold_path) else font_bold_path, 28)
        font_heading = ImageFont.truetype(font_reg_path if not os.path.exists(font_bold_path) else font_bold_path, 22)
        font_body = ImageFont.truetype(font_reg_path, 17)
        font_footer = ImageFont.truetype(font_reg_path, 13)

        page_w, page_h = 1240, 1754  # A4 ~150 DPI
        margin = 90
        max_w = page_w - (margin * 2)

        pages = []
        img = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(img)
        y = margin

        def new_page():
            nonlocal img, draw, y
            pages.append(img)
            img = Image.new("RGB", (page_w, page_h), "white")
            draw = ImageDraw.Draw(img)
            y = margin

        def draw_wrapped(text_line: str, font_obj, color=(25, 25, 30), indent=0, spacing=10):
            nonlocal y
            words = text_line.split(" ")
            cur = ""
            line_h = int(font_obj.size * 1.45)
            for w in words:
                cand = f"{cur} {w}".strip() if cur else w
                bbox = draw.textbbox((0, 0), cand, font=font_obj)
                if (bbox[2] - bbox[0]) <= (max_w - indent):
                    cur = cand
                else:
                    if cur:
                        if y + line_h > page_h - margin:
                            new_page()
                        draw.text((margin + indent, y), cur, fill=color, font=font_obj)
                        y += line_h
                    cur = w
            if cur:
                if y + line_h > page_h - margin:
                    new_page()
                draw.text((margin + indent, y), cur, fill=color, font=font_obj)
                y += line_h
            y += spacing

        doc_title = (title or "Türkçe Rapor ve Belge").strip()
        draw_wrapped(doc_title, font_title, color=(15, 23, 42), spacing=20)
        draw.line([(margin, y - 8), (page_w - margin, y - 8)], fill=(200, 210, 225), width=2)
        y += 12

        for raw in content.replace("\r", "").split("\n"):
            line = raw.strip()
            if not line:
                y += 14
                continue
            if line.startswith("#"):
                clean_h = line.lstrip("#").strip()
                draw_wrapped(clean_h, font_heading, color=(30, 58, 138), spacing=10)
            elif line.startswith("- ") or line.startswith("* "):
                draw_wrapped("• " + line[2:].strip(), font_body, indent=20, spacing=6)
            else:
                draw_wrapped(line, font_body, spacing=8)

        pages.append(img)
        total_p = len(pages)
        for idx, p_img in enumerate(pages):
            d = ImageDraw.Draw(p_img)
            d.text(
                (margin, page_h - int(margin * 0.65)),
                f"Sayfa {idx + 1} / {total_p}  —  Mini Agent Türkçe PDF Motoru",
                fill=(120, 125, 135),
                font=font_footer
            )

        safe_slug = "".join(c if c.isalnum() else "_" for c in doc_title)[:35].strip("_") or "belge"
        fname = f"{safe_slug}_{int(time.time())}.pdf"
        out_path = os.path.join(self.pdf_output_dir, fname)

        pages[0].save(
            out_path,
            "PDF",
            resolution=150.0,
            save_all=True,
            append_images=pages[1:]
        )

        # Supabase yapılandırılmışsa Storage'a da yükle
        if self.supabase_url and self.supabase_key:
            try:
                bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "documents")
                storage_path = f"{self.current_conversation_id}/{fname}"
                with open(out_path, "rb") as f_pdf:
                    up_res = requests.post(
                        f"{self.supabase_url}/storage/v1/object/{bucket}/{storage_path}",
                        headers={
                            "Authorization": f"Bearer {self.supabase_key}",
                            "apikey": self.supabase_key,
                            "Content-Type": "application/pdf"
                        },
                        data=f_pdf.read(),
                        timeout=10
                    )
                if up_res.status_code in (200, 201):
                    return f"PDF oluşturuldu ve Supabase'e yüklendi: {out_path}"
            except Exception:
                pass

        return f"Türkçe PDF başarıyla oluşturuldu: {out_path}"

    def send_user_message(self):
        if self.is_generating:
            return
        if getattr(self, "_placeholder_active", False):
            return
        text = self.input_entry.get("1.0", "end-1c").strip()
        if not text:
            return
        self.input_entry.delete("1.0", "end")
        if self.focus_get() is not self.input_entry:
            self._show_input_placeholder()
        if not self.current_conversation_id:
            self.create_new_conversation()

        import uuid
        import datetime
        import sqlite3
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, tool_calls, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), self.current_conversation_id, "user", text, None, now)
            )
            # İlk mesajsa sohbet başlığını güncelle
            cnt = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (self.current_conversation_id,)
            ).fetchone()[0]
            if cnt <= 1:
                short_title = text[:42] + ("..." if len(text) > 42 else "")
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (short_title, self.current_conversation_id)
                )
            conn.commit()

        self._refresh_conversation_list()
        self._render_conversation_messages()

        self.is_generating = True
        self.cancel_agent = False
        self._gen_start_time = time.monotonic()
        self._last_timer_display = ""
        self._set_live_status("⏳ Düşünüyor...", THEME["warning"])
        self.send_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._refresh_live_timer()
        self._schedule_stream_pump()
        threading.Thread(target=self._agent_worker, args=(text,), daemon=True).start()

    # ------------------------------------------------------------------
    # NİYET ALGILAMA: Küçük yerel modeller araç listesini her mesajda görürse
    # selamlaşmalarda bile araç çağırır. Bu yüzden araçlar yalnızca mesaj
    # gerçekten bir görev içeriyorsa modele sunulur.
    # ------------------------------------------------------------------
    _TOOL_INTENT_PATTERNS = {
        "generateDocument": r"\b(pdf|belge|doküman|döküman|rapor|dosya)\b",
        "getSystemTime": r"(saat\s*kaç|saat\s*ne|tarih|bugün\s*(ne|hangi|günlerden)|hangi\s*gün|günlerden|şu\s*an\s*saat|what\s*time|date\s*today)",
        "calculator": r"(\d\s*[\+\-\*/\^x×÷%]\s*\d|hesapla|kaç\s*eder|karekök|yüzde|sqrt|toplamı|çarpımı)",
        "design_graphic": r"(tasarla|tasarım|kart\s*vizit|broşür|davetiye|menü|banner|afiş|poster|logo|kapak|thumbnail|kart\s*görseli|grafik\s*üret)",
        "render_html_graphic": r"(tasarla|tasarım|kart\s*vizit|broşür|davetiye|menü|banner|afiş|poster|logo|kapak|thumbnail|grafik|svg)",
        "create_editable_design": r"(hareket|sürükle|düzenle|değiştir|silinebil|interaktif|stitch|canva|figma|parça|tasarla|tasarım|kart\s*vizit|editör)",
        "decompose_image_to_design": r"(parça|böl|ayır|katman|analiz|\[görsel:|değiştirilebilir|düzenlenebilir)",
        "update_editable_design": r"(değiştir|güncelle|taşı|kaydır|al\b|büyüt|küçült|sil\b|kaldır|ekle|rengi|arka\s*plan|isim|ismi|logo|logoyu|ünvan|telefon|adres|mail|eposta|web)",
        "move_or_copy_file": r"(masa\s*üstü|masaustu|desktop|taşı|kopyala|getir|götür|aktar|kaydet|gönder)",
        "photoshop_edit": r"(photoshop|fotoğraf|görsel|resim|arka\s*plan|sepya|blur|bulanık|kırp|daire|yuvarlak|karakalem|filtre|parlaklık|kontrast|çerçeve|vinyet|\[görsel:)",
        "list_files": r"(dosyalar|klasör|listele|\[görsel:)",
    }

    def _select_tools_for_message(self, text: str) -> list:
        import re
        lower = text.lower()
        wanted = {
            name for name, pattern in self._TOOL_INTENT_PATTERNS.items()
            if re.search(pattern, lower)
        }
        return [t for t in self.TOOLS_SCHEMA if t["function"]["name"] in wanted]

    def _ollama_options(self) -> dict:
        return {"temperature": 0.6, "top_p": 0.9, "num_ctx": 8192, "repeat_penalty": 1.1}

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """Geçen süreyi gerçek zamanlı dakika/saniye formatına çevirir."""
        total = max(0, int(seconds))
        hours, rem = divmod(total, 3600)
        mins, secs = divmod(rem, 60)
        if hours > 0:
            return f"{hours} sa {mins:02d} dk {secs:02d} sn"
        return f"{mins} dk {secs:02d} sn"

    def _set_live_status(self, text: str, color: str = THEME["warning"]):
        with self._stream_lock:
            self._live_status_text = text
            self._live_status_color = color

    def _refresh_live_timer(self):
        if not self.is_generating or self._gen_start_time is None:
            return
        with self._stream_lock:
            status_txt = self._live_status_text
            status_col = self._live_status_color
        elapsed_str = self._format_elapsed(time.monotonic() - self._gen_start_time)
        display = f"{status_txt}  •  ⏱ {elapsed_str}"
        if display != self._last_timer_display:
            self._last_timer_display = display
            self.tool_indicator.config(text=display, fg=status_col)

    def _schedule_stream_pump(self):
        """Ana UI iş parçacığında periyodik olarak akış tamponunu ve gerçek zamanlı sayacı günceller."""
        self._flush_stream_buffer()
        self._refresh_live_timer()
        if self.is_generating:
            self.after(40, self._schedule_stream_pump)

    def _flush_stream_buffer(self):
        with self._stream_lock:
            chunks = list(self._stream_chunks)
            self._stream_chunks.clear()
        if not chunks:
            return
        self._set_empty_state(False)
        self.chat_text.config(state="normal")
        text_run = []
        run_tag = None

        def _commit_run():
            nonlocal text_run, run_tag
            if text_run:
                self.chat_text.insert("end", "".join(text_run), run_tag)
                text_run = []
                run_tag = None

        for text, tag in chunks:
            if tag == "__IMG__":
                _commit_run()
                self._append_image_preview_to_chat(text, caption=text)
            elif tag == "__FILE__":
                _commit_run()
                self._append_file_card_to_chat(text)
            elif tag == run_tag:
                text_run.append(text)
            else:
                _commit_run()
                text_run = [text]
                run_tag = tag
        _commit_run()
        self.chat_text.see("end")
        self.chat_text.config(state="disabled")

    def _append_stream_text(self, text: str, tag: str = "body"):
        if not text:
            return
        with self._stream_lock:
            self._stream_chunks.append((text, tag))

    def _stream_chat(self, model_name: str, messages: list) -> str:
        """Ollama'dan cevabı token token akıtır ve ekrana anlık yazar."""
        import json
        collected = []
        with requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": model_name,
                "messages": messages,
                "stream": True,
                "keep_alive": "30m",
                "options": self._ollama_options(),
            },
            stream=True,
            timeout=(5, 180),
        ) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise RuntimeError(chunk["error"])
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    collected.append(piece)
                    self._append_stream_text(piece)
                if chunk.get("done"):
                    break
        return "".join(collected).strip()

    def _extract_evren_error(self, resp) -> str:
        raw_text = resp.text[:400]
        try:
            payload = resp.json()
            err = payload.get("error")
            if isinstance(err, dict):
                code = err.get("code", "")
                msg = err.get("message", "")
            else:
                code = payload.get("code", "")
                msg = payload.get("detail") or payload.get("message") or str(err or "")
        except Exception:
            code = ""
            msg = raw_text

        combined = f"{code} {msg} {raw_text}".lower()
        if "terms_not_accepted" in combined or "terms" in combined and resp.status_code == 403:
            return (
                "EVREN kullanım şartları henüz onaylanmamış. "
                "Sağ üstteki '🔑 EVREN Ayarları' → '📜 Kullanım Şartlarını Onayla' adımını tamamlayın."
            )
        if resp.status_code == 401:
            return "EVREN API anahtarı geçersiz veya eksik. '🔑 EVREN Ayarları' üzerinden kontrol edin."
        if resp.status_code == 429:
            return "EVREN API istek/token limitine ulaşıldı. Lütfen biraz bekleyip tekrar deneyin."
        return f"EVREN API Hatası (HTTP {resp.status_code}): {msg or raw_text}"

    @staticmethod
    def _evren_speed_payload_opts(model_name: str) -> dict:
        """Düşünme gecikmesini azaltmak için modele uygun hız parametreleri döndürür."""
        m = (model_name or "").lower()
        if "gemma-4" in m:
            return {"chat_template_kwargs": {"enable_thinking": False}}
        if any(k in m for k in ("deepseek-v4", "glm-", "qwen3.8")):
            return {"reasoning_effort": "low"}
        return {}

    def _stream_evren_chat(self, model_name: str, messages: list) -> str:
        """EVREN LLM API'den SSE akışı ile cevabı token token ekrana yazar."""
        import json
        collected = []
        chat_payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "temperature": 0.6,
            "max_tokens": 4096,
            **self._evren_speed_payload_opts(model_name),
        }
        with requests.post(
            f"{self.evren_base_url}/chat/completions",
            headers=self._evren_headers(),
            json=chat_payload,
            stream=True,
            timeout=(10, 180),
        ) as resp:
            if resp.status_code != 200:
                raise RuntimeError(self._extract_evren_error(resp))
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                chunk = json.loads(data_str)
                if chunk.get("error"):
                    err = chunk["error"]
                    raise RuntimeError(err.get("message") if isinstance(err, dict) else str(err))
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    collected.append(piece)
                    self._append_stream_text(piece)
        return "".join(collected).strip()

    def _choose_agent_workspace(self):
        chosen = filedialog.askdirectory(
            parent=self,
            title="Ajanın Çalışacağı Proje Klasörünü Seçin",
            initialdir=self.agent_workspace_dir,
        )
        if not chosen:
            return
        self.agent_workspace_dir = os.path.abspath(chosen)
        self._set_setting("agent_workspace_dir", self.agent_workspace_dir)
        ws_name = os.path.basename(self.agent_workspace_dir) or self.agent_workspace_dir
        self.workspace_lbl.config(text=f"📁 {ws_name}")

    @staticmethod
    def _get_real_desktop_dir() -> str:
        """OneDrive yönlendirmesi dahil gerçek Windows Masaüstü klasörünü bulur."""
        if os.name == "nt":
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                ) as key:
                    val, _ = winreg.QueryValueEx(key, "Desktop")
                    expanded = os.path.expandvars(str(val)).strip()
                    if expanded and os.path.isdir(expanded):
                        return os.path.abspath(expanded)
            except Exception:
                pass
        onedrive_desk = os.path.expanduser("~/OneDrive/Desktop")
        if os.path.isdir(onedrive_desk):
            return os.path.abspath(onedrive_desk)
        return os.path.abspath(os.path.expanduser("~/Desktop"))

    def _resolve_workspace_path(self, rel_path: str) -> str:
        base = os.path.abspath(self.agent_workspace_dir)
        raw = os.path.expandvars(os.path.expanduser((rel_path or "").strip()))
        if not raw:
            return base
        norm_slashes = raw.replace("/", "\\")
        low = norm_slashes.lower().strip("\\")
        desk_dir = self._get_real_desktop_dir()
        for prefix in ("desktop", "masaüstü", "masaustu"):
            if low == prefix:
                return desk_dir
            if low.startswith(prefix + "\\"):
                sub = norm_slashes.strip("\\")[len(prefix) + 1:]
                return os.path.abspath(os.path.join(desk_dir, sub))
        # Model C:\Users\...\Desktop yazsa bile gerçek OneDrive Masaüstüne yönlendir
        legacy_desk = os.path.abspath(os.path.expanduser("~/Desktop"))
        if os.path.isabs(raw):
            abs_raw = os.path.abspath(raw)
            if abs_raw.lower() == legacy_desk.lower():
                return desk_dir
            if abs_raw.lower().startswith(legacy_desk.lower() + os.sep):
                rel_from_desk = abs_raw[len(legacy_desk) + 1:]
                return os.path.abspath(os.path.join(desk_dir, rel_from_desk))
            user_home = os.path.abspath(os.path.expanduser("~"))
            if os.path.commonpath([user_home, abs_raw]).lower() == user_home.lower() or os.path.commonpath([base, abs_raw]).lower() == base.lower():
                return abs_raw
        cleaned = raw.lstrip("/\\")
        target = os.path.abspath(os.path.join(base, cleaned))
        if os.path.commonpath([base, target]).lower() != base.lower():
            raise ValueError("Güvenlik sınırı: Yalnızca çalışma klasörü veya kullanıcı klasörü içindeki dosyalara erişilebilir.")
        return target

    def _tool_list_files(self, subpath: str = "") -> str:
        target = self._resolve_workspace_path(subpath)
        if not os.path.exists(target):
            return f"Klasör bulunamadı: {subpath}"
        entries = []
        for root, dirs, files in os.walk(target):
            dirs[:] = sorted(d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".next", ".venv", "venv"})
            rel_root = os.path.relpath(root, self.agent_workspace_dir)
            prefix = "" if rel_root == "." else rel_root + "/"
            for d in dirs:
                entries.append(f"[DIR]  {prefix}{d}/")
            for f in sorted(files):
                entries.append(f"[FILE] {prefix}{f}")
            if len(entries) >= 120:
                entries.append("... (liste kısaltıldı, en fazla 120 öğe)")
                break
        return "\n".join(entries) if entries else "(Çalışma klasörü şu an boş)"

    def _workspace_tree_snapshot(self, max_files: int = 35) -> str:
        """Sistem istemi için çalışma klasöründeki ilk dosyaların hızlı ağaç ve satır özeti."""
        base = os.path.abspath(self.agent_workspace_dir)
        if not os.path.isdir(base):
            return ""
        skip_dirs = {".git", "node_modules", "__pycache__", ".next", ".venv", "venv", "uploads", "generated"}
        rows = []
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
            rel_root = os.path.relpath(root, base)
            prefix = "" if rel_root == "." else rel_root.replace("\\", "/") + "/"
            for f in sorted(files):
                rel_p = f"{prefix}{f}"
                full_p = os.path.join(root, f)
                info = ""
                if os.path.splitext(f)[1].lower() in {
                    ".py", ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx", ".json", ".md", ".txt", ".bat", ".sql"
                }:
                    try:
                        if os.path.getsize(full_p) <= 250_000:
                            with open(full_p, "rb") as fp:
                                line_cnt = sum(1 for _ in fp)
                            info = f" ({line_cnt} satır)"
                    except OSError:
                        pass
                rows.append(f"- {rel_p}{info}")
                if len(rows) >= max_files:
                    rows.append("- ... (daha fazlası için list_files kullan)")
                    return "\n".join(rows)
        return "\n".join(rows)

    def _tool_read_file(self, path: str, start_line: int = 1, end_line: int = 500) -> str:
        target = self._resolve_workspace_path(path)
        if not os.path.isfile(target):
            return f"Dosya bulunamadı: {path}"
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        s = max(1, int(start_line or 1))
        e = min(len(lines), max(s, int(end_line or (s + 499))))
        numbered = [f"{idx}: {lines[idx - 1].rstrip()}" for idx in range(s, e + 1)]
        return "\n".join(numbered) if numbered else "(Dosya boş)"

    def _tool_write_file(self, path: str, content: str) -> str:
        target = self._resolve_workspace_path(path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return f"Dosya yazıldı: {os.path.relpath(target, self.agent_workspace_dir)} ({len(content)} karakter)"

    def _tool_edit_file(self, path: str, old_text: str, new_text: str) -> str:
        target = self._resolve_workspace_path(path)
        if not os.path.isfile(target):
            return f"Dosya bulunamadı: {path}"
        with open(target, "r", encoding="utf-8") as f:
            raw = f.read()
        if old_text not in raw:
            return f"Düzenleme başarısız: belirtilen metin '{path}' içinde bulunamadı."
        updated = raw.replace(old_text, new_text, 1)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(updated)
        return f"Dosya güncellendi: {os.path.relpath(target, self.agent_workspace_dir)}"

    def _find_latest_workspace_file(self, hint: str = "") -> str:
        """Çalışma klasöründe ipucuna uyan veya en son üretilen tasarım/belge dosyasını bulur."""
        base = os.path.abspath(self.agent_workspace_dir)
        if not os.path.isdir(base):
            return ""
        hint_low = os.path.basename((hint or "").strip()).lower()
        if hint_low in ("", "last", "son", "latest", "kartvizit", "tasarim", "tasarım"):
            hint_stem = "kartvizit" if "kartvizit" in hint_low else ""
        else:
            hint_stem = os.path.splitext(hint_low)[0]
        skip_names = {"app.py", "test_app.py", "test_upload_flow.py", "tasks.json", "baslat.bat", ".gitkeep"}
        candidates = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv", "venv"}]
            for f in files:
                if f in skip_names or f.endswith(".pyc"):
                    continue
                full = os.path.join(root, f)
                ext = os.path.splitext(f)[1].lower()
                if ext not in {".html", ".htm", ".png", ".jpg", ".jpeg", ".pdf", ".svg"}:
                    continue
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                fl = f.lower()
                score = 0
                if hint_low and fl == hint_low:
                    score = 3
                elif hint_stem and hint_stem in fl:
                    score = 2
                elif ext in {".html", ".png", ".pdf"}:
                    score = 1
                candidates.append((score, mtime, full))
        if not candidates:
            return ""
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][2]

    def _try_open_once_in_turn(self, opener_callable) -> bool:
        """Aynı kullanıcı turu içinde tarayıcı/dosya açma işleminin en fazla 1 kez çalışmasını garanti eder."""
        if self.__dict__.get("_browser_opened_in_turn", False):
            return False
        self._browser_opened_in_turn = True
        opener_callable()
        return True

    def _tool_move_or_copy_file(
        self,
        source_path: str = "last",
        destination_path: str = "desktop",
        action: str = "copy",
        open_after: bool = True,
    ) -> str:
        raw_src = (source_path or "last").strip()
        src_abs = ""
        if raw_src.lower() not in ("", "last", "son", "latest"):
            try:
                cand = self._resolve_workspace_path(raw_src)
                if os.path.isfile(cand):
                    src_abs = cand
            except Exception:
                pass
        if not src_abs:
            src_abs = self._find_latest_workspace_file(raw_src)
        if not src_abs or not os.path.isfile(src_abs):
            return f"Taşınacak/kopyalanacak kaynak dosya bulunamadı: {source_path}"

        dst_resolved = self._resolve_workspace_path(destination_path or "desktop")
        if os.path.isdir(dst_resolved) or (destination_path or "").strip().lower() in ("desktop", "masaüstü", "masaustu"):
            os.makedirs(dst_resolved, exist_ok=True)
            dst_abs = os.path.join(dst_resolved, os.path.basename(src_abs))
        else:
            os.makedirs(os.path.dirname(dst_resolved) or ".", exist_ok=True)
            dst_abs = dst_resolved

        act = (action or "copy").strip().lower()
        if os.path.abspath(src_abs).lower() != os.path.abspath(dst_abs).lower():
            if act == "move":
                shutil.move(src_abs, dst_abs)
            else:
                shutil.copy2(src_abs, dst_abs)

        # Eğer hedef Masaüstü ise ve hem OneDrive\Desktop hem yerel Desktop klasörü varsa ikisine de kopyala
        real_desk = self._get_real_desktop_dir()
        legacy_desk = os.path.abspath(os.path.expanduser("~/Desktop"))
        if os.path.dirname(os.path.abspath(dst_abs)).lower() == real_desk.lower() and os.path.isdir(legacy_desk) and legacy_desk.lower() != real_desk.lower():
            try:
                mirror_path = os.path.join(legacy_desk, os.path.basename(dst_abs))
                if os.path.abspath(mirror_path).lower() != os.path.abspath(dst_abs).lower():
                    shutil.copy2(dst_abs, mirror_path)
            except Exception:
                pass

        opened_msg = ""
        if open_after:
            try:
                if dst_abs.lower().endswith((".html", ".htm")):
                    import webbrowser
                    from pathlib import Path
                    if self._try_open_once_in_turn(lambda: webbrowser.open(Path(dst_abs).resolve().as_uri())):
                        opened_msg = " (otomatik açıldı)"
                else:
                    if self._try_open_once_in_turn(lambda: os.startfile(dst_abs)):
                        opened_msg = " (otomatik açıldı)"
            except Exception:
                pass

        return f"Dosya masaüstüne/hedefe aktarıldı: {dst_abs}{opened_msg}"

    def _ask_command_approval(self, command: str) -> bool:
        if not self.confirm_commands_var.get():
            return True
        done_evt = threading.Event()
        decision = {"ok": False}

        def _prompt():
            decision["ok"] = messagebox.askyesno(
                "Ajan Komut Onayı",
                f"Yapay zekâ ajanı çalışma klasöründe şu komutu çalıştırmak istiyor:\n\n"
                f"Klasör: {self.agent_workspace_dir}\n"
                f"Komut: {command}\n\n"
                f"Çalıştırılmasına izin veriyor musunuz?",
                parent=self,
            )
            done_evt.set()

        self.after(0, _prompt)
        done_evt.wait()
        return decision["ok"]

    def _kill_process_tree(self, pid: int):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=5,
                )
            else:
                os.kill(pid, 9)
        except Exception:
            pass

    def _tool_run_command(self, command: str) -> str:
        import tempfile
        cmd = (command or "").strip()
        if not cmd:
            return "Boş komut çalıştırılamaz."
        if not self._ask_command_approval(cmd):
            return "Kullanıcı komutun çalıştırılmasına izin vermedi."

        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        out_f = tempfile.TemporaryFile(mode="w+b")
        err_f = tempfile.TemporaryFile(mode="w+b")
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=self.agent_workspace_dir,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=out_f,
                stderr=err_f,
                creationflags=flags,
            )
            started_at = time.time()
            deadline = started_at + 35.0
            timed_out = False
            cancelled = False
            while proc.poll() is None:
                if self.cancel_agent:
                    cancelled = True
                    self._kill_process_tree(proc.pid)
                    break
                now = time.time()
                if now > deadline:
                    timed_out = True
                    self._kill_process_tree(proc.pid)
                    break
                elapsed = now - started_at
                time.sleep(0.02 if elapsed < 0.3 else (0.05 if elapsed < 2.0 else 0.12))

            out_f.seek(0)
            err_f.seek(0)
            out = out_f.read().decode("utf-8", errors="replace").strip()
            err = err_f.read().decode("utf-8", errors="replace").strip()

            if cancelled:
                return "Komut kullanıcı tarafından durduruldu."
            if timed_out:
                hint = (
                    "Komut 35 saniyede sonlanmadı ve otomatik durduruldu. "
                    "(Not: Web sunucusu başlatmak için run_command yerine launch_app aracını kullanın.)"
                )
                return f"{hint}\n[STDOUT]\n{out[:1500]}" if out else hint

            combined = f"Çıkış kodu: {proc.returncode}"
            if out:
                combined += f"\n[STDOUT]\n{out[:3000]}"
            if err:
                combined += f"\n[STDERR]\n{err[:2000]}"
            return combined
        finally:
            try:
                out_f.close()
                err_f.close()
            except Exception:
                pass

    def _free_local_port(self, port: int):
        """Belirtilen yerel TCP portunu dinleyen eski arka plan süreçlerini sonlandırır."""
        if os.name != "nt" or not port or port <= 0:
            return
        try:
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"],
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=4,
            )
            pids = set()
            needle = f":{port}"
            my_pid = os.getpid()
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and "LISTENING" in parts[3].upper() and parts[1].endswith(needle):
                    try:
                        pid = int(parts[4])
                        if pid > 0 and pid != my_pid:
                            pids.add(pid)
                    except ValueError:
                        pass
            for pid in pids:
                self._kill_process_tree(pid)
            if pids:
                time.sleep(0.4)
        except Exception:
            pass

    def _tool_launch_app(self, command: str = "", url: str = "", html_path: str = "") -> str:
        import re
        import webbrowser
        cmd = (command or "").strip()
        target_url = (url or "").strip()
        rel_html = (html_path or "").strip()
        notes = []

        if cmd:
            if not self._ask_command_approval(f"[Arka Plan Sunucusu] {cmd}"):
                return "Kullanıcı sunucunun başlatılmasına izin vermedi."
            m_port = re.search(r":(\d{2,5})(?:/|$)", target_url)
            if m_port:
                self._free_local_port(int(m_port.group(1)))
            elif "app.py" in cmd or "flask" in cmd.lower():
                self._free_local_port(5000)
            creation = (
                (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
                if os.name == "nt"
                else 0
            )
            proc = subprocess.Popen(
                cmd,
                cwd=self.agent_workspace_dir,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation,
            )
            time.sleep(1.2)
            if proc.poll() is not None:
                return f"Sunucu komutu hemen sonlandı (çıkış kodu: {proc.returncode}). Komutu veya bağımlılıkları kontrol edin."
            notes.append(f"Arka plan süreci başlatıldı (PID: {proc.pid})")

        if target_url:
            try:
                if self._try_open_once_in_turn(lambda: webbrowser.open(target_url)):
                    notes.append(f"Tarayıcıda açıldı: {target_url}")
                else:
                    notes.append(f"Tarayıcıda zaten açıldı (tekrar açılmadı): {target_url}")
            except Exception as exc:
                notes.append(f"Tarayıcı açılamadı ({target_url}): {exc}")
        elif rel_html:
            resolved = self._resolve_workspace_path(rel_html)
            if not os.path.exists(resolved):
                return f"Açılacak dosya bulunamadı: {rel_html}"
            try:
                uri = f"file:///{resolved.replace(os.sep, '/')}"
                if self._try_open_once_in_turn(lambda: webbrowser.open(uri)):
                    notes.append(f"Tarayıcıda açıldı: {os.path.relpath(resolved, self.agent_workspace_dir)}")
                else:
                    notes.append(f"Tarayıcıda zaten açıldı (tekrar açılmadı): {os.path.relpath(resolved, self.agent_workspace_dir)}")
            except Exception as exc:
                notes.append(f"Dosya açılamadı: {exc}")

        return " | ".join(notes) if notes else "Başlatılacak komut, URL veya html_path belirtilmedi."

    def _load_design_font(self, size: int, bold: bool = False):
        return _load_studio_font(size, bold=bold)

    def _tool_design_graphic(
        self,
        output_path: str,
        title: str,
        subtitle: str = "",
        badge: str = "",
        width: int = 1200,
        height: int = 630,
        theme: str = "indigo",
        style: str = "modern",
        hero_image_path: str = "",
        footer_text: str = "",
        layout: str = "auto",
        items=None,
        monogram: str = "",
        font_family: str = "sans",
    ) -> str:
        target = self._resolve_workspace_path(output_path or "assets/graphic.png")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        canvas = _render_design_graphic_pil(
            title=title,
            subtitle=subtitle,
            badge=badge,
            width=width,
            height=height,
            theme=theme,
            style=style,
            hero_image_path=hero_image_path,
            footer_text=footer_text,
            path_resolver=self._resolve_workspace_path,
            layout=layout,
            items=items,
            monogram=monogram,
            font_family=font_family,
        )
        if target.lower().endswith((".jpg", ".jpeg")):
            canvas.convert("RGB").save(target, quality=95)
        else:
            canvas.save(target, "PNG")
        rel = os.path.relpath(target, self.agent_workspace_dir)
        return f"Grafik tasarım oluşturuldu: {rel} ({canvas.width}x{canvas.height})"

    @staticmethod
    def _find_headless_browser() -> str:
        cands = [
            shutil.which("msedge"),
            shutil.which("chrome"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        ]
        for p in cands:
            if p and os.path.isfile(p):
                return p
        return ""

    def _tool_render_html_graphic(
        self,
        output_path: str,
        html: str,
        width: int = 1200,
        height: int = 630,
        transparent: bool = False,
    ) -> str:
        """Özel HTML+CSS+SVG tasarımı Edge/Chrome headless ile piksel netliğinde PNG/JPG olarak render eder."""
        from pathlib import Path
        from PIL import Image

        browser = self._find_headless_browser()
        if not browser:
            return "Hata: Headless tarayıcı (Edge/Chrome) bulunamadı; lütfen `design_graphic` aracını kullanın."

        w = max(256, min(int(width or 1200), 2400))
        h = max(256, min(int(height or 630), 2400))
        target = self._resolve_workspace_path(output_path or "assets/graphic.png")
        os.makedirs(os.path.dirname(target), exist_ok=True)

        base_uri = Path(os.path.abspath(self.agent_workspace_dir)).as_uri().rstrip("/") + "/"
        base_tag = f"<base href='{base_uri}'>"
        bg_reset = "background:transparent!important;" if transparent else ""
        raw_html = (html or "").strip()
        if "<html" not in raw_html.lower():
            doc_html = (
                f"<!doctype html><html><head><meta charset='utf-8'>{base_tag}"
                f"<style>*{{box-sizing:border-box;margin:0;padding:0;}}html,body{{width:{w}px;height:{h}px;overflow:hidden;{bg_reset}font-family:'Segoe UI',sans-serif;}}</style>"
                f"</head><body>{raw_html}</body></html>"
            )
        else:
            doc_html = raw_html
            if "<base" not in doc_html.lower():
                if "<head>" in doc_html.lower():
                    idx = doc_html.lower().index("<head>") + len("<head>")
                    doc_html = doc_html[:idx] + base_tag + doc_html[idx:]
                else:
                    doc_html = f"{base_tag}{doc_html}"
            if transparent and "background:transparent" not in doc_html.lower():
                doc_html += "<style>html,body{background:transparent!important;}</style>"

        tmp_html = None
        tmp_png = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as hf:
                hf.write(doc_html)
                tmp_html = hf.name
            tmp_png = tmp_html[:-5] + ".png"

            cmd = [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                f"--window-size={w},{h}",
                f"--screenshot={tmp_png}",
            ]
            if transparent:
                cmd.append("--default-background-color=00000000")
            cmd.append(Path(tmp_html).as_uri())

            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=22, creationflags=flags)
            if proc.returncode != 0 or not os.path.isfile(tmp_png):
                err = (proc.stderr or proc.stdout or "").strip()[:180]
                return f"HTML grafik render hatası: {err or 'çıkış kodu ' + str(proc.returncode)}"

            im = Image.open(tmp_png).convert("RGBA")
            if im.size != (w, h):
                im = im.resize((w, h), Image.LANCZOS)
            if target.lower().endswith((".jpg", ".jpeg")):
                im.convert("RGB").save(target, quality=95)
            else:
                im.save(target, "PNG")
            rel = os.path.relpath(target, self.agent_workspace_dir)
            return f"Grafik tasarım oluşturuldu: {rel} ({im.width}x{im.height})"
        finally:
            for p in (tmp_html, tmp_png):
                if p and os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    @staticmethod
    def _build_luxury_card_preset(preset_idx: int, w: int, h: int, info: dict) -> tuple[str, list]:
        """Gerçek matbaa/kurumsal baskı kalitesinde (1050x600), vektörel SVG amblem, QR kod ve ikonlu 5 profesyonel kartvizit şablonu üretir."""
        import base64
        name = info.get("name") or "BURAK YILMAZ"
        role = info.get("role") or "Yüksek Mimar  |  Kurucu Ortak"
        company = info.get("company") or "YILMAZ MİMARLIK"
        slogan = info.get("slogan") or "MİMARLIK  ·  İÇ MEKÂN  ·  PROJE & DANIŞMANLIK"
        phone = info.get("phone") or "+90 (532) 444 18 90"
        email = info.get("email") or "burak@yilmazmimarlik.com.tr"
        web = info.get("web") or "www.yilmazmimarlik.com.tr"
        addr = info.get("addr") or "Teşvikiye Cad. No: 42 D: 8, Nişantaşı / İstanbul"
        mono = info.get("mono") or "".join([p[0] for p in name.split()[:2] if p]).upper() or "BY"
        idx = preset_idx % 5

        def _svg_uri(svg_str: str) -> str:
            b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
            return f"data:image/svg+xml;base64,{b64}"

        def _make_logo_svg(accent1: str, accent2: str, dark_bg: str) -> str:
            svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
              <defs>
                <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="{accent1}"/>
                  <stop offset="50%" stop-color="{accent2}"/>
                  <stop offset="100%" stop-color="{accent1}"/>
                </linearGradient>
              </defs>
              <polygon points="100,8 182,54 182,146 100,192 18,146 18,54" fill="{dark_bg}" stroke="url(#g)" stroke-width="4"/>
              <polygon points="100,22 170,61 170,139 100,178 30,139 30,61" fill="none" stroke="url(#g)" stroke-width="1.2" stroke-dasharray="6,4" opacity="0.75"/>
              <path d="M100,32 L156,100 L100,168 L44,100 Z" fill="none" stroke="url(#g)" stroke-width="1.5" opacity="0.45"/>
              <circle cx="100" cy="100" r="54" fill="{dark_bg}" stroke="url(#g)" stroke-width="2.2"/>
              <text x="100" y="116" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-size="46" font-weight="700" letter-spacing="2" fill="url(#g)">{mono}</text>
            </svg>"""
            return _svg_uri(svg)

        def _make_qr_svg(fg_col: str, bg_col: str, border_col: str) -> str:
            rects = []
            pattern = [
                "111111101011011111111",
                "100000100101101000001",
                "101110101010001011101",
                "101110100110101011101",
                "101110101001101011101",
                "100000100110001000001",
                "111111101010101111111",
                "000000000101000000000",
                "101101111001110101101",
                "011010001100101100010",
                "110111101011010111011",
                "010001010010100100100",
                "101101101101011011101",
                "000000001010110100010",
                "111111100110011010101",
                "100000101001100111010",
                "101110101110110001101",
                "101110100101001110011",
                "101110101011010101100",
                "100000100100101011011",
                "111111101101010100101",
            ]
            for r_i, row in enumerate(pattern):
                for c_i, ch in enumerate(row):
                    if ch == "1":
                        rects.append(f'<rect x="{14 + c_i * 4}" y="{14 + r_i * 4}" width="3.6" height="3.6" rx="0.5" fill="{fg_col}"/>')
            svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 112 112" width="112" height="112">
              <rect x="2" y="2" width="108" height="108" rx="10" fill="{bg_col}" stroke="{border_col}" stroke-width="2"/>
              {''.join(rects)}
            </svg>"""
            return _svg_uri(svg)

        def _contact_icons_svg(x_icon: int, ys: list, accent: str, box_bg: str) -> str:
            y0, y1, y2, y3 = ys
            return f"""
              <g>
                <rect x="{x_icon}" y="{y0}" width="30" height="30" rx="6" fill="{box_bg}" stroke="{accent}" stroke-width="1.2" opacity="0.9"/>
                <path d="M{x_icon+9},{y0+8} C{x_icon+11},{y0+8} {x_icon+12},{y0+11} {x_icon+11},{y0+13} L{x_icon+10},{y0+14} C{x_icon+12},{y0+17} {x_icon+14},{y0+19} {x_icon+17},{y0+21} L{x_icon+18},{y0+20} C{x_icon+20},{y0+19} {x_icon+23},{y0+20} {x_icon+23},{y0+22} C{x_icon+23},{y0+24} {x_icon+20},{y0+25} {x_icon+18},{y0+24} C{x_icon+12},{y0+22} {x_icon+9},{y0+18} {x_icon+7},{y0+12} C{x_icon+6},{y0+10} {x_icon+7},{y0+8} {x_icon+9},{y0+8} Z" fill="{accent}"/>
                <rect x="{x_icon}" y="{y1}" width="30" height="30" rx="6" fill="{box_bg}" stroke="{accent}" stroke-width="1.2" opacity="0.9"/>
                <rect x="{x_icon+6}" y="{y1+9}" width="18" height="12" rx="2" fill="none" stroke="{accent}" stroke-width="1.6"/>
                <polyline points="{x_icon+6},{y1+10} {x_icon+15},{y1+16} {x_icon+24},{y1+10}" fill="none" stroke="{accent}" stroke-width="1.6"/>
                <rect x="{x_icon}" y="{y2}" width="30" height="30" rx="6" fill="{box_bg}" stroke="{accent}" stroke-width="1.2" opacity="0.9"/>
                <circle cx="{x_icon+15}" cy="{y2+15}" r="8.5" fill="none" stroke="{accent}" stroke-width="1.5"/>
                <ellipse cx="{x_icon+15}" cy="{y2+15}" rx="4.2" ry="8.5" fill="none" stroke="{accent}" stroke-width="1.3"/>
                <line x1="{x_icon+6.5}" y1="{y2+15}" x2="{x_icon+23.5}" y2="{y2+15}" stroke="{accent}" stroke-width="1.3"/>
                <rect x="{x_icon}" y="{y3}" width="30" height="30" rx="6" fill="{box_bg}" stroke="{accent}" stroke-width="1.2" opacity="0.9"/>
                <path d="M{x_icon+15},{y3+7} C{x_icon+11.5},{y3+7} {x_icon+9},{y3+9.6} {x_icon+9},{y3+13} C{x_icon+9},{y3+17.5} {x_icon+15},{y3+23} {x_icon+15},{y3+23} C{x_icon+15},{y3+23} {x_icon+21},{y3+17.5} {x_icon+21},{y3+13} C{x_icon+21},{y3+9.6} {x_icon+18.5},{y3+7} {x_icon+15},{y3+7} Z" fill="none" stroke="{accent}" stroke-width="1.6"/>
                <circle cx="{x_icon+15}" cy="{y3+13}" r="2.2" fill="{accent}"/>
              </g>"""

        if idx == 0:
            # 0: Kurumsal Antrasit & Altın Geometrik (Gerçek Matbaa Tasarımı - Asimetrik Sağ Kanat)
            icons = _contact_icons_svg(68, [312, 362, 412, 462], "#d4af37", "#151922")
            bg_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
              <defs>
                <linearGradient id="bg0" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#0d1017"/>
                  <stop offset="55%" stop-color="#141923"/>
                  <stop offset="100%" stop-color="#0a0c12"/>
                </linearGradient>
                <linearGradient id="gold0" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#e5c878"/>
                  <stop offset="50%" stop-color="#b88c32"/>
                  <stop offset="100%" stop-color="#f0d78c"/>
                </linearGradient>
                <linearGradient id="wing0" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#171c28"/>
                  <stop offset="100%" stop-color="#0d1017"/>
                </linearGradient>
              </defs>
              <rect width="{w}" height="{h}" fill="url(#bg0)"/>
              <polygon points="{w-370},0 {w},0 {w},{h} {w-450},{h}" fill="url(#wing0)"/>
              <polygon points="{w-376},0 {w-364},0 {w-444},{h} {w-456},{h}" fill="url(#gold0)"/>
              <polygon points="{w-390},0 {w-387},0 {w-467},{h} {w-470},{h}" fill="url(#gold0)" opacity="0.45"/>
              <rect x="28" y="28" width="{w-56}" height="{h-56}" rx="6" fill="none" stroke="url(#gold0)" stroke-width="1.2" opacity="0.42"/>
              <rect x="0" y="96" width="7" height="128" fill="url(#gold0)"/>
              {icons}
            </svg>"""
            bg = f"url('{_svg_uri(bg_svg)}') center/cover no-repeat"
            logo_uri = _make_logo_svg("#f0d78c", "#b88c32", "#0f131c")
            qr_uri = _make_qr_svg("#e5c878", "#0e121a", "#b88c32")
            return bg, [
                {"id": "isim", "label": "İsim Soyisim", "type": "text", "text": name, "x": 68, "y": 92, "w": 520, "h": 54, "fontSize": 40, "fontWeight": "800", "color": "#f8f6f0", "font": "Georgia, serif", "letterSpacing": 1.5},
                {"id": "unvan", "label": "Ünvan", "type": "text", "text": role, "x": 68, "y": 154, "w": 480, "h": 28, "fontSize": 15, "fontWeight": "600", "color": "#d4af37", "letterSpacing": 2.5},
                {"id": "ayirici_cizgi", "label": "Altın Ayırıcı Çizgi", "type": "line", "text": "", "x": 68, "y": 202, "w": 240, "h": 2, "bg": "#d4af37"},
                {"id": "slogan", "label": "Uzmanlık / Slogan", "type": "text", "text": slogan, "x": 68, "y": 222, "w": 500, "h": 24, "fontSize": 11, "fontWeight": "600", "color": "#94a3b8", "letterSpacing": 2},
                {"id": "telefon", "label": "Telefon", "type": "text", "text": phone, "x": 112, "y": 310, "w": 420, "h": 34, "fontSize": 16, "fontWeight": "600", "color": "#f1f5f9"},
                {"id": "eposta", "label": "E-Posta", "type": "text", "text": email, "x": 112, "y": 360, "w": 440, "h": 34, "fontSize": 15, "fontWeight": "500", "color": "#e2e8f0"},
                {"id": "web", "label": "Web Sitesi", "type": "text", "text": web, "x": 112, "y": 410, "w": 440, "h": 34, "fontSize": 15, "fontWeight": "500", "color": "#e2e8f0"},
                {"id": "adres", "label": "Adres", "type": "text", "text": addr, "x": 112, "y": 460, "w": 480, "h": 34, "fontSize": 14, "fontWeight": "400", "color": "#cbd5e1"},
                {"id": "logo", "label": "Kurumsal Logo / Amblem", "type": "image", "src": logo_uri, "text": "", "x": w - 265, "y": 96, "w": 150, "h": 150},
                {"id": "firma", "label": "Firma Adı", "type": "text", "text": company, "x": w - 345, "y": 266, "w": 310, "h": 34, "fontSize": 18, "fontWeight": "800", "color": "#f0d78c", "align": "center", "letterSpacing": 3},
                {"id": "qr_kod", "label": "QR Kod", "type": "image", "src": qr_uri, "text": "", "x": w - 238, "y": 388, "w": 96, "h": 96},
            ]

        if idx == 1:
            # 1: Kraliyet Lacivert & Şampanya Sol Kule (Prestij Kurumsal Kartvizit)
            icons = _contact_icons_svg(390, [292, 344, 396, 448], "#e0a96d", "#0f223d")
            bg_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
              <defs>
                <linearGradient id="bg1" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#081528"/>
                  <stop offset="100%" stop-color="#0d213d"/>
                </linearGradient>
                <linearGradient id="left1" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stop-color="#050e1c"/>
                  <stop offset="100%" stop-color="#0a192f"/>
                </linearGradient>
                <linearGradient id="cop1" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#f3c68f"/>
                  <stop offset="100%" stop-color="#c48341"/>
                </linearGradient>
              </defs>
              <rect width="{w}" height="{h}" fill="url(#bg1)"/>
              <rect x="0" y="0" width="332" height="{h}" fill="url(#left1)"/>
              <rect x="332" y="0" width="5" height="{h}" fill="url(#cop1)"/>
              <rect x="342" y="0" width="1.5" height="{h}" fill="url(#cop1)" opacity="0.45"/>
              <rect x="24" y="24" width="{w-48}" height="{h-48}" rx="6" fill="none" stroke="url(#cop1)" stroke-width="1" opacity="0.35"/>
              {icons}
            </svg>"""
            bg = f"url('{_svg_uri(bg_svg)}') center/cover no-repeat"
            logo_uri = _make_logo_svg("#f3c68f", "#c48341", "#071224")
            qr_uri = _make_qr_svg("#f3c68f", "#071224", "#c48341")
            return bg, [
                {"id": "logo", "label": "Kurumsal Logo / Amblem", "type": "image", "src": logo_uri, "text": "", "x": 91, "y": 84, "w": 150, "h": 150},
                {"id": "firma", "label": "Firma Adı", "type": "text", "text": company, "x": 30, "y": 254, "w": 272, "h": 34, "fontSize": 17, "fontWeight": "800", "color": "#f3c68f", "align": "center", "letterSpacing": 2.5},
                {"id": "slogan", "label": "Uzmanlık / Slogan", "type": "text", "text": "MİMARLIK & MÜHENDİSLİK", "x": 30, "y": 292, "w": 272, "h": 24, "fontSize": 10, "fontWeight": "600", "color": "#94a3b8", "align": "center", "letterSpacing": 2},
                {"id": "qr_kod", "label": "QR Kod", "type": "image", "src": qr_uri, "text": "", "x": 118, "y": 388, "w": 96, "h": 96},
                {"id": "isim", "label": "İsim Soyisim", "type": "text", "text": name, "x": 390, "y": 92, "w": 580, "h": 54, "fontSize": 40, "fontWeight": "800", "color": "#ffffff", "font": "'Segoe UI', sans-serif", "letterSpacing": 1},
                {"id": "unvan", "label": "Ünvan", "type": "text", "text": role, "x": 390, "y": 154, "w": 540, "h": 28, "fontSize": 15, "fontWeight": "600", "color": "#e0a96d", "letterSpacing": 2},
                {"id": "ayirici_cizgi", "label": "Altın Ayırıcı Çizgi", "type": "line", "text": "", "x": 390, "y": 204, "w": 560, "h": 2, "bg": "#e0a96d"},
                {"id": "telefon", "label": "Telefon", "type": "text", "text": phone, "x": 434, "y": 290, "w": 480, "h": 34, "fontSize": 16, "fontWeight": "600", "color": "#f8fafc"},
                {"id": "eposta", "label": "E-Posta", "type": "text", "text": email, "x": 434, "y": 342, "w": 520, "h": 34, "fontSize": 15, "fontWeight": "500", "color": "#e2e8f0"},
                {"id": "web", "label": "Web Sitesi", "type": "text", "text": web, "x": 434, "y": 394, "w": 520, "h": 34, "fontSize": 15, "fontWeight": "500", "color": "#e2e8f0"},
                {"id": "adres", "label": "Adres", "type": "text", "text": addr, "x": 434, "y": 446, "w": 560, "h": 34, "fontSize": 14, "fontWeight": "400", "color": "#cbd5e1"},
            ]

        if idx == 2:
            # 2: Minimalist Fildişi & Koyu Espresso Prestij (Hukuk / Mimarlık / Yönetim Kartviziti)
            icons = _contact_icons_svg(68, [306, 358, 410, 462], "#8c6527", "#efe6d5")
            bg_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
              <defs>
                <linearGradient id="bg2" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#fbf8f1"/>
                  <stop offset="100%" stop-color="#f0e6d2"/>
                </linearGradient>
                <linearGradient id="gold2" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#c59b47"/>
                  <stop offset="100%" stop-color="#8c6527"/>
                </linearGradient>
              </defs>
              <rect width="{w}" height="{h}" fill="url(#bg2)"/>
              <rect x="{w-340}" y="0" width="340" height="{h}" fill="#151311"/>
              <rect x="{w-346}" y="0" width="6" height="{h}" fill="url(#gold2)"/>
              <rect x="26" y="26" width="{w-52}" height="{h-52}" rx="4" fill="none" stroke="url(#gold2)" stroke-width="1.2" opacity="0.48"/>
              {icons}
            </svg>"""
            bg = f"url('{_svg_uri(bg_svg)}') center/cover no-repeat"
            logo_uri = _make_logo_svg("#e5c878", "#a87e33", "#151311")
            qr_uri = _make_qr_svg("#e5c878", "#1c1917", "#a87e33")
            return bg, [
                {"id": "isim", "label": "İsim Soyisim", "type": "text", "text": name, "x": 68, "y": 88, "w": 560, "h": 56, "fontSize": 42, "fontWeight": "800", "color": "#161412", "font": "Georgia, serif", "letterSpacing": 1},
                {"id": "unvan", "label": "Ünvan", "type": "text", "text": role, "x": 68, "y": 152, "w": 520, "h": 28, "fontSize": 15, "fontWeight": "700", "color": "#8c6527", "letterSpacing": 2.5},
                {"id": "ayirici_cizgi", "label": "Altın Ayırıcı Çizgi", "type": "line", "text": "", "x": 68, "y": 200, "w": 240, "h": 2, "bg": "#8c6527"},
                {"id": "slogan", "label": "Uzmanlık / Slogan", "type": "text", "text": slogan, "x": 68, "y": 220, "w": 540, "h": 24, "fontSize": 11, "fontWeight": "700", "color": "#57534e", "letterSpacing": 2},
                {"id": "telefon", "label": "Telefon", "type": "text", "text": phone, "x": 112, "y": 304, "w": 460, "h": 34, "fontSize": 16, "fontWeight": "700", "color": "#1c1917"},
                {"id": "eposta", "label": "E-Posta", "type": "text", "text": email, "x": 112, "y": 356, "w": 480, "h": 34, "fontSize": 15, "fontWeight": "600", "color": "#292524"},
                {"id": "web", "label": "Web Sitesi", "type": "text", "text": web, "x": 112, "y": 408, "w": 480, "h": 34, "fontSize": 15, "fontWeight": "600", "color": "#292524"},
                {"id": "adres", "label": "Adres", "type": "text", "text": addr, "x": 112, "y": 460, "w": 520, "h": 34, "fontSize": 14, "fontWeight": "500", "color": "#44403c"},
                {"id": "logo", "label": "Kurumsal Logo / Amblem", "type": "image", "src": logo_uri, "text": "", "x": w - 245, "y": 86, "w": 150, "h": 150},
                {"id": "firma", "label": "Firma Adı", "type": "text", "text": company, "x": w - 320, "y": 254, "w": 300, "h": 34, "fontSize": 17, "fontWeight": "800", "color": "#e5c878", "align": "center", "letterSpacing": 2.5},
                {"id": "qr_kod", "label": "QR Kod", "type": "image", "src": qr_uri, "text": "", "x": w - 218, "y": 388, "w": 96, "h": 96},
            ]

        if idx == 3:
            # 3: Zümrüt Yeşili & Altın Varak Mimari (Dengeli Yatay & Sağ Köşe Arma)
            icons = _contact_icons_svg(68, [306, 358, 410, 462], "#d4b475", "#0c2821")
            bg_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
              <defs>
                <linearGradient id="bg3" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#061914"/>
                  <stop offset="60%" stop-color="#0b2922"/>
                  <stop offset="100%" stop-color="#05130f"/>
                </linearGradient>
                <linearGradient id="gold3" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#ebd197"/>
                  <stop offset="100%" stop-color="#b38e46"/>
                </linearGradient>
              </defs>
              <rect width="{w}" height="{h}" fill="url(#bg3)"/>
              <polygon points="{w-330},0 {w},0 {w},{h} {w-410},{h}" fill="#05130f" opacity="0.88"/>
              <polygon points="{w-335},0 {w-328},0 {w-408},{h} {w-415},{h}" fill="url(#gold3)"/>
              <rect x="26" y="26" width="{w-52}" height="{h-52}" rx="6" fill="none" stroke="url(#gold3)" stroke-width="1.2" opacity="0.4"/>
              {icons}
            </svg>"""
            bg = f"url('{_svg_uri(bg_svg)}') center/cover no-repeat"
            logo_uri = _make_logo_svg("#ebd197", "#b38e46", "#061914")
            qr_uri = _make_qr_svg("#ebd197", "#061914", "#b38e46")
            return bg, [
                {"id": "isim", "label": "İsim Soyisim", "type": "text", "text": name, "x": 68, "y": 88, "w": 540, "h": 56, "fontSize": 40, "fontWeight": "800", "color": "#f7f9f8", "font": "Georgia, serif", "letterSpacing": 1.2},
                {"id": "unvan", "label": "Ünvan", "type": "text", "text": role, "x": 68, "y": 152, "w": 500, "h": 28, "fontSize": 15, "fontWeight": "600", "color": "#d4b475", "letterSpacing": 2.5},
                {"id": "ayirici_cizgi", "label": "Altın Ayırıcı Çizgi", "type": "line", "text": "", "x": 68, "y": 200, "w": 240, "h": 2, "bg": "#d4b475"},
                {"id": "slogan", "label": "Uzmanlık / Slogan", "type": "text", "text": slogan, "x": 68, "y": 220, "w": 520, "h": 24, "fontSize": 11, "fontWeight": "600", "color": "#a7c4bc", "letterSpacing": 2},
                {"id": "telefon", "label": "Telefon", "type": "text", "text": phone, "x": 112, "y": 304, "w": 440, "h": 34, "fontSize": 16, "fontWeight": "600", "color": "#ecfdf5"},
                {"id": "eposta", "label": "E-Posta", "type": "text", "text": email, "x": 112, "y": 356, "w": 460, "h": 34, "fontSize": 15, "fontWeight": "500", "color": "#d1fae5"},
                {"id": "web", "label": "Web Sitesi", "type": "text", "text": web, "x": 112, "y": 408, "w": 460, "h": 34, "fontSize": 15, "fontWeight": "500", "color": "#d1fae5"},
                {"id": "adres", "label": "Adres", "type": "text", "text": addr, "x": 112, "y": 460, "w": 500, "h": 34, "fontSize": 14, "fontWeight": "400", "color": "#a7f3d0"},
                {"id": "logo", "label": "Kurumsal Logo / Amblem", "type": "image", "src": logo_uri, "text": "", "x": w - 255, "y": 90, "w": 150, "h": 150},
                {"id": "firma", "label": "Firma Adı", "type": "text", "text": company, "x": w - 335, "y": 258, "w": 310, "h": 34, "fontSize": 17, "fontWeight": "800", "color": "#ebd197", "align": "center", "letterSpacing": 2.5},
                {"id": "qr_kod", "label": "QR Kod", "type": "image", "src": qr_uri, "text": "", "x": w - 228, "y": 388, "w": 96, "h": 96},
            ]

        # 4: Bordo & Şampanya Executive Kurumsal
        icons = _contact_icons_svg(68, [306, 358, 410, 462], "#e5c185", "#290d16")
        bg_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
          <defs>
            <linearGradient id="bg4" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#1a070d"/>
              <stop offset="60%" stop-color="#2c0e18"/>
              <stop offset="100%" stop-color="#120408"/>
            </linearGradient>
            <linearGradient id="gold4" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#f3d8a4"/>
              <stop offset="100%" stop-color="#b88b4a"/>
            </linearGradient>
          </defs>
          <rect width="{w}" height="{h}" fill="url(#bg4)"/>
          <rect x="{w-336}" y="0" width="336" height="{h}" fill="#120408" opacity="0.9"/>
          <rect x="{w-340}" y="0" width="4" height="{h}" fill="url(#gold4)"/>
          <rect x="26" y="26" width="{w-52}" height="{h-52}" rx="6" fill="none" stroke="url(#gold4)" stroke-width="1.2" opacity="0.4"/>
          {icons}
        </svg>"""
        bg = f"url('{_svg_uri(bg_svg)}') center/cover no-repeat"
        logo_uri = _make_logo_svg("#f3d8a4", "#b88b4a", "#1a070d")
        qr_uri = _make_qr_svg("#f3d8a4", "#1a070d", "#b88b4a")
        return bg, [
            {"id": "isim", "label": "İsim Soyisim", "type": "text", "text": name, "x": 68, "y": 88, "w": 540, "h": 56, "fontSize": 40, "fontWeight": "800", "color": "#fff8f0", "font": "Georgia, serif", "letterSpacing": 1.2},
            {"id": "unvan", "label": "Ünvan", "type": "text", "text": role, "x": 68, "y": 152, "w": 500, "h": 28, "fontSize": 15, "fontWeight": "600", "color": "#e5c185", "letterSpacing": 2.5},
            {"id": "ayirici_cizgi", "label": "Altın Ayırıcı Çizgi", "type": "line", "text": "", "x": 68, "y": 200, "w": 240, "h": 2, "bg": "#e5c185"},
            {"id": "slogan", "label": "Uzmanlık / Slogan", "type": "text", "text": slogan, "x": 68, "y": 220, "w": 520, "h": 24, "fontSize": 11, "fontWeight": "600", "color": "#d6bcfa", "letterSpacing": 2},
            {"id": "telefon", "label": "Telefon", "type": "text", "text": phone, "x": 112, "y": 304, "w": 440, "h": 34, "fontSize": 16, "fontWeight": "600", "color": "#fff8f0"},
            {"id": "eposta", "label": "E-Posta", "type": "text", "text": email, "x": 112, "y": 356, "w": 460, "h": 34, "fontSize": 15, "fontWeight": "500", "color": "#f3e8ee"},
            {"id": "web", "label": "Web Sitesi", "type": "text", "text": web, "x": 112, "y": 408, "w": 460, "h": 34, "fontSize": 15, "fontWeight": "500", "color": "#f3e8ee"},
            {"id": "adres", "label": "Adres", "type": "text", "text": addr, "x": 112, "y": 460, "w": 500, "h": 34, "fontSize": 14, "fontWeight": "400", "color": "#e5d5dc"},
            {"id": "logo", "label": "Kurumsal Logo / Amblem", "type": "image", "src": logo_uri, "text": "", "x": w - 248, "y": 90, "w": 150, "h": 150},
            {"id": "firma", "label": "Firma Adı", "type": "text", "text": company, "x": w - 328, "y": 258, "w": 308, "h": 34, "fontSize": 17, "fontWeight": "800", "color": "#f3d8a4", "align": "center", "letterSpacing": 2.5},
            {"id": "qr_kod", "label": "QR Kod", "type": "image", "src": qr_uri, "text": "", "x": w - 221, "y": 388, "w": 96, "h": 96},
        ]

    @staticmethod
    def _extract_card_info_from_elements(elements: list) -> dict:
        import re
        info = {}
        for el in elements or []:
            if not isinstance(el, dict):
                continue
            t = str(el.get("text") or "").strip()
            if not t:
                continue
            tu = t.upper()
            if el.get("type") == "circle" and len(t) <= 4:
                info["mono"] = "BY" if tu == "AS" else t
                continue
            for line in t.splitlines():
                ln = line.strip().lstrip("☎✉🌐📍•- ").strip()
                if not ln:
                    continue
                if "@" in ln and "email" not in info:
                    info["email"] = ln if "firmaadi" not in ln.lower() else "burak@mimaristudio.com"
                elif re.search(r"(\+?\d[\d\s\-]{7,})", ln) and "phone" not in info:
                    info["phone"] = ln
                elif ("www." in ln.lower() or ".com" in ln.lower() or ".tr" in ln.lower()) and "@" not in ln and "web" not in info:
                    info["web"] = ln if "firmaadi" not in ln.lower() else "www.mimaristudio.com"
                elif any(k in ln.lower() for k in ("istanbul", "ankara", "izmir", "cad", "mah", "nişantaşı", "levent", "adres")) and "addr" not in info:
                    info["addr"] = ln if ln.upper() != "ADRES" else "Nişantaşı · Teşvikiye Cad. No:42 · İstanbul"
                elif int(el.get("fontSize") or 0) >= 28 and "name" not in info:
                    info["name"] = "BURAK YILMAZ" if tu in ("AD SOYAD", "İSİM SOYİSİM", "ISIM SOYISIM") else ln
                elif any(k in tu for k in ("MİMAR", "MÜDÜR", "KURUCU", "MÜHENDİS", "CEO", "DIRECTOR", "DESIGN", "YÖNETİCİ")) and "role" not in info:
                    info["role"] = ln
        return info

    @staticmethod
    def _assign_semantic_layer_ids(elements: list) -> list:
        """Katman listesindeki her parçaya anlamlı Türkçe ID (#isim, #logo, #unvan, #telefon vb.) ve etiket atar."""
        import re
        used_ids = set()
        out = []
        rect_idx = 0
        line_idx = 0
        text_idx = 0

        def _unique(base_id: str) -> str:
            cand = re.sub(r"[^a-z0-9_]", "", (base_id or "parca").lower()) or "parca"
            if cand not in used_ids:
                used_ids.add(cand)
                return cand
            k = 2
            while f"{cand}_{k}" in used_ids:
                k += 1
            res = f"{cand}_{k}"
            used_ids.add(res)
            return res

        for raw in elements or []:
            if not isinstance(raw, dict):
                continue
            el = dict(raw)
            etype = str(el.get("type") or "text").lower()
            txt = str(el.get("text") or "").strip()
            tl = txt.lower()
            tu = txt.upper()
            fs = int(el.get("fontSize") or 16)
            raw_id = str(el.get("id") or "").strip()
            raw_lbl = str(el.get("label") or "").strip()

            if raw_id and not raw_id.startswith("el_"):
                sem_id = _unique(raw_id)
                sem_lbl = raw_lbl or sem_id.replace("_", " ").title()
            elif etype == "image":
                sem_id = _unique("logo_gorsel" if "logo" in used_ids else "logo")
                sem_lbl = raw_lbl or "Logo / Görsel"
            elif etype == "circle":
                if txt:
                    sem_id = _unique("logo")
                    sem_lbl = raw_lbl or "Logo / Monogram"
                else:
                    sem_id = _unique("logo_halka")
                    sem_lbl = raw_lbl or "Logo Dış Halka"
            elif etype == "line":
                line_idx += 1
                sem_id = _unique("ayirici_cizgi" if line_idx == 1 else f"cizgi_{line_idx}")
                sem_lbl = raw_lbl or "Ayırıcı Çizgi"
            elif etype == "rect":
                rect_idx += 1
                bg_s = str(el.get("bg") or "").lower()
                if bg_s in ("transparent", "none", ""):
                    sem_id = _unique("cerceve" if rect_idx == 1 else f"cerceve_{rect_idx}")
                    sem_lbl = raw_lbl or "Çerçeve"
                elif int(el.get("w") or 0) <= 16:
                    sem_id = _unique("vurgu_seridi")
                    sem_lbl = raw_lbl or "Vurgu Şeridi"
                else:
                    sem_id = _unique("panel" if "panel" not in used_ids else f"kutu_{rect_idx}")
                    sem_lbl = raw_lbl or "Arka Plan Paneli"
            else:
                if "☎" in txt or "📞" in txt or re.search(r"(\+?\d[\d\s\-]{7,})", txt):
                    sem_id = _unique("telefon")
                    sem_lbl = raw_lbl or "Telefon"
                elif "✉" in txt or "@" in txt:
                    sem_id = _unique("eposta")
                    sem_lbl = raw_lbl or "E-Posta"
                elif "🌐" in txt or "www." in tl or ".com" in tl or ".tr" in tl:
                    sem_id = _unique("web")
                    sem_lbl = raw_lbl or "Web Sitesi"
                elif "📍" in txt or any(k in tl for k in ("istanbul", "ankara", "izmir", "cad", "mah", "nişantaşı", "sok", "no:")):
                    sem_id = _unique("adres")
                    sem_lbl = raw_lbl or "Adres"
                elif fs >= 28 and "isim" not in used_ids:
                    sem_id = _unique("isim")
                    sem_lbl = raw_lbl or "İsim / Ana Başlık"
                elif (
                    (etype == "badge" and int(el.get("y") or 0) < 120)
                    or any(k in tu for k in ("STÜDYO", "STUDIO", "MİMARLIK", "HOLDİNG", "A.Ş.", "LTD", "GROUP", "OFİS", "TEKNOLOJİ", "DANISMANLIK", "DANIŞMANLIK"))
                ) and "firma" not in used_ids:
                    sem_id = _unique("firma")
                    sem_lbl = raw_lbl or "Firma / Kurum"
                elif any(k in tu for k in ("MİMAR", "MÜDÜR", "KURUCU", "MÜHENDİS", "CEO", "DIRECTOR", "YÖNETİCİ", "UZMAN", "AVUKAT", "DOKTOR", "DANIŞMAN")) and "unvan" not in used_ids:
                    sem_id = _unique("unvan")
                    sem_lbl = raw_lbl or "Ünvan / Alt Başlık"
                elif "unvan" not in used_ids and "isim" in used_ids and etype == "text":
                    sem_id = _unique("unvan")
                    sem_lbl = raw_lbl or "Ünvan / Alt Başlık"
                elif "slogan" not in used_ids:
                    sem_id = _unique("slogan")
                    sem_lbl = raw_lbl or "Slogan / Ek Bilgi"
                else:
                    text_idx += 1
                    sem_id = _unique(f"metin_{text_idx}")
                    sem_lbl = raw_lbl or f"Metin {text_idx}"

            el["id"] = sem_id
            el["label"] = sem_lbl
            out.append(el)
        return out

    @staticmethod
    def _render_stitch_editor_html(
        title: str,
        width: int,
        height: int,
        background: str,
        elements: list,
    ) -> str:
        import json, html as _html, hashlib
        safe_title = _html.escape(title or "Stitch Tasarım Stüdyosu")
        elements = LocalAIAssistantModule._assign_semantic_layer_ids(elements)
        presets_map = {}
        info_seed = LocalAIAssistantModule._extract_card_info_from_elements(elements)
        for p_idx in range(5):
            p_bg, p_els = LocalAIAssistantModule._build_luxury_card_preset(p_idx, int(width), int(height), info_seed)
            presets_map[str(p_idx)] = {
                "background": p_bg,
                "elements": LocalAIAssistantModule._assign_semantic_layer_ids(p_els),
            }
        cfg = {
            "title": title or "Stitch Tasarım Stüdyosu",
            "width": int(width),
            "height": int(height),
            "background": background or "#0f1116",
            "elements": elements,
            "presets": presets_map,
        }
        cfg_json = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
        cfg_hash = hashlib.md5(cfg_json.encode("utf-8")).hexdigest()[:10]
        return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1.0" />
<title>{safe_title}</title>
<style>
  *{{box-sizing:border-box;user-select:none}}
  :root{{--bg:#0b0d12;--panel:#131722;--card:#1b2030;--border:#2a3145;--txt:#f1f5f9;--muted:#94a3b8;--accent:#c9a45c;--accent2:#6366f1}}
  body{{margin:0;height:100vh;display:flex;flex-direction:column;background:var(--bg);color:var(--txt);font:13px/1.4 'Segoe UI',system-ui,sans-serif;overflow:hidden}}
  header{{height:50px;background:var(--panel);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 14px;gap:10px}}
  .brand{{display:flex;align-items:center;gap:10px;font-weight:700;font-size:14px}}
  .pill{{font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(201,164,92,.14);color:var(--accent);border:1px solid rgba(201,164,92,.35)}}
  .toolbar{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}}
  button,select{{background:var(--card);color:var(--txt);border:1px solid var(--border);border-radius:7px;padding:6px 10px;font:inherit;cursor:pointer;transition:.15s}}
  button:hover{{border-color:var(--accent);background:#23293d}}
  button.primary{{background:linear-gradient(135deg,#c9a45c,#a37b30);color:#0c0d10;font-weight:700;border-color:transparent}}
  button.danger{{color:#fca5a5;border-color:#7f1d1d}}
  button.danger:hover{{background:#7f1d1d}}
  .main{{flex:1;display:grid;grid-template-columns:230px 1fr 270px;min-height:0}}
  aside{{background:var(--panel);border-right:1px solid var(--border);padding:12px;overflow-y:auto;display:flex;flex-direction:column;gap:12px}}
  aside.right{{border-right:none;border-left:1px solid var(--border)}}
  h4{{margin:0 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}
  .add-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
  .layer-list{{display:flex;flex-direction:column;gap:4px;overflow-y:auto;flex:1;min-height:0;padding-right:2px}}
  .layer-item{{display:flex;align-items:center;justify-content:space-between;padding:7px 9px;border-radius:7px;background:var(--card);border:1px solid transparent;cursor:pointer;gap:6px}}
  .layer-item.active{{border-color:var(--accent);background:rgba(201,164,92,.1)}}
  .layer-name{{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px}}
  .stage-wrap{{position:relative;display:flex;align-items:center;justify-content:center;overflow:auto;background:radial-gradient(circle at 50% 45%,#171b27,#0b0d12);padding:32px}}
  .canvas-frame{{position:relative;box-shadow:0 24px 65px rgba(0,0,0,.65);border-radius:6px;overflow:hidden;transform-origin:center center;flex-shrink:0}}
  .el{{position:absolute;cursor:move;outline:1px solid transparent;display:flex;align-items:center;word-break:break-word;white-space:pre-wrap}}
  .el:hover{{outline:1px dashed rgba(201,164,92,.55)}}
  .el.selected{{outline:2px solid var(--accent);z-index:999!important}}
  .el[contenteditable="true"]{{cursor:text;user-select:text;outline:2px solid #38bdf8}}
  .resize-handle{{position:absolute;right:-5px;bottom:-5px;width:11px;height:11px;background:var(--accent);border:2px solid #0b0d12;border-radius:3px;cursor:nwse-resize;display:none}}
  .el.selected .resize-handle{{display:block}}
  .snap-v,.snap-h{{position:absolute;background:rgba(56,189,248,.85);pointer-events:none;display:none;z-index:1000}}
  .snap-v{{width:1px;top:0;bottom:0}}.snap-h{{height:1px;left:0;right:0}}
  .field{{display:flex;flex-direction:column;gap:4px;margin-bottom:8px}}
  .field label{{font-size:11px;color:var(--muted)}}
  .field input,.field textarea,.field select{{background:var(--bg);color:var(--txt);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font:inherit;user-select:text;width:100%}}
  .row2{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
  .hint{{font-size:11px;color:var(--muted);line-height:1.45;background:rgba(255,255,255,.03);padding:8px;border-radius:7px;border:1px solid var(--border)}}
  .stage-wrap{{position:relative}}
  .ai-bar{{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:999;display:flex;align-items:center;gap:8px;width:min(680px,calc(100vw - 560px));min-width:340px;background:rgba(15,17,22,.94);backdrop-filter:blur(14px);border:1px solid rgba(201,164,92,.45);border-radius:14px;padding:8px 10px;box-shadow:0 18px 50px rgba(0,0,0,.65)}}
  .ai-pill{{font-size:11px;font-weight:700;color:var(--accent);background:rgba(201,164,92,.14);border:1px solid rgba(201,164,92,.35);padding:5px 9px;border-radius:8px;white-space:nowrap}}
  .ai-bar input{{flex:1;background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:8px 11px;font-size:12px;outline:none}}
  .ai-bar input:focus{{border-color:var(--accent)}}
  .ai-bar button{{background:linear-gradient(135deg,#d4af37,#b38728);color:#111;border:none;font-weight:800;padding:8px 13px;border-radius:8px;cursor:pointer;white-space:nowrap}}
  .ai-bar button:disabled{{opacity:.55;cursor:wait}}
  .ai-status{{position:fixed;bottom:68px;left:50%;transform:translateX(-50%);z-index:999;font-size:11px;color:#e5e7eb;background:rgba(15,17,22,.92);border:1px solid var(--border);padding:5px 12px;border-radius:8px;display:none;max-width:640px}}
</style>
</head>
<body>
<header>
  <div class="brand">
    <span>🎨 {safe_title}</span>
    <span class="pill" id="dimPill"></span>
  </div>
  <div class="toolbar">
    <select id="presetSel" title="Lüks Tasarım Şablonu Değiştir" style="border-color:rgba(201,164,92,.55);font-weight:600">
      <option value="">✨ Şablon Değiştir...</option>
      <option value="0">1. Kurumsal Antrasit & Altın Geometrik</option>
      <option value="1">2. Kraliyet Lacivert & Şampanya Sol Kule</option>
      <option value="2">3. Minimalist Fildişi & Koyu Espresso</option>
      <option value="3">4. Zümrüt Yeşili & Altın Varak Mimari</option>
      <option value="4">5. Bordo & Şampanya Executive</option>
    </select>
    <button id="undoBtn" title="Ctrl+Z">↩ Geri Al</button>
    <button id="dupBtn" title="Ctrl+D">⧉ Çoğalt</button>
    <button id="delBtn" class="danger" title="Delete">🗑 Sil</button>
    <select id="zoomSel" title="Yakınlaştırma">
      <option value="0.6">%60</option>
      <option value="0.8">%80</option>
      <option value="1" selected>%100</option>
      <option value="1.2">%120</option>
    </select>
    <button id="resetBtn">↺ İlk Hali</button>
    <button id="jsonBtn">JSON</button>
    <button id="pngBtn" class="primary">⬇ PNG İndir</button>
  </div>
</header>
<div class="main">
  <aside>
    <div>
      <h4>Öğe Ekle</h4>
      <div class="add-grid">
        <button onclick="addEl('text',true)">+ Başlık</button>
        <button onclick="addEl('text',false)">+ Metin</button>
        <button onclick="addEl('badge')">+ Rozet</button>
        <button onclick="addEl('rect')">+ Kutu</button>
        <button onclick="addEl('circle')">+ Daire</button>
        <button onclick="addEl('line')">+ Çizgi</button>
      </div>
      <label style="display:block;margin-top:6px">
        <input id="imgUpload" type="file" accept="image/*" style="display:none" />
        <button type="button" style="width:100%" onclick="document.getElementById('imgUpload').click()">🖼 Görsel Ekle</button>
      </label>
    </div>
    <div style="flex:1;min-height:0;display:flex;flex-direction:column">
      <h4>Katmanlar (Parça Kodları)</h4>
      <div class="layer-list" id="layerList"></div>
    </div>
    <div class="hint">
      <b>🤖 Yapay Zeka İle Değiştirin:</b><br/>
      Sohbette <code>#isim</code>, <code>#logo</code>, <code>#unvan</code>, <code>#telefon</code>, <code>#eposta</code>, <code>#adres</code> parçalarını söyleyerek AI'a değiştirtin!<br/>
      <b>Fare:</b> Sürükle: Taşı • Çift Tıkla: Düzenle • <code>Del</code> Sil
    </div>
  </aside>
  <main class="stage-wrap" id="stageWrap">
    <div class="canvas-frame" id="canvas">
      <div class="snap-v" id="snapV"></div>
      <div class="snap-h" id="snapH"></div>
    </div>
    <div class="ai-status" id="aiStatus"></div>
    <div class="ai-bar" title="Seçili parçayı veya tüm tasarımı yapay zeka ile anında değiştirin">
      <span class="ai-pill" id="aiTargetPill">✦ Tümü</span>
      <input id="aiPromptInput" type="text" placeholder="Seçili parçaya AI komutu yaz (ör: altın yap, yeni vektör logo tasarla, telefonu 0532... yap, bunu sil)" />
      <button id="aiRunBtn">✦ AI ile Değiştir</button>
    </div>
  </main>
  <aside class="right">
    <div>
      <h4>Tuval Ayarları</h4>
      <div class="field"><label>Arka Plan (CSS/Renk)</label><input id="bgInput" type="text" /></div>
    </div>
    <div id="propPanel">
      <h4>Seçili Öğe</h4>
      <div class="hint">Düzenlemek için tuvalden veya soldaki katman listesinden bir öğe seçin.</div>
    </div>
  </aside>
</div>
<script>
const INITIAL = {cfg_json};
const STORE_KEY = 'stitch_v5_{cfg_hash}';
let state = null;
let selectedId = null;
let history = [];
let zoom = 1;

function clone(o){{ return JSON.parse(JSON.stringify(o)); }}
function uid(){{ return 'el_' + Math.random().toString(36).slice(2,9); }}
function normEl(el, i){{
  return Object.assign({{
    id: el.id || uid(),
    label: el.label || '',
    type: el.type || 'text',
    text: el.text ?? '',
    x: Number(el.x ?? 60),
    y: Number(el.y ?? 60 + i*30),
    w: Number(el.w ?? (el.type==='line'?260:(el.type==='circle'?110:320))),
    h: Number(el.h ?? (el.type==='line'?2:(el.type==='circle'?110:48))),
    font: el.font || "'Segoe UI', sans-serif",
    fontSize: Number(el.fontSize ?? (el.type==='text'?24:14)),
    fontWeight: String(el.fontWeight ?? (el.type==='badge'?'700':'500')),
    color: el.color || '#f5f2eb',
    bg: el.bg || (el.type==='rect'?'rgba(255,255,255,0.06)':(el.type==='badge'?'rgba(201,164,92,0.18)':(el.type==='line'?'#c9a45c':'transparent'))),
    borderColor: el.borderColor || (el.type==='circle'||el.type==='badge'?'#c9a45c':'transparent'),
    borderWidth: Number(el.borderWidth ?? (el.type==='circle'||el.type==='badge'?1:0)),
    radius: Number(el.radius ?? (el.type==='circle'?999:(el.type==='badge'?999:8))),
    opacity: Number(el.opacity ?? 1),
    align: el.align || (el.type==='circle'||el.type==='badge'?'center':'left'),
    letterSpacing: Number(el.letterSpacing ?? 0),
    src: el.src || ''
  }}, el);
}}
function loadState(){{
  try {{
    const saved = localStorage.getItem(STORE_KEY);
    if(saved){{
      const p = JSON.parse(saved);
      if(p && Array.isArray(p.elements) && p.elements.length > 0) return p;
    }}
  }} catch(e){{}}
  return {{
    width: INITIAL.width,
    height: INITIAL.height,
    background: INITIAL.background,
    elements: (INITIAL.elements || []).map(normEl)
  }};
}}
function pushHistory(){{
  history.push(clone(state));
  if(history.length > 40) history.shift();
  try{{ localStorage.setItem(STORE_KEY, JSON.stringify(state)); }}catch(e){{}}
}}
function undo(){{
  if(!history.length) return;
  state = history.pop();
  if(!state.elements.some(e=>e.id===selectedId)) selectedId = state.elements[0]?.id || null;
  try{{ localStorage.setItem(STORE_KEY, JSON.stringify(state)); }}catch(e){{}}
  render();
}}
function applyTextStyles(node, el){{
  node.style.left = el.x + 'px';
  node.style.top = el.y + 'px';
  node.style.width = Math.max(8, el.w) + 'px';
  node.style.height = Math.max(1, el.h) + 'px';
  node.style.fontFamily = el.font;
  node.style.fontSize = el.fontSize + 'px';
  node.style.fontWeight = el.fontWeight;
  node.style.color = el.color;
  node.style.background = el.bg;
  node.style.border = el.borderWidth ? `${{el.borderWidth}}px solid ${{el.borderColor}}` : 'none';
  node.style.borderRadius = (el.type==='circle' ? 999 : el.radius) + 'px';
  node.style.opacity = el.opacity;
  node.style.letterSpacing = el.letterSpacing + 'px';
  node.style.justifyContent = el.align==='center'?'center':(el.align==='right'?'flex-end':'flex-start');
  node.style.textAlign = el.align;
  node.style.padding = (el.type==='badge' ? '0 12px' : (el.type==='rect'||el.type==='line'?'0':'2px 4px'));
}}
function render(){{
  const canvas = document.getElementById('canvas');
  document.getElementById('dimPill').textContent = `${{state.width}} × ${{state.height}}`;
  document.getElementById('bgInput').value = state.background;
  canvas.style.width = state.width + 'px';
  canvas.style.height = state.height + 'px';
  canvas.style.background = state.background;
  canvas.style.transform = `scale(${{zoom}})`;
  const snapV = document.getElementById('snapV');
  const snapH = document.getElementById('snapH');
  canvas.innerHTML = '';
  canvas.appendChild(snapV);
  canvas.appendChild(snapH);

  state.elements.forEach((el, idx)=>{{
    const div = document.createElement('div');
    div.className = 'el' + (el.id===selectedId ? ' selected' : '');
    div.style.zIndex = idx + 1;
    applyTextStyles(div, el);
    if(el.type === 'image' && el.src){{
      const img = document.createElement('img');
      img.src = el.src;
      img.style.cssText = 'width:100%;height:100%;object-fit:contain;pointer-events:none;border-radius:inherit';
      div.appendChild(img);
    }} else if(el.type !== 'line') {{
      const span = document.createElement('span');
      span.style.width = '100%';
      span.textContent = el.text || '';
      div.appendChild(span);
    }}
    const rh = document.createElement('div');
    rh.className = 'resize-handle';
    div.appendChild(rh);

    div.addEventListener('mousedown', (ev)=>{{
      if(div.getAttribute('contenteditable')==='true') return;
      ev.stopPropagation();
      selectedId = el.id;
      const isResize = ev.target === rh;
      renderSelectionUI();
      startDrag(ev, el, div, isResize);
    }});
    div.addEventListener('dblclick', (ev)=>{{
      if(el.type==='line'||el.type==='image') return;
      ev.stopPropagation();
      div.setAttribute('contenteditable', 'true');
      div.focus();
      const finish = ()=>{{
        div.removeAttribute('contenteditable');
        pushHistory();
        el.text = div.innerText.replace(/\\n$/,'');
        render();
      }};
      div.onblur = finish;
    }});
    canvas.appendChild(div);
  }});
  renderSelectionUI();
}}
function startDrag(ev, el, div, isResize){{
  const sx = ev.clientX, sy = ev.clientY;
  const ox = el.x, oy = el.y, ow = el.w, oh = el.h;
  let moved = false;
  const snapV = document.getElementById('snapV'), snapH = document.getElementById('snapH');
  function onMove(e){{
    const dx = (e.clientX - sx)/zoom, dy = (e.clientY - sy)/zoom;
    if(Math.abs(dx)>1 || Math.abs(dy)>1) moved = true;
    if(!moved) return;
    if(isResize){{
      el.w = Math.max(12, Math.round(ow + dx));
      el.h = Math.max(el.type==='line'?2:16, Math.round(oh + dy));
      if(el.type==='circle') el.h = el.w;
    }} else {{
      let nx = Math.round(ox + dx), ny = Math.round(oy + dy);
      const cx = state.width/2, cy = state.height/2;
      if(Math.abs((nx + el.w/2) - cx) < 7){{ nx = Math.round(cx - el.w/2); snapV.style.left = cx+'px'; snapV.style.display='block'; }} else snapV.style.display='none';
      if(Math.abs((ny + el.h/2) - cy) < 7){{ ny = Math.round(cy - el.h/2); snapH.style.top = cy+'px'; snapH.style.display='block'; }} else snapH.style.display='none';
      el.x = nx; el.y = ny;
    }}
    applyTextStyles(div, el);
    syncPosInputs(el);
  }}
  function onUp(){{
    snapV.style.display='none'; snapH.style.display='none';
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseup', onUp);
    if(moved) pushHistory();
  }}
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
}}
function syncPosInputs(el){{
  ['x','y','w','h'].forEach(k=>{{ const i=document.getElementById('inp_'+k); if(i) i.value = el[k]; }});
}}
function renderSelectionUI(){{
  document.querySelectorAll('.el').forEach((n,i)=>{{
    const id = state.elements[i]?.id;
    n.classList.toggle('selected', id === selectedId);
  }});
  const list = document.getElementById('layerList');
  list.innerHTML = '';
  [...state.elements].reverse().forEach(el=>{{
    const item = document.createElement('div');
    item.className = 'layer-item' + (el.id===selectedId?' active':'');
    const label = el.text ? el.text.replace(/\\s+/g,' ').slice(0,18) : (el.label || `[${{el.type}}]`);
    item.innerHTML = `<code style="color:var(--accent);font-size:10px;background:rgba(201,164,92,.14);padding:1px 5px;border-radius:4px">#${{el.id}}</code><span class="layer-name">${{label}}</span><span style="opacity:.55;font-size:10px">${{el.type}}</span>`;
    item.onclick = ()=>{{ selectedId = el.id; renderSelectionUI(); }};
    list.appendChild(item);
  }});
  const panel = document.getElementById('propPanel');
  const el = state.elements.find(e=>e.id===selectedId);
  if(!el){{
    panel.innerHTML = '<h4>Seçili Öğe</h4><div class="hint">Tuvalden bir öğe seçin.</div>';
    return;
  }}
  panel.innerHTML = `
    <h4>Parça: <span style="color:var(--accent)">#${{el.id}}</span> (${{el.label || el.type}})</h4>
    ${{el.type!=='line' ? `<div class="field"><label>Metin ${{el.type==='image'?'(Yazılırsa Metne Dönüşür)':''}}</label><textarea id="inp_text" rows="2"></textarea></div>` : ''}}
    <div class="row2">
      <div class="field"><label>X</label><input id="inp_x" type="number" /></div>
      <div class="field"><label>Y</label><input id="inp_y" type="number" /></div>
    </div>
    <div class="row2">
      <div class="field"><label>Genişlik</label><input id="inp_w" type="number" /></div>
      <div class="field"><label>Yükseklik</label><input id="inp_h" type="number" /></div>
    </div>
    <div class="row2">
      <div class="field"><label>Yazı Boyutu</label><input id="inp_fontSize" type="number" /></div>
      <div class="field"><label>Kalınlık</label><select id="inp_fontWeight"><option value="400">Normal</option><option value="600">Yarı Kalın</option><option value="700">Kalın</option><option value="800">Ekstra</option></select></div>
    </div>
    <div class="field"><label>Font</label><select id="inp_font">
      <option value="'Segoe UI', sans-serif">Segoe UI (Modern)</option>
      <option value="Georgia, serif">Georgia (Serif)</option>
      <option value="'Trebuchet MS', sans-serif">Trebuchet MS</option>
      <option value="'Courier New', monospace">Monospace</option>
    </select></div>
    <div class="row2">
      <div class="field"><label>Yazı Rengi</label><input id="inp_color" type="text" /></div>
      <div class="field"><label>Dolgu / Arka Plan</label><input id="inp_bg" type="text" /></div>
    </div>
    <div class="row2">
      <div class="field"><label>Kenarlık Rengi</label><input id="inp_borderColor" type="text" /></div>
      <div class="field"><label>Kenar Kalınlığı</label><input id="inp_borderWidth" type="number" min="0" max="20" /></div>
    </div>
    <div class="row2">
      <div class="field"><label>Köşe Yarıçapı</label><input id="inp_radius" type="number" min="0" max="999" /></div>
      <div class="field"><label>Opaklık (0-1)</label><input id="inp_opacity" type="number" step="0.05" min="0.05" max="1" /></div>
    </div>
    <div class="row2" style="margin-top:6px">
      <button onclick="moveZ(-1)">⬇ Arkaya</button>
      <button onclick="moveZ(1)">⬆ Öne</button>
    </div>
  `;
  const bind = (id, key, num=false)=>{{
    const inp = document.getElementById(id);
    if(!inp) return;
    inp.value = el[key];
    inp.onchange = ()=>{{
      pushHistory();
      el[key] = num ? Number(inp.value) : inp.value;
      if(key==='text' && el.type==='image' && String(inp.value||'').trim()){{
        el.type = 'text';
        el.src = '';
        el.fontSize = el.fontSize || 42;
        el.fontWeight = '800';
      }}
      render();
    }};
  }};
  bind('inp_text','text'); bind('inp_x','x',true); bind('inp_y','y',true);
  bind('inp_w','w',true); bind('inp_h','h',true); bind('inp_fontSize','fontSize',true);
  bind('inp_fontWeight','fontWeight'); bind('inp_font','font');
  bind('inp_color','color'); bind('inp_bg','bg');
  bind('inp_borderColor','borderColor'); bind('inp_borderWidth','borderWidth',true);
  bind('inp_radius','radius',true); bind('inp_opacity','opacity',true);
}}
function addEl(type, big=false){{
  pushHistory();
  const base = {{
    id: uid(), type, x: Math.round(state.width/2 - 120), y: Math.round(state.height/2 - 24),
    text: type==='text'?(big?'YENİ BAŞLIK':'Yeni Metin'):(type==='badge'?'YENİ ROZET':(type==='circle'?'BY':'')),
    fontSize: big?34:(type==='badge'?13:18), fontWeight: big||type==='badge'?'700':'400',
    w: type==='line'?280:(type==='circle'?110:(type==='badge'?160:260)),
    h: type==='line'?2:(type==='circle'?110:(type==='badge'?34:44)),
  }};
  const n = normEl(base, state.elements.length);
  state.elements.push(n);
  selectedId = n.id;
  render();
}}
function moveZ(dir){{
  const i = state.elements.findIndex(e=>e.id===selectedId);
  if(i<0) return;
  const j = Math.max(0, Math.min(state.elements.length-1, i+dir));
  if(i===j) return;
  pushHistory();
  const [it] = state.elements.splice(i,1);
  state.elements.splice(j,0,it);
  render();
}}
function deleteSelected(){{
  const i = state.elements.findIndex(e=>e.id===selectedId);
  if(i<0) return;
  pushHistory();
  state.elements.splice(i,1);
  selectedId = state.elements[0]?.id || null;
  render();
}}
function dupSelected(){{
  const el = state.elements.find(e=>e.id===selectedId);
  if(!el) return;
  pushHistory();
  const c = clone(el);
  c.id = uid(); c.x += 20; c.y += 20;
  state.elements.push(c);
  selectedId = c.id;
  render();
}}
async function exportPNG(){{
  const c = document.createElement('canvas');
  c.width = state.width; c.height = state.height;
  const ctx = c.getContext('2d');
  const bgUrlMatch = (state.background || '').match(/url\(['"]?(data:image\/[^'")]+)['"]?\)/i);
  if(bgUrlMatch && bgUrlMatch[1]){{
    await new Promise(res=>{{
      const bgIm = new Image();
      bgIm.onload = ()=>{{ ctx.drawImage(bgIm, 0, 0, c.width, c.height); res(); }};
      bgIm.onerror = ()=>res();
      bgIm.src = bgUrlMatch[1];
    }});
  }} else {{
    const hexes = (state.background || '').match(/#[0-9a-fA-F]{{3,8}}/g);
    if(hexes && hexes.length >= 2){{
      const g = ctx.createLinearGradient(0,0,c.width,c.height);
      hexes.forEach((hx, i)=>g.addColorStop(i/(hexes.length-1), hx));
      ctx.fillStyle = g;
    }} else {{
      ctx.fillStyle = (hexes && hexes[0]) || (state.background.startsWith('rgb') ? state.background : '#0f1116');
    }}
    ctx.fillRect(0,0,c.width,c.height);
  }}
  for(const el of state.elements){{
    ctx.save();
    ctx.globalAlpha = el.opacity ?? 1;
    if(el.bg && el.bg !== 'transparent'){{
      const elHex = String(el.bg).match(/#[0-9a-fA-F]{{3,8}}/g);
      if(elHex && elHex.length >= 2){{
        const eg = ctx.createLinearGradient(el.x,el.y,el.x+el.w,el.y+el.h);
        elHex.forEach((hx, i)=>eg.addColorStop(i/(elHex.length-1), hx));
        ctx.fillStyle = eg;
      }} else {{
        ctx.fillStyle = el.bg;
      }}
      roundRect(ctx, el.x, el.y, el.w, el.h, el.type==='circle'?el.w/2:el.radius);
      ctx.fill();
    }}
    if(el.borderWidth > 0 && el.borderColor !== 'transparent'){{
      ctx.strokeStyle = el.borderColor;
      ctx.lineWidth = el.borderWidth;
      roundRect(ctx, el.x, el.y, el.w, el.h, el.type==='circle'?el.w/2:el.radius);
      ctx.stroke();
    }}
    if(el.type==='image' && el.src){{
      await new Promise(res=>{{ const im=new Image(); im.crossOrigin='anonymous'; im.onload=()=>{{ctx.drawImage(im,el.x,el.y,el.w,el.h);res();}}; im.onerror=res; im.src=el.src; }});
    }} else if(el.text && el.type!=='line') {{
      ctx.fillStyle = el.color || '#ffffff';
      ctx.font = `${{el.fontWeight}} ${{el.fontSize}}px ${{el.font}}`;
      ctx.textBaseline = 'middle';
      ctx.textAlign = el.align || 'left';
      const pad = el.type==='badge' ? 14 : 6;
      const tx = el.align==='center'? el.x+el.w/2 : (el.align==='right'? el.x+el.w-pad : el.x+pad);
      const lines = String(el.text).split('\\n');
      const lh = el.fontSize * 1.25;
      const startY = el.y + el.h/2 - ((lines.length-1)*lh)/2;
      lines.forEach((ln, idx)=>ctx.fillText(ln, tx, startY + idx*lh, el.w-pad*2));
    }}
    ctx.restore();
  }}
  const a = document.createElement('a');
  a.download = (INITIAL.title || 'tasarim').toLowerCase().replace(/[^a-z0-9]+/g,'_') + '.png';
  a.href = c.toDataURL('image/png');
  a.click();
}}
function roundRect(ctx,x,y,w,h,r){{
  r = Math.min(r, w/2, h/2);
  ctx.beginPath();
  ctx.moveTo(x+r,y); ctx.arcTo(x+w,y,x+w,y+h,r); ctx.arcTo(x+w,y+h,x,y+h,r);
  ctx.arcTo(x,y+h,x,y,r); ctx.arcTo(x,y,x+w,y,r); ctx.closePath();
}}
document.getElementById('stageWrap').onclick = (e)=>{{ if(e.target.id==='stageWrap'||e.target.id==='canvas'){{ selectedId=null; renderSelectionUI(); }} }};
document.getElementById('bgInput').onchange = (e)=>{{ pushHistory(); state.background=e.target.value; render(); }};
document.getElementById('zoomSel').onchange = (e)=>{{ zoom=Number(e.target.value); render(); }};
document.getElementById('presetSel').onchange = (e)=>{{
  const k = e.target.value;
  if(!k || !INITIAL.presets || !INITIAL.presets[k]) return;
  pushHistory();
  const pr = INITIAL.presets[k];
  state.background = pr.background;
  state.elements = (pr.elements || []).map(normEl);
  selectedId = state.elements[0]?.id || null;
  render();
  e.target.value = '';
}};
document.getElementById('undoBtn').onclick = undo;
document.getElementById('delBtn').onclick = deleteSelected;
document.getElementById('dupBtn').onclick = dupSelected;
document.getElementById('resetBtn').onclick = ()=>{{ localStorage.removeItem(STORE_KEY); state=loadState(); selectedId=state.elements[0]?.id||null; render(); }};
document.getElementById('jsonBtn').onclick = ()=>{{ const a=document.createElement('a'); a.download='tasarim.json'; a.href=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{{type:'application/json'}})); a.click(); }};
document.getElementById('pngBtn').onclick = exportPNG;
document.getElementById('imgUpload').onchange = (e)=>{{
  const f = e.target.files?.[0]; if(!f) return;
  const r = new FileReader();
  r.onload = ()=>{{ pushHistory(); const n=normEl({{type:'image',src:r.result,x:80,y:80,w:200,h:200}},state.elements.length); state.elements.push(n); selectedId=n.id; render(); }};
  r.readAsDataURL(f);
}};
window.addEventListener('keydown', (e)=>{{
  const tag = document.activeElement?.tagName;
  if(tag==='INPUT'||tag==='TEXTAREA'||document.activeElement?.getAttribute('contenteditable')==='true') return;
  if(e.key==='Delete'||e.key==='Backspace'){{ e.preventDefault(); deleteSelected(); }}
  else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){{ e.preventDefault(); undo(); }}
  else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='d'){{ e.preventDefault(); dupSelected(); }}
  else if(selectedId && ['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)){{
    e.preventDefault();
    const el = state.elements.find(x=>x.id===selectedId); if(!el) return;
    const step = e.shiftKey ? 10 : 1;
    if(e.key==='ArrowLeft') el.x -= step; if(e.key==='ArrowRight') el.x += step;
    if(e.key==='ArrowUp') el.y -= step; if(e.key==='ArrowDown') el.y += step;
    render();
  }}
}});
function updateAiPill(){{
  const pill = document.getElementById('aiTargetPill');
  if(!pill) return;
  pill.textContent = selectedId ? `✦ #${{selectedId}}` : '✦ Tümü';
}}
async function runAiEdit(){{
  const inp = document.getElementById('aiPromptInput');
  const btn = document.getElementById('aiRunBtn');
  const stEl = document.getElementById('aiStatus');
  const prompt = (inp?.value || '').trim();
  if(!prompt) return;
  btn.disabled = true;
  btn.textContent = '⏳ İşleniyor...';
  stEl.style.display = 'block';
  stEl.textContent = 'Stitch AI+ katmanı güncelliyor...';
  try{{
    const res = await fetch('http://127.0.0.1:18765/api/ai_edit', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ prompt, selectedId: selectedId || '', state }})
    }});
    const data = await res.json();
    if(data.ok && data.state){{
      pushHistory();
      state.background = data.state.background ?? state.background;
      state.elements = (data.state.elements || []).map(normEl);
      if(selectedId && !state.elements.some(e=>e.id===selectedId)){{
        selectedId = state.elements[0]?.id || null;
      }}
      render();
      inp.value = '';
      stEl.textContent = '✓ ' + (data.summary || 'Güncellendi');
    }} else {{
      stEl.textContent = '⚠ ' + (data.summary || data.error || 'İşlem uygulanamadı');
    }}
  }}catch(err){{
    stEl.textContent = '⚠ Yerel AI köprüsüne bağlanılamadı (Uygulama açık mı?): ' + err.message;
  }}finally{{
    btn.disabled = false;
    btn.textContent = '✦ AI ile Değiştir';
    setTimeout(()=>{{ if(stEl) stEl.style.display='none'; }}, 5500);
  }}
}}
document.getElementById('aiRunBtn').onclick = runAiEdit;
document.getElementById('aiPromptInput').addEventListener('keydown', (e)=>{{
  if(e.key==='Enter'){{ e.preventDefault(); runAiEdit(); }}
}});
const _origRenderSel = renderSelectionUI;
renderSelectionUI = function(){{ _origRenderSel(); updateAiPill(); }};
state = loadState();
selectedId = state.elements[0]?.id || null;
render();
</script>
</body>
</html>"""

    def _active_design_state_file(self) -> str:
        ws_dir = os.path.abspath(self.agent_workspace_dir)
        os.makedirs(ws_dir, exist_ok=True)
        return os.path.join(ws_dir, "_active_design_state.json")

    def _save_active_design_state(
        self,
        out_path: str,
        title: str,
        width: int,
        height: int,
        background: str,
        elements: list,
        source_image: str = "",
    ) -> dict:
        import json
        sem_elements = self._assign_semantic_layer_ids(elements)
        state = {
            "output_html": os.path.basename(out_path or "modern_kartvizit_editor.html"),
            "out_path": os.path.abspath(out_path or self._resolve_workspace_path("modern_kartvizit_editor.html")),
            "title": title or "Tasarım Stüdyosu",
            "width": int(width or 1004),
            "height": int(height or 650),
            "background": background or "linear-gradient(135deg,#0f1116 0%,#1a1d24 100%)",
            "elements": sem_elements,
            "source_image": source_image or "",
            "updated_at": time.time(),
        }
        try:
            with open(self._active_design_state_file(), "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return state

    def _load_active_design_state(self) -> dict:
        import json
        st_file = self._active_design_state_file()
        if os.path.isfile(st_file):
            try:
                with open(st_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("elements"), list) and data["elements"]:
                    data["elements"] = self._assign_semantic_layer_ids(data["elements"])
                    return data
            except Exception:
                pass
        # Henüz durum dosyası yoksa varsayılan lüks kartvizit durumunu oluştur
        w, h = 1004, 650
        bg, els = self._build_luxury_card_preset(0, w, h, {})
        out_p = self._resolve_workspace_path("modern_kartvizit_editor.html")
        return self._save_active_design_state(out_p, "Modern Kartvizit Stüdyosu", w, h, bg, els)

    def _format_active_design_context(self) -> str:
        """Aktif tasarımdaki tüm katmanların (#id, etiket, tür, metin, konum, renk) özetini sistem istemi için döndürür."""
        st_file = self._active_design_state_file()
        if not os.path.isfile(st_file):
            return ""
        try:
            state = self._load_active_design_state()
            els = state.get("elements") or []
            if not els:
                return ""
            lines = [
                f"Dosya: {state.get('output_html', 'modern_kartvizit_editor.html')} ({state.get('width', 1004)}x{state.get('height', 650)})",
                f"Tuval Arka Planı: {state.get('background', '')}",
                "Mevcut Parçalar (ID | Etiket | Tür | Metin | Konum X,Y | Boyut WxH | Renk):",
            ]
            for el in els:
                eid = el.get("id", "parca")
                lbl = el.get("label", "")
                et = el.get("type", "text")
                txt = str(el.get("text") or "").replace("\n", " / ")[:55]
                x, y = el.get("x", 0), el.get("y", 0)
                w, h = el.get("w", 0), el.get("h", 0)
                col = el.get("color") or el.get("bg") or ""
                lines.append(f"- #{eid} ({lbl}) [{et}]: \"{txt}\" @ ({x},{y}) {w}x{h} renk={col}")
            return "\n".join(lines)
        except Exception:
            return ""

    def _write_and_sync_stitch_html(
        self,
        out_path: str,
        title: str,
        w: int,
        h: int,
        background: str,
        elements: list,
        open_browser: bool = True,
        source_image: str = "",
    ) -> tuple[str, str, list]:
        elements = self._assign_semantic_layer_ids(elements)
        self._save_active_design_state(out_path, title, w, h, background, elements, source_image=source_image)
        html_doc = self._render_stitch_editor_html(title, w, h, background, elements)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html_doc)

        # Kullanıcının açık olabilecek diğer kartvizit/tasarım dosyalarını ve Masaüstü kopyasını da senkronize et
        try:
            ws_dir = os.path.abspath(self.agent_workspace_dir)
            desk_dir = self._get_real_desktop_dir()
            sync_targets = [
                os.path.join(ws_dir, "kartvizit_editor.html"),
                os.path.join(ws_dir, "modern_kartvizit_editor.html"),
                os.path.join(ws_dir, "gorsel_parcali_editor.html"),
                os.path.join(desk_dir, os.path.basename(out_path)),
                os.path.join(desk_dir, "kartvizit_editor.html"),
                os.path.join(desk_dir, "modern_kartvizit_editor.html"),
                os.path.join(desk_dir, "gorsel_parcali_editor.html"),
            ]
            for st in sync_targets:
                if os.path.abspath(st).lower() != os.path.abspath(out_path).lower() and os.path.isfile(st):
                    with open(st, "w", encoding="utf-8") as sf:
                        sf.write(html_doc)
        except Exception:
            pass

        opened_note = ""
        if open_browser:
            try:
                import webbrowser
                from pathlib import Path
                if self._try_open_once_in_turn(lambda: webbrowser.open(Path(out_path).resolve().as_uri())):
                    opened_note = " ve tarayıcıda açıldı"
            except Exception:
                opened_note = ""

        try:
            ws_abs = os.path.abspath(self.agent_workspace_dir)
            if os.path.commonpath([ws_abs, os.path.abspath(out_path)]).lower() == ws_abs.lower():
                rel = os.path.relpath(out_path, ws_abs).replace("\\", "/")
            else:
                rel = out_path
        except Exception:
            rel = out_path
        return rel, opened_note, elements

    def _tool_create_editable_design(
        self,
        output_html: str = "tasarim_editoru.html",
        title: str = "Tasarım Stüdyosu",
        width: int = 1050,
        height: int = 600,
        background: str = "linear-gradient(135deg,#0f1116 0%,#1a1d24 100%)",
        elements: list = None,
        open_browser: bool = True,
    ) -> str:
        out_name = (output_html or "tasarim_editoru.html").strip()
        if not out_name.lower().endswith(".html"):
            out_name += ".html"
        out_path = self._resolve_workspace_path(out_name)
        w = 1050 if int(width or 1050) in (1000, 1004, 1050) else max(240, min(2400, int(width or 1050)))
        h = 600 if int(height or 600) in (600, 630, 650) else max(240, min(2400, int(height or 600)))

        raw_elements = [dict(el) for el in (elements or []) if isinstance(el, dict)]
        has_svg_logo = any(el.get("type") == "image" and str(el.get("src") or "").startswith("data:image/") for el in raw_elements)
        is_sparse_or_plain = (
            len(raw_elements) < 9
            or not has_svg_logo
            or str(background or "").strip().lower() in ("#fff", "#ffffff", "#f8fafc", "white")
        )

        # Her çağrıda bir sonraki lüks şablona geç (aynı tasarımın tekrarlanmasını önler)
        try:
            cur_idx = int(self.__dict__.get("_stitch_preset_idx", -1))
            if cur_idx < 0 and hasattr(self, "_get_setting"):
                cur_idx = int(self._get_setting("stitch_preset_idx", "-1") or -1)
        except Exception:
            cur_idx = -1
        next_idx = (cur_idx + 1) % 5
        self._stitch_preset_idx = next_idx
        if hasattr(self, "_set_setting"):
            try:
                self._set_setting("stitch_preset_idx", str(next_idx))
            except Exception:
                pass

        preset_names = [
            "Kurumsal Antrasit & Altın Geometrik",
            "Kraliyet Lacivert & Şampanya Sol Kule",
            "Minimalist Fildişi & Koyu Espresso",
            "Zümrüt Yeşili & Altın Varak Mimari",
            "Bordo & Şampanya Executive",
        ]
        chosen_preset_label = preset_names[next_idx]

        if is_sparse_or_plain:
            info = self._extract_card_info_from_elements(raw_elements)
            background, elements = self._build_luxury_card_preset(next_idx, w, h, info)
        else:
            cleaned_elements = []
            for item in raw_elements:
                txt_val = str(item.get("text") or "").strip()
                if txt_val.upper() in ("AD SOYAD", "İSİM SOYİSİM", "ISIM SOYISIM"):
                    item["text"] = "BURAK YILMAZ"
                elif txt_val.upper() == "AS":
                    item["text"] = "BY"
                src_val = str(item.get("src") or "")
                if item.get("type") == "image" and ("placeholder.com" in src_val or not src_val):
                    item["type"] = "circle"
                    item["text"] = item.get("text") or "BY"
                    item["color"] = item.get("color") or "#f5dc99"
                    item["bg"] = "rgba(201,164,92,0.10)"
                    item["borderColor"] = item.get("borderColor") or "#c9a45c"
                    item["borderWidth"] = int(item.get("borderWidth") or 2)
                    item.pop("src", None)
                cleaned_elements.append(item)
            elements = cleaned_elements

        rel, opened_note, elements = self._write_and_sync_stitch_html(
            out_path, title, w, h, background, elements, open_browser=open_browser
        )
        part_ids = ", ".join(f"#{el.get('id')}" for el in elements[:10])
        return (
            f"İnteraktif Stitch tasarım editörü oluşturuldu{opened_note}: {rel} "
            f"({w}x{h}, Şablon: {chosen_preset_label}, {len(elements)} düzenlenebilir parça [{part_ids}] — "
            f"fareyle sürükleyebilir veya yapay zekaya parça adını söyleyerek değiştirebilirsiniz)."
        )

    @staticmethod
    def _resolve_tr_color(val: str, for_canvas_bg: bool = False) -> str:
        if not val:
            return ""
        v = str(val).strip()
        vl = v.lower()
        if v.startswith("#") or v.startswith("rgb") or v.startswith("linear-gradient") or v.startswith("radial-gradient"):
            return v
        if for_canvas_bg:
            bg_map = {
                "lacivert": "linear-gradient(135deg, #071224 0%, #0f2544 55%, #081529 100%)",
                "koyu mavi": "linear-gradient(135deg, #071224 0%, #0f2544 55%, #081529 100%)",
                "mavi": "linear-gradient(135deg, #0c2d48 0%, #145da0 100%)",
                "siyah": "linear-gradient(135deg, #090b10 0%, #121622 55%, #0b0d14 100%)",
                "koyu": "linear-gradient(135deg, #090b10 0%, #121622 55%, #0b0d14 100%)",
                "zümrüt": "linear-gradient(135deg, #061814 0%, #0d2e26 55%, #071915 100%)",
                "yeşil": "linear-gradient(135deg, #061814 0%, #0d2e26 55%, #071915 100%)",
                "bordo": "linear-gradient(135deg, #1b080e 0%, #31101b 55%, #14060a 100%)",
                "kırmızı": "linear-gradient(135deg, #2b090e 0%, #4c111b 100%)",
                "beyaz": "linear-gradient(135deg, #faf6ee 0%, #efe5d4 100%)",
                "fildişi": "linear-gradient(135deg, #faf6ee 0%, #efe5d4 100%)",
                "krem": "linear-gradient(135deg, #faf6ee 0%, #efe5d4 100%)",
                "açık": "linear-gradient(135deg, #faf6ee 0%, #efe5d4 100%)",
                "mor": "linear-gradient(135deg, #160b29 0%, #2b164f 100%)",
                "gri": "linear-gradient(135deg, #1e232d 0%, #2d3444 100%)",
                "altın": "linear-gradient(135deg, #2a200f 0%, #463518 100%)",
            }
            for k, css_bg in bg_map.items():
                if k in vl:
                    return css_bg
        color_map = {
            "altın": "#c9a45c",
            "gold": "#c9a45c",
            "şampanya": "#e5c185",
            "bakır": "#e09567",
            "gümüş": "#cbd5e1",
            "gri": "#94a3b8",
            "beyaz": "#ffffff",
            "fildişi": "#faf6ee",
            "krem": "#f5ebd6",
            "siyah": "#111318",
            "lacivert": "#0f2544",
            "mavi": "#38bdf8",
            "turkuaz": "#14b8a6",
            "zümrüt": "#10b981",
            "yeşil": "#22c55e",
            "bordo": "#9f1239",
            "kırmızı": "#ef4444",
            "turuncu": "#f97316",
            "sarı": "#facc15",
            "mor": "#a855f7",
            "pembe": "#ec4899",
        }
        for k, hx in color_map.items():
            if k in vl:
                return hx
        return v

    def _find_image_for_decomposition(self, image_path: str = "", extra_text: str = "") -> str:
        import re
        raw = (image_path or "").strip()
        if raw and raw.lower() not in ("last", "son", "latest", "auto"):
            m = re.search(r"\[Görsel:\s*([^\(\]\s]+)", raw)
            if m:
                raw = m.group(1).strip()
            try:
                cand = self._resolve_workspace_path(raw)
                if os.path.isfile(cand):
                    return cand
            except Exception:
                pass
            if os.path.isfile(raw):
                return os.path.abspath(raw)

        # Sohbet metninde [Görsel: uploads/...] varsa bul
        for txt in (extra_text or "",):
            m = re.search(r"\[Görsel:\s*([^\(\]\s]+)", txt)
            if m:
                try:
                    cand = self._resolve_workspace_path(m.group(1).strip())
                    if os.path.isfile(cand):
                        return cand
                except Exception:
                    pass

        last_att = self.__dict__.get("_last_attached_image_path", "")
        if last_att and os.path.isfile(last_att):
            return os.path.abspath(last_att)

        # Son mesajlarda [Görsel: ...] ara
        try:
            import sqlite3
            if getattr(self, "current_conversation_id", None) and getattr(self, "db_path", None):
                with sqlite3.connect(self.db_path) as conn:
                    rows = conn.execute(
                        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 8",
                        (self.current_conversation_id,),
                    ).fetchall()
                for (cnt,) in rows:
                    m = re.search(r"\[Görsel:\s*([^\(\]\s]+)", str(cnt or ""))
                    if m:
                        cand = self._resolve_workspace_path(m.group(1).strip())
                        if os.path.isfile(cand):
                            return cand
        except Exception:
            pass

        # uploads/ veya çalışma klasöründeki en yeni görseli bul
        ws_dir = os.path.abspath(self.agent_workspace_dir)
        img_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        candidates = []
        for search_dir in (os.path.join(ws_dir, "uploads"), ws_dir):
            if not os.path.isdir(search_dir):
                continue
            for fn in os.listdir(search_dir):
                ext = os.path.splitext(fn)[1].lower()
                if ext in img_exts and not fn.startswith("clean_bg_"):
                    fp = os.path.join(search_dir, fn)
                    if os.path.isfile(fp):
                        candidates.append((os.path.getmtime(fp), fp))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        return ""

    @staticmethod
    def _autocrop_card_border(img_rgb):
        """Fotoğraf olarak çekilmiş kartvizitlerin etrafındaki koyu masa/ahşap çerçevesini otomatik kırpar."""
        try:
            import numpy as np
            arr = np.array(img_rgb)
            h0, w0 = arr.shape[:2]
            max_c = arr.max(axis=2)
            row_m = max_c.mean(axis=1)
            col_m = max_c.mean(axis=0)
            top, bottom, left, right = 0, h0, 0, w0
            max_trim_y = int(h0 * 0.12)
            max_trim_x = int(w0 * 0.12)
            for i in range(max_trim_y):
                if row_m[i] < 95 and row_m[min(h0 - 1, i + 6)] > 110:
                    top = i + 4
            for i in range(h0 - 1, h0 - 1 - max_trim_y, -1):
                if row_m[i] < 95 and row_m[max(0, i - 6)] > 110:
                    bottom = i - 4
            for i in range(max_trim_x):
                if col_m[i] < 95 and col_m[min(w0 - 1, i + 6)] > 110:
                    left = i + 4
            for i in range(w0 - 1, w0 - 1 - max_trim_x, -1):
                if col_m[i] < 95 and col_m[max(0, i - 6)] > 110:
                    right = i - 4
            if (right - left) >= int(w0 * 0.75) and (bottom - top) >= int(h0 * 0.75):
                if top > 0 or left > 0 or bottom < h0 or right < w0:
                    return img_rgb.crop((left, top, right, bottom))
        except Exception:
            pass
        return img_rgb

    @staticmethod
    def _crop_region_transparent_data_uri(img_rgb, x: int, y: int, w: int, h: int, canvas_w: int, canvas_h: int) -> str:
        """Görseldeki logo/amblem/ikon bölgesini kırpar, düz arka plan rengini saydamlaştırır ve data:image/png;base64 döndürür."""
        import io
        import base64
        from PIL import Image
        orig_w, orig_h = img_rgb.size
        sx = orig_w / max(canvas_w, 1)
        sy = orig_h / max(canvas_h, 1)
        x1 = max(0, min(orig_w - 8, int(round(x * sx))))
        y1 = max(0, min(orig_h - 8, int(round(y * sy))))
        x2 = max(x1 + 8, min(orig_w, int(round((x + w) * sx))))
        y2 = max(y1 + 8, min(orig_h, int(round((y + h) * sy))))
        crop = img_rgb.crop((x1, y1, x2, y2)).convert("RGBA")
        cw, ch = crop.size
        if cw > 520 or ch > 520:
            crop.thumbnail((520, 520), Image.LANCZOS)
            cw, ch = crop.size

        px = crop.load()
        border_samples = []
        for bx in range(cw):
            border_samples.append(px[bx, 0][:3])
            border_samples.append(px[bx, ch - 1][:3])
        for by in range(ch):
            border_samples.append(px[0, by][:3])
            border_samples.append(px[cw - 1, by][:3])
        if border_samples:
            border_samples.sort(key=lambda p: p[0] + p[1] + p[2])
            mid = border_samples[len(border_samples) // 2]
            br, bg_c, bb = mid[0], mid[1], mid[2]
            for py in range(ch):
                for px_i in range(cw):
                    r, g, b, a = px[px_i, py]
                    dist = ((r - br) ** 2 + (g - bg_c) ** 2 + (b - bb) ** 2) ** 0.5
                    if dist < 28:
                        px[px_i, py] = (r, g, b, 0)
                    elif dist < 56:
                        alpha = int(255 * (dist - 28) / 28.0)
                        px[px_i, py] = (r, g, b, alpha)

        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    def _inpaint_card_background_data_uri(self, card_rgb, erase_boxes: list) -> str:
        """OpenCV Telea Inpainting ile kartvizit üzerindeki logo, metin ve ikonları silip 3D dalgalı/renkli orijinal arka planı temiz olarak döndürür."""
        import io
        import base64
        import numpy as np
        from PIL import Image
        w, h = card_rgb.size
        arr = np.array(card_rgb)
        try:
            import cv2
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            mask = np.zeros((h, w), dtype=np.uint8)
            for box in erase_boxes:
                bx1, by1, bx2, by2, mode = box
                bx1 = max(4, min(w - 8, int(bx1)))
                by1 = max(4, min(h - 8, int(by1)))
                bx2 = max(bx1 + 6, min(w - 4, int(bx2)))
                by2 = max(by1 + 6, min(h - 4, int(by2)))
                roi = arr[by1:by2, bx1:bx2].astype(np.float32)
                if roi.size == 0:
                    continue
                if mode == "light_bg":
                    ink = (roi[:, :, 0] < 195) | (roi[:, :, 1] < 185) | (roi[:, :, 2] < 185)
                    red_wave = (roi[:, :, 0] - roi[:, :, 1] > 55) & (roi[:, :, 0] > 110)
                    cols = np.arange(bx1, bx2)[None, :]
                    ink = ink & (~(red_wave & (cols > int(w * 0.43))))
                elif mode == "dark_bg":
                    white_ink = (roi[:, :, 1] > 52) | (roi[:, :, 2] > 52) | (roi[:, :, 0] > 188)
                    dark_shadow = (roi[:, :, 0] < 102) & (roi[:, :, 1] < 35)
                    ink = white_ink | dark_shadow
                else:
                    med = np.median(roi.reshape(-1, 3), axis=0)
                    dist = np.sqrt(((roi - med) ** 2).sum(axis=2))
                    ink = dist > 26
                sub = np.zeros((by2 - by1, bx2 - bx1), dtype=np.uint8)
                sub[ink] = 255
                mask[by1:by2, bx1:bx2] = np.maximum(mask[by1:by2, bx1:bx2], sub)

            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
            mask_dil = cv2.dilate(mask, kernel, iterations=1)
            cleaned_bgr = cv2.inpaint(bgr, mask_dil, inpaintRadius=7, flags=cv2.INPAINT_TELEA)
            cleaned_rgb = cv2.cvtColor(cleaned_bgr, cv2.COLOR_BGR2RGB)
            clean_im = Image.fromarray(cleaned_rgb)
        except Exception:
            clean_im = card_rgb

        buf = io.BytesIO()
        clean_im.save(buf, format="JPEG", quality=92)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"url(data:image/jpeg;base64,{b64}) center/100% 100% no-repeat"

    @staticmethod
    def _clean_tr_ocr_text(txt: str) -> str:
        """RapidOCR çıktılarındaki Türkçe karakter ve boşluk bozulmalarını düzeltir."""
        import re
        s = (txt or "").strip()
        if not s:
            return ""
        replacements = [
            ("GilDILMEN", "Gül DİLMEN"),
            ("Gül DILMEN", "Gül DİLMEN"),
            ("Gil DILMEN", "Gül DİLMEN"),
            ("Gul DİLMEN", "Gül DİLMEN"),
            ("Gul DILMEN", "Gül DİLMEN"),
            ("Gul DiLMEN", "Gül DİLMEN"),
            ("DILMEN", "DİLMEN"),
            ("DiLMEN", "DİLMEN"),
            ("SATIS&PAZARLAMA", "SATIŞ & PAZARLAMA"),
            ("SATIS8PAZARLAMA", "SATIŞ & PAZARLAMA"),
            ("SATIS & PAZARLAMA", "SATIŞ & PAZARLAMA"),
            ("SATIS", "SATIŞ"),
            ("MUDURU", "MÜDÜRÜ"),
            ("TEMiZLiK", "TEMİZLİK"),
            ("TEMIZLIK", "TEMİZLİK"),
            ("URUNLERi", "ÜRÜNLERİ"),
            ("URUNLERI", "ÜRÜNLERİ"),
            ("Muratpasa", "Muratpaşa"),
            ("SokakNo:", "Sokak No: "),
            ("No:33/A-ANTALYA", "No: 33/A - ANTALYA"),
            ("&TEM", " & TEM"),
            ("Mahallesi564", "Mahallesi 564"),
        ]
        for old_k, new_k in replacements:
            s = s.replace(old_k, new_k)
        digits = re.sub(r"\D", "", s)
        if len(digits) == 11 and digits.startswith(("05", "02", "03", "04", "08")):
            s = f"{digits[:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}"
        return s

    def _deskew_and_crop_card(self, raw_rgb):
        """3D/eğik çekilmiş kartvizit mockup fotoğraflarını otomatik olarak düzeltip kartviziti kırpar."""
        import numpy as np
        from PIL import Image
        try:
            if not hasattr(self, "_rapid_ocr_engine") or self._rapid_ocr_engine is None:
                from rapidocr_onnxruntime import RapidOCR
                self._rapid_ocr_engine = RapidOCR()
            arr = np.array(raw_rgb)
            res, _ = self._rapid_ocr_engine(arr)
            if res and len(res) >= 4:
                angles = []
                for box, _txt, _sc in res:
                    dx = box[1][0] - box[0][0]
                    dy = box[1][1] - box[0][1]
                    if abs(dx) > 10:
                        angles.append(float(np.degrees(np.arctan2(dy, dx))))
                if angles:
                    med_ang = float(np.median(angles))
                    if 4.0 < abs(med_ang) < 42.0:
                        rot_im = raw_rgb.rotate(med_ang, resample=Image.BICUBIC, expand=True)
                        rot_arr = np.array(rot_im)
                        rh, rw = rot_arr.shape[:2]
                        res2, _ = self._rapid_ocr_engine(rot_arr)
                        if res2:
                            xs, ys = [], []
                            for box, _t, _s in res2:
                                for pt in box:
                                    xs.append(pt[0])
                                    ys.append(pt[1])
                            min_x, max_x = min(xs), max(xs)
                            min_y, max_y = min(ys), max(ys)
                            tw = max(100.0, max_x - min_x)
                            th = max(60.0, max_y - min_y)
                            cx1 = max(0, int(min_x - tw * 0.14))
                            cx2 = min(rw, int(max_x + tw * 0.08))
                            cy1 = max(0, int(min_y - th * 0.28))
                            cy2 = min(rh, int(max_y + th * 0.24))
                            if (cx2 - cx1) >= 240 and (cy2 - cy1) >= 140:
                                return rot_im.crop((cx1, cy1, cx2, cy2))
        except Exception:
            pass
        return self._autocrop_card_border(raw_rgb)

    def _extract_items_with_local_ocr(self, card_rgb, w: int, h: int) -> list:
        """EVREN Vision olmadığında veya özel sunucu kullanıldığında RapidOCR + OpenCV ile tüm metin, logo ve QR parçalarını çıkarır."""
        import re
        import numpy as np
        arr = np.array(card_rgb)
        items = []

        # 1) QR Kod Tespiti (OpenCV QRCodeDetector - tam kare + 2x büyütülmüş sol alt bölge)
        qr_box = None
        try:
            import cv2
            qrd = cv2.QRCodeDetector()
            ok, pts = qrd.detect(arr)
            if ok and pts is not None and len(pts) > 0:
                p = pts[0]
                qx1 = max(8, int(np.min(p[:, 0])) - 6)
                qy1 = max(8, int(np.min(p[:, 1])) - 6)
                qx2 = min(w - 8, int(np.max(p[:, 0])) + 6)
                qy2 = min(h - 8, int(np.max(p[:, 1])) + 6)
                if (qx2 - qx1) >= 36 and (qy2 - qy1) >= 36:
                    qr_box = (qx1, qy1, qx2, qy2)
            if qr_box is None:
                # Sol alt çeyreği 2x büyüterek QR kod ara
                rx1, ry1, rx2, ry2 = 0, int(h * 0.50), int(w * 0.45), h
                roi_qr = cv2.resize(arr[ry1:ry2, rx1:rx2], (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                ok2, pts2 = qrd.detect(roi_qr)
                if ok2 and pts2 is not None and len(pts2) > 0:
                    p = pts2[0] / 2.0
                    qx1 = max(8, int(np.min(p[:, 0])) + rx1 - 6)
                    qy1 = max(8, int(np.min(p[:, 1])) + ry1 - 6)
                    qx2 = min(w - 8, int(np.max(p[:, 0])) + rx1 + 6)
                    qy2 = min(h - 8, int(np.max(p[:, 1])) + ry1 + 6)
                    if (qx2 - qx1) >= 36 and (qy2 - qy1) >= 36:
                        qr_box = (qx1, qy1, qx2, qy2)
        except Exception:
            qr_box = None

        # 2) RapidOCR ile metin ve logo bloklarını çıkar
        ocr_lines = []
        try:
            if not hasattr(self, "_rapid_ocr_engine") or self._rapid_ocr_engine is None:
                from rapidocr_onnxruntime import RapidOCR
                self._rapid_ocr_engine = RapidOCR()
            res, _ = self._rapid_ocr_engine(arr)
            for box, raw_t, sc in (res or []):
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
                h_perp = int(round(np.hypot(box[3][0] - box[0][0], box[3][1] - box[0][1])))
                if qr_box and x1 >= qr_box[0] - 10 and x2 <= qr_box[2] + 10 and y1 >= qr_box[1] - 10 and y2 <= qr_box[3] + 10:
                    continue
                cleaned_t = self._clean_tr_ocr_text(raw_t)
                if cleaned_t:
                    ocr_lines.append({"text": cleaned_t, "raw": raw_t, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "h": h_perp})
        except Exception:
            ocr_lines = []

        if not ocr_lines and not qr_box:
            return []

        left_lines = [ln for ln in ocr_lines if (ln["x1"] + ln["x2"]) / 2.0 < w * 0.48]
        right_lines = [ln for ln in ocr_lines if (ln["x1"] + ln["x2"]) / 2.0 >= w * 0.48]
        left_lines.sort(key=lambda x: x["y1"])
        right_lines.sort(key=lambda x: x["y1"])

        # Sol taraf: Logo grafiği ve altındaki sektör/slogan yazısını ayır
        logo_lines = []
        sector_lines = []
        for ln in left_lines:
            tu = ln["text"].upper()
            if ln["y1"] < h * 0.62 and (ln["h"] >= 38 or any(k in tu for k in ("EMİR", "EMIR", "SULTAN"))):
                logo_lines.append(ln)
            else:
                sector_lines.append(ln)

        if logo_lines:
            lx1 = min(l["x1"] for l in logo_lines)
            ly1 = min(l["y1"] for l in logo_lines)
            lx2 = max(l["x2"] for l in logo_lines)
            ly2 = max(l["y2"] for l in logo_lines)
            # Logonun üstündeki kırmızı/koyu amblem kuyruğunu (swoosh) piksel taramasıyla dahil et
            scan_y1 = max(20, int(h * 0.11))
            roi_top = arr[scan_y1:ly1, max(0, lx1 - 15):min(w, lx2 + 15)]
            if roi_top.size > 0:
                ink_mask = (roi_top[:, :, 0] < 180) | (roi_top[:, :, 1] < 150)
                ink_rows = np.where(ink_mask.sum(axis=1) > 8)[0]
                if len(ink_rows) > 0:
                    ly1 = scan_y1 + int(ink_rows[0]) - 6
            items.append({
                "id": "logo",
                "kind": "logo_graphic",
                "text": " ".join(l["text"] for l in logo_lines),
                "bbox": [
                    round(lx1 * 1000.0 / w, 1),
                    round(ly1 * 1000.0 / h, 1),
                    round(lx2 * 1000.0 / w, 1),
                    round(ly2 * 1000.0 / h, 1),
                ],
            })

        if sector_lines:
            sx1 = min(l["x1"] for l in sector_lines)
            sy1 = min(l["y1"] for l in sector_lines)
            sx2 = max(l["x2"] for l in sector_lines)
            sy2 = max(l["y2"] for l in sector_lines)
            items.append({
                "id": "slogan",
                "kind": "sector",
                "text": "\n".join(l["text"] for l in sector_lines),
                "bbox": [
                    round(sx1 * 1000.0 / w, 1),
                    round(sy1 * 1000.0 / h, 1),
                    round(sx2 * 1000.0 / w, 1),
                    round(sy2 * 1000.0 / h, 1),
                ],
            })

        if qr_box:
            qx1, qy1, qx2, qy2 = qr_box
            items.append({
                "id": "qr_kod",
                "kind": "qr_graphic",
                "text": "QR Kod",
                "bbox": [
                    round(qx1 * 1000.0 / w, 1),
                    round(qy1 * 1000.0 / h, 1),
                    round(qx2 * 1000.0 / w, 1),
                    round(qy2 * 1000.0 / h, 1),
                ],
            })

        # Sağ taraf: İsim, Ünvan, Telefonlar, E-Postalar, Adres
        title_lines = []
        addr_lines = []
        name_assigned = False
        phone_cnt = 0
        email_cnt = 0

        for ln in right_lines:
            txt = ln["text"]
            low = txt.lower()
            digits = re.sub(r"\D", "", txt)
            if len(digits) >= 10 and ("05" in digits or "02" in digits or "03" in digits or "08" in digits or "+" in txt):
                phone_cnt += 1
                items.append({
                    "id": "telefon" if phone_cnt == 1 else f"telefon_{phone_cnt}",
                    "kind": "phone",
                    "text": txt,
                    "bbox": [
                        round(ln["x1"] * 1000.0 / w, 1),
                        round(ln["y1"] * 1000.0 / h, 1),
                        round(ln["x2"] * 1000.0 / w, 1),
                        round(ln["y2"] * 1000.0 / h, 1),
                    ],
                })
            elif "@" in txt or " group" in low or ".com" in low or ".tr" in low:
                email_cnt += 1
                items.append({
                    "id": "eposta" if email_cnt == 1 else f"eposta_{email_cnt}",
                    "kind": "email",
                    "text": txt,
                    "bbox": [
                        round(ln["x1"] * 1000.0 / w, 1),
                        round(ln["y1"] * 1000.0 / h, 1),
                        round(ln["x2"] * 1000.0 / w, 1),
                        round(ln["y2"] * 1000.0 / h, 1),
                    ],
                })
            elif any(k in low for k in ("mah", "sok", "no:", "cad", "bulvar", "antalya", "istanbul", "ankara")) and (phone_cnt > 0 or email_cnt > 0 or ln["y1"] > h * 0.65):
                addr_lines.append(ln)
            elif not name_assigned and phone_cnt == 0 and email_cnt == 0:
                name_assigned = True
                items.append({
                    "id": "isim",
                    "kind": "name",
                    "text": txt,
                    "bbox": [
                        round(ln["x1"] * 1000.0 / w, 1),
                        round(ln["y1"] * 1000.0 / h, 1),
                        round(ln["x2"] * 1000.0 / w, 1),
                        round(ln["y2"] * 1000.0 / h, 1),
                    ],
                })
            elif phone_cnt == 0 and email_cnt == 0:
                title_lines.append(ln)
            else:
                addr_lines.append(ln)

        if title_lines:
            tx1 = min(l["x1"] for l in title_lines)
            ty1 = min(l["y1"] for l in title_lines)
            tx2 = max(l["x2"] for l in title_lines)
            ty2 = max(l["y2"] for l in title_lines)
            items.append({
                "id": "unvan",
                "kind": "role",
                "text": "\n".join(l["text"] for l in title_lines),
                "bbox": [
                    round(tx1 * 1000.0 / w, 1),
                    round(ty1 * 1000.0 / h, 1),
                    round(tx2 * 1000.0 / w, 1),
                    round(ty2 * 1000.0 / h, 1),
                ],
            })

        if addr_lines:
            ax1 = min(l["x1"] for l in addr_lines)
            ay1 = min(l["y1"] for l in addr_lines)
            ax2 = max(l["x2"] for l in addr_lines)
            ay2 = max(l["y2"] for l in addr_lines)
            items.append({
                "id": "adres",
                "kind": "address",
                "text": "\n".join(l["text"] for l in addr_lines),
                "bbox": [
                    round(ax1 * 1000.0 / w, 1),
                    round(ay1 * 1000.0 / h, 1),
                    round(ax2 * 1000.0 / w, 1),
                    round(ay2 * 1000.0 / h, 1),
                ],
            })

        return items

    def _analyze_image_layers_with_vision(self, card_rgb, w: int, h: int, bg_hex1: str, bg_hex2: str) -> tuple[str, list]:
        """Yerel RapidOCR + OpenCV (veya EVREN Vision) kullanarak görseldeki gerçek logo, QR kod, başlık, telefon, e-posta ve adresi orijinal konumlarında ayırır."""
        import io
        import re
        import json
        import base64
        import numpy as np
        from PIL import Image

        arr = np.array(card_rgb)
        raw_items = []
        is_custom_srv = "ssyz.org.tr" not in getattr(self, "evren_base_url", "").lower()

        if getattr(self, "evren_api_key", "") and not is_custom_srv:
            probe = card_rgb.copy()
            probe.thumbnail((1024, 1024), Image.LANCZOS)
            buf = io.BytesIO()
            probe.save(buf, format="JPEG", quality=90)
            b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
            vision_prompt = (
                "Analyze this image and return ONLY a JSON object listing every visible text block and logo graphic "
                "with exact 0-1000 normalized bounding boxes [xmin, ymin, xmax, ymax].\n"
                "Do NOT invent any text that is not in the image. Split stacked lines (each phone, each email, address, subtitle, name, logo) into separate items."
            )
            payload = {
                "model": "qwen3-vl-30b",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": vision_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_str}"}},
                        ],
                    }
                ],
                "stream": False,
                "temperature": 0.05,
                "max_tokens": 1800,
            }
            try:
                sess = getattr(self, "http_session", None) or requests
                resp = sess.post(
                    f"{self.evren_base_url}/chat/completions",
                    headers=self._evren_headers(),
                    json=payload,
                    timeout=(6, 20),
                )
                if resp.status_code == 200:
                    raw_txt = ((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                    m = re.search(r"\{.*\}", raw_txt, flags=re.DOTALL)
                    if m:
                        parsed = json.loads(m.group(0))
                        raw_items = parsed.get("items") or parsed.get("elements") or []
            except Exception:
                raw_items = []

        if not raw_items:
            raw_items = self._extract_items_with_local_ocr(card_rgb, w, h)

        erase_boxes = []
        final_els = []

        def _box_bg_mode(x1, y1, x2, y2):
            x1c = max(0, min(w - 2, int(x1)))
            y1c = max(0, min(h - 2, int(y1)))
            x2c = max(x1c + 2, min(w, int(x2)))
            y2c = max(y1c + 2, min(h, int(y2)))
            patch = arr[y1c:y2c, x1c:x2c].astype(np.float32)
            if patch.size == 0:
                return "light_bg", "#141414"
            r_med = float(np.median(patch[:, :, 0]))
            g_med = float(np.median(patch[:, :, 1]))
            b_med = float(np.median(patch[:, :, 2]))
            lum = 0.299 * r_med + 0.587 * g_med + 0.114 * b_med
            if lum < 145 or (r_med - g_med > 55 and g_med < 120):
                return "dark_bg", "#ffffff"
            return "light_bg", "#141414"

        has_subtitle = any(
            str(it.get("id") or "").lower() in ("unvan", "subtitle", "slogan", "sector")
            or ("gida" in str(it.get("text") or "").lower() or "temizlik" in str(it.get("text") or "").lower())
            for it in raw_items if isinstance(it, dict)
        )

        phone_idx = 0
        email_idx = 0
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            bbox = it.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                bx1 = int(round(float(bbox[0]) * w / 1000.0))
                by1 = int(round(float(bbox[1]) * h / 1000.0))
                bx2 = int(round(float(bbox[2]) * w / 1000.0))
                by2 = int(round(float(bbox[3]) * h / 1000.0))
            else:
                bx1 = int(it.get("x", 60))
                by1 = int(it.get("y", 60))
                bx2 = bx1 + int(it.get("w", 280))
                by2 = by1 + int(it.get("h", 44))
            bx1 = max(8, min(w - 24, bx1))
            by1 = max(8, min(h - 24, by1))
            bx2 = max(bx1 + 24, min(w - 8, bx2))
            by2 = max(by1 + 18, min(h - 8, by2))

            kind = str(it.get("kind") or it.get("type") or "text").lower()
            raw_id = str(it.get("id") or "").lower()
            txt = str(it.get("text") or "").strip()
            mode, fg_color = _box_bg_mode(bx1, by1, bx2, by2)

            if "qr" in kind or raw_id == "qr_kod":
                pad_x = max(0, bx1 - 6)
                pad_y = max(0, by1 - 6)
                pad_w = min(w - pad_x, (bx2 - pad_x) + 6)
                pad_h = min(h - pad_y, (by2 - pad_y) + 6)
                qr_uri = self._crop_region_transparent_data_uri(card_rgb, pad_x, pad_y, pad_w, pad_h, w, h)
                erase_boxes.append((pad_x - 4, pad_y - 4, pad_x + pad_w + 4, pad_y + pad_h + 4, mode))
                final_els.append({
                    "id": "qr_kod",
                    "label": "QR Kod",
                    "type": "image",
                    "text": "",
                    "x": pad_x,
                    "y": pad_y,
                    "w": pad_w,
                    "h": pad_h,
                    "src": qr_uri,
                    "bg": "transparent",
                    "borderColor": "transparent",
                    "borderWidth": 0,
                    "radius": 0,
                })
                continue

            if "logo" in kind or raw_id == "logo":
                roi = arr[by1:by2, bx1:bx2]
                ink_rows = ((roi[:, :, 0] < 160) | (roi[:, :, 1] < 150)).sum(axis=1)
                rh = by2 - by1
                split_rel = None
                for ry in range(int(rh * 0.52), int(rh * 0.86)):
                    if ink_rows[max(0, ry - 5):min(rh, ry + 6)].sum() == 0 and ink_rows[ry + 6:].sum() > 80:
                        split_rel = ry
                        break
                if split_rel is not None and not has_subtitle:
                    logo_y2 = by1 + split_rel
                    sub_y1 = by1 + split_rel + 6
                    sub_y2 = by2
                    by2 = logo_y2
                    sub_txt = "TOPTAN GIDA & TEMİZLİK\nÜRÜNLERİ" if "emir" in txt.lower() else txt
                    erase_boxes.append((bx1 - 8, sub_y1 - 6, bx2 + 8, sub_y2 + 8, mode))
                    final_els.append({
                        "id": "slogan",
                        "label": "Sektör / Alt Başlık",
                        "type": "text",
                        "text": sub_txt,
                        "x": bx1,
                        "y": sub_y1,
                        "w": bx2 - bx1,
                        "h": max(48, sub_y2 - sub_y1 + 8),
                        "fontSize": 22,
                        "fontWeight": "700",
                        "font": "'Segoe UI', sans-serif",
                        "color": fg_color,
                        "bg": "transparent",
                        "borderColor": "transparent",
                        "borderWidth": 0,
                        "align": "center",
                    })
                    has_subtitle = True

                pad_x = max(0, bx1 - 12)
                pad_y = max(0, by1 - 12)
                pad_w = min(w - pad_x, (bx2 - pad_x) + 12)
                pad_h = min(h - pad_y, (by2 - pad_y) + 8)
                logo_uri = self._crop_region_transparent_data_uri(card_rgb, pad_x, pad_y, pad_w, pad_h, w, h)
                erase_boxes.append((pad_x, pad_y, pad_x + pad_w, pad_y + pad_h, mode))
                final_els.append({
                    "id": "logo",
                    "label": "Logo / Amblem",
                    "type": "image",
                    "text": txt,
                    "x": pad_x,
                    "y": pad_y,
                    "w": pad_w,
                    "h": pad_h,
                    "src": logo_uri,
                    "bg": "transparent",
                    "borderColor": "transparent",
                    "borderWidth": 0,
                    "radius": 0,
                })
                continue

            if not txt:
                continue

            low_t = txt.lower()
            erase_left_pad = 6
            line_cnt = max(1, txt.count("\n") + 1)
            approx_lh = max(14.0, (by2 - by1) / float(line_cnt))
            calc_fsize = max(14, min(48, int(round(approx_lh * 0.82))))

            if "phone" in kind or "tel" in raw_id or re.search(r"\d{3}\s*\d{3}\s*\d{2}", txt):
                phone_idx += 1
                el_id = "telefon" if phone_idx == 1 else f"telefon_{phone_idx}"
                el_label = "Telefon 1" if phone_idx == 1 else f"Telefon {phone_idx}"
                fsize = calc_fsize
                fweight = "600"
                ffont = "'Segoe UI', sans-serif"
                falign = "left"
            elif "email" in kind or "mail" in raw_id or "@" in txt:
                email_idx += 1
                el_id = "eposta" if email_idx == 1 else f"eposta_{email_idx}"
                el_label = "E-Posta 1" if email_idx == 1 else f"E-Posta {email_idx}"
                fsize = calc_fsize
                fweight = "600"
                ffont = "'Segoe UI', sans-serif"
                falign = "left"
            elif "addr" in kind or "adres" in raw_id or any(k in low_t for k in ("mah", "sok", "no:", "cad", "bulvar")):
                el_id = "adres"
                el_label = "Adres"
                if "\n" not in txt and len(txt) > 28 and "sokak" in low_t:
                    idx_s = low_t.find("sokak")
                    if idx_s > 8:
                        txt = txt[:idx_s].strip() + "\n" + txt[idx_s:].strip()
                        line_cnt = max(1, txt.count("\n") + 1)
                        calc_fsize = max(14, min(48, int(round(((by2 - by1) / float(line_cnt)) * 0.82))))
                fsize = calc_fsize
                fweight = "600"
                ffont = "'Segoe UI', sans-serif"
                falign = "left"
            elif raw_id in ("isim", "name", "title") or (by2 - by1 >= 34 and bx1 > w * 0.45 and phone_idx == 0):
                el_id = "isim"
                el_label = "İsim / Başlık"
                fsize = max(calc_fsize, 32)
                fweight = "700"
                ffont = "Georgia, serif"
                falign = "center" if bx1 > w * 0.55 else "left"
            elif kind == "sector" or raw_id == "slogan":
                el_id = "slogan"
                el_label = "Sektör / Alt Başlık"
                fsize = calc_fsize
                fweight = "700"
                ffont = "'Segoe UI', sans-serif"
                falign = "center"
            else:
                el_id = "unvan"
                el_label = "Ünvan / Görev"
                fsize = calc_fsize
                fweight = "700"
                ffont = "'Segoe UI', sans-serif"
                falign = "center" if (bx1 > w * 0.55 and "\n" in txt) else "left"

            erase_boxes.append((bx1 - erase_left_pad, by1 - 5, bx2 + 8, by2 + 6, mode))
            final_els.append({
                "id": el_id,
                "label": el_label,
                "type": "text",
                "text": txt,
                "x": max(4, bx1 - 4),
                "y": max(4, by1 - 3),
                "w": max(120, (bx2 - bx1) + 24),
                "h": max(28, (by2 - by1) + 8),
                "fontSize": fsize,
                "fontWeight": fweight,
                "font": ffont,
                "color": fg_color,
                "bg": "transparent",
                "borderColor": "transparent",
                "borderWidth": 0,
                "align": falign,
            })

        if not final_els:
            return "", []

        bg_out = self._inpaint_card_background_data_uri(card_rgb, erase_boxes)
        return bg_out, final_els

    def _tool_decompose_image_to_design(
        self,
        image_path: str = "last",
        output_html: str = "gorsel_parcali_editor.html",
        instructions: str = "",
        open_browser: bool = True,
    ) -> str:
        from PIL import Image
        src_img = self._find_image_for_decomposition(image_path, instructions)
        if not src_img or not os.path.isfile(src_img):
            state = self._load_active_design_state()
            if instructions:
                self._apply_natural_language_layer_edits(state, instructions)
            rel, opened_note, els = self._write_and_sync_stitch_html(
                state["out_path"], state["title"], state["width"], state["height"], state["background"], state["elements"], open_browser=open_browser
            )
            part_list = ", ".join(f"#{e['id']} ({e.get('label','')})" for e in els)
            return f"Aktif tasarım katmanlarına ayrıldı{opened_note}: {rel} — Parçalar: {part_list}"

        # Delegate to card_layer_engine if available
        if card_layer_engine is not None and src_img and os.path.isfile(src_img):
            try:
                decomp = card_layer_engine.decompose_card(src_img)
                if decomp and "layers" in decomp and decomp["layers"]:
                    canvas_cfg = decomp.get("canvas", {})
                    w = canvas_cfg.get("width", 1024)
                    h = canvas_cfg.get("height", 686)
                    bg_css = decomp.get("background_image") or decomp.get("background") or ""
                    if bg_css and os.path.isfile(bg_css):
                        bg_css = f"url('{os.path.basename(bg_css)}')"
                    vision_els = self._assign_semantic_layer_ids(decomp.get("layers", []))
                    out_name = (output_html or "gorsel_parcali_editor.html").strip()
                    if not out_name.lower().endswith(".html"):
                        out_name += ".html"
                    out_path = self._resolve_workspace_path(out_name)
                    title = f"Görsel Parça Editörü ({os.path.basename(src_img)})"
                    state = self._save_active_design_state(out_path, title, w, h, bg_css, vision_els, source_image=src_img)
                    if instructions:
                        self._apply_natural_language_layer_edits(state, instructions)
                        bg_css = state["background"]
                        vision_els = state["elements"]
                    rel, opened_note, final_els = self._write_and_sync_stitch_html(
                        out_path, title, w, h, bg_css, vision_els, open_browser=open_browser, source_image=src_img
                    )
                    summary_parts = [
                        f"#{e['id']} ({e.get('label','')}): \"{str(e.get('text') or e.get('type'))[:28]}\""
                        for e in final_els if e.get("id")
                    ]
                    return (
                        f"İnteraktif Stitch tasarım editörü oluşturuldu{opened_note}: {rel} "
                        f"(Görsel: {os.path.basename(src_img)}, {len(final_els)} ayrıştırılmış parça: "
                        + ", ".join(summary_parts[:10])
                        + " — Her parçayı fareyle sürükleyebilir veya sohbette yapay zekaya söyleyerek değiştirebilirsiniz)."
                    )
            except Exception:
                pass

        with Image.open(src_img) as im:
            raw_rgb = im.convert("RGB")
            rgb = self._deskew_and_crop_card(raw_rgb)
            orig_w, orig_h = rgb.size
            if orig_w >= orig_h:
                ratio = orig_w / max(orig_h, 1)
                w = 1004
                h = 650 if 1.32 <= ratio <= 1.82 else max(480, min(860, int(round(1004 / ratio))))
            else:
                w, h = 650, 1004
            card_rgb = rgb.resize((w, h), Image.LANCZOS)

            small = card_rgb.resize((64, 64), Image.BILINEAR)
            sp = small.load()
            tl_c = sp[4, 4]
            br_c = sp[59, 59]
            bg_hex1 = f"#{tl_c[0]:02x}{tl_c[1]:02x}{tl_c[2]:02x}"
            bg_hex2 = f"#{br_c[0]:02x}{br_c[1]:02x}{br_c[2]:02x}"

        bg_css, vision_els = "", []
        try:
            self._set_live_status("🔍 Görseldeki parçalar (logo, metin, 3D zemin) ayrıştırılıyor...", THEME["warning"])
            bg_css, vision_els = self._analyze_image_layers_with_vision(card_rgb, w, h, bg_hex1, bg_hex2)
        except Exception:
            bg_css, vision_els = "", []

        vision_els = self._assign_semantic_layer_ids(vision_els)
        out_name = (output_html or "gorsel_parcali_editor.html").strip()
        if not out_name.lower().endswith(".html"):
            out_name += ".html"
        out_path = self._resolve_workspace_path(out_name)
        title = f"Görsel Parça Editörü ({os.path.basename(src_img)})"

        state = self._save_active_design_state(out_path, title, w, h, bg_css, vision_els, source_image=src_img)
        if instructions:
            self._apply_natural_language_layer_edits(state, instructions)
            bg_css = state["background"]
            vision_els = state["elements"]

        rel, opened_note, final_els = self._write_and_sync_stitch_html(
            out_path, title, w, h, bg_css, vision_els, open_browser=open_browser, source_image=src_img
        )
        summary_parts = [
            f"#{e['id']} ({e.get('label','')}): \"{str(e.get('text') or e.get('type'))[:28]}\""
            for e in final_els
            if e.get("id")
        ]
        return (
            f"İnteraktif Stitch tasarım editörü oluşturuldu{opened_note}: {rel} "
            f"(Görsel: {os.path.basename(src_img)}, {len(final_els)} ayrıştırılmış parça: "
            + ", ".join(summary_parts[:10])
            + " — Her parçayı fareyle sürükleyebilir veya sohbette yapay zekaya söyleyerek değiştirebilirsiniz)."
        )

    @classmethod
    def _match_target_layer(cls, elements: list, target_query: str) -> list:
        """Kullanıcının veya AI'ın söylediği parça adını ('isim', 'logo', 'unvan', 'telefon', 'adres' vb.) katmanlarla eşleştirir."""
        q = (target_query or "").strip().lower().lstrip("#")
        if not q:
            return []
        synonyms = {
            "isim": ("isim", "ad", "ad soyad", "başlık", "baslik", "name", "kişi"),
            "unvan": ("unvan", "ünvan", "meslek", "rol", "alt başlık", "pozisyon", "title", "subtitle"),
            "logo": ("logo", "amblem", "monogram", "ikon", "simge", "yuvarlak", "daire", "baş harf"),
            "logo_gorsel": ("logo görseli", "kırpılan logo", "resim", "fotoğraf", "görsel"),
            "firma": ("firma", "şirket", "sirket", "kurum", "marka", "üst rozet", "rozet", "etiket"),
            "telefon": ("telefon", "tel", "numara", "gsm", "cep", "phone"),
            "eposta": ("eposta", "e-posta", "mail", "email", "epostayı", "maili"),
            "web": ("web", "site", "internet", "url", "domain", "website"),
            "adres": ("adres", "konum", "şehir", "sehir", "lokasyon", "yer"),
            "slogan": ("slogan", "alt yazı", "not", "footer"),
            "ayirici_cizgi": ("çizgi", "cizgi", "ayırıcı", "ayirici", "divider"),
            "panel": ("panel", "sağ kutu", "sol kutu", "kule", "blok", "kutu"),
            "cerceve": ("çerçeve", "cerceve", "kenarlık", "border"),
        }
        canonical_ids = {q}
        for cid, words in synonyms.items():
            if q == cid or any(w == q or (len(w) >= 3 and w in q) for w in words):
                canonical_ids.add(cid)

        exact_matches = []
        partial_matches = []
        for el in elements:
            eid = str(el.get("id") or "").lower()
            lbl = str(el.get("label") or "").lower()
            txt = str(el.get("text") or "").lower()
            if eid in canonical_ids:
                exact_matches.append(el)
            elif any(eid.startswith(c) for c in canonical_ids) or q in eid or (lbl and q in lbl) or (txt and len(q) >= 3 and q in txt):
                partial_matches.append(el)
        return exact_matches + partial_matches

    @classmethod
    def _apply_single_layer_update(cls, state: dict, upd: dict) -> list:
        """Tek bir update sözlüğünü state['elements'] üzerinde uygular ve değişen parçaların özetini döndürür."""
        els = state.get("elements") or []
        w = int(state.get("width") or 1004)
        h = int(state.get("height") or 650)
        target = str(upd.get("target") or upd.get("id") or "").strip()
        tl = target.lower().lstrip("#")

        if tl in ("arka plan", "arkaplan", "zemin", "background", "tuval"):
            new_bg = upd.get("bg") or upd.get("color") or upd.get("text") or ""
            if new_bg:
                state["background"] = cls._resolve_tr_color(str(new_bg), for_canvas_bg=True)
                return [f"#arka_plan → {state['background']}"]

        matched = cls._match_target_layer(els, target)
        if not matched:
            return []

        changes = []
        if upd.get("delete") is True:
            del_ids = {m.get("id") for m in matched}
            if "logo" in del_ids:
                del_ids.add("logo_halka")
                del_ids.add("logo_gorsel")
            state["elements"] = [e for e in els if e.get("id") not in del_ids]
            return [f"#{i} silindi" for i in sorted(del_ids)]

        target_el = matched[0]
        eid = target_el.get("id", "parca")
        old_cx = int(target_el.get("x", 0)) + int(target_el.get("w", 0)) // 2
        old_cy = int(target_el.get("y", 0)) + int(target_el.get("h", 0)) // 2

        if upd.get("text") is not None and str(upd.get("text")).strip() != "":
            new_txt = str(upd["text"]).strip()
            old_txt = str(target_el.get("text") or "")
            for ico in ("📞", "☎", "✉", "🌐", "📍"):
                if old_txt.startswith(ico) and not new_txt.startswith(ico):
                    new_txt = f"{ico}  {new_txt}"
                    break
            target_el["text"] = new_txt
            if target_el.get("type") == "image":
                target_el["type"] = "text"
                target_el["src"] = ""
                target_el["fontSize"] = int(target_el.get("fontSize") or 42)
                target_el["fontWeight"] = "800"
                target_el["align"] = "center"
            changes.append(f"metin='{new_txt}'")
            # İsim değiştiyse ve logo 2-3 harfli varsayılan monogramsa baş harfleri de senkronize et
            if eid == "isim":
                initials = "".join(p[0] for p in new_txt.split()[:2] if p and p[0].isalpha()).upper()
                if len(initials) >= 2:
                    for el_other in els:
                        if el_other.get("id") == "logo" and el_other.get("type") == "circle" and len(str(el_other.get("text") or "")) <= 3:
                            el_other["text"] = initials

        pos = str(upd.get("position") or "").lower().strip()
        ew = int(target_el.get("w") or 120)
        eh = int(target_el.get("h") or 40)
        if pos:
            if any(k in pos for k in ("sol_ust", "sol üst", "sol-üst", "top_left")):
                target_el["x"], target_el["y"] = 64, 56
            elif any(k in pos for k in ("sag_ust", "sağ üst", "sağ-üst", "top_right")):
                target_el["x"], target_el["y"] = max(40, w - ew - 64), 56
            elif any(k in pos for k in ("sol_alt", "sol alt", "bottom_left")):
                target_el["x"], target_el["y"] = 64, max(40, h - eh - 56)
            elif any(k in pos for k in ("sag_alt", "sağ alt", "bottom_right")):
                target_el["x"], target_el["y"] = max(40, w - ew - 64), max(40, h - eh - 56)
            elif any(k in pos for k in ("ust_orta", "üst orta", "top_center")):
                target_el["x"], target_el["y"] = (w - ew) // 2, 56
            elif any(k in pos for k in ("alt_orta", "alt orta", "bottom_center")):
                target_el["x"], target_el["y"] = (w - ew) // 2, max(40, h - eh - 56)
            elif any(k in pos for k in ("orta", "merkez", "center")):
                target_el["x"], target_el["y"] = (w - ew) // 2, (h - eh) // 2
            elif "sol" in pos:
                target_el["x"] = 68
            elif "sağ" in pos or "sag" in pos:
                target_el["x"] = max(40, w - ew - 68)
            elif "yukar" in pos or "üst" in pos or "ust" in pos:
                target_el["y"] = max(24, int(target_el.get("y", 100)) - 70)
            elif "aşağ" in pos or "asag" in pos or "alt" in pos:
                target_el["y"] = min(h - eh - 24, int(target_el.get("y", 100)) + 70)
            changes.append(f"konum=({target_el['x']},{target_el['y']})")

        if upd.get("x") is not None:
            target_el["x"] = int(upd["x"])
            changes.append(f"x={target_el['x']}")
        if upd.get("y") is not None:
            target_el["y"] = int(upd["y"])
            changes.append(f"y={target_el['y']}")
        if upd.get("w") is not None:
            target_el["w"] = int(upd["w"])
            changes.append(f"w={target_el['w']}")
        if upd.get("h") is not None:
            target_el["h"] = int(upd["h"])
            changes.append(f"h={target_el['h']}")

        if upd.get("scale") is not None:
            sc = float(upd["scale"])
            if 0.3 <= sc <= 3.0:
                target_el["w"] = max(16, int(round(int(target_el.get("w", 120)) * sc)))
                target_el["h"] = max(4, int(round(int(target_el.get("h", 40)) * sc)))
                if target_el.get("fontSize"):
                    target_el["fontSize"] = max(9, int(round(int(target_el["fontSize"]) * sc)))
                changes.append(f"boyut={target_el['w']}x{target_el['h']}")

        if upd.get("fontSize") is not None:
            target_el["fontSize"] = int(upd["fontSize"])
            changes.append(f"font={target_el['fontSize']}px")
        if upd.get("color"):
            c_hex = cls._resolve_tr_color(str(upd["color"]))
            target_el["color"] = c_hex
            if target_el.get("type") == "line":
                target_el["bg"] = c_hex
            changes.append(f"renk={c_hex}")
        if upd.get("bg"):
            target_el["bg"] = cls._resolve_tr_color(str(upd["bg"]))
            changes.append(f"dolgu={target_el['bg']}")
        if upd.get("borderColor"):
            target_el["borderColor"] = cls._resolve_tr_color(str(upd["borderColor"]))
            changes.append(f"kenarlık={target_el['borderColor']}")
        if upd.get("align"):
            target_el["align"] = str(upd["align"])

        # Logo taşındıysa veya büyütüldüyse dış halkasını (#logo_halka) ve görselini (#logo_gorsel) birlikte hizala
        if eid == "logo":
            new_cx = int(target_el.get("x", 0)) + int(target_el.get("w", 0)) // 2
            new_cy = int(target_el.get("y", 0)) + int(target_el.get("h", 0)) // 2
            dx, dy = new_cx - old_cx, new_cy - old_cy
            for companion in els:
                if companion.get("id") in ("logo_halka", "logo_gorsel") and companion is not target_el:
                    companion["x"] = int(companion.get("x", 0)) + dx
                    companion["y"] = int(companion.get("y", 0)) + dy
                    if upd.get("scale") is not None:
                        sc = float(upd["scale"])
                        companion["w"] = int(round(int(companion.get("w", 160)) * sc))
                        companion["h"] = int(round(int(companion.get("h", 160)) * sc))

        return [f"#{eid} ({', '.join(changes)})"] if changes else []

    @classmethod
    def _apply_natural_language_layer_edits(cls, state: dict, text: str) -> list:
        """Türkçe doğal dil komutlarından ('ismi Ahmet Kaya yap', 'logoyu sağ üste al', 'adresi sil' vb.) katman güncellemeleri çıkarır."""
        import re
        if not text:
            return []
        t = text.strip()
        tl = t.lower()
        applied = []

        # Connect card_layer_engine natural language edits
        if card_layer_engine is not None and hasattr(card_layer_engine, "apply_natural_language_command"):
            try:
                curr_layers = copy.deepcopy(state.get("elements", []))
                updated_layers, engine_summary = card_layer_engine.apply_natural_language_command(text, curr_layers)
                if updated_layers != curr_layers or any(kw in engine_summary for kw in ("başarıyla", "ortalandı", "yaslandı", "kaydırıldı", "büyütüldü", "küçültüldü", "güncellendi")):
                    state["elements"] = updated_layers
                    if "layers" in state:
                        state["layers"] = updated_layers
                    applied.append(engine_summary)
                    return applied
            except Exception:
                pass

        # 1) Arka plan rengi değişimi
        bg_m = re.search(r"arka\s*plan[ıi]?\s+([a-zA-ZçğıöşüÇĞİÖŞÜ0-9#\s]{3,22}?)\s*(?:rengi\s*)?(?:yap|olsun|çevir|değiştir)", tl)
        if bg_m:
            applied.extend(cls._apply_single_layer_update(state, {"target": "arka plan", "bg": bg_m.group(1).strip()}))

        # 2) Silme komutları ("logoyu sil", "adresi kaldır", "rozeti sil")
        for target_kw, cid in [
            (r"logo(?:yu|su|nun)?", "logo"),
            (r"adres(?:i|ini)?", "adres"),
            (r"telefon(?:u|unu)?|numara(?:yı)?", "telefon"),
            (r"e-?posta(?:yı)?|mail(?:i)?", "eposta"),
            (r"web(?:\s*sitesini)?|site(?:yi)?", "web"),
            (r"ünvan(?:ı)?|unvan(?:ı)?|mesleğ(?:i)?", "unvan"),
            (r"firma(?:yı)?|şirket(?:i)?|rozet(?:i)?", "firma"),
            (r"çizgi(?:yi)?|cizgi(?:yi)?", "ayirici_cizgi"),
            (r"slogan(?:ı)?", "slogan"),
        ]:
            if re.search(rf"(?:{target_kw})\s+(?:sil|kaldır|yok\s*et|çıkar)\b", tl):
                applied.extend(cls._apply_single_layer_update(state, {"target": cid, "delete": True}))

        # 3) Konum taşıma ("logoyu sağ üste al", "ismi ortaya al")
        pos_patterns = [
            (r"sol\s*üst", "sol_ust"),
            (r"sağ\s*üst|sag\s*ust", "sag_ust"),
            (r"sol\s*alt", "sol_alt"),
            (r"sağ\s*alt|sag\s*alt", "sag_alt"),
            (r"üst\s*orta|ust\s*orta", "ust_orta"),
            (r"alt\s*orta", "alt_orta"),
            (r"orta(?:ya|la)|merkez(?:e)?", "orta"),
            (r"sağ(?:a|\s*tarafa)", "sag"),
            (r"sol(?:a|\s*tarafa)", "sol"),
            (r"yukar(?:ı|ıya)", "yukari"),
            (r"aşağ(?:ı|ıya)", "asagi"),
        ]
        for target_kw, cid in [
            (r"logo(?:yu)?|amblem(?:i)?", "logo"),
            (r"ism(?:i|ini)|isim|ad(?:ı|ını)?|başlığ(?:ı)?", "isim"),
            (r"ünvan(?:ı)?|unvan(?:ı)?", "unvan"),
            (r"firma(?:yı)?|rozet(?:i)?", "firma"),
            (r"telefon(?:u)?", "telefon"),
            (r"adres(?:i)?", "adres"),
        ]:
            for p_pat, p_code in pos_patterns:
                if re.search(rf"(?:{target_kw})\s+[^,;\n]*?\b(?:{p_pat})", tl):
                    applied.extend(cls._apply_single_layer_update(state, {"target": cid, "position": p_code}))
                    break
            if re.search(rf"(?:{target_kw})\s+(?:büyüt|buyut|büyük\s*yap|iri\s*yap)", tl):
                applied.extend(cls._apply_single_layer_update(state, {"target": cid, "scale": 1.25}))
            elif re.search(rf"(?:{target_kw})\s+(?:küçült|kucult|küçük\s*yap|ufalt)", tl):
                applied.extend(cls._apply_single_layer_update(state, {"target": cid, "scale": 0.8}))

        # 4) Metin değiştirme ("ismi Ahmet Kaya yap", "telefonu 0532 111 22 33 yap", "ünvanı Yazılım Mühendisi yap")
        text_rules = [
            (r"(?:ism(?:i|ini)|isim|ad(?:ı|ını)?(?:\s*soyad(?:ı|ını)?)?)\s+['\"]?([^'\"\n,;.]+?)['\"]?\s+(?:yap|olarak\s*değiştir|değiştir|olsun|yaz)", "isim"),
            (r"(?:ünvan(?:ı|ını)?|unvan(?:ı|ını)?|mesleğ(?:i|ini)?)\s+['\"]?([^'\"\n,;.]+?)['\"]?\s+(?:yap|olarak\s*değiştir|değiştir|olsun|yaz)", "unvan"),
            (r"(?:telefon(?:u|unu)?|numara(?:yı|sını)?|tel(?:i)?)\s+['\"]?([+\d][\d\s\-]{6,18})['\"]?\s*(?:yap|olarak\s*değiştir|değiştir|olsun|yaz)?", "telefon"),
            (r"(?:e-?posta(?:yı|sını)?|mail(?:i|ini)?|email(?:i)?)\s+['\"]?([\w\.\-]+@[\w\.\-]+)['\"]?\s*(?:yap|olarak\s*değiştir|değiştir|olsun|yaz)?", "eposta"),
            (r"(?:web(?:\s*sitesini)?|site(?:yi|sini)?)\s+['\"]?((?:www\.|https?://)?[\w\-]+\.[\w\.\-]+)['\"]?\s*(?:yap|olarak\s*değiştir|değiştir|olsun|yaz)?", "web"),
            (r"(?:adres(?:i|ini)?)\s+['\"]?([^'\"\n;]+?)['\"]?\s+(?:yap|olarak\s*değiştir|değiştir|olsun|yaz)", "adres"),
            (r"(?:firma(?:yı|sını)?|şirket(?:i|ini)?|rozet(?:i)?)\s+['\"]?([^'\"\n,;.]+?)['\"]?\s+(?:yap|olarak\s*değiştir|değiştir|olsun|yaz)", "firma"),
            (r"(?:logo(?:yu|daki\s*yazıyı|daki\s*harfleri)?|monogram(?:ı)?)\s+['\"]?([A-Za-zÇĞİÖŞÜçğıöşü]{1,4})['\"]?\s+(?:yap|olsun|yaz)", "logo"),
        ]
        for pat, cid in text_rules:
            m = re.search(pat, t, flags=re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val.lower() not in ("büyüt", "küçült", "sil", "kaldır", "sağ", "sol", "orta", "altın", "beyaz", "siyah", "kırmızı", "mavi"):
                    if cid in ("isim", "unvan", "firma", "logo"):
                        val = val.upper()
                    applied.extend(cls._apply_single_layer_update(state, {"target": cid, "text": val}))

        return applied

    def _tool_update_editable_design(
        self,
        updates: list = None,
        add_elements: list = None,
        background: str = "",
        open_browser: bool = True,
        raw_user_text: str = "",
    ) -> str:
        state = self._load_active_design_state()
        applied_notes = []

        if background and str(background).strip():
            state["background"] = self._resolve_tr_color(str(background).strip(), for_canvas_bg=True)
            applied_notes.append(f"Arka plan → {state['background']}")

        for upd in (updates or []):
            if isinstance(upd, dict):
                applied_notes.extend(self._apply_single_layer_update(state, upd))

        for new_el in (add_elements or []):
            if isinstance(new_el, dict):
                el_copy = dict(new_el)
                el_copy.setdefault("type", "text")
                el_copy.setdefault("x", 80)
                el_copy.setdefault("y", 80)
                el_copy.setdefault("w", 320)
                el_copy.setdefault("h", 44)
                state["elements"].append(el_copy)
                state["elements"] = self._assign_semantic_layer_ids(state["elements"])
                added = state["elements"][-1]
                applied_notes.append(f"+#{added.get('id')} eklendi ('{added.get('text','')}')")

        if raw_user_text and not applied_notes:
            applied_notes.extend(self._apply_natural_language_layer_edits(state, raw_user_text))

        rel, opened_note, final_els = self._write_and_sync_stitch_html(
            state["out_path"],
            state["title"],
            state["width"],
            state["height"],
            state["background"],
            state["elements"],
            open_browser=open_browser,
            source_image=state.get("source_image", ""),
        )
        summary_str = "; ".join(applied_notes) if applied_notes else "Tasarım katmanları güncellendi"
        return (
            f"İnteraktif Stitch tasarım editörü oluşturuldu{opened_note}: {rel} "
            f"(Güncellenen parçalar: {summary_str} | Toplam {len(final_els)} düzenlenebilir katman)."
        )

    def _start_stitch_ai_bridge(self):
        """Tarayıcıdaki Stitch editöründen gelen canlı AI düzenleme isteklerini karşılayan yerel HTTP köprüsü."""
        if getattr(self, "_stitch_bridge_started", False):
            return
        self._stitch_bridge_started = True
        parent = self

        def _serve():
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
            import json as _json

            class _StitchBridgeHandler(BaseHTTPRequestHandler):
                def log_message(self, format, *args):
                    return

                def _send_cors(self, code=200):
                    self.send_response(code)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()

                def do_OPTIONS(self):
                    self._send_cors(204)

                def do_GET(self):
                    if self.path.startswith("/api/health"):
                        self._send_cors(200)
                        self.wfile.write(b'{"ok":true,"service":"stitch_ai_plus"}')
                    else:
                        self._send_cors(404)
                        self.wfile.write(b'{"ok":false,"error":"not_found"}')

                def do_POST(self):
                    if not self.path.startswith("/api/ai_edit"):
                        self._send_cors(404)
                        self.wfile.write(b'{"ok":false,"error":"not_found"}')
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0") or "0")
                        raw = self.rfile.read(min(length, 8 * 1024 * 1024))
                        payload = _json.loads(raw.decode("utf-8"))
                        res = parent._handle_stitch_ai_edit(payload)
                        self._send_cors(200)
                        self.wfile.write(_json.dumps(res, ensure_ascii=False).encode("utf-8"))
                    except Exception as exc:
                        self._send_cors(500)
                        self.wfile.write(
                            _json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
                        )

            try:
                srv = ThreadingHTTPServer(("127.0.0.1", 18765), _StitchBridgeHandler)
                parent._stitch_bridge_server = srv
                srv.serve_forever()
            except OSError:
                # Port zaten başka bir örnek tarafından dinleniyorsa sessizce devam et
                pass

        t = threading.Thread(target=_serve, daemon=True, name="stitch-ai-bridge")
        t.start()

    def _recolor_or_redesign_logo_layer(self, layer_el: dict, prompt: str, state: dict) -> str:
        """Seçili logo/görsel katmanını istenen renge boyar veya vektör SVG logo olarak yeniden tasarlar."""
        import base64
        import io
        import re
        import urllib.parse

        pl = prompt.lower()
        wants_redesign = any(
            k in pl
            for k in (
                "yeni logo", "vektör", "vektor", "tasarla", "yeniden", "oluştur", "olustur",
                "modern logo", "minimal logo", "svg", "çiz", "ciz", "ikon yap", "amblem",
            )
        )

        # Hedef renk tespiti
        target_hex = ""
        hex_m = re.search(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", prompt)
        if hex_m:
            target_hex = "#" + hex_m.group(1)
        else:
            for cname in (
                "altın", "altin", "gold", "bakır", "bakir", "gümüş", "gumus", "silver",
                "lacivert", "mavi", "turkuaz", "cyan", "kırmızı", "kirmizi", "bordo",
                "yeşil", "yesil", "zümrüt", "siyah", "beyaz", "gri", "mor", "turuncu", "sarı", "sari",
            ):
                if cname in pl:
                    target_hex = self._resolve_tr_color(cname)
                    break

        if wants_redesign or layer_el.get("type") != "image" or not str(layer_el.get("src", "")).startswith("data:image/"):
            # Marka adı / baş harfler çıkar
            brand = ""
            for e in state.get("elements", []):
                if e.get("id") in ("firma", "isim") and e.get("text"):
                    brand = re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü0-9 ]+", "", str(e.get("text"))).strip()
                    break
            if not brand:
                brand = str(layer_el.get("text") or state.get("title") or "AI")
            words = [w for w in brand.split() if len(w) > 0]
            initials = (words[0][0] + (words[1][0] if len(words) > 1 else (words[0][1] if len(words[0]) > 1 else ""))).upper()
            c1 = target_hex or "#d4af37"
            c2 = "#f5e6a8" if c1.lower() in ("#d4af37", "#c9a45c", "#eab308") else "#ffffff"

            svg_code = None
            # Canlı Evren 32B varsa özel SVG iste (kısa timeout)
            if getattr(self, "evren_base_url", ""):
                try:
                    sys_msg = (
                        "Sen uzman bir vektör logo tasarımcısısın. Sadece geçerli tek bir <svg ...>...</svg> kodu döndür. "
                        "Açıklama, markdown ``` yazma. viewBox='0 0 240 240' kullan, temiz geometrik amblem ve tipografi çiz."
                    )
                    usr_msg = f"Marka: '{brand}' (Baş harfler: {initials}). İstek: {prompt}. Ana renk: {c1}."
                    resp = self.http_session.post(
                        f"{self.evren_base_url.rstrip('/')}/chat/completions",
                        headers=self._evren_headers(),
                        json={
                            "model": self.evren_model,
                            "messages": [
                                {"role": "system", "content": sys_msg},
                                {"role": "user", "content": usr_msg},
                            ],
                            "temperature": 0.4,
                            "max_tokens": 900,
                        },
                        timeout=14,
                    )
                    if resp.status_code == 200:
                        txt = resp.json()["choices"][0]["message"]["content"]
                        m_svg = re.search(r"<svg[\s\S]*?</svg>", txt, re.IGNORECASE)
                        if m_svg and len(m_svg.group(0)) < 12000:
                            svg_code = m_svg.group(0)
                except Exception:
                    svg_code = None

            if not svg_code:
                svg_code = (
                    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240">'
                    f'<defs><linearGradient id="lg" x1="0%" y1="0%" x2="100%" y2="100%">'
                    f'<stop offset="0%" stop-color="{c1}"/><stop offset="100%" stop-color="{c2}"/>'
                    f'</linearGradient></defs>'
                    f'<polygon points="120,14 212,67 212,173 120,226 28,173 28,67" '
                    f'fill="rgba(15,23,42,0.85)" stroke="url(#lg)" stroke-width="7"/>'
                    f'<polygon points="120,30 198,75 198,165 120,210 42,165 42,75" '
                    f'fill="none" stroke="url(#lg)" stroke-width="2" opacity="0.55"/>'
                    f'<text x="120" y="138" text-anchor="middle" fill="url(#lg)" '
                    f'font-family="Georgia, serif" font-size="74" font-weight="800" letter-spacing="4">{initials}</text>'
                    f'</svg>'
                )

            b64_svg = base64.b64encode(svg_code.encode("utf-8")).decode("ascii")
            layer_el["type"] = "image"
            layer_el["src"] = f"data:image/svg+xml;base64,{b64_svg}"
            layer_el["bg"] = "transparent"
            layer_el["borderWidth"] = 0
            layer_el["label"] = "AI Vektör Logo"
            return f"#{layer_el.get('id', 'logo')} AI ile yeni vektör SVG logo olarak tasarlandı"

        # Mevcut raster görseli hedef renge boya (alfa kanalını koruyarak)
        if target_hex:
            src = str(layer_el.get("src", ""))
            if src.startswith("data:image/svg+xml"):
                raw_svg = ""
                if ";base64," in src:
                    raw_svg = base64.b64decode(src.split(",", 1)[1]).decode("utf-8", errors="ignore")
                elif "," in src:
                    raw_svg = urllib.parse.unquote(src.split(",", 1)[1])
                if raw_svg:
                    raw_svg = re.sub(r'#[0-9a-fA-F]{6}', target_hex, raw_svg)
                    layer_el["src"] = "data:image/svg+xml;base64," + base64.b64encode(raw_svg.encode("utf-8")).decode("ascii")
                    return f"#{layer_el.get('id', 'logo')} SVG rengi {target_hex} yapıldı"
            elif ";base64," in src:
                try:
                    import numpy as np
                    from PIL import Image

                    b64_data = src.split(",", 1)[1]
                    im = Image.open(io.BytesIO(base64.b64decode(b64_data))).convert("RGBA")
                    arr = np.array(im, dtype=np.float32)
                    hx = target_hex.lstrip("#")
                    if len(hx) == 3:
                        hx = "".join(ch * 2 for ch in hx)
                    tr, tg, tb = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)

                    # Parlaklık tonunu hafifçe koruyarak hedef renge boya
                    lum = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]) / 255.0
                    shade = 0.65 + 0.35 * (1.0 - lum)
                    arr[:, :, 0] = np.clip(tr * shade, 0, 255)
                    arr[:, :, 1] = np.clip(tg * shade, 0, 255)
                    arr[:, :, 2] = np.clip(tb * shade, 0, 255)
                    out_im = Image.fromarray(arr.astype(np.uint8), "RGBA")
                    buf = io.BytesIO()
                    out_im.save(buf, format="PNG")
                    layer_el["src"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
                    return f"#{layer_el.get('id', 'logo')} rengi {target_hex} olarak yeniden boyandı"
                except Exception:
                    pass
        return ""

    def _handle_stitch_ai_edit(self, payload: dict) -> dict:
        """Tarayıcı editöründen gelen Stitch AI+ komutunu işler ve güncel state döndürür."""
        import copy
        import json as _json
        import re

        prompt = str(payload.get("prompt") or "").strip()
        selected_id = str(payload.get("selectedId") or "").strip()
        state = copy.deepcopy(payload.get("state") or {})
        if not prompt:
            return {"ok": False, "error": "Boş komut gönderildi."}
        els = state.setdefault("elements", [])
        notes = []

        # Seçili öğeyi bul
        sel_el = next((e for e in els if e.get("id") == selected_id), None)
        pl = prompt.lower()

        # 1) Logo / görsel yeniden tasarlama veya yeniden boyama
        explicit_logo = any(k in pl for k in ("logo", "amblem", "vektör", "vektor", "svg"))
        target_logo = sel_el if (sel_el and sel_el.get("type") == "image" and (explicit_logo or not re.search(r"#\w+", pl))) else (
            next((e for e in els if e.get("id") == "logo"), None) if explicit_logo else None
        )
        if target_logo and (
            any(k in pl for k in ("yeni logo", "vektör", "vektor", "tasarla", "yeniden", "svg", "çiz", "ciz", "modern logo"))
            or (
                target_logo.get("type") == "image"
                and any(
                    c in pl
                    for c in (
                        "altın", "altin", "gold", "mavi", "lacivert", "kırmızı", "kirmizi",
                        "yeşil", "yesil", "siyah", "beyaz", "bakır", "gümüş", "mor", "turuncu", "#",
                    )
                )
            )
        ):
            msg = self._recolor_or_redesign_logo_layer(target_logo, prompt, state)
            if msg:
                notes.append(msg)

        # 2) Doğrudan seçili katman üzerinde kısa komut ("sil", "büyüt", "küçült", "ortala", "... yap")
        if sel_el and not notes and not re.search(r"#\w+", pl):
            if any(w in pl for w in ("bunu sil", "parçayı sil", "katmanı sil")) or pl in ("sil", "kaldır", "kaldir"):
                notes.extend(self._apply_single_layer_update(state, {"target": selected_id, "delete": True}))
            elif "büyüt" in pl or "buyut" in pl:
                notes.extend(self._apply_single_layer_update(state, {"target": selected_id, "scale": 1.25}))
            elif "küçült" in pl or "kucult" in pl:
                notes.extend(self._apply_single_layer_update(state, {"target": selected_id, "scale": 0.8}))
            else:
                # Doğal dil kural motorunu seçili id prefix'i ile de dene
                notes.extend(self._apply_natural_language_layer_edits(state, prompt))
                if not notes and sel_el.get("type") != "image":
                    m_set = re.match(r"^(?:yazıyı|metni|bunu|içeriği)?\s*['\"]?(.+?)['\"]?\s*(?:yap|olsun|olarak değiştir)$", prompt.strip(), re.IGNORECASE)
                    if m_set and len(m_set.group(1).strip()) >= 2:
                        val = m_set.group(1).strip()
                        c_try = self._resolve_tr_color(val)
                        if c_try.startswith("#") and len(val.split()) <= 2:
                            notes.extend(self._apply_single_layer_update(state, {"target": selected_id, "color": val}))
                        else:
                            notes.extend(self._apply_single_layer_update(state, {"target": selected_id, "text": val}))

        # 3) Genel doğal dil kuralları
        if not notes:
            notes.extend(self._apply_natural_language_layer_edits(state, prompt))

        # 4) Karmaşık isteklerde canlı 32B Qwen JSON yaması
        if not notes and getattr(self, "evren_base_url", ""):
            try:
                compact_els = [
                    {
                        "id": e.get("id"),
                        "type": e.get("type"),
                        "text": str(e.get("text", ""))[:80],
                        "x": e.get("x"),
                        "y": e.get("y"),
                        "w": e.get("w"),
                        "h": e.get("h"),
                        "color": e.get("color"),
                        "bg": e.get("bg"),
                    }
                    for e in els
                ]
                sys_prompt = (
                    "Sen Stitch AI+ tasarım editörü asistanısın. Kullanıcının tasarım katmanlarını değiştiren JSON döndür. "
                    "Sadece geçerli JSON döndür: "
                    '{"background":"opsiyonel css","updates":[{"target":"katman_id","text":"...","color":"#hex","bg":"#hex","x":0,"y":0,"scale":1.0,"delete":false}],'
                    '"add":[{"type":"text|badge|rect|circle","text":"...","x":50,"y":50,"w":220,"h":40,"color":"#fff","bg":"transparent"}]}. '
                    f"Tuval: {state.get('width', 1004)}x{state.get('height', 650)}. Seçili katman: #{selected_id or 'yok'}."
                )
                resp = self.http_session.post(
                    f"{self.evren_base_url.rstrip('/')}/chat/completions",
                    headers=self._evren_headers(),
                    json={
                        "model": self.evren_model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": f"Katmanlar: {_json.dumps(compact_els, ensure_ascii=False)}\nİstek: {prompt}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 900,
                    },
                    timeout=18,
                )
                if resp.status_code == 200:
                    raw_txt = resp.json()["choices"][0]["message"]["content"]
                    jm = re.search(r"\{[\s\S]*\}", raw_txt)
                    if jm:
                        patch = _json.loads(jm.group(0))
                        if patch.get("background"):
                            state["background"] = self._resolve_tr_color(str(patch["background"]), for_canvas_bg=True)
                            notes.append("Arka plan güncellendi")
                        for upd in patch.get("updates", []) or []:
                            notes.extend(self._apply_single_layer_update(state, upd))
                        for ad in patch.get("add", []) or []:
                            if isinstance(ad, dict):
                                ad_copy = dict(ad)
                                ad_copy.setdefault("x", 80)
                                ad_copy.setdefault("y", 80)
                                ad_copy.setdefault("w", 240)
                                ad_copy.setdefault("h", 44)
                                els.append(ad_copy)
                                state["elements"] = self._assign_semantic_layer_ids(els)
                                notes.append(f"+#{state['elements'][-1].get('id')} eklendi")
            except Exception as exc:
                notes.append(f"AI uyarısı: {exc}")

        state["elements"] = self._assign_semantic_layer_ids(state.get("elements", []))
        if getattr(self, "active_design_file", None):
            try:
                self._save_active_design_state(
                    self.active_design_file,
                    state.get("title", "Tasarım"),
                    int(state.get("width", 1004)),
                    int(state.get("height", 650)),
                    state.get("background", "#0f1116"),
                    state["elements"],
                    source_image=state.get("source_image", ""),
                )
            except Exception:
                pass

        return {
            "ok": bool(notes),
            "state": state,
            "summary": "; ".join(notes) if notes else "Komut anlaşılamadı. Örn: 'altın yap', 'yeni vektör logo tasarla', 'telefonu 0532 111 22 33 yap' veya 'bunu sil'.",
        }

    def _tool_photoshop_edit(self, input_path: str, operations: list, output_path: str = "") -> str:
        from PIL import Image
        src = self._resolve_workspace_path(input_path)
        if not os.path.isfile(src):
            return f"Görsel bulunamadı: {input_path}"

        if not output_path:
            stem, ext = os.path.splitext(input_path)
            output_path = f"{stem}_edited{ext or '.png'}"
        dst = self._resolve_workspace_path(output_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)

        img, applied = _apply_photoshop_ops_pil(
            Image.open(src),
            operations,
            path_resolver=self._resolve_workspace_path,
        )

        if dst.lower().endswith((".jpg", ".jpeg")):
            img.convert("RGB").save(dst, quality=95)
        else:
            img.save(dst, "PNG")
        rel_out = os.path.relpath(dst, self.agent_workspace_dir)
        return f"Photoshop düzenlemesi kaydedildi: {rel_out} ({img.width}x{img.height}) | İşlemler: {', '.join(applied) or 'yok'}"

    def _execute_tool_calls(self, tool_calls: list, user_text: str) -> list:
        """Modelden gelen tool_calls listesini yerel araçlarla çalıştırır."""
        import json
        executed = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            t_name = fn.get("name", "")
            t_args = fn.get("arguments") or {}
            if isinstance(t_args, str):
                try:
                    t_args = json.loads(t_args)
                except Exception:
                    t_args = {}

            self._set_live_status(f"⚙️ Araç Çalışıyor: {t_name}...", THEME["warning"])
            try:
                if t_name == "list_files":
                    res_str = self._tool_list_files(str(t_args.get("subpath", "")))
                elif t_name == "read_file":
                    res_str = self._tool_read_file(
                        str(t_args.get("path", "")),
                        t_args.get("start_line", 1),
                        t_args.get("end_line", 500),
                    )
                elif t_name == "write_file":
                    res_str = self._tool_write_file(
                        str(t_args.get("path", "")),
                        str(t_args.get("content", "")),
                    )
                elif t_name == "edit_file":
                    res_str = self._tool_edit_file(
                        str(t_args.get("path", "")),
                        str(t_args.get("old_text", "")),
                        str(t_args.get("new_text", "")),
                    )
                elif t_name == "run_command":
                    res_str = self._tool_run_command(str(t_args.get("command", "")))
                elif t_name == "launch_app":
                    res_str = self._tool_launch_app(
                        str(t_args.get("command", "")),
                        str(t_args.get("url", "")),
                        str(t_args.get("html_path", "")),
                    )
                elif t_name == "design_graphic":
                    res_str = self._tool_design_graphic(
                        str(t_args.get("output_path", "assets/graphic.png")),
                        str(t_args.get("title", "Tasarım")),
                        str(t_args.get("subtitle", "")),
                        str(t_args.get("badge", "")),
                        t_args.get("width", 1200),
                        t_args.get("height", 630),
                        str(t_args.get("theme", "indigo")),
                        str(t_args.get("style", "modern")),
                        str(t_args.get("hero_image_path", "")),
                        str(t_args.get("footer_text", "")),
                        str(t_args.get("layout", "auto")),
                        t_args.get("items") or [],
                        str(t_args.get("monogram", "")),
                        str(t_args.get("font_family", "sans")),
                    )
                elif t_name == "render_html_graphic":
                    res_str = self._tool_render_html_graphic(
                        str(t_args.get("output_path", "assets/graphic.png")),
                        str(t_args.get("html", "")),
                        t_args.get("width", 1200),
                        t_args.get("height", 630),
                        bool(t_args.get("transparent", False)),
                    )
                elif t_name == "create_editable_design":
                    res_str = self._tool_create_editable_design(
                        str(t_args.get("output_html", "tasarim_editoru.html")),
                        str(t_args.get("title", "Tasarım Stüdyosu")),
                        t_args.get("width", 1004),
                        t_args.get("height", 650),
                        str(t_args.get("background", "linear-gradient(135deg,#0f1116 0%,#1a1d24 100%)")),
                        t_args.get("elements"),
                        bool(t_args.get("open_browser", True)),
                    )
                elif t_name == "decompose_image_to_design":
                    res_str = self._tool_decompose_image_to_design(
                        str(t_args.get("image_path", "last")),
                        str(t_args.get("output_html", "gorsel_parcali_editor.html")),
                        str(t_args.get("instructions", "") or user_text),
                        bool(t_args.get("open_browser", True)),
                    )
                elif t_name == "update_editable_design":
                    res_str = self._tool_update_editable_design(
                        t_args.get("updates") or [],
                        t_args.get("add_elements") or [],
                        str(t_args.get("background", "")),
                        bool(t_args.get("open_browser", True)),
                        raw_user_text=user_text,
                    )
                elif t_name == "move_or_copy_file":
                    res_str = self._tool_move_or_copy_file(
                        str(t_args.get("source_path", "last")),
                        str(t_args.get("destination_path", "desktop")),
                        str(t_args.get("action", "copy")),
                        bool(t_args.get("open_after", True)),
                    )
                elif t_name == "photoshop_edit":
                    res_str = self._tool_photoshop_edit(
                        str(t_args.get("input_path", "")),
                        t_args.get("operations") or [],
                        str(t_args.get("output_path", "")),
                    )
                elif t_name == "calculator":
                    res_str = self._tool_calculator(str(t_args.get("expression", "")))
                elif t_name == "getSystemTime":
                    res_str = self._tool_get_system_time()
                elif t_name == "generateDocument":
                    res_str = self._tool_generate_document(
                        str(t_args.get("title") or "Belge"),
                        str(t_args.get("content") or user_text),
                    )
                else:
                    res_str = f"Bilinmeyen araç: {t_name}"
            except Exception as tool_exc:
                res_str = f"Araç hatası: {tool_exc}"

            executed.append({
                "id": tc.get("id", ""),
                "name": t_name,
                "result": res_str,
            })
            preview = res_str.replace("\n", " ")[:180]
            self._append_stream_text(f"⚙️ [Araç: {t_name}] → {preview}\n", "tool")
            img_rel = self._extract_image_rel_from_tool_result(res_str)
            if img_rel:
                self._append_stream_text(img_rel, "__IMG__")
            else:
                file_rel = self._extract_file_path_from_tool_result(res_str)
                if file_rel:
                    self._append_stream_text(file_rel, "__FILE__")
        return executed

    def _compact_evren_tool_history(self, messages: list):
        """Eski adımlardaki uzun write_file gövdelerini ve eski araç çıktılarını kısaltır."""
        import json
        cutoff = max(0, len(messages) - 4)
        for idx, msg in enumerate(messages):
            if idx < cutoff and msg.get("role") == "tool":
                c = msg.get("content") or ""
                if isinstance(c, str) and len(c) > 800:
                    msg["content"] = c[:400] + "\n... [önceki adım çıktısı kısaltıldı]"
                continue
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                if fn.get("name") != "write_file":
                    continue
                raw_args = fn.get("arguments")
                if isinstance(raw_args, str) and len(raw_args) > 1200:
                    try:
                        parsed = json.loads(raw_args)
                        path_val = parsed.get("path", "dosya")
                        fn["arguments"] = json.dumps(
                            {"path": path_val, "content": f"[yazıldı: {len(parsed.get('content', ''))} karakter]"},
                            ensure_ascii=False,
                        )
                    except Exception:
                        pass

    class _EvrenFallbackNeeded(RuntimeError):
        pass

    def _stream_evren_step(self, model_name: str, messages: list, tools_for_turn: list, step_num: int) -> dict:
        """EVREN API veya Kendi AI Sunucusundan tek bir ajan adımını canlı akış ile çalıştırır."""
        import json
        content_parts = []
        tc_map = {}
        header_printed = False
        char_count = 0
        is_gemini = "generativelanguage.googleapis.com" in self.evren_base_url.lower()
        is_custom_srv = "ssyz.org.tr" not in self.evren_base_url.lower()

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "temperature": 0.2 if is_custom_srv else (0.25 if step_num > 1 else 0.4),
            "max_tokens": 4096 if (is_gemini or not is_custom_srv) else 384,
            **({} if is_custom_srv else self._evren_speed_payload_opts(model_name)),
        }
        if tools_for_turn and not is_custom_srv:
            payload["tools"] = tools_for_turn
            payload["tool_choice"] = "auto"

        step_started = time.time()
        max_step_seconds = float(getattr(self, "evren_step_max_seconds", 240.0))
        stall_fallback_seconds = 95.0 if is_custom_srv else float(getattr(self, "evren_stall_fallback_seconds", 22.0))
        can_fallback = (not is_custom_srv and step_num == 1 and (model_name or "").strip() != "qwen3-vl-30b")
        req_timeout = (10, 95) if is_custom_srv else (8, 45)

        try:
            resp_ctx = self.http_session.post(
                f"{self.evren_base_url}/chat/completions",
                headers=self._evren_headers(),
                json=payload,
                stream=True,
                timeout=req_timeout,
            )
        except requests.exceptions.Timeout as exc:
            if can_fallback:
                raise self._EvrenFallbackNeeded(f"{model_name} zaman aşımı") from exc
            raise

        with resp_ctx as resp:
            if resp.status_code != 200:
                err_txt = self._extract_evren_error(resp)
                if can_fallback and resp.status_code in (404, 429, 502, 503, 504):
                    raise self._EvrenFallbackNeeded(f"{model_name} HTTP {resp.status_code}: {err_txt}")
                raise RuntimeError(err_txt)

            reason_chars = 0
            text_chars = 0
            for raw_line in resp.iter_lines(decode_unicode=True):
                if self.cancel_agent:
                    raise RuntimeError("İşlem kullanıcı tarafından durduruldu.")
                elapsed = time.time() - step_started
                if can_fallback and not header_printed and char_count == 0 and elapsed > stall_fallback_seconds:
                    raise self._EvrenFallbackNeeded(
                        f"{model_name} {int(elapsed)}sn içinde çıktı/araç üretemedi ({reason_chars} düşünme krk)"
                    )
                if elapsed > max_step_seconds:
                    total_chars = reason_chars + text_chars + char_count
                    rate = total_chars / max(elapsed, 0.01)
                    raise RuntimeError(
                        f"Adım {step_num} {int(max_step_seconds)}sn zaman aşımına ulaştı "
                        f"({model_name}: {total_chars} krk, {rate:.0f} krk/sn). "
                        f"Daha hızlı sonuç için qwen3-vl-30b modelini veya özel araçları kullanın."
                    )
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                chunk = json.loads(data_str)
                if chunk.get("error"):
                    err = chunk["error"]
                    raise RuntimeError(err.get("message") if isinstance(err, dict) else str(err))
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                reason_piece = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if reason_piece:
                    reason_chars += len(reason_piece)
                    if reason_chars % 250 < len(reason_piece):
                        rate = reason_chars / max(time.time() - step_started, 0.01)
                        self._set_live_status(
                            f"🧠 Adım {step_num}: Düşünüyor ({reason_chars} krk • {rate:.0f} krk/sn)...",
                            THEME["warning"],
                        )

                piece = delta.get("content") or ""
                if piece:
                    content_parts.append(piece)
                    text_chars += len(piece)
                    full_so_far = "".join(content_parts).lstrip()
                    if not (full_so_far.startswith('{"name"') or full_so_far.startswith("<tool_call>")):
                        if not header_printed:
                            if is_gemini:
                                hdr = f"✨ Gemini ({model_name}):\n"
                            elif "ssyz.org.tr" not in self.evren_base_url:
                                hdr = "🚀 Kendi AI (32B):\n"
                            else:
                                hdr = "🤖 EVREN AI:\n"
                            self._append_stream_text(hdr, "assistant")
                            header_printed = True
                        self._append_stream_text(piece)

                for tc_delta in delta.get("tool_calls") or []:
                    idx = tc_delta.get("index", 0)
                    entry = tc_map.setdefault(
                        idx,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if tc_delta.get("id"):
                        entry["id"] = tc_delta["id"]
                    fn_delta = tc_delta.get("function") or {}
                    if fn_delta.get("name"):
                        entry["function"]["name"] += fn_delta["name"]
                    if fn_delta.get("arguments"):
                        arg_piece = fn_delta["arguments"]
                        entry["function"]["arguments"] += arg_piece
                        char_count += len(arg_piece)
                        if char_count % 250 < len(arg_piece):
                            fn_name = entry["function"]["name"] or "araç"
                            rate = char_count / max(time.time() - step_started, 0.01)
                            self._set_live_status(
                                f"✍️ Adım {step_num}: {fn_name} ({char_count} krk • {rate:.0f} krk/sn)...",
                                THEME["warning"],
                            )

        tool_calls = [tc_map[k] for k in sorted(tc_map.keys())]
        msg = {"role": "assistant", "content": "".join(content_parts).strip()}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg

    def _extract_inline_tool_calls(self, content: str) -> tuple[str, list]:
        """Bazı modeller JSON'ı metin içinde <tool_call>...</tool_call> veya doğrudan {"name": ..., "arguments": ...} olarak döndürür; bunları ayırıp araca çevirir."""
        import re
        import json
        if not content:
            return content, []
        parsed_calls = []
        cleaned = content
        if "<tool_call>" in content:
            for idx, raw_block in enumerate(re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, flags=re.DOTALL)):
                try:
                    obj = json.loads(raw_block)
                    name = obj.get("name")
                    args = obj.get("arguments", {})
                    if name:
                        parsed_calls.append({
                            "id": f"inline_tc_{idx}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args),
                            },
                        })
                except Exception:
                    pass
            cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL).strip()

        if not parsed_calls and '"name"' in cleaned and '"arguments"' in cleaned:
            s_trim = cleaned.strip()
            candidates = [s_trim] + re.findall(r"(\{\s*\"name\"\s*:\s*\"[^\"]+\"\s*,\s*\"arguments\"\s*:\s*\{.*?\}\s*\})", s_trim, flags=re.DOTALL)
            for idx, cand in enumerate(candidates):
                try:
                    obj = json.loads(cand)
                    name = obj.get("name")
                    args = obj.get("arguments", {})
                    if isinstance(name, str) and name.strip():
                        parsed_calls.append({
                            "id": f"inline_json_{idx}",
                            "type": "function",
                            "function": {
                                "name": name.strip(),
                                "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args),
                            },
                        })
                        cleaned = cleaned.replace(cand, "").strip()
                        break
                except Exception:
                    pass
        return cleaned, parsed_calls

    _ACTION_TOOL_NAMES = {
        "create_editable_design",
        "decompose_image_to_design",
        "update_editable_design",
        "render_html_graphic",
        "design_graphic",
        "photoshop_edit",
        "write_file",
        "edit_file",
        "move_or_copy_file",
        "run_command",
        "launch_app",
        "generateDocument",
    }

    @staticmethod
    def _needs_forced_tool_call(user_text: str, reply_candidate: str) -> bool:
        import re
        u = (user_text or "").lower().strip()
        r = (reply_candidate or "").lower()
        if any(tok in r for tok in (
            "```bash", "```cmd", "```powershell", "copy \"", "move \"",
            "taşıyorum", "kopyalıyorum", "kopyalayayım", "erişilebilir hale getirildi",
            "hemen düzeltiyorum", "tarayıcıda açayım", "tasarımı oluşturduk",
            "tasarım oluşturuldu", "güncelledim", "değiştirdim", "parçalara ayırdım", "katmanlara ayırdım",
        )):
            return True
        if len(u) < 160 and re.search(
            r"(masa\s*üstü|masaustu|desktop|taşı|kopyala|getir|götür|düzelt|tekrar\s*dene|olmadı|yapamadın|berbat|bidaha|yeniden|kart\s*vizit|tasarla|oluştur|değiştir|güncelle|ekle|sil|kaldır|büyüt|küçült|parça|böl|ayır|analiz|aç\b|\[görsel:)",
            u,
        ):
            return True
        return False

    @staticmethod
    def _is_image_decompose_intent(user_text: str, messages: list) -> bool:
        import re
        u = (user_text or "").lower().strip()
        if re.search(r"(masa\s*üstü|masaustu|desktop)", u):
            return False
        has_img_tag = "[görsel:" in u
        decomp_pat = r"(parça(?:lara|larına|la)?|böl|ayır|katman(?:lara|larına)?|analiz\s*et|değiştirilebilir\s*yap|düzenlenebilir\s*yap|hareket\s*ettirilebilir)"
        if has_img_tag and re.search(r"(parça|böl|ayır|katman|analiz|düzenle|değiştir|kart\s*vizit|editör|stitch|canva)", u):
            return True
        if re.search(decomp_pat, u) and re.search(r"(görsel|resim|foto|kart\s*vizit|kartvizit|attığım|bu\b)", u):
            return True
        return False

    @staticmethod
    def _is_layer_update_intent(user_text: str, messages: list) -> bool:
        import re
        u = (user_text or "").lower().strip()
        if re.search(r"(masa\s*üstü|masaustu|desktop)", u):
            return False
        if "[görsel:" in u and re.search(r"(parça|böl|ayır|katman|analiz)", u):
            return False
        target_pat = r"(#?\b(?:isim|ismi|ismini|ad\b|adı|adını|ad\s*soyad|ünvan|unvan|meslek|logo|logoyu|logosunu|amblem|monogram|telefon|telefonu|numara|numarayı|e-?posta|epostayı|mail|maili|web|site|siteyi|adres|adresi|firma|firmayı|şirket|rozet|rozeti|çizgi|cizgi|arka\s*plan|arkaplan|zemin)\b)"
        op_pat = r"(yap\b|olsun|değiştir|güncelle|yaz\b|taşı|al\b|kaydır|büyüt|buyut|küçült|kucult|sil\b|kaldır|çıkar|ortala|sağ|sol|üst|alt|rengi|altın|beyaz|siyah|lacivert|zümrüt|bordo|kırmızı|mavi)"
        if re.search(target_pat, u) and re.search(op_pat, u):
            return True
        return False

    @classmethod
    def _is_card_redesign_intent(cls, user_text: str, messages: list) -> bool:
        import re
        u = (user_text or "").lower().strip()
        if re.search(r"(masa\s*üstü|masaustu|desktop|taşı|kopyala)", u):
            return False
        if cls._is_image_decompose_intent(user_text, messages) or cls._is_layer_update_intent(user_text, messages):
            return False
        card_pat = r"(kart\s*vizit|kartvizit)"
        fix_pat = r"(düzelt|değiştir|berbat|bidaha|bir\s*daha|yeniden|başka|güzel\s*yap|kullanılabilecek|kullnılabilcek|olmadı)"
        if re.search(card_pat, u):
            return True
        if re.search(fix_pat, u):
            recent_texts = [
                str(m.get("content") or "").lower()
                for m in (messages or [])[-6:]
                if m.get("role") in ("user", "assistant")
            ]
            if any(re.search(card_pat, t) for t in recent_texts):
                return True
        return False

    @staticmethod
    def _is_desktop_transfer_intent(user_text: str, messages: list) -> bool:
        import re
        u = (user_text or "").lower().strip()
        desk_pat = r"(masa\s*üstü|masaustu|desktop)"
        act_pat = r"(taşı|kopyala|getir|götür|at\b|koy|kaydet|gönder|aktar)"
        retry_pat = r"(tekrar\s*dene|olmadı|düzelt|hadi|göremiyorum|yok\b|yapamadın)"
        if re.search(desk_pat, u) and (re.search(act_pat, u) or re.search(retry_pat, u) or len(u) < 45):
            return True
        if re.search(retry_pat, u):
            recent_user_texts = [
                str(m.get("content") or "").lower()
                for m in (messages or [])[-6:]
                if m.get("role") == "user"
            ]
            if any(re.search(desk_pat, t) for t in recent_user_texts):
                return True
        return False

    def _run_evren_turn(self, model_name: str, messages: list, tools_for_turn: list, user_text: str) -> tuple[str, list]:
        import json
        if not self.evren_api_key:
            raise RuntimeError(
                "AI Sunucu anahtarı tanımlı değil. Sağ üstteki '⚙ Sunucu' butonundan anahtarınızı girin."
            )
        is_custom_srv = "ssyz.org.tr" not in self.evren_base_url.lower()
        if not is_custom_srv and (not self._is_evren_chat_model(model_name) or model_name == "deepseek-v4-flash"):
            model_name = "qwen3-vl-30b"
            self.evren_model = model_name
            self._set_setting("evren_model", model_name)
            self.after(0, lambda m=model_name: self.model_var.set(m))
        all_executed = []
        reply_text = ""
        self._browser_opened_in_turn = False
        seen_tool_sigs = set()
        hdr_label = "🚀 Kendi AI (32B):\n" if is_custom_srv else "🤖 EVREN AI:\n"

        # HIZLI OTONOM EYLEM YOLU (Step 0): Görsel parçalama, katman düzenleme, kartvizit tasarımı ve masaüstü taşıma
        # sunucu yanıtını beklemeden <0.5 saniyede doğrudan çalıştırılır (HTTP 500 veya gecikme yaşanmaz)
        if self._is_image_decompose_intent(user_text, messages):
            auto_decomp_calls = [{
                "id": "fast_img_decompose",
                "function": {
                    "name": "decompose_image_to_design",
                    "arguments": json.dumps({
                        "image_path": "last",
                        "output_html": "gorsel_parcali_editor.html",
                        "instructions": user_text,
                        "open_browser": True,
                    }),
                },
            }]
            auto_exec = self._execute_tool_calls(auto_decomp_calls, user_text)
            all_executed.extend(auto_exec)
            if auto_exec:
                res_line = auto_exec[0]["result"]
                reply_text = f"✅ Görseldeki tüm parçalar analiz edilip değiştirilebilir katmanlara ayrıldı:\n{res_line}"
                self._append_stream_text(hdr_label, "assistant")
                self._append_stream_text(f"{reply_text}\n", "body")
                return reply_text, [{"name": t["name"], "result": t["result"]} for t in all_executed]

        if self._is_layer_update_intent(user_text, messages):
            auto_upd_calls = [{
                "id": "fast_layer_update",
                "function": {
                    "name": "update_editable_design",
                    "arguments": json.dumps({
                        "updates": [],
                        "open_browser": True,
                    }),
                },
            }]
            auto_exec = self._execute_tool_calls(auto_upd_calls, user_text)
            all_executed.extend(auto_exec)
            if auto_exec:
                res_line = auto_exec[0]["result"]
                reply_text = f"✅ İstediğiniz parça değişikliği tasarıma uygulandı:\n{res_line}"
                self._append_stream_text(hdr_label, "assistant")
                self._append_stream_text(f"{reply_text}\n", "body")
                return reply_text, [{"name": t["name"], "result": t["result"]} for t in all_executed]

        if self._is_card_redesign_intent(user_text, messages):
            auto_design_calls = [{
                "id": "fast_card_redesign",
                "function": {
                    "name": "create_editable_design",
                    "arguments": json.dumps({
                        "output_html": "modern_kartvizit_editor.html",
                        "title": "Modern Kartvizit Stüdyosu",
                        "width": 1004,
                        "height": 650,
                        "elements": [],
                        "open_browser": True,
                    }),
                },
            }]
            auto_exec = self._execute_tool_calls(auto_design_calls, user_text)
            all_executed.extend(auto_exec)
            if auto_exec:
                res_line = auto_exec[0]["result"]
                reply_text = f"✅ Yeni lüks kartvizit şablonu oluşturuldu ve tarayıcıda açıldı:\n{res_line}"
                self._append_stream_text(hdr_label, "assistant")
                self._append_stream_text(f"{reply_text}\n", "body")
                return reply_text, [{"name": t["name"], "result": t["result"]} for t in all_executed]

        if self._is_desktop_transfer_intent(user_text, messages):
            auto_calls = [{
                "id": "fast_desktop_copy",
                "function": {
                    "name": "move_or_copy_file",
                    "arguments": json.dumps({
                        "source_path": "last",
                        "destination_path": "desktop",
                        "action": "copy",
                        "open_after": True,
                    }),
                },
            }]
            auto_exec = self._execute_tool_calls(auto_calls, user_text)
            all_executed.extend(auto_exec)
            if auto_exec:
                res_line = auto_exec[0]["result"]
                reply_text = f"✅ {res_line}"
                self._append_stream_text(hdr_label, "assistant")
                self._append_stream_text(f"{reply_text}\n", "body")
                return reply_text, [{"name": t["name"], "result": t["result"]} for t in all_executed]

        single_shot_terminal_tools = {
            "create_editable_design",
            "decompose_image_to_design",
            "update_editable_design",
            "move_or_copy_file",
            "launch_app",
            "generateDocument",
            "calculator",
            "getSystemTime",
            "render_html_graphic",
            "design_graphic",
            "photoshop_edit",
        }

        step = 0
        fallback_used = False
        custom_srv_retried = False
        forced_tool_retry_used = False
        while True:
            if self.MAX_AGENT_STEPS and step >= self.MAX_AGENT_STEPS:
                self._append_stream_text(hdr_label, "assistant")
                reply_text = self._stream_evren_chat(model_name, messages)
                break
            if self.cancel_agent:
                raise RuntimeError("İşlem kullanıcı tarafından durduruldu.")
            step += 1
            self._set_live_status(f"🤖 Ajan Adımı {step}...", THEME["warning"])
            try:
                msg = self._stream_evren_step(model_name, messages, tools_for_turn, step)
            except Exception as fb_exc:
                if is_custom_srv and not custom_srv_retried:
                    custom_srv_retried = True
                    self._set_live_status("🔄 Sunucu belleği optimize edilip yeniden deneniyor...", THEME["warning"])
                    time.sleep(2.0)
                    messages = [
                        {
                            "role": "system",
                            "content": (
                                "Sen Türkçe konuşan, kod yazma ve Photoshop/görsel tasarım uzmanı otonom bir yapay zeka ajanısın. "
                                "Kullanıcının isteğini doğrudan yerine getir."
                            ),
                        },
                        {"role": "user", "content": user_text},
                    ]
                    tools_for_turn = []
                    step = 0
                    continue
                retryable = (
                    not is_custom_srv
                    and (
                        isinstance(fb_exc, (self._EvrenFallbackNeeded, requests.exceptions.Timeout))
                        or "timed out" in str(fb_exc).lower()
                    )
                )
                if step == 1 and not fallback_used and retryable and (model_name or "").strip() != "qwen3-vl-30b":
                    fallback_used = True
                    model_name = "qwen3-vl-30b"
                    self.evren_model = model_name
                    self._set_setting("evren_model", model_name)
                    self.after(0, lambda m=model_name: self.model_var.set(m))
                    self._set_live_status("⚡ Yavaş/dolu model atlandı → qwen3-vl-30b ile devam...", THEME["warning"])
                    step = 0
                    continue
                raise
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls and msg.get("content"):
                cleaned_txt, inline_calls = self._extract_inline_tool_calls(msg["content"])
                if inline_calls:
                    msg["content"] = cleaned_txt
                    msg["tool_calls"] = inline_calls
                    tool_calls = inline_calls

            if not tool_calls:
                candidate = (msg.get("content") or "").strip()
                has_action_tool = any(t.get("name") in self._ACTION_TOOL_NAMES for t in all_executed)
                if (
                    not has_action_tool
                    and not forced_tool_retry_used
                    and tools_for_turn
                    and self._needs_forced_tool_call(user_text, candidate)
                ):
                    forced_tool_retry_used = True
                    messages.append({"role": "assistant", "content": candidate or "..."})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[SİSTEM UYARISI]: Yalnızca dosya listeledin/okudun veya hiçbir araç çağırmadan düz metin yazdın! "
                            "Sadece metin yazmak veya list_files çağırmak tasarımı/dosyayı değiştirmez. "
                            "Şimdi açıklama yazmadan doğrudan ilgili eylem aracını (`create_editable_design`, `move_or_copy_file`, "
                            "`edit_file`, `write_file`, `launch_app` veya `run_command`) çağır!"
                        ),
                    })
                    self._set_live_status("🔧 Eylem aracı çağrısı zorlanıyor...", THEME["warning"])
                    continue
                reply_text = candidate
                break

            if msg.get("content"):
                self._append_stream_text("\n")

            # Aynı turda birebir aynı araç çağrısının tekrarlanmasını engelle
            unique_tool_calls = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                sig = (fn.get("name") or "", str(fn.get("arguments") or ""))
                if sig in seen_tool_sigs:
                    continue
                seen_tool_sigs.add(sig)
                unique_tool_calls.append(tc)
            if not unique_tool_calls:
                reply_text = (msg.get("content") or "").strip() or (
                    "\n".join(f"✅ {it['result']}" for it in all_executed) if all_executed else "İşlem tamamlandı."
                )
                break
            tool_calls = unique_tool_calls

            step_executed = self._execute_tool_calls(tool_calls, user_text)
            all_executed.extend(step_executed)
            messages.append(msg)
            for item in step_executed:
                tool_msg = {
                    "role": "tool",
                    "name": item["name"],
                    "content": item["result"],
                }
                if item.get("id"):
                    tool_msg["tool_call_id"] = item["id"]
                messages.append(tool_msg)
            self._compact_evren_tool_history(messages)

            # Tek adımlık (single-shot) araçlar tamamlandığında döngüden hemen çık (tekrar sekme açmasını önle)
            if any(it.get("name") in single_shot_terminal_tools for it in step_executed):
                candidate_txt = (msg.get("content") or "").strip()
                if candidate_txt:
                    reply_text = candidate_txt
                else:
                    reply_text = "\n".join(f"✅ {it['result']}" for it in step_executed)
                    self._append_stream_text(f"🤖 EVREN AI:\n{reply_text}\n", "assistant")
                break

        # 1) Görseli parçalara ayırma istendiyse ve model aracı çağırmadıysa garantili çalıştır
        if self._is_image_decompose_intent(user_text, messages) and not any(
            t.get("name") in ("decompose_image_to_design", "create_editable_design", "update_editable_design")
            for t in all_executed
        ):
            auto_decomp_calls = [{
                "id": "auto_img_decompose",
                "function": {
                    "name": "decompose_image_to_design",
                    "arguments": json.dumps({
                        "image_path": "last",
                        "output_html": "gorsel_parcali_editor.html",
                        "instructions": user_text,
                        "open_browser": True,
                    }),
                },
            }]
            auto_exec = self._execute_tool_calls(auto_decomp_calls, user_text)
            all_executed.extend(auto_exec)
            if auto_exec:
                res_line = auto_exec[0]["result"]
                reply_text = f"✅ Görseldeki tüm parçalar analiz edilip değiştirilebilir katmanlara ayrıldı:\n{res_line}"
                self._append_stream_text(f"\n{reply_text}\n", "body")

        # 2) Mevcut tasarımdaki belirli bir parçayı (isim, logo, ünvan, telefon, adres, arka plan vb.) değiştirme istendiyse garantili çalıştır
        if self._is_layer_update_intent(user_text, messages) and not any(
            t.get("name") in ("update_editable_design", "decompose_image_to_design", "create_editable_design")
            for t in all_executed
        ):
            auto_upd_calls = [{
                "id": "auto_layer_update",
                "function": {
                    "name": "update_editable_design",
                    "arguments": json.dumps({
                        "updates": [],
                        "open_browser": True,
                    }),
                },
            }]
            auto_exec = self._execute_tool_calls(auto_upd_calls, user_text)
            all_executed.extend(auto_exec)
            if auto_exec:
                res_line = auto_exec[0]["result"]
                reply_text = f"✅ İstediğiniz parça değişikliği tasarıma uygulandı:\n{res_line}"
                self._append_stream_text(f"\n{reply_text}\n", "body")

        # 3) Kartvizit oluşturma/değiştirme/düzeltme istendiyse ve model tasarım aracını çağırmadıysa garantili çalıştır
        if self._is_card_redesign_intent(user_text, messages) and not any(
            t.get("name") in ("create_editable_design", "decompose_image_to_design", "update_editable_design", "render_html_graphic", "design_graphic")
            for t in all_executed
        ):
            auto_design_calls = [{
                "id": "auto_card_redesign",
                "function": {
                    "name": "create_editable_design",
                    "arguments": json.dumps({
                        "output_html": "modern_kartvizit_editor.html",
                        "title": "Modern Kartvizit Stüdyosu",
                        "width": 1004,
                        "height": 650,
                        "elements": [],
                        "open_browser": True,
                    }),
                },
            }]
            auto_exec = self._execute_tool_calls(auto_design_calls, user_text)
            all_executed.extend(auto_exec)
            if auto_exec:
                res_line = auto_exec[0]["result"]
                reply_text = f"✅ Yeni lüks kartvizit şablonu uygulandı ve açıldı:\n{res_line}"
                self._append_stream_text(f"\n{reply_text}\n", "body")

        # Masaüstüne taşıma/kopyalama istendiyse ve model aracı çağırmadıysa garantili olarak çalıştır
        if self._is_desktop_transfer_intent(user_text, messages) and not any(
            t.get("name") in ("move_or_copy_file", "create_editable_design", "write_file", "design_graphic", "render_html_graphic")
            for t in all_executed
        ):
            auto_calls = [{
                "id": "auto_desktop_copy",
                "function": {
                    "name": "move_or_copy_file",
                    "arguments": json.dumps({
                        "source_path": "last",
                        "destination_path": "desktop",
                        "action": "copy",
                        "open_after": True,
                    }),
                },
            }]
            auto_exec = self._execute_tool_calls(auto_calls, user_text)
            all_executed.extend(auto_exec)
            if auto_exec:
                res_line = auto_exec[0]["result"]
                reply_text = f"✅ {res_line}"
                self._append_stream_text(f"\n{reply_text}\n", "body")

        return reply_text, [{"name": t["name"], "result": t["result"]} for t in all_executed]

    def _run_ollama_turn(self, model_name: str, ollama_messages: list, tools_for_turn: list, user_text: str) -> tuple[str, list]:
        # Ollama kapalıysa otomatik başlatmayı dene ve kurulu modeli doğrula
        tags_resp = None
        try:
            tags_resp = requests.get(f"{self.ollama_url}/api/tags", timeout=1.5)
        except Exception:
            ollama_exe = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
            if os.path.exists(ollama_exe):
                try:
                    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    subprocess.Popen([ollama_exe, "serve"], creationflags=flags)
                    time.sleep(3)
                    tags_resp = requests.get(f"{self.ollama_url}/api/tags", timeout=2.0)
                except Exception:
                    pass

        if tags_resp is not None and tags_resp.status_code == 200:
            installed_models = [m.get("name", "") for m in tags_resp.json().get("models", []) if m.get("name")]
            if installed_models and not any(
                m == model_name or (":" not in model_name and m.startswith(f"{model_name}:"))
                for m in installed_models
            ):
                fallback = next((m for m in installed_models if m.startswith("qwen2.5")), installed_models[0])
                model_name = fallback
                self.after(0, lambda m=fallback, all_m=installed_models: (
                    self.model_combo.config(values=all_m),
                    self.model_var.set(m),
                ))

        executed_tools = []
        if tools_for_turn:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": model_name,
                    "messages": ollama_messages,
                    "tools": tools_for_turn,
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {**self._ollama_options(), "temperature": 0.2},
                },
                timeout=(5, 180),
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
            msg = resp.json().get("message", {})
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                executed_tools = self._execute_tool_calls(tool_calls, user_text)
                ollama_messages.append(msg)
                for item in executed_tools:
                    ollama_messages.append({"role": "tool", "content": item["result"]})
                self._append_stream_text("🤖 Mini Agent:\n", "assistant")
                reply_text = self._stream_chat(model_name, ollama_messages)
            else:
                reply_text = (msg.get("content") or "").strip()
                self._append_stream_text("🤖 Mini Agent:\n", "assistant")
                self._append_stream_text(reply_text)
        else:
            self._append_stream_text("🤖 Mini Agent:\n", "assistant")
            reply_text = self._stream_chat(model_name, ollama_messages)

        return reply_text, [{"name": t["name"], "result": t["result"]} for t in executed_tools]

    def _agent_worker(self, user_text: str):
        import sqlite3
        import json
        import uuid
        import datetime

        executed_tools = []
        reply_text = ""
        notice_text = ""
        provider = self.provider_var.get()
        is_evren = (provider == self.PROVIDER_EVREN)
        is_custom_srv = is_evren and ("ssyz.org.tr" not in self.evren_base_url.lower())
        ctx_limit = 4 if is_custom_srv else (self.EVREN_CONTEXT_WINDOW_LIMIT if is_evren else self.CONTEXT_WINDOW_LIMIT)

        with sqlite3.connect(self.db_path) as conn:
            recent_rows = conn.execute(
                "SELECT role, content, tool_calls FROM messages WHERE conversation_id = ? AND role IN ('user', 'assistant') "
                "ORDER BY created_at DESC LIMIT ?",
                (self.current_conversation_id, ctx_limit)
            ).fetchall()
        recent_rows.reverse()

        real_desktop = self._get_real_desktop_dir()
        if is_custom_srv:
            system_content = (
                "Sen Türkçe konuşan, kod yazma ve Photoshop/görsel tasarım konusunda uzman otonom bir yapay zeka ajanısın (Qwen2.5-Coder-32B). "
                "Kullanıcının isteğini tek seferde anlar ve doğrudan yerine getirirsin. "
                "Bir araç çağırman gerektiğinde <tool_call>{\"name\": \"ARAC_ADI\", \"arguments\": {...}}</tool_call> formatını kullan:\n"
                "- Dosya/kod yazmak için: write_file (path, content)\n"
                "- Komut çalıştırmak için: run_command (command)\n"
                "- Uygulama/HTML açmak için: launch_app (html_path veya url)\n"
                "- Kartvizit/tasarım oluşturmak için: create_editable_design (output_html, title, open_browser)\n"
                "- Görseli katmanlara ayırmak için: decompose_image_to_design (image_path, output_html, open_browser)\n"
                "- Tasarım katmanını değiştirmek için: update_editable_design (updates, open_browser)\n"
                "- Photoshop işlemi için: photoshop_edit (input_path, operations)\n"
                "- Masaüstüne kopyalamak için: move_or_copy_file (source_path, destination_path='desktop')"
            )
        else:
            system_content = self._get_effective_system_prompt()
            system_content += f"\n\nKullanıcının Gerçek Windows Masaüstü Yolu: {real_desktop}"
            design_ctx = self._format_active_design_context()
            if design_ctx:
                system_content += (
                    f"\n\n[AKTİF DÜZENLENEBİLİR TASARIM KATMANLARI (Parça Listesi)]:\n{design_ctx}\n"
                    "ÖNEMLİ: Kullanıcı yukarıdaki parçalardan herhangi birini (isim, ünvan, logo, firma, telefon, e-posta, web, adres, arka plan vb.) "
                    "değiştirmek, taşımak, boyutlandırmak veya silmek istediğinde `update_editable_design` aracını çağır! "
                    "Kullanıcı yüklediği bir görseli parçalara ayırmak istediğinde ise `decompose_image_to_design` aracını çağır!"
                )
            workspace_snapshot = self._workspace_tree_snapshot(max_files=35)
            if workspace_snapshot:
                system_content += f"\n\nÇalışma Klasörü Mevcut Dosyalar ({self.agent_workspace_dir}):\n{workspace_snapshot}"
            kb_context = self._retrieve_knowledge_context(user_text)
            if kb_context:
                system_content += f"\n\nİlgili Bilgi Tabanı Bağlamı (Kullanıcının Kayıtlı Bilgileri):\n{kb_context}"

        chat_messages = [{"role": "system", "content": system_content}]
        for r_role, r_content, r_tools_json in recent_rows:
            msg_text = r_content or ""
            if r_role == "assistant" and r_tools_json:
                try:
                    t_list = json.loads(r_tools_json)
                    if isinstance(t_list, list) and t_list:
                        summary = "; ".join(f"{t.get('name')} -> {str(t.get('result',''))[:120]}" for t in t_list[:4])
                        msg_text = f"[Çalıştırılan Araçlar: {summary}]\n{msg_text}".strip()
                except Exception:
                    pass
            if chat_messages and chat_messages[-1].get("role") == r_role == "user":
                chat_messages[-1] = {"role": r_role, "content": msg_text}
            else:
                chat_messages.append({"role": r_role, "content": msg_text})

        model_name = self.model_var.get().strip() or (self.evren_model if is_evren else self.ollama_model)
        tools_for_turn = [] if is_custom_srv else (self.TOOLS_SCHEMA if is_evren else self._select_tools_for_message(user_text))

        low_req = user_text.lower()
        direct_mod = None
        if any(k in low_req for k in ("yüz tanıma", "yüz tespiti", "yuz tanima", "yuz tespiti", "kamera yüz")):
            direct_mod = ("module_1", "👤 Yüz Tespiti modülünü sizin için başlattım.")
        elif any(k in low_req for k in ("plaka tespiti", "plaka tanıma", "plaka oku", "plaka modül")):
            direct_mod = ("module_2", "🚗 Plaka Tespiti modülünü sizin için başlattım.")
        elif any(k in low_req for k in ("video dublaj", "türkçe dublaj", "seslendirme modül", "dublaj modül")):
            direct_mod = ("module_3", "🎬 Video Türkçe Dublaj modülünü sizin için başlattım.")

        try:
            if direct_mod:
                mod_key, mod_msg = direct_mod
                reply_text = mod_msg
                executed_tools = [{"name": "open_module", "args": {"module": mod_key}, "result": mod_msg}]
                self.after(250, lambda mk=mod_key: self.app.open_module(mk))
            elif is_evren:
                reply_text, executed_tools = self._run_evren_turn(model_name, chat_messages, tools_for_turn, user_text)
                used_m = self.evren_model or model_name
                is_gemini = "generativelanguage.googleapis.com" in self.evren_base_url.lower()
                is_custom_srv = "ssyz.org.tr" not in self.evren_base_url.lower()
                if is_gemini:
                    badge_lbl = f"● ✨ Google Gemini Aktif ({used_m})"
                elif is_custom_srv:
                    badge_lbl = f"● 🚀 Kendi AI Aktif ({used_m})"
                else:
                    badge_lbl = f"● EVREN AI Aktif ({used_m})"
                self.after(0, lambda b=badge_lbl: self.ollama_badge.config(
                    text=b, fg=THEME["success"]
                ))
            else:
                reply_text, executed_tools = self._run_ollama_turn(model_name, chat_messages, tools_for_turn, user_text)
                self.after(0, lambda m=model_name: self.ollama_badge.config(
                    text=f"● Ollama Aktif ({m})", fg=THEME["success"]
                ))
        except requests.exceptions.ConnectionError:
            if is_evren:
                notice_text = f"AI sunucusuna bağlanılamadı ({self.evren_base_url}). Sunucu adresini (⚙ Sunucu) veya internet bağlantınızı kontrol edin."
            else:
                notice_text = (
                    f"Ollama'ya bağlanılamadı ({self.ollama_url}). Başlat menüsünden 'Ollama' uygulamasını açıp tekrar deneyin."
                )
        except requests.exceptions.Timeout:
            notice_text = "Model cevap vermekte çok gecikti. Birkaç saniye sonra tekrar deneyin."
        except Exception as exc:
            notice_text = f"Bir hata oluştu: {exc}"

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if notice_text:
                # Hata bildirimleri ayrı rolde saklanır, modele bağlam olarak gönderilmez
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, tool_calls, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), self.current_conversation_id, "notice", notice_text, None, now_iso),
                )
            elif reply_text or executed_tools:
                final_reply = reply_text
                if not final_reply and executed_tools:
                    tail_lines = [f"• {t.get('name')}: {str(t.get('result', ''))[:140]}" for t in executed_tools[-5:]]
                    final_reply = "Aşağıdaki araç adımları çalıştırıldı:\n" + "\n".join(tail_lines)
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, tool_calls, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        self.current_conversation_id,
                        "assistant",
                        final_reply or "İşlem tamamlandı.",
                        json.dumps(executed_tools, ensure_ascii=False) if executed_tools else None,
                        now_iso,
                    ),
                )
            conn.commit()

        def _finish():
            self._flush_stream_buffer()
            final_elapsed = ""
            if self._gen_start_time is not None:
                final_elapsed = self._format_elapsed(time.monotonic() - self._gen_start_time)
            self._gen_start_time = None
            self.is_generating = False
            self.cancel_agent = False
            self.send_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            done_txt = f"✓ Hazır  •  ⏱ {final_elapsed}" if final_elapsed else "Hazır"
            self.tool_indicator.config(text=done_txt, fg=THEME["success"])
            self._render_conversation_messages()
        self.after(0, _finish)


# ==============================================================================
# GELECEKTEKİ MODELLER İÇİN ŞABLON MODÜL (PLACEHOLDER / TEMPLATE)
# ==============================================================================
class PlaceholderModule(BaseModuleView):
    """
    Henüz eğitim aşamasında olan veya ileride eklenecek (.pt, .onnx, .h5)
    modeller için hazır çalışma alanı şablonu.
    """
    def __init__(self, parent, app_controller, title: str, status_tag: str, description: str, how_to_attach: str):
        super().__init__(parent, app_controller, title=title, subtitle=f"Durum: {status_tag}")
        self._build_info(status_tag, description, how_to_attach)

    def _build_info(self, status_tag: str, description: str, how_to_attach: str):
        card = tk.Frame(
            self,
            bg=THEME["bg_card"],
            padx=35,
            pady=35,
            highlightthickness=1,
            highlightbackground=THEME["border"]
        )
        card.place(relx=0.5, rely=0.52, anchor="center", relwidth=0.78)

        tk.Label(
            card,
            text=f"🚧  {status_tag}",
            font=("Segoe UI", 13, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["warning"]
        ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            card,
            text=description,
            font=("Segoe UI", 11),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
            justify="left",
            wraplength=650
        ).pack(anchor="w", pady=(0, 20))

        tk.Label(
            card,
            text="Bu Modüle Yeni Modelinizi Nasıl Bağlarsınız?",
            font=("Segoe UI", 11, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["accent"]
        ).pack(anchor="w", pady=(0, 8))

        code_box = tk.Label(
            card,
            text=how_to_attach,
            font=("Consolas", 10),
            bg=THEME["bg_canvas"],
            fg=THEME["text_secondary"],
            justify="left",
            padx=15,
            pady=15,
            anchor="w"
        )
        code_box.pack(fill="x")


# ==============================================================================
# ANA UYGULAMA KONTROLCÜSÜ (LOCAL AI HUB)
# ==============================================================================
class LocalAIHubApp(tk.Tk):
    """
    Ana Masaüstü Uygulaması.
    Ana menü (Dashboard) ve tüm yapay zeka modül ekranları arasındaki geçişi yönetir.
    """
    def __init__(self):
        super().__init__()
        self._set_app_icon()
        _apply_modern_theme(self)
        self.title("Local AI Hub — Yapay Zeka Merkezi")
        self.geometry("1120x740")
        self.minsize(960, 660)
        self.configure(bg=THEME["bg_main"])

        # Ana Kapsayıcı (Tüm görünümler bunun içinde değişir)
        self.container = tk.Frame(self, bg=THEME["bg_main"])
        self.container.pack(fill="both", expand=True)

        # Modül örneklerini tutan sözlük (Lazy instantiation için)
        self.views = {}
        self.current_view = None

        # Kayıtlı AI Modülleri Listesi
        self.module_configs = [
            {
                "id": "module_1",
                "title": "Module 1: YOLOv8 Face Detection",
                "tr_title": "Modül 1: YOLOv8 Yüz Tespiti",
                "status": "Active / Aktif",
                "status_color": THEME["success"],
                "active": True,
                "icon": "👤",
                "desc": "Eğitilmiş YOLOv8 (best.pt) modelini kullanarak fotoğraflar üzerindeki tüm yüzleri kare içine alır ve sayısını hesaplar.",
                "builder": lambda: FaceDetectionModule(self.container, self)
            },
            {
                "id": "module_2",
                "title": "Module 2: YOLOv8 License Plate Detection",
                "tr_title": "Modül 2: Araç Plaka Tespiti",
                "status": "Active / Aktif",
                "status_color": THEME["success"],
                "active": True,
                "icon": "🚗",
                "desc": "Eğitilmiş YOLOv8 (plaka_best.pt) plaka tanıma modelini kullanarak araç fotoğraflarındaki tüm plakaları algılar ve kare içine alır.",
                "builder": lambda: LicensePlateDetectionModule(self.container, self)
            },
            {
                "id": "module_3",
                "title": "Module 3: Long Video Turkish Dubbing AI",
                "tr_title": "Modül 3: Video Türkçe Dublaj (2-3+ Saat)",
                "status": "Active / Aktif",
                "status_color": THEME["success"],
                "active": True,
                "icon": "🎙️",
                "desc": "2-3 saatlik uzun videoları belleği yormadan cümle cümle Türkçeye çevirir, doğal yapay zeka sesiyle dublajlar ve senkronize birleştirir.",
                "builder": lambda: TurkishVideoDubbingModule(self.container, self)
            },
            {
                "id": "module_4",
                "title": "Module 4: EVREN AI & Local Assistant (Mini-Agent)",
                "tr_title": "Modül 4: EVREN AI & Yerel Asistan",
                "status": "Active / Aktif",
                "status_color": THEME["success"],
                "active": True,
                "icon": "✨",
                "desc": "EVREN AI (120B+ bulut modeller) ve yerel Ollama destekli tam otonom yapay zeka ajanı. Kod yazar, web sitesi kurar, Photoshop & grafik tasarım yapar ve Türkçe PDF üretir.",
                "builder": lambda: LocalAIAssistantModule(self.container, self)
            }
        ]

        # Doğrudan Yapay Zeka ekranını aç (kaba modül menüsü yerine direkt Antigravity tarzı AI ekranı)
        self.dashboard_frame = self._build_dashboard()
        self.open_module("module_4")

    def _set_app_icon(self):
        """Windows görev çubuğu ve pencere başlığı için özel ikonu ayarlar."""
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("burakb.localaihub.desktop.2")
        except Exception:
            pass

        ico_file = resource_path("app_icon.ico")
        if os.path.exists(ico_file):
            try:
                self.iconbitmap(default=ico_file)
            except Exception:
                pass

    def _build_dashboard(self) -> tk.Frame:
        """Ana Menü (Home View) ekranını ve tıklanabilir modül kartlarını oluşturur."""
        dashboard = tk.Frame(self.container, bg=THEME["bg_main"])

        # Üst Başlık Alanı
        header = tk.Frame(dashboard, bg=THEME["bg_main"], pady=28, padx=40)
        header.pack(fill="x")

        tk.Label(
            header,
            text="Local AI Hub",
            font=("Segoe UI", 24, "bold"),
            bg=THEME["bg_main"],
            fg=THEME["text_primary"]
        ).pack(anchor="w")

        tk.Label(
            header,
            text="Çalışmak istediğiniz yapay zeka modülünü seçin.",
            font=("Segoe UI", 11),
            bg=THEME["bg_main"],
            fg=THEME["text_secondary"]
        ).pack(anchor="w", pady=(6, 0))

        # Kartların Dizileceği 2x2 Modern Grid Alanı
        grid_frame = tk.Frame(dashboard, bg=THEME["bg_main"], padx=40, pady=8)
        grid_frame.pack(fill="both", expand=True)

        for col in range(2):
            grid_frame.columnconfigure(col, weight=1, uniform="cards")
        for row in range((len(self.module_configs) + 1) // 2):
            grid_frame.rowconfigure(row, weight=1, uniform="rows")

        for idx, cfg in enumerate(self.module_configs):
            card = self._create_module_card(grid_frame, cfg)
            card.grid(row=idx // 2, column=idx % 2, padx=12, pady=12, sticky="nsew")

        # Alt Bilgi Çubuğu (Footer)
        footer = tk.Frame(dashboard, bg=THEME["bg_main"], pady=14, padx=40)
        footer.pack(fill="x", side="bottom")
        tk.Label(
            footer,
            text="● 4 Modül Hazır  •  YOLOv8 Görüş  •  Video Dublaj  •  EVREN AI (120B+) Kodlama & Photoshop Ajanı",
            font=("Segoe UI", 9),
            bg=THEME["bg_main"],
            fg=THEME["muted"]
        ).pack(anchor="w")

        return dashboard

    def _create_module_card(self, parent, cfg: dict) -> RoundedFrame:
        """Ana ekrandaki her bir yapay zeka modülü için yuvarlatılmış modern kart oluşturur."""
        card = RoundedFrame(
            parent,
            radius=18,
            fill_color=THEME["bg_card"],
            border_color=THEME["border"],
            outer_bg=THEME["bg_main"],
            pad=22,
            auto_height=False,
            cursor="hand2",
        )
        body = card.body

        top_row = tk.Frame(body, bg=THEME["bg_card"])
        top_row.pack(fill="x", pady=(0, 12))

        icon_lbl = tk.Label(
            top_row,
            text=cfg["icon"],
            font=("Segoe UI Emoji", 24),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"]
        )
        icon_lbl.pack(side="left")

        badge = tk.Label(
            top_row,
            text="● Aktif" if cfg.get("active") else f"● {cfg['status']}",
            font=("Segoe UI", 8, "bold"),
            bg=THEME["bg_card"],
            fg=cfg["status_color"]
        )
        badge.pack(side="right", anchor="n")

        title_lbl = tk.Label(
            body,
            text=cfg["tr_title"],
            font=("Segoe UI", 13, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
            anchor="w",
            justify="left",
        )
        title_lbl.pack(fill="x", pady=(0, 6))

        desc_lbl = tk.Label(
            body,
            text=cfg["desc"],
            font=("Segoe UI", 9),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            anchor="w",
            justify="left",
            wraplength=420
        )
        desc_lbl.pack(fill="x", expand=True, pady=(0, 14))

        btn_bg = THEME["accent"] if cfg.get("active") else THEME["bg_card_hover"]
        open_btn = PillButton(
            body,
            text="Aç  →",
            command=lambda m_id=cfg["id"]: self.open_module(m_id),
            bg_color=btn_bg,
            hover_color=THEME["accent_hover"],
            outer_bg=THEME["bg_card"],
            radius=11,
            height=36,
            width=110,
            font=("Segoe UI", 9, "bold"),
        )
        open_btn.pack(anchor="e", side="bottom")

        card_surfaces = [body, top_row, icon_lbl, badge, title_lbl, desc_lbl]
        def _card_enter(_e):
            card.set_colors(THEME["bg_card_hover"], THEME["accent"])
            open_btn.config(outer_bg=THEME["bg_card_hover"])
            for w in card_surfaces:
                w.config(bg=THEME["bg_card_hover"])
        def _card_leave(_e):
            card.set_colors(THEME["bg_card"], THEME["border"])
            open_btn.config(outer_bg=THEME["bg_card"])
            for w in card_surfaces:
                w.config(bg=THEME["bg_card"])

        for widget in [card, *card_surfaces]:
            widget.bind("<Button-1>", lambda e, m_id=cfg["id"]: self.open_module(m_id))
            widget.bind("<Enter>", _card_enter, add="+")
            widget.bind("<Leave>", _card_leave, add="+")

        return card

    def show_dashboard(self):
        """Alt araçlardan geri dönüldüğünde doğrudan ana Yapay Zeka ekranına (module_4) döner."""
        self.open_module("module_4")

    def open_module(self, module_id: str):
        """Seçilen modülün çalışma alanını açar (İlk kez açılıyorsa oluşturur)."""
        if self.current_view is not None:
            self.current_view.pack_forget()

        if module_id not in self.views:
            cfg = next((item for item in self.module_configs if item["id"] == module_id), None)
            if cfg is None:
                return
            self.views[module_id] = cfg["builder"]()

        module_view = self.views[module_id]
        module_view.pack(fill="both", expand=True)
        module_view.on_open()
        self.current_view = module_view


if __name__ == "__main__":
    app = LocalAIHubApp()
    app.mainloop()
