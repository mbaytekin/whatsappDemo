# WhatsApp Bot - Sultangazi Belediyesi

WhatsApp benzeri web arayüzüne sahip, Gemini AI destekli belediye destek hattı botu. Vatandaşların taleplerini Excel'deki konu-birim eşleştirmelerine göre otomatik olarak yönlendirir.

## 🚀 Özellikler

- **WhatsApp Benzeri Web Arayüzü**: Modern, responsive chat arayüzü
- **Gemini AI Entegrasyonu**: Google Gemini 2.5 Flash modeli ile akıllı yönlendirme
- **Ses Kaydı ve Transkripsiyon**: Faster-Whisper ile ses mesajlarını metne çevirme
- **TF-IDF Ön Filtreleme**: Hızlı ve maliyet-etkin arama
- **Excel Tabanlı Yönetim**: Konu ve birim bilgileri Excel'den yüklenir
- **Türkçe Dil Desteği**: Türkçe metin işleme ve karakter normalizasyonu
- **Session Yönetimi**: Kullanıcı oturumları TTL ile yönetilir
- **Kategori Bazlı İşleme**: İstek/şikayet kategorileri
- **FastAPI Backend**: Modern, hızlı web framework

## 📋 Gereksinimler

- Python 3.11+
- Conda (önerilen) veya pip
- Gemini API anahtarı
- Excel dosyası (Konu-Birim bilgileri)
- FFmpeg (opsiyonel - ses süresi kontrolü için)

## 🛠️ Kurulum

### 1. Repository'yi Klonlayın

```bash
git clone https://github.com/mbaytekin/whatsappDemo.git
cd whatsappDemo
```

### 2. Conda Ortamını Oluşturun

```bash
conda env create -f environment.yml
conda activate whatsapp-bot
```

Veya pip kullanıyorsanız:

```bash
pip install -r requirements.txt
```

### 3. Environment Variables Ayarlayın

`.env.example` dosyasını `.env` olarak kopyalayın ve düzenleyin:

```bash
cp .env.example .env
```

`.env` dosyasına Gemini API anahtarınızı ekleyin:

```
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

### 4. Excel Dosyasını Hazırlayın

`data/Konular.xlsx` dosyasını hazırlayın. Gerekli sütunlar:

- **ID**: Sayısal ID (zorunlu)
- **Konu**: Konu adı (zorunlu)
- **Birim**: İlgili birim adı (zorunlu)
- **Aktif**: "Evet"/"Hayır" (opsiyonel - varsa sadece "Evet" olanlar yüklenir)

Opsiyonel sütunlar:
- **AnahtarKelimeler**, **Anahtar**, **Etiketler**, **Keywords**, **Açıklama**: Arama kalitesini artırmak için

## 🎯 Kullanım

### Web Arayüzü ile Çalıştırma

```bash
uvicorn app:app --reload --port 8000
```

Tarayıcıda `http://localhost:8000` adresini açın.

**Ses Kaydı Özelliği**: Web arayüzünde mikrofon butonuna tıklayarak ses kaydı yapabilir ve mesajınızı sesli olarak gönderebilirsiniz. Ses otomatik olarak metne çevrilir ve bot'a iletilir.

### CLI Demo ile Test

```bash
python demo_cli.py --excel data/Konular.xlsx
```

Gemini olmadan sadece TF-IDF ile test:

```bash
python demo_cli.py --excel data/Konular.xlsx --no-gemini
```

## 📁 Proje Yapısı

```
whatsappDemo/
├── app.py                 # FastAPI ana uygulama
├── bot.py                 # WhatsApp bot mantığı ve session yönetimi
├── router.py              # Topic routing (TF-IDF + Gemini)
├── konu_birim.py          # Excel yükleme ve veri işleme
├── demo_cli.py            # CLI demo uygulaması
├── templates/
│   └── index.html         # Web arayüzü template
├── static/
│   ├── css/
│   │   └── style.css      # WhatsApp benzeri stil
│   └── js/
│       └── chat.js        # Chat mantığı
├── data/
│   └── Konular.xlsx       # Konu-Birim Excel dosyası
├── .env                   # Environment variables (git'te yok)
├── .env.example           # Environment variables örneği
├── requirements.txt       # Python bağımlılıkları
└── environment.yml        # Conda environment
```

## 🔧 Konfigürasyon

### Environment Variables

#### Gemini AI
- `GEMINI_API_KEY`: Gemini API anahtarı (zorunlu)
- `GEMINI_MODEL`: Kullanılacak model (varsayılan: `gemini-2.5-flash`)

#### Whisper (Ses Transkripsiyon)
- `WHISPER_MODEL`: Whisper model adı (varsayılan: `medium`)
  - Seçenekler: `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3`
- `WHISPER_DEVICE`: Cihaz tipi (varsayılan: `auto`)
  - Seçenekler: `auto`, `cpu`, `cuda`
- `WHISPER_COMPUTE_TYPE`: Hesaplama tipi (varsayılan: `auto`)
  - Seçenekler: `auto`, `int8`, `float16`, `int8_float16`
- `WHISPER_MAX_MB`: Maksimum ses dosyası boyutu MB (varsayılan: `15`)
- `WHISPER_MAX_SECONDS`: Maksimum ses süresi saniye (varsayılan: `90`)

#### Diğer
- `KONU_BIRIM_EXCEL`: Excel dosyası yolu (varsayılan: `data/Konular.xlsx`)
- `LOG_LEVEL`: Log seviyesi (varsayılan: `INFO`)
- `LOG_FILE`: Log dosyası yolu (opsiyonel)
- `TMPDIR`: Geçici dosya dizini (opsiyonel)

**Not**: `ffprobe` (FFmpeg) ses süresi kontrolü için kullanılır. Yüklü değilse süre kontrolü atlanır. FFmpeg'i [buradan](https://ffmpeg.org/download.html) indirebilirsiniz.

### Router Ayarları

`router.py` içinde ayarlanabilir parametreler:

- `top_k`: TF-IDF ile seçilecek aday sayısı (varsayılan: 8)
- `min_confidence`: Minimum güven skoru (varsayılan: 0.55)
- `min_score`: Minimum TF-IDF skoru (varsayılan: 0.18)
- `temperature`: Gemini temperature (varsayılan: 0.2)

## 🧪 Test

### Örnek Sorular

Excel dosyanızdaki konulara göre:

- "park bahçe sorunu var"
- "temizlik yapılmıyor"
- "zabıta şikayeti"
- "çöp toplama yapılmıyor"
- "yol çukuru var"

## 📊 Nasıl Çalışır?

1. **Excel Yükleme**: Uygulama başlangıcında Excel'den tüm konular yüklenir
2. **Mesaj Alma**: Kullanıcı metin veya ses mesajı gönderir
3. **Ses Transkripsiyon** (opsiyonel): Ses mesajı varsa Faster-Whisper ile metne çevrilir
4. **TF-IDF Ön Filtreleme**: Kullanıcı mesajı geldiğinde TF-IDF ile en iyi 8 aday seçilir
5. **Gemini AI Kararı**: Seçilen adaylar Gemini'ye gönderilir, en uygun eşleşme seçilir
6. **Yönlendirme**: Kullanıcıya ilgili birim bilgisi döndürülür

## 🔒 Güvenlik

- `.env` dosyası `.gitignore`'da (API anahtarları git'e eklenmez)
- Hassas bilgiler environment variables ile yönetilir
- Excel dosyaları git'e eklenmez (`.gitignore`)

## 📝 Lisans

Bu proje özel kullanım içindir.

## 🤝 Katkıda Bulunma

1. Fork edin
2. Feature branch oluşturun (`git checkout -b feature/amazing-feature`)
3. Commit edin (`git commit -m 'Add amazing feature'`)
4. Push edin (`git push origin feature/amazing-feature`)
5. Pull Request açın

## 📞 İletişim

Sorularınız için issue açabilirsiniz.

## 🙏 Teşekkürler

- Google Gemini AI
- Faster-Whisper
- FastAPI
- scikit-learn
