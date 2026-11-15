# PC Kapalıyken 7/24 Çalışma ve Ücretsiz Sunucu Rehberi

## Neden Vercel Değil?
- **Vercel** yalnızca kısa süreli HTTP web isteklerini karşılayan *serverless* bir platformdur; arka planda 7/24 çalışan bir Python masaüstü uygulaması veya kod geliştirme ajanı barındıramaz.
- PC kapalıyken de kesintisiz çalışma için **sürekli açık bir sanal makine (VPS)** gerekir.

## En İyi Ücretsiz VPS Seçenekleri
1. **Oracle Cloud Always Free (Önerilen — Süresiz Ücretsiz)**
   - 4 ARM vCPU, 24 GB RAM, 200 GB disk ($0/ay).
   - Ubuntu veya Windows kurup projeyi ve Antigravity'yi 7/24 açık tutabilirsiniz.
2. **Google Cloud Free Tier (`e2-micro`)**
   - 1 vCPU, 1 GB RAM (hafif işler ve Git/API köprüsü için ücretsiz).
3. **GitHub Codespaces**
   - Aylık 60 saat ücretsiz bulut geliştirme ortamı (tarayıcıdan erişim).

## Sunucuda Kurulum Adımları
```bash
git clone <REPO_URL>
cd "Yeni klasör"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Kendi PC'nize Değişiklikleri Çekmek
Sunucudaki geliştirmeler bittiğinde sabah kendi Windows PC'nizde:
```powershell
git pull
pythonw.exe uygulama.py
```
