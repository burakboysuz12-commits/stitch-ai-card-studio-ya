# EVREN AI Üzerinde Sürekli Öğrenen ve Geliştirilebilen Model Hattı

Bu klasör, asistanının yalnızca hazır modelleri tüketen bir sohbet botu olarak kalmaması; **kendi verinle eğitilip büyüyebilen bir yapay zekâ** haline gelmesi için hazırlanmıştır.

## 1. Gerçekçi Beklenti: Token ve Kredi (CR) Gerçeği
- **EVREN LLM API (`evren-llmapi.ssyz.org.tr`)** başlangıç kredisi ve dönemsel kullanım kotaları sunar; teknik olarak **katkı esaslı kredi (`CR`)** ve günlük token/hız limitleri vardır (tamamen sınırsız değildir).
- Ancak EVREN platformu (`evren.ssyz.org.tr`) üzerinde **veri seti yükleyip etiketleyerek kredi kazanabilir**, bu kredilerle NVIDIA H200 GPU kümelerinde **kendi açık ağırlıklı modelini eğitebilir** ve model ağırlıklarının kontrolünü elinde tutabilirsin.

## 2. Sürekli Gelişim Döngüsü

1. **Asistanı Kullan & İyi Cevapları İşaretle:**
   - Masaüstü uygulamasında ([uygulama.py](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/uygulama.py)) beğendiğin son cevabın ardından **👍 Eğitime Al** butonuna bas.
   - Yeni dokümanlarını/notlarını **🧠 Bilgi & Eğitim** penceresinden Bilgi Tabanına ekle.
2. **Veri Setini Dışa Aktar (`JSONL`):**
   - Arayüzden veya terminalden çalıştır:
     ```bash
     python evren_train/export_dataset.py
     # Sadece 👍 işaretlenen en kaliteli örnekler için:
     python evren_train/export_dataset.py --only-rated
     ```
   - Çıktı: `evren_train/dataset_train.jsonl` ve `evren_train/dataset_eval.jsonl`.
3. **EVREN H200 Kümesinde İnce Ayar (LoRA Fine-Tuning):**
   - `dataset_train.jsonl` ve `train_lora.py` dosyalarını EVREN çalışma alanına (`evren.ssyz.org.tr`) yükle:
     ```bash
     pip install -r requirements.txt
     python train_lora.py --base-model Qwen/Qwen2.5-32B-Instruct --dataset dataset_train.jsonl --epochs 3 --merge
     ```
   - H200 GPU (141 GB VRAM) üzerinde 14B–32B–72B+ modelleri rahatlıkla LoRA/QLoRA ile eğitebilirsin.
4. **Eğittiğin Modeli Projeye Bağla:**
   - EVREN'de yayınladığın (deploy ettiğin) kendi model uç noktasını veya model adını [uygulama.py](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/uygulama.py) → `Model:` alanına ya da [ai-assistant/.env.local](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/ai-assistant/.env.example) → `EVREN_MODEL=` satırına yazarak doğrudan kullanmaya başla.
