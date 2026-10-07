# أهلية أكاديمي — الموقع + السيرفر + قاعدة البيانات

الموقع بقى مشروع Flask فيه قاعدة بيانات SQLite. الطلاب يسجّلوا حساب ويدخلوا، وبياناتهم محفوظة على السيرفر.

## الهيكل
```
app.py            السيرفر (الحسابات + الـ API + حماية الصفحات والملفات)
manage.py         أوامر إدارة (عدد الطلاب، تغيير باسورد، تصدير CSV ...)
public/           صفحات الموقع (HTML/JS/CSS + ملفات PDF)
instance/         قاعدة البيانات ahlia.db + المفتاح السري (بيتعمل تلقائي — لا ترفعه على GitHub)
requirements.txt
```

## التشغيل على جهازك
```bash
pip install -r requirements.txt
python app.py          # افتح http://127.0.0.1:5000
```

## الرفع على سيرفر (مهم)
الموقع محتاج استضافة بتشغّل **Python**. مش هيشتغل على استضافة HTML بس أو PHP فقط.
خيارات مناسبة: PythonAnywhere، VPS (DigitalOcean/Hetzner...)، أو أي استضافة فيها "Setup Python App".

**تحذير:** قاعدة البيانات ملف على القرص (`instance/ahlia.db`). لازم الاستضافة تحفظ الملفات بشكل دائم.
خدمات زي Render/Railway/Heroku المجانية بتمسح الملفات عند كل إعادة تشغيل — استخدم Persistent Disk
(ومرّر مساره بالمتغير `DATABASE=/data/ahlia.db`) أو VPS.

### على VPS (Ubuntu)
```bash
pip install -r requirements.txt
HTTPS=1 TRUST_PROXY=1 gunicorn -w 3 -b 127.0.0.1:8000 app:app
```
وبعدها nginx يعمل proxy على المنفذ 8000 مع شهادة HTTPS (certbot).

### على PythonAnywhere
ارفع المجلد، وأنشئ Web app (Flask)، وفي ملف WSGI اكتب:
```python
import sys; sys.path.insert(0, "/home/USERNAME/ahlia")
from app import app as application
```

## متغيرات البيئة (اختيارية)
| المتغير | الاستخدام |
|---|---|
| `HTTPS=1` | فعّله أول ما الموقع يشتغل على https (يخلّي الكوكي Secure) |
| `TRUST_PROXY=1` | لو الموقع وراء nginx أو خدمة استضافة بتعمل proxy |
| `ALLOWED_EMAIL_DOMAINS` | مثال `ahlia.edu.eg` — يقصر التسجيل على الإيميل الجامعي |
| `SECRET_KEY` | مفتاح الجلسات (لو ما اتحددش بيتولّد في `instance/secret.key`) |
| `DATABASE` | مسار ملف قاعدة البيانات |

## إدارة الحسابات
```bash
python manage.py stats
python manage.py list
python manage.py export users.csv
python manage.py reset-password student@mail.com
python manage.py delete student@mail.com
```

## النسخ الاحتياطي
انسخ ملف `instance/ahlia.db` بشكل دوري (يفضّل والسيرفر شغال عن طريق `sqlite3 ahlia.db ".backup backup.db"`).

## صلاحيات الوصول
كل طالب يفتح سنته أو تخصصه بس (صفحات وملفات). لتغيير القاعدة عدّل الدالة `access_for` في `app.py`.

## ما هو غير موجود حاليًا
- **استعادة كلمة المرور بالإيميل:** محتاجة سيرفر إيميل. حاليًا الإدارة تغيّرها بـ `manage.py reset-password`.
- **التحقق من ملكية الإيميل:** التسجيل مفتوح لأي إيميل صيغته صحيحة؛ استخدم `ALLOWED_EMAIL_DOMAINS` لو عايز تقصره على الجامعة.
- **الشهادة** بتتحسب في المتصفح من تقدّم الطالب وبتتعرض للطباعة؛ مش وثيقة موثّقة من السيرفر.
