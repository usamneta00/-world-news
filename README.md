# العالمية NEWS 🌍

> منصة أخبار ذكية تجمع آخر الأخبار العالمية واليمنية من قنوات يوتيوب موثوقة

![Version](https://img.shields.io/badge/version-2.0-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-latest-teal)

## ✨ المميزات

### 🎨 تصميم احترافي
- واجهة داكنة أنيقة مع تأثيرات Glass Morphism
- تصميم متجاوب يعمل على جميع الأجهزة
- تجربة مستخدم سلسة مع انتقالات سلسة

### 📰 مصادر متنوعة
- **16 قناة عالمية**: Reuters, BBC, Al Jazeera English, Sky News, وغيرها
- **15 قناة يمنية وعربية**: تغطية شاملة للأحبار اليمنية

### 🔍 فلترة ذكية
- نظام فلترة متقدم لأخبار اليمن
- تركيز على: درع الوطن، الانتقالي الجنوبي، والأحداث اليمنية
- أكثر من 35 كلمة مفتاحية للفلترة الدقيقة

### ⚡ تحديثات فورية
- WebSocket للتحديثات اللحظية
- إشعارات بالأخبار الجديدة
- فحص القنوات كل 3 دقائق

## 🚀 التثبيت والتشغيل

### المتطلبات
- Python 3.8 أو أحدث
- pip

### التثبيت المحلي

1. **استنساخ المشروع:**
```bash
git clone <repository-url>
cd world-news
```

2. **تثبيت المتطلبات:**
```bash
pip install -r requirements.txt
```

3. **تشغيل الخادم:**
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8002
```

4. **فتح المتصفح:**
```
http://localhost:8002
```

### النشر على Railway

1. **رفع الكود إلى GitHub:**
```bash
git add .
git commit -m "Deploy to Railway"
git push origin main
```

2. **ربط المشروع بـ Railway:**
   - افتح [Railway.app](https://railway.app)
   - أنشئ مشروع جديد
   - اربط مستودع GitHub
   - سيتم النشر تلقائياً

3. **التحقق من النشر:**
   - انتظر حتى يكتمل البناء
   - افتح الرابط المخصص من Railway

## 📁 هيكل المشروع

```
world-news/
├── backend/
│   └── main.py              # الخادم الرئيسي (FastAPI)
├── public/
│   ├── index.html           # الواجهة الرئيسية
│   └── app.js               # منطق JavaScript
├── requirements.txt         # متطلبات Python
├── Procfile                 # ملف Railway
├── CHANGELOG.md             # سجل التغييرات
└── README.md                # هذا الملف
```

## 🔧 التكوين

### إضافة قنوات جديدة

**للأخبار العالمية** - عدّل `YOUTUBE_CHANNELS` في `backend/main.py`:
```python
YOUTUBE_CHANNELS = [
    {"url": "https://www.youtube.com/@ChannelName/videos", "name": "اسم القناة", "type": "channel"},
    # أضف المزيد...
]
```

**لأخبار اليمن** - عدّل `YEMEN_YOUTUBE_CHANNELS`:
```python
YEMEN_YOUTUBE_CHANNELS = [
    {"url": "https://www.youtube.com/@ChannelName/videos", "name": "اسم القناة", "type": "channel"},
    # أضف المزيد...
]
```

### تعديل الكلمات المفتاحية للفلترة

عدّل `YEMEN_FILTER_KEYWORDS` في `backend/main.py`:
```python
YEMEN_FILTER_KEYWORDS = [
    'يمن',
    'درع الوطن',
    'الانتقالي',
    # أضف كلمات مفتاحية جديدة...
]
```

### تغيير وقت الفحص

عدّل السطر في دالة `fetch_youtube_feeds`:
```python
await asyncio.sleep(180)  # 180 ثانية = 3 دقائق
```

### إعداد DownSub لجلب نصوص الفيديو

يستخدم التطبيق DownSub API لجلب ملفات `TXT` و`SRT`. ضع مفتاح الاشتراك في متغير البيئة، ولا تضعه داخل الملفات أو المستودع:

```bash
DOWNSUB_API_KEY=ضع_مفتاح_DownSub_هنا
```

يمكن ضبط مهلات الطلب وعدد المحاولات عبر `DOWNSUB_RETRIES` و`DOWNSUB_POST_TIMEOUT` و`DOWNSUB_GET_TIMEOUT`.

## 📊 API Endpoints

### الأخبار العالمية
```
GET /api/news?page=1&limit=20
```

### أخبار اليمن
```
GET /api/yemen-news?page=1&limit=20
```

### WebSocket
```
WS /ws
```

## 🎯 الكلمات المفتاحية للفلترة

### المدن اليمنية
صنعاء، عدن، تعز، حضرموت، الحديدة، مأرب، ذمار، إب، المكلا، سيئون، شبوة، أبين، لحج، الضالع

### الجهات السياسية والعسكرية
- **الحوثيين**: حوثي، الحوثي، الحوثيين، أنصار الله
- **درع الوطن**: درع الوطن، درع وطن
- **الانتقالي الجنوبي**: الانتقالي، الانتقالي الجنوبي، المجلس الانتقالي، STC
- **الحكومة**: الحكومة اليمنية، الشرعية، الشرعية اليمنية

## 🛠️ التقنيات المستخدمة

- **Backend**: FastAPI, SQLAlchemy, yt-dlp
- **Frontend**: HTML5, Tailwind CSS, Vanilla JavaScript
- **Database**: SQLite
- **Real-time**: WebSocket
- **Deployment**: Railway

## 📝 الملاحظات

- يتم حفظ آخر 30 خبر فقط في قاعدة البيانات
- يتم تتبع آخر 10 فيديوهات لكل قناة لتجنب التكرار
- الفلترة تطبق فقط على أخبار اليمن
- الأخبار العالمية تُعرض بدون فلترة

## 🐛 الإبلاغ عن المشاكل

إذا واجهت أي مشاكل، يرجى:
1. التحقق من سجلات الخادم (logs)
2. التأكد من تثبيت جميع المتطلبات
3. التحقق من اتصال الإنترنت

## 📜 الترخيص

هذا المشروع مفتوح المصدر ومتاح للاستخدام الشخصي والتجاري.

## 👨‍💻 المطور

تم التطوير بواسطة Antigravity AI

---

**نسخة**: 2.0  
**آخر تحديث**: 2026-01-08
