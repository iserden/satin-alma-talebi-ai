# AI Destekli Satın Alma Talebi Otomasyonu

Yapay zekâ destekli satın alma talebi otomasyonu; işletmelerden gelen satın alma talep formlarının dijital olarak işlenmesi, ürün kataloğuyla eşleştirilmesi, taleplerin birleştirilmesi ve onaylanan verilerin **SAP Business One** sistemine aktarılması amacıyla geliştirilmiş Django tabanlı bir web uygulamasıdır.

Proje, belge okuma ve ürün eşleştirme süreçlerinde yapay zekâ desteği kullanır ve SAP Business One ile **Service Layer API** üzerinden haberleşir.

---

## Projenin Temel Özellikleri

* PDF ve görsel formatındaki satın alma talep formlarının yüklenmesi
* Gemini API ile form içerisindeki verilerin okunması
* Ürünlerin sistemdeki ürün kataloğuyla otomatik eşleştirilmesi
* Eşleşmeler için güven skorlarının gösterilmesi
* Kullanıcı tarafından eşleşmelerin kontrol edilmesi ve düzenlenmesi
* Ürün alternatif isimlerinin öğrenilmesi
* Satın alma taleplerinin onaylanması
* Birden fazla onaylı talebin tek bir satın alma talebinde birleştirilmesi
* Haftalık ürün miktarlarının otomatik olarak toplanması
* Excel, CSV ve JSON çıktılarının oluşturulması
* SAP aktarımı öncesinde satın alma talebi önizlemesi
* SAP Business One üzerinde gerçek Purchase Request oluşturulması
* SAP `DocEntry` ve `DocNum` bilgilerinin sistemde saklanması
* Aynı talebin SAP'ye ikinci kez gönderilmesinin engellenmesi
* Docker ile taşınabilir çalışma ortamı

---

# Kullanılan Teknolojiler

### Backend

* Python 3.12
* Django 5.2
* SQLite
* Django ORM

### Artificial Intelligence

* Google Gemini API
* Google GenAI Python SDK
* RapidFuzz

### SAP Integration

* SAP Business One
* SAP Business One Service Layer
* REST / OData API
* Python Requests

### Dosya İşleme

* Pillow
* OpenPyXL

### Deployment / Development

* Docker
* Docker Compose
* Git
* GitHub

---

# Sistem Akışı

```text
Satın Alma Talep Formu
        ↓
Form Yükleme
        ↓
Gemini ile Belge Analizi
        ↓
Ürün Bilgilerinin Çıkarılması
        ↓
Ürün Kataloğu ile Eşleştirme
        ↓
Kullanıcı Kontrolü
        ↓
Talep Onayı
        ↓
Birden Fazla Talebin Birleştirilmesi
        ↓
SAP Önizleme
        ↓
SAP Business One Service Layer
        ↓
Purchase Request
```

---

# Kurulum

Bu proje Docker kullanılarak çalıştırılmak üzere hazırlanmıştır.

Projeyi çalıştıracak bilgisayarda aşağıdaki programların kurulu olması yeterlidir:

* Git
* Docker Desktop

Python veya sanal ortam kurulmasına gerek yoktur.

---

## 1. Repository'yi Klonlayın

Private GitHub repository erişiminizin bulunduğundan emin olun.

```bash
git clone <repository-url>
```

Ardından proje klasörüne geçin:

```bash
cd satin-alma-talebi-ai
```

---

## 2. Environment Dosyasını Oluşturun

Projede örnek environment dosyası bulunmaktadır:

```text
.env.example
```

Bu dosyanın bir kopyasını oluşturup adını:

```text
.env
```

olarak değiştirin.

PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

---

## 3. `.env` Ayarlarını Yapılandırın

`.env` dosyasındaki gerekli alanları doldurun.

Örnek:

```env
DJANGO_SECRET_KEY=your-secret-key
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=your-gemini-model

SAP_BASE_URL=https://mersapvm01:50000/b1s/v1
SAP_COMPANY_DB=your-company-database
SAP_USERNAME=your-sap-username
SAP_PASSWORD=your-sap-password
SAP_VERIFY_SSL=false
SAP_TIMEOUT=30
SAP_DEFAULT_WAREHOUSE=your-warehouse-code
```

> Gerçek kullanıcı adı, şifre ve API anahtarları repository içerisinde tutulmamalıdır.

---

# Docker ile Çalıştırma

Docker Desktop çalışır durumda olmalıdır.

Proje klasöründe:

```bash
docker compose up --build
```

komutunu çalıştırın.

İlk çalıştırmada gerekli Docker image'ları ve Python paketleri indirileceği için işlem birkaç dakika sürebilir.

Başarılı çalıştırma sonrasında terminalde aşağıdakine benzer bir çıktı görülür:

```text
Starting development server at http://0.0.0.0:8001/
```

Uygulama:

```text
http://127.0.0.1:8001/
```

adresinden açılabilir.

---

# Database Migration

İlk kurulumdan sonra migration işlemlerini çalıştırın:

```bash
docker compose exec web python manage.py migrate
```

Migration durumunu kontrol etmek için:

```bash
docker compose exec web python manage.py showmigrations
```

---

# Django Admin Kullanıcısı Oluşturma

İlk kurulumda admin kullanıcısı oluşturmak için:

```bash
docker compose exec web python manage.py createsuperuser
```

Komut sizden:

```text
Username
Email
Password
```

bilgilerini isteyecektir.

Admin paneli:

```text
http://127.0.0.1:8001/admin/
```

adresinden açılabilir.

---

# SAP Business One Bağlantısı

Uygulama SAP Business One ile **Service Layer** üzerinden haberleşmektedir.

SAP bağlantısı `.env` içerisindeki aşağıdaki değişkenlerle yapılandırılır:

```env
SAP_BASE_URL=
SAP_COMPANY_DB=
SAP_USERNAME=
SAP_PASSWORD=
SAP_VERIFY_SSL=
SAP_TIMEOUT=
SAP_DEFAULT_WAREHOUSE=
```

Mevcut şirket ortamında Service Layer hostname'i kullanılıyorsa Docker Compose içerisinde gerekli hostname yönlendirmesi tanımlanmalıdır.

Örnek:

```yaml
extra_hosts:
  - "mersapvm01:<SAP-SERVER-IP>"
```

SAP sunucu adresi ortamdan ortama değişebileceği için gerekli IP bilgisi sistem yöneticisinden alınmalıdır.

---

## SAP Bağlantısını Test Etme

Container içerisinden SAP login testi:

```bash
docker compose exec web python test_sap_login.py
```

Başarılı bağlantıda:

```text
HTTP durum kodu: 200
SONUÇ: SAP Service Layer girişi başarılı.
```

çıktısı görülmelidir.

---

# Gemini API Bağlantısı

Gemini API anahtarı `.env` içerisinden okunmaktadır:

```env
GEMINI_API_KEY=
```

API anahtarı kesinlikle doğrudan kaynak kod içerisine yazılmamalıdır.

---

# Docker Komutları

Uygulamayı başlatmak:

```bash
docker compose up
```

Image'ı tekrar oluşturmak:

```bash
docker compose up --build
```

Arka planda çalıştırmak:

```bash
docker compose up -d
```

Container'ları durdurmak:

```bash
docker compose down
```

Çalışan container'ları görmek:

```bash
docker compose ps
```

Logları görüntülemek:

```bash
docker compose logs -f web
```

Container içerisinde Django komutu çalıştırmak:

```bash
docker compose exec web python manage.py <command>
```

---

# Proje Yapısı

```text
satin-alma-talebi-ai/
│
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── requests_app/
│   ├── migrations/
│   ├── services/
│   ├── templates/
│   ├── admin.py
│   ├── forms.py
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── static/
├── templates/
│
├── Dockerfile
├── compose.yaml
├── .dockerignore
├── .env.example
├── .gitignore
├── requirements.txt
├── test_sap_login.py
└── manage.py
```

---

# Temel Servisler

`requests_app/services/` altında uygulamanın ana iş mantıkları bulunmaktadır.

Başlıca servisler:

```text
gemini_service.py
```

Gemini API üzerinden form analiz işlemlerini gerçekleştirir.

```text
product_matching_service.py
```

AI tarafından okunan ürünleri ürün kataloğuyla eşleştirir.

```text
alias_learning_service.py
```

Manuel olarak doğrulanan ürün isimlerinden alternatif ürün isimleri oluşturur.

```text
approval_service.py
```

Satın alma talebi onay süreçlerini yönetir.

```text
consolidation_service.py
```

Birden fazla satın alma talebini birleştirir.

```text
consolidation_export_service.py
```

Excel, CSV ve JSON çıktılarını oluşturur.

```text
sap_service_layer_client.py
```

SAP Business One Service Layer iletişimini yönetir.

```text
sap_purchase_request_builder.py
```

SAP'ye gönderilecek Purchase Request verisini oluşturur.

```text
sap_purchase_request_service.py
```

Purchase Request'in SAP Business One'a gönderilmesini ve SAP belge bilgilerinin saklanmasını yönetir.

---

# Verilerin Saklanması

Geliştirme ve demo ortamında SQLite kullanılmaktadır.

```text
db.sqlite3
```

dosyası Git repository içerisine gönderilmez.

Docker Compose ile bu dosya host bilgisayara volume olarak bağlanmıştır. Böylece container silinse bile mevcut veriler korunabilir.

Yüklenen belgeler:

```text
media/
```

klasöründe tutulur ve bu klasör de repository dışında bırakılmıştır.

---

# Yeni Güncellemeleri Alma

Repository'de yeni bir geliştirme yapıldıysa:

```bash
git pull origin main
```

ardından Docker image'ını tekrar oluşturun:

```bash
docker compose up --build
```

Yeni migration bulunuyorsa:

```bash
docker compose exec web python manage.py migrate
```

komutunu çalıştırın.

---

# Geliştirme Yapmak

Yeni bir geliştirme yapılacaksa doğrudan `main` branch üzerinde çalışmak yerine yeni branch oluşturulması önerilir.

Örnek:

```bash
git checkout -b feature/yeni-ozellik
```

Değişikliklerden sonra:

```bash
git add .
git commit -m "Add: yeni özellik"
git push -u origin feature/yeni-ozellik
```

Ardından GitHub üzerinden Pull Request oluşturulabilir.

---

# Güvenlik

Aşağıdaki dosya ve bilgiler Git repository içerisine kesinlikle gönderilmemelidir:

```text
.env
db.sqlite3
media/
.venv/
```

Özellikle şu bilgiler kaynak kod içerisine doğrudan yazılmamalıdır:

* Gemini API Key
* SAP kullanıcı adı ve şifresi
* Django Secret Key
* Production veritabanı bilgileri
* Şirket içi erişim bilgileri

Bu bilgiler environment variables üzerinden yönetilmelidir.

---

# Proje Durumu

Mevcut sürüm çalışan bir **MVP / şirket içi demo sürümüdür**.

Tamamlanan ana fonksiyonlar:

```text
Form yükleme                         ✅
Gemini belge analizi                 ✅
Ürün kataloğu                        ✅
AI ürün eşleştirme                   ✅
Manuel kontrol                       ✅
Talep onayı                          ✅
Talep birleştirme                    ✅
Excel / CSV / JSON export            ✅
SAP Business One Service Layer       ✅
SAP Purchase Request oluşturma       ✅
SAP DocEntry / DocNum kaydı          ✅
Tekrar gönderim koruması             ✅
Docker                               ✅
```

Production kullanımı öncesinde ayrıca production web server, merkezi veritabanı, SSL, kullanıcı yetkilendirmeleri, loglama, yedekleme ve deployment altyapısının kurumsal standartlara göre yapılandırılması önerilir.

---

# Repository Erişimi

Bu repository **private** olarak tutulmaktadır.

Projede çalışacak kullanıcıların GitHub hesapları repository'ye collaborator veya ilgili organizasyon/team üzerinden eklenmelidir.

---

## Not

Bu proje şirket içi geliştirme, değerlendirme ve demo amaçlı hazırlanmıştır. SAP Business One bağlantı bilgileri, API anahtarları ve şirket verileri repository dışında tutulmalıdır.
