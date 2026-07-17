# Vocalize Admin Dashboard

מערכת ניהול מרכזית לבוט Vocalize - ממשק Web מודרני לניהול משתמשים, הכנסות, ומנוע ה-AI.

## 🎯 תכונות

- **📊 סקירה כללית** - סטטיסטיקות בזמן אמת של משתמשים, תמלולים והכנסות
- **👥 ניהול משתמשים** - טבלת משתמשים מלאה עם אפשרות חיפוש וסינון
- **💰 מעקב הכנסות** - דוחות הכנסות מפורטים ותשלומים
- **🤖 ניהול AI** - עריכת System Prompt ישירות מהדשבורד
- **📝 לוגים חיים** - צפייה בפעולות הבוט בזמן אמת (WebSocket)

## 🚀 התקנה והרצה

### דרישות מקדימות

```bash
# Python 3.10+
pip install -r requirements.txt
```

### הרצת השרת

```bash
cd admin_dashboard/backend
python server.py
```

השרת יפעל בכתובת: `http://localhost:8080`

### קביעת קוד גישה

```bash
export ADMIN_DASHBOARD_TOKEN="your-secret-token"
```

או הזן את הקוד הסודי בממשק ההתחברות.

## 🔌 API Endpoints

### אימות
- `POST /api/login` - התחברות עם קוד סודי

### סטטיסטיקות
- `GET /api/dashboard/stats` - סטטיסטיקות כלליות
- `GET /api/revenue` - נתוני הכנסות

### משתמשים
- `GET /api/users` - רשימת משתמשים (עם pagination)
- `GET /api/users/{id}` - פרטי משתמש

### תשלומים
- `GET /api/revenue/payments` - כל התשלומים

### AI
- `GET /api/ai/prompt` - קרא System Prompt
- `POST /api/ai/prompt` - עדכן (בזיכרון)
- `POST /api/ai/prompt/save` - שמור לקובץ

### לוגים
- `GET /api/logs` - לוגים (REST)
- `WS /ws/logs` - לוגים בזמן אמת (WebSocket)

## 📁 מבנה התיקיות

```
admin_dashboard/
├── backend/
│   └── server.py          # שרת FastAPI
├── frontend/
│   └── index.html         # ממשק משתמש
└── README.md
```

## 🎨 טכנולוגיות

- **Backend**: FastAPI, SQLAlchemy (Async)
- **Frontend**: HTML5, Tailwind CSS, JavaScript
- **Real-time**: WebSocket
- **Database**: SQLite (משותף עם VocalizeBot)

## 🔐 אבטחה

- אימות באמצעות Token
- CORS מוגדר לכתובות מותרות
- גישה ל-API מוגנת

---

נוצר על ידי OpenHands | Tal HaTil Empire
