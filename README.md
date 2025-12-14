# FNP SDN Backend API

Backend API สำหรับระบบจัดการ Software-Defined Network (SDN) ที่พัฒนาด้วย FastAPI, Prisma และ PostgreSQL

## 🚀 เทคโนโลยีที่ใช้

- **FastAPI** - Modern Python web framework
- **Prisma** - Next-generation ORM
- **PostgreSQL** - Relational database
- **Docker** - Containerization
- **JWT** - Authentication
- **TOTP** - Two-Factor Authentication
- **Bcrypt** - Password hashing
- **Resend** - Email service

## 📦 ความต้องการของระบบ

- Python 3.12.2
- Docker & Docker Compose
- supabase (postgreSQL)
- FastAPI 
- Prisma ORM

## 🛠️ การติดตั้งและเริ่มต้นใช้งาน

### 1. Clone Repository

```bash
git clone https://github.com/FNP-SND-AUTOMATE-Network/SDN-Backend.git
cd SDN-Backend
```

### 2. ตั้งค่า Environment Variables

สร้างไฟล์ `.env` ใน directory `backend/`:

### 3. ติดตั้ง Dependencies

#### วิธีที่ 1: ใช้ Docker (แนะนำ)

```bash
cd backend
docker-compose up -d
```

#### วิธีที่ 2: ติดตั้งแบบ Local

```bash
cd backend

# สร้าง virtual environment
python -m venv .venv
source .venv\Scripts\activate  # Windows

# ติดตั้ง dependencies
pip install -r requirements.txt
```

### 4. เริ่มต้น Server

#### Docker:

```bash
docker-compose up
```

Server จะรันที่: `http://localhost:8000`

API Documentation (Swagger): `http://localhost:8000/docs`

## 📁 โครงสร้างโปรเจค

```
backend/
├── app/
│   ├── api/              # API endpoints
│   │   ├── auth.py       # Authentication (Login, Register, TOTP)
│   │   ├── users.py      # User management
│   │   ├── device_networks.py
│   │   ├── device_credentials.py
│   │   ├── tags.py
│   │   └── ...
│   ├── models/           # Pydantic models
│   │   ├── auth.py
│   │   ├── user.py
│   │   └── ...
│   ├── services/         # Business logic
│   │   ├── user_service.py
│   │   ├── totp_service.py
│   │   ├── otp_service.py
│   │   └── ...
│   ├── core/             # Core configurations
│   │   └── constants.py
│   ├── database.py       # Database connection
│   └── main.py           # Application entry point
├── prisma/
│   └── schema.prisma     # Database schema
├── requirements.txt      # Python dependencies
├── Dockerfile
└── docker-compose.yml
```

## 🔌 API Endpoints

``` localhost:8000/docs```

### Database Migrations

```bash
# สร้าง migration ใหม่
cd backend
prisma migrate dev --name migration_name

# Apply migrations (production)
prisma migrate deploy

# Reset database (ระวัง: ลบข้อมูลทั้งหมด!)
prisma migrate reset
```

## 💻 Development

### การรัน Tests

```bash
# ติดตั้ง pytest
pip install pytest pytest-asyncio

# รัน tests
pytest
```

### Code Style

โปรเจคใช้:

- **Type hints** - ระบุ type ให้ชัดเจน
- **Pydantic models** - Validation
- **Async/await** - Asynchronous programming
- **Logging** - ใช้ `logging` module แทน `print`

### การเพิ่ม Endpoint ใหม่

1. สร้าง Pydantic models ใน `app/models/`
2. สร้าง service logic ใน `app/services/`
3. สร้าง API endpoint ใน `app/api/`
4. Register router ใน `app/main.py`

## 🐛 Troubleshooting

### ปัญหาที่พบบ่อย

#### 1. `ModuleNotFoundError: No module named 'pyotp'`

**แก้ไข:**

```bash
# ถ้าใช้ Docker
docker exec -it backend-backend-1 pip install pyotp
docker restart backend-backend-1

# หรือ rebuild
docker-compose build backend
docker-compose up -d
```

#### 2. Database connection error

**ตรวจสอบ:**

- `.env` มี `DATABASE_URL` ถูกต้องหรือไม่
- PostgreSQL รันอยู่หรือไม่
- Network connection

#### 3. Prisma Client ไม่ generate

**แก้ไข:**

```bash
cd backend
prisma generate
```

#### 4. CORS errors

**แก้ไข:** ตรวจสอบ `app/main.py` ว่ามี CORS middleware และ allowed origins ถูกต้อง

### Debug Mode

เปิด debug logging:

```python
# app/main.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Docker Logs

```bash
# ดู logs
docker logs -f backend-backend-1

# ดู logs แบบ real-time
docker-compose logs -f backend
```