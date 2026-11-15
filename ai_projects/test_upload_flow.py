"""Gorsel yukleme + aciklama akisini uctan uca test eder."""
import io
import json

import app

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

client = app.app.test_client()

print("GET /            ->", client.get("/").status_code)
css = client.get("/static/style.css")
js = client.get("/static/app.js")
print("GET style.css    ->", css.status_code, len(css.data), "bayt")
print("GET app.js       ->", js.status_code, len(js.data), "bayt")
print("no-cache basligi ->", css.headers.get("Cache-Control"))

up = client.post(
    "/api/upload",
    data={"file": (io.BytesIO(PNG), "deneme.png")},
    content_type="multipart/form-data",
)
print("POST /api/upload ->", up.status_code, up.get_json())
url = (up.get_json() or {}).get("url", "")
print("GET yuklenen     ->", client.get(url).status_code if url else "URL YOK")

new = client.post(
    "/api/tasks",
    json={"title": "Gorsel testi", "description": "Aciklama satiri", "image": url},
)
print("POST /api/tasks  ->", new.status_code)
task = new.get_json()
print("  donen image    ->", repr(task.get("image")))
print("  donen desc     ->", repr(task.get("description")))

tid = task["id"]
print("PATCH image      ->", client.patch(f"/api/tasks/{tid}", json={"image": ""}).status_code)
print("DELETE           ->", client.delete(f"/api/tasks/{tid}").status_code)

listing = client.get("/api/tasks")
print("GET /api/tasks   ->", listing.status_code, len(json.loads(listing.data)), "kayit")
