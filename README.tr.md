> ⚠️ **Uyarı (İngilizce)**: Bu proje yapay zeka tarafından desteklenmiştir. Hatalar ve eksik uygulamalar içerebilir ve halen aktif olarak geliştirilme aşamasındadır. Nihai sürüm DEĞİLDİR.

# RenLocalizer

**RenLocalizer**, Ren'Py görsel roman (.rpy) dosyalarını yüksek doğruluk ve performansla otomatik olarak çevirmek için tasarlanmış modern bir masaüstü uygulamasıdır. Birden fazla çeviri motoru, akıllı metin filtreleme ve profesyonel bir kullanıcı arayüzü sunar.

## ✨ Temel Özellikler

### 🎯 Akıllı Çeviri
- **Birden fazla motor**: Google Translate (web), DeepL API, Deep-Translator (çoklu motor) desteği
- **RenPy uyumlu ayrıştırma**: Menü seçeneklerini, diyalogları ve UI öğelerini doğru şekilde işler
- **Koşullu menü desteği**: `“choice” if condition:` sözdizimini işler
- **Teknik filtreleme**: Renk kodlarını, yazı tipi dosyalarını ve performans ölçütlerini otomatik olarak hariç tutar
- **Karakter koruma**: `[karakter_adı]` değişkenlerini ve yer tutucuları korur

### 🚀 Yüksek Performans
- **Eşzamanlı işleme**: Yapılandırılabilir iş parçacığı sayısı (1-256)
- **Toplu çeviri**: Birden fazla metni birlikte işler (1-2000)
- **Proxy rotasyonu**: Otomatik proxy yönetimi ve doğrulama
- **Yapılandırılabilir davranış**: Proxy güncelleme aralığı, hata limiti ve başlangıçta test etme gibi ayarlar artık tamamen `Proxy` sekmesinden yönetilir.
- **Akıllı yedekleme**: Proxy'ler başarısız olursa doğrudan isteklere geri döner
- **Hız sınırlama**: Engellemeyi önlemek için uyarlanabilir gecikmeler

### 🎨 Modern Arayüz
- **Profesyonel temalar**: Koyu ve Solarized temalar
- **Basit ana ekran**: Sadece klasör seçimi, temel çeviri ayarları ve ilerleme çubuğu
- **Ayrı ayarlar penceresi**: Gelişmiş performans / proxy / günlük ayarları `Ayarlar` menüsünde
- **İki dilli kullanıcı arayüzü**: İngilizce ve Türkçe arayüz desteği
- **Otomatik kaydetme**: Uygun RenPy yapısı ile zaman damgalı çıktı

### 🔧 RenPy Entegrasyonu
- **Doğru formatlı çıktı**: RenPy'nin gerektirdiği şekilde ayrı ayrı `çeviri dizeleri` blokları
- **Dil başlatma**: Otomatik dil kurulum dosyaları
- **Önbellek yönetimi**: Yerleşik RenPy önbellek temizleme
- **Dizin yapısı**: Uygun `game/tl/[dil]/` düzeni

## 📦 Kurulum

### Ön Koşullar
- Python 3.8 veya üstü
- Git (isteğe bağlı, ZIP olarak da indirebilirsiniz)
- pip (Python paket yöneticisi)
- Windows kullanıcıları için: C++ desteği ile Visual Studio Build Tools (bazı bağımlılıklar için)

### Adımlar

1. **Depoyu klonlayın:**
```bash
git clone https://github.com/yourusername/RenLocalizer.git
cd RenLocalizer
```

2. **Sanal ortam oluşturun (önerilir):**
```bash
python -m venv venv

# Windows'ta:
venv\Scripts\activate

# Linux/macOS'ta:
source venv/bin/activate
```

3. **Bağımlılıkları yükleyin:**
```bash
pip install -r requirements.txt
```

4. **Uygulamayı çalıştırın:**
```bash
python run.py
```

Veya Windows'ta, `run.bat` dosyasını çift tıklayabilirsiniz.

## 🚀 Hızlı Başlangıç
1. Uygulamayı başlatın (`python run.py`)
2. `.rpy` dosyalarını içeren klasörü seçin
3. Kaynak ve hedef dili seçin (ör. EN → TR)
4. Motor ve toplu iş ayarlarını yapılandırın
5. Çeviriyi başlatın – canlı ilerlemeyi izleyin
6. Çeviriler otomatik olarak kaydedilir (veya manuel olarak kaydedebilirsiniz)

## ⚙️ Ayarlar
- Eşzamanlı iş parçacıkları (1–256)
- Toplu iş boyutu (1–2000)
- İstek gecikmesi (0–5 s)
- Maksimum yeniden deneme sayısı
- Proxy'yi etkinleştir / devre dışı bırak
- Proxy hata limiti, güncelleme aralığı ve özel proxy listesi (her satıra bir tane)

## 🌍 Motor Durumu Tablosu
| Motor | Durum | Not |
|--------|--------|------|
| Google | ✅ Etkin | Web istemcisi + proxy yedeği |
| DeepL | ✅ Etkin | Yalnızca kullandığınızda API anahtarı gerekir |
| OPUS-MT | ❌ Kaldırıldı | - | OPUS-MT yerel bağımlılık sorunları nedeniyle kaldırıldı |
| Deep-Translator | ✅ Etkin | Çoklu motor sarmalayıcısı (Google, Bing, Yandex vb.) |
| Bing / Microsoft | ⏳ Planlanmış | Henüz eklenmedi |
| Yandex | ⏳ Planlanmış | Henüz eklenmedi |
| LibreTranslator | ⏳ Planlanmış | Gelecekte kendi kendine barındırma seçeneği |

## 🧠 Ayrıştırma Mantığı
- Kod blokları, etiket tanımları, python blokları hariç tutulur
- Yalnızca gerçek diyaloglar ve kullanıcı tarafından görülebilen dizeler çıkarılır
- Dosya yolları, değişkenler, `%s`, `{name}` vb. korunur

## 📁 Proje Yapısı
```
src/
    core/ (çeviri, ayrıştırıcı, proxy)
    gui/  (arayüz ve temalar)
    utils/ (yapılandırma)
run.py (başlatıcı)
README.md / README.tr.md
LİSANS
```

## 🔐 API Anahtarları
Şu anda sadece DeepL anahtarı anlamlıdır; diğerleri motorlar geldiğinde etkinleşir.

## 📦 Yürütülebilir Dosya Oluşturma
Bağımsız yürütülebilir dosyalar oluşturma konusunda ayrıntılı talimatlar için `BUILD.md` dosyasına bakın.

## 🧪 Test Etme ve Katkı Sağlama
Pull Request'ler memnuniyetle kabul edilir. Önerilen iyileştirmeler:
- Yeni motor entegrasyonu
- Performans optimizasyonu
- Ek dil desteği
- UI iyileştirmeleri

### Gelişmiş Kullanıcılar İçin Yardımcı Script'ler

`tools/` klasöründe tanılama ve test için bazı ek script'ler bulunur:

- `tools/system_check.py`: Ortamı ve bağımlılıkları kontrol eder, tipik hataları raporlar.
- `tools/parser_smoke.py`: Örnek `.rpy` dosyaları üzerinde ayrıştırıcının temel çalışmasını test eder.
- `tools/renpy_compatibility_test.py`: Üretilen çıktıların Ren'Py ile uyumluluğunu basit kontrollerle doğrular.
- `tools/performance_test.py`: Farklı thread/batch ayarlarıyla kaba performans testi yapar.

Bu script'leri çalıştırmak için (sanal ortam aktifken) proje kök dizininde şu komutlardan birini kullanabilirsiniz:

```bash
python tools/system_check.py
python tools/parser_smoke.py
```

## ❓ Sorun Giderme
| Sorun | Çözüm |
|---------|----------|
| ‘src’ modülü bulunamadı | `PYTHONPATH` ayarlayın veya kökten çalıştırın |
| Yavaş çeviri | İş parçacığı ve toplu iş sayısını artırın, gecikmeyi azaltın |
| Hız sınırı | Proxy'yi etkinleştirin veya motoru değiştirin |
| Bozuk etiket | Yer tutucu korumasının etkinleştirildiğinden emin olun |

