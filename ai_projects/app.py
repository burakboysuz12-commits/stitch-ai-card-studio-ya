"""
Görev Defteri — Flask ile şık bir yapılacaklar listesi web uygulaması.

Özellikler:
- Görev ekleme, tamamlanmış işaretleme, silme
- Görev başlığı + çok satırlı açıklama/not alanı
- Görevlere görsel ekleme (yükleme + önizleme + tam ekran inceleme)
- Filtreleme (Tümü / Aktif / Tamamlanan)
- JSON dosyasında kalıcı depolama
- REST API uçları
"""

import os
import uuid
import json
from datetime import datetime, timezone

from flask import (Flask, jsonify, render_template, request,
                   send_from_directory, after_this_request)
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "tasks.json")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

MAX_TITLE = 200
MAX_DESC = 1000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "avif"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.json.ensure_ascii = False                 # Türkçe karakterler JSON'da okunsun
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0   # statik dosya önbelleği KAPALI


# ---------------------------------------------------------------------------
# Önbellek önlemleri — tarayıcı asla eski CSS/JS/HTML'i göstermesin
# ---------------------------------------------------------------------------
@app.after_request
def no_cache(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ---------------------------------------------------------------------------
# Depolama katmanı (basit JSON dosyası)
# ---------------------------------------------------------------------------
def load_tasks() -> list[dict]:
    """tasks.json dosyasından görev listesini okur."""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        tasks = data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []

    # Eski kayıtlarda yeni alanlar olmayabilir → şemayı tamamla
    for t in tasks:
        t.setdefault("description", "")
        t.setdefault("image", "")
    return tasks


def save_tasks(tasks: list[dict]) -> None:
    """Görev listesini tasks.json dosyasına yazar."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def delete_image_file(image_url: str) -> None:
    """Göreve bağlı görsel dosyasını diskten siler."""
    if not image_url:
        return
    name = os.path.basename(image_url.split("?")[0])
    if name:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, name))
        except OSError:
            pass  # dosya zaten yoksa sorun çıkarma


def allowed_file(filename: str) -> bool:
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Sayfa
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# REST API — Görevler
# ---------------------------------------------------------------------------
@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    """Tüm görevleri döndürür; ?status=active|completed ile filtrelenir."""
    tasks = load_tasks()
    status = request.args.get("status")
    if status == "active":
        tasks = [t for t in tasks if not t["done"]]
    elif status == "completed":
        tasks = [t for t in tasks if t["done"]]
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    """Yeni görev oluşturur (başlık zorunlu; açıklama ve görsel opsiyonel)."""
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    image = (payload.get("image") or "").strip()

    if not title:
        return jsonify({"error": "Görev başlığı boş olamaz."}), 400
    if len(title) > MAX_TITLE:
        return jsonify({"error": f"Görev başlığı en fazla {MAX_TITLE} karakter olabilir."}), 400
    if len(description) > MAX_DESC:
        return jsonify({"error": f"Açıklama en fazla {MAX_DESC} karakter olabilir."}), 400

    task = {
        "id": uuid.uuid4().hex,
        "title": title,
        "description": description,
        "image": image,
        "done": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    return jsonify(task), 201


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id):
    """Görevin başlığını/açıklamasını/görselini günceller veya durumunu değiştirir."""
    tasks = load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        return jsonify({"error": "Görev bulunamadı."}), 404

    payload = request.get_json(silent=True) or {}

    if "done" in payload:
        task["done"] = bool(payload["done"])

    if "title" in payload:
        new_title = str(payload["title"]).strip()
        if not new_title:
            return jsonify({"error": "Görev başlığı boş olamaz."}), 400
        if len(new_title) > MAX_TITLE:
            return jsonify({"error": f"Görev başlığı en fazla {MAX_TITLE} karakter olabilir."}), 400
        task["title"] = new_title

    if "description" in payload:
        new_desc = str(payload["description"] or "").strip()
        if len(new_desc) > MAX_DESC:
            return jsonify({"error": f"Açıklama en fazla {MAX_DESC} karakter olabilir."}), 400
        task["description"] = new_desc

    if "image" in payload:
        new_image = str(payload["image"] or "").strip()
        old_image = task.get("image", "")
        if old_image and old_image != new_image:
            delete_image_file(old_image)   # eski görsel diskte kalmasın
        task["image"] = new_image

    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_tasks(tasks)
    return jsonify(task)


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    """Bir görevi (ve varsa görselini) siler."""
    tasks = load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        return jsonify({"error": "Görev bulunamadı."}), 404

    delete_image_file(task.get("image", ""))
    save_tasks([t for t in tasks if t["id"] != task_id])
    return "", 204


@app.route("/api/completed", methods=["DELETE"])
def clear_completed():
    """Tamamlanmış tüm görevleri (görselleriyle birlikte) temizler."""
    tasks = load_tasks()
    for t in tasks:
        if t.get("done"):
            delete_image_file(t.get("image", ""))
    remaining = [t for t in tasks if not t["done"]]
    removed = len(tasks) - len(remaining)
    save_tasks(remaining)
    return jsonify({"removed": removed})


# ---------------------------------------------------------------------------
# REST API — Görsel yükleme
# ---------------------------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
def upload_image():
    """Göreve eklenecek görseli yükler ve erişim URL'sini döndürür."""
    if "file" not in request.files:
        return jsonify({"error": "Dosya bulunamadı."}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "Dosya seçilmedi."}), 400

    if not allowed_file(file.filename):
        return jsonify({
            "error": "Desteklenmeyen dosya türü. PNG, JPG, GIF, WEBP, BMP veya AVIF kullanın."
        }), 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    # Türkçe/boşluklu dosya adlarını da güvenle desteklemek için uuid adlandırma
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, safe_name))

    return jsonify({
        "url": f"/static/uploads/{safe_name}",
        "original_name": secure_filename(file.filename) or safe_name,
    }), 201


@app.route("/static/uploads/<path:filename>")
def serve_upload(filename):
    """Yüklenen görselleri sunar."""
    @after_this_request
    def _cache(resp):
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.errorhandler(413)
def too_large(_err):
    return jsonify({"error": "Dosya çok büyük. En fazla 8 MB yükleyebilirsiniz."}), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
