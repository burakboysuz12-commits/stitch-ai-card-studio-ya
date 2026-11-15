"""Görev Defteri API testleri — Flask test client ile."""

import json
import os
import sys

# Test sırasında gerçek tasks.json'u bozmamak için ayrı dosya kullan
import app as app_module

app_module.DATA_FILE = os.path.join(os.path.dirname(__file__), "tasks_test.json")

# Test öncesi temizle
if os.path.exists(app_module.DATA_FILE):
    os.remove(app_module.DATA_FILE)

client = app_module.app.test_client()
passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {detail}")


print("=== Ana sayfa testi ===")
r = client.get("/")
check("GET / 200 döndürüyor", r.status_code == 200, f"(kod={r.status_code})")
check("HTML içinde 'Görev Defteri' geçiyor", "Görev Defteri" in r.get_data(as_text=True))

print("\n=== Boş liste testi ===")
r = client.get("/api/tasks")
check("GET /api/tasks boş dizi döndürüyor", r.status_code == 200 and r.get_json() == [])

print("\n=== Görev oluşturma testleri ===")
r = client.post("/api/tasks", json={"title": "Flask uygulamasını yaz"})
check("POST 201 döndürüyor", r.status_code == 201, f"(kod={r.status_code})")
task1 = r.get_json()
check("Görev alanları doğru", task1["title"] == "Flask uygulamasını yaz"
      and task1["done"] is False and "id" in task1 and "created_at" in task1)

r = client.post("/api/tasks", json={"title": "Türkçe karakterler: çğıöşü"})
task2 = r.get_json()
check("Türkçe karakterler korunuyor", task2["title"] == "Türkçe karakterler: çğıöşü")

r = client.post("/api/tasks", json={"title": "  boşluklar temizlenir  "})
task3 = r.get_json()
check("Başlık kırpılıyor (strip)", task3["title"] == "boşluklar temizlenir")

r = client.post("/api/tasks", json={"title": ""})
check("Boş başlık 400 döndürüyor", r.status_code == 400, f"(kod={r.status_code})")

r = client.post("/api/tasks", json={"title": "x" * 201})
check("200+ karakter 400 döndürüyor", r.status_code == 400, f"(kod={r.status_code})")

print("\n=== Liste ve filtre testleri ===")
r = client.get("/api/tasks")
check("3 görev listeleniyor", len(r.get_json()) == 3, f"(adet={len(r.get_json())})")

# Bir görevi tamamla
r = client.patch(f"/api/tasks/{task1['id']}", json={"done": True})
check("PATCH done=True çalışıyor", r.status_code == 200 and r.get_json()["done"] is True)

r = client.get("/api/tasks?status=active")
check("Aktif filtresi 2 görev döndürüyor", len(r.get_json()) == 2)

r = client.get("/api/tasks?status=completed")
data = r.get_json()
check("Tamamlanan filtresi 1 görev döndürüyor", len(data) == 1 and data[0]["id"] == task1["id"])

print("\n=== Açıklama (description) testleri ===")
r = client.post("/api/tasks", json={
    "title": "Toplantı notları",
    "description": "Gündem:\n1. Bütçe\n2. Yol haritası\n3. Atamalar",
})
task_d = r.get_json()
check("Açıklamalı görev 201 döndürüyor", r.status_code == 201, f"(kod={r.status_code})")
check("Açıklama çok satırlı korunuyor",
      task_d["description"] == "Gündem:\n1. Bütçe\n2. Yol haritası\n3. Atamalar")
check("Açıklamada Türkçe karakterler korunuyor", "Bütçe" in task_d["description"])

r = client.post("/api/tasks", json={"title": "Açıklamasız görev"})
check("Açıklama boşsa alan '' olarak geliyor", r.get_json()["description"] == "")

r = client.post("/api/tasks", json={"title": "Uzun", "description": "x" * 1001})
check("1000+ karakter açıklama 400 döndürüyor", r.status_code == 400, f"(kod={r.status_code})")

r = client.patch(f"/api/tasks/{task3['id']}", json={"description": "Sonradan eklenen açıklama"})
check("Mevcut göreve sonradan açıklama eklenebiliyor",
      r.status_code == 200 and r.get_json()["description"] == "Sonradan eklenen açıklama")

r = client.patch(f"/api/tasks/{task_d['id']}",
                 json={"title": "Toplantı notları v2", "description": "Kısa not"})
body = r.get_json()
check("Başlık + açıklama birlikte güncelleniyor",
      body["title"] == "Toplantı notları v2" and body["description"] == "Kısa not")

r = client.patch(f"/api/tasks/{task_d['id']}", json={"description": ""})
check("Açıklama boşaltılabiliyor", r.get_json()["description"] == "")

r = client.patch(f"/api/tasks/{task_d['id']}", json={"done": True})
check("Sadece done gönderince açıklama korunuyor",
      r.get_json()["description"] == "")
client.patch(f"/api/tasks/{task_d['id']}", json={"done": False})  # eski durumuna al

r = client.patch(f"/api/tasks/{task_d['id']}", json={"description": "Korunan not"})
r = client.patch(f"/api/tasks/{task_d['id']}", json={"done": True})
check("Dolu açıklamalı görevde done değiştirince açıklama korunuyor",
      r.get_json()["description"] == "Korunan not")
client.patch(f"/api/tasks/{task_d['id']}", json={"done": False})

r = client.get("/api/tasks")
check("Açıklamalar GET ile de geri geliyor",
      any(t.get("description") == "Sonradan eklenen açıklama" for t in r.get_json()))

print("\n=== Güncelleme testleri ===")
r = client.patch(f"/api/tasks/{task2['id']}", json={"title": "Yeni başlık"})
check("Başlık güncellenebiliyor", r.get_json()["title"] == "Yeni başlık")

r = client.patch("/api/tasks/olmayan-id", json={"done": True})
check("Olmayan görev 404 döndürüyor", r.status_code == 404)

r = client.patch(f"/api/tasks/{task2['id']}", json={"title": "   "})
check("Boş başlıkla güncelleme 400", r.status_code == 400)

print("\n=== Kalıcılık testi ===")
with open(app_module.DATA_FILE, encoding="utf-8") as f:
    on_disk = json.load(f)
check("Görevler diske yazıldı", len(on_disk) == 5, f"(diskte={len(on_disk)})")
check("Diskteki açıklamada Türkçe karakter bozulmadı",
      any("Sonradan eklenen açıklama" == t.get("description") for t in on_disk))

print("\n=== Silme testleri ===")
r = client.delete(f"/api/tasks/{task3['id']}")
check("DELETE 204 döndürüyor", r.status_code == 204, f"(kod={r.status_code})")

r = client.delete(f"/api/tasks/{task3['id']}")
check("Tekrar silme 404 döndürüyor", r.status_code == 404)

# task1 tamamlanmış durumda -> temizleme testi
r = client.delete("/api/completed")
check("Tamamlananları temizle 1 sildi", r.get_json()["removed"] == 1)

r = client.get("/api/tasks")
check("Son durumda kalan görevler (task2 + 2 açıklama testi)", len(r.get_json()) == 3)

print(f"\n{'='*40}")
print(f"SONUÇ: {passed} başarılı, {failed} başarısız")
print("=" * 40)

# Temizlik
if os.path.exists(app_module.DATA_FILE):
    os.remove(app_module.DATA_FILE)

sys.exit(1 if failed else 0)
