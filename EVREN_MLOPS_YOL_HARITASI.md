# EVREN AI ile 120B+ Seviyesine Ölçekleme ve MLOps Yol Haritası

Bu rehber, mevcut **Local AI Hub** ([uygulama.py](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/uygulama.py)) ve **Mini Agent** ([ai-assistant](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/ai-assistant)) projesini **7–8B** yerel modellerden **EVREN AI** (`https://evren.ssyz.org.tr`) altyapısı üzerindeki büyük modellere (**120B+ sınıfı / MoE / gelişmiş açık ağırlıklı modeller**) taşımak ve kendi modelini EVREN MLOps üzerinde geliştirmek için hazırlanmıştır.

---

## 1. İki Aşamalı Mimari: Çıkarım (Inference) vs. Eğitim (MLOps)

| Aşama | Ne Yapar? | Nerede Çalışır? | Bu Projede Nasıl Kullanılır? |
| :--- | :--- | :--- | :--- |
| **1. EVREN LLM API (Çıkarım)** | Hazır büyük modelleri (`auto`, `glm-5.3`, `deepseek-v4-flash`, `qwen3.8-flash-next`, `gemma-4-31b` vb.) H200 GPU kümeleri üzerinden çalıştırır. | `https://evren-llmapi.ssyz.org.tr/v1` | [uygulama.py](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/uygulama.py) (Modül 4) ve [ai-assistant](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/ai-assistant) doğrudan bu OpenAI-uyumlu API'ye bağlanır. |
| **2. EVREN MLOps (Özel Eğitim)** | Veri seti yönetimi, etiketleme, ince ayar (Fine-Tuning / LoRA) ve özel model dağıtımı sağlar. | `https://evren.ssyz.org.tr` | Kendi veri setini hazırlayıp EVREN GPU'larında eğittikten sonra ürettiğin modeli/uç noktayı projeye bağlarsın. |

---

## 2. Hızlı Kurulum: EVREN LLM API Bağlantısı

### Adım 1: API Anahtarı ve Kullanım Şartları
1. [evren.ssyz.org.tr](https://evren.ssyz.org.tr) adresine **e-Devlet** ile giriş yap.
2. Hesap / API Anahtarları bölümünden `evren_llm_...` ile başlayan anahtarını oluştur.
3. İlk kullanımda EVREN API şartlarını onaylamak gerekir:
   - **Masaüstü uygulamasında ([uygulama.py](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/uygulama.py)):** Modül 4 içinde **🔑 EVREN Ayarları** → anahtarı gir → **📜 Kullanım Şartlarını Onayla** butonuna tıkla.
   - **Terminal üzerinden (isteğe bağlı):**
     ```bash
     curl -s https://evren-llmapi.ssyz.org.tr/v1/terms/status -H "X-API-Key: $EVREN_API_KEY"
     curl -s -X POST https://evren-llmapi.ssyz.org.tr/v1/terms/accept -H "X-API-Key: $EVREN_API_KEY" -H "Content-Type: application/json" -d "{\"version\": 1}"
     ```

### Adım 2: Web Arayüzü (`ai-assistant`) Yapılandırması
[ai-assistant/.env.example](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/ai-assistant/.env.example) dosyasını `.env.local` olarak kopyalayıp şu alanları doldur:
```env
AI_PROVIDER=evren
EVREN_BASE_URL=https://evren-llmapi.ssyz.org.tr/v1
EVREN_API_KEY=evren_llm_BURAYA_ANAHTARINI_YAZ
EVREN_MODEL=auto
```
> Not: Hesabına tanımlı tüm güncel modelleri görmek için `GET https://evren-llmapi.ssyz.org.tr/v1/models` uç noktasını veya masaüstü uygulamasındaki model listesini kullanabilirsin.

---

## 3. EVREN MLOps Üzerinde Kendi Modelini Geliştirme Yol Haritası

Kendi bilgisayarındaki 7–8B modellerin ötesine geçip **alanına özel (ör. Türkçe asistan, savunma/teknik doküman analizi, görüntü tespiti)** bir yapay zekâ geliştirmek için EVREN MLOps döngüsünü şu sırayla izlemelisin:

1. **Veri Seti Toplama ve Sürümleme (Dataset Versioning)**
   - **Sohbet / Ajan için:** Önceki konuşma kayıtlarını (`mini_agent_history.db` veya Supabase `messages` tablosu) temizleyip `instruction / input / output` (veya OpenAI `messages` JSONL) formatına dönüştür.
   - **Görüntü Modülleri ([uygulama.py](file:///c:/Users/burakb/Downloads/Yeni%20klas%C3%B6r/uygulama.py) Modül 1 & 2 YOLOv8) için:** Yüz ve plaka veri setlerini EVREN veri havuzuna yükleyip sürümle.

2. **Kredi (CR) Kazanımı ve GPU Kaynağı**
   - EVREN'de veri seti yükleme, etiketleme ve topluluk katkıları ile kredi (`CR`) kazanılır; bu krediler NVIDIA H200 GPU kümeleri üzerinde eğitim ve çıkarım için kullanılır.

3. **Sıfırdan Eğitim Yerine Verimli Büyük Model Eğitimi (LoRA / QLoRA / Distillation)**
   - 120B sınıfı bir modeli sıfırdan eğitmek yerine:
     - **Öğretmen-Öğrenci Damıtma (Knowledge Distillation):** EVREN üzerindeki büyük modellerle (`deepseek`, `qwen`, `glm` vb.) yüksek kaliteli sentetik Türkçe eğitim verisi üret.
     - **LoRA / QLoRA Fine-Tuning:** Seçtiğin güçlü temel modeli EVREN GPU kümesinde kendi Türkçe görev verinle (araç çağırma, PDF özetleme, özel alan bilgisi) ince ayarla eğit.

4. **RAG (Kendi Bilgi Evrenin) ile Güçlendirme**
   - Büyük modeli her bilgi için yeniden eğitmek yerine, kendi belgelerini (`generated_pdfs/` ve özel dokümanların) vektör veritabanına (ör. Supabase `pgvector`) gömüp modele bağlam olarak ver.
   - Böylece hem **120B+ akıl yürütme gücü** hem de **senin verilerine dayalı güncel bilgi evreni** bir arada çalışır.

5. **Canlıya Alma ve Projeye Bağlama**
   - Eğittiğin model EVREN üzerinde yayınlandığında (inference endpoint), tek yapman gereken `.env.local` veya masaüstü uygulamasındaki `Model` alanına yeni model ID'sini yazmaktır.
