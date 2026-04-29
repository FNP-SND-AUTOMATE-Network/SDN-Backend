# FNP SDN Backend API

Backend API for the Software-Defined Network (SDN) management system, developed with FastAPI, Prisma, and PostgreSQL.

## 🚀 Technologies Used

- **FastAPI** - Modern Python web framework
- **Prisma** - Next-generation ORM
- **PostgreSQL** - Relational database
- **Docker** - Containerization
- **JWT** - Authentication
- **TOTP** - Two-Factor Authentication
- **Bcrypt** - Password hashing
- **Resend** - Email service

## 📦 System Requirements

- Python 3.12.2
- Docker & Docker Compose
- Supabase (PostgreSQL)
- FastAPI 
- Prisma ORM

## 🛠️ Installation and Setup

### 1. Clone Repository

```bash
git clone https://github.com/FNP-SND-AUTOMATE-Network/SDN-Backend.git
cd SDN-Backend
```

### 2. Configure Environment Variables

Create a `.env` file in the `backend/` directory.

### 3. Install Dependencies

#### Method 1: Using Docker (Recommended)

```bash
cd backend
docker-compose up -d
```

#### Method 2: Local Installation

```bash
cd backend

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# source .venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### 4. Start the Server

#### Docker:

```bash
docker-compose up
```

The server will run at: `http://localhost:8000`

API Documentation (Swagger): `http://localhost:8000/docs`

## 📁 Project Structure

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
# Create a new migration
cd backend
prisma migrate dev --name migration_name

# Apply migrations (production)
prisma migrate deploy

# Reset database (Warning: Deletes all data!)
prisma migrate reset
```

## 💻 Development

### Running Tests

```bash
# Install pytest
pip install pytest pytest-asyncio

# Run tests
pytest
```

### Code Style

This project utilizes:

- **Type hints** - Clear type definitions
- **Pydantic models** - Data validation
- **Async/await** - Asynchronous programming
- **Logging** - Uses the `logging` module instead of `print`

### Adding a New Endpoint

1. Create Pydantic models in `app/models/`
2. Implement service logic in `app/services/`
3. Create the API endpoint in `app/api/`
4. Register the router in `app/main.py`

## 🐛 Troubleshooting

### Common Issues

#### 1. `ModuleNotFoundError: No module named 'pyotp'`

**Fix:**

```bash
# If using Docker
docker exec -it backend-backend-1 pip install pyotp
docker restart backend-backend-1

# Or rebuild
docker-compose build backend
docker-compose up -d
```

#### 2. Database connection error

**Check:**

- Is `DATABASE_URL` correct in the `.env` file?
- Is PostgreSQL running?
- Network connection

#### 3. Prisma Client not generating

**Fix:**

```bash
cd backend
prisma generate
```

#### 4. CORS errors

**Fix:** Verify `app/main.py` to ensure CORS middleware and allowed origins are correctly configured.

### Debug Mode

Enable debug logging:

```python
# app/main.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Docker Logs

```bash
# View logs
docker logs -f backend-backend-1

# View logs in real-time
docker-compose logs -f backend
```