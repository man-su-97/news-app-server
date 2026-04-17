# 🏗️ Auth Service Architecture

## 📌 Overview

The **Auth Service** is a standalone microservice responsible for handling authentication and authorization across the system.

It supports multiple authentication strategies:

- **Local Authentication** (Email + Password)
- **Social Authentication** (Google OAuth 2.0 SSO)

The service is built using an **async-first architecture** with FastAPI and integrates with PostgreSQL using SQLAlchemy ORM.

---

## 🎯 Objectives

- Provide secure and scalable authentication
- Support multiple login strategies
- Enable stateless authorization using JWT
- Maintain extensibility for future providers and RBAC

---

## 🧱 Tech Stack

| Layer | Technology |
|------|----------|
| Framework | FastAPI |
| ORM | SQLAlchemy (Async 2.0) |
| Database | PostgreSQL |
| Migration | Alembic |
| Authentication | JWT (python-jose) |
| OAuth | Authlib |
| Password Hashing | Passlib + bcrypt |
| Config Management | Pydantic Settings |
| Server | Uvicorn |


---

## 🔄 Authentication Strategies

The system supports **two independent authentication methods**:

---

### 1️⃣ Local Authentication (Email + Password)

#### Registration Flow

User → Register (email + password)  
→ Password is hashed and stored  
→ OTP generated and sent to email  
→ User verifies OTP  
→ Account marked as verified  

#### Login Flow

User → Login (email + password)  
→ Validate credentials  
→ Ensure user is verified  
→ Generate JWT Access Token  
→ Generate Refresh Token  
→ Return tokens  

> OTP is used only for **account verification**, not for login.

---

### 2️⃣ Social Authentication (Google SSO)

User → `/auth/oauth/google/login`  
→ Redirect to Google OAuth  
→ User authenticates  
→ Callback receives user info  

System:
→ Check if user exists  
→ If exists → login  
→ If not → create user  

→ Generate JWT Access Token  
→ Generate Refresh Token  
→ Return tokens  

---

## 🔐 Token Strategy

### Access Token

- Short-lived (e.g., 60 minutes)
- Used for API authentication
- Stateless (not stored in DB)

### Refresh Token

- Long-lived (e.g., 7 days)
- Stored in database
- Used to issue new access tokens
- Supports revocation and logout

---

## 🧠 Database Design

### Users Table

| Field | Description |
|------|------------|
| id | UUID (Primary Key) |
| email | Unique identifier |
| password_hash | Nullable (OAuth users) |
| full_name | User name |
| is_verified | Email verification status |
| provider | local / google |
| provider_id | OAuth provider ID |
| role | User role |
| status | active / disabled |
| created_at | Timestamp |
| updated_at | Timestamp |

---

### OTP Table

| Field | Description |
|------|------------|
| id | Int (Primary Key) |
| user_id | FK → users |
| otp_code | One-time password |
| expires_at | Expiry timestamp |
| is_used | Boolean flag |

---

### Refresh Tokens Table

| Field | Description |
|------|------------|
| id | Int (Primary Key) |
| user_id | FK → users |
| token | Refresh token string |
| expires_at | Expiry |
| is_revoked | Boolean |

---

### Access Logs Table

| Field | Description |
|------|------------|
| id | (Primary Key) |
| user_id | FK |
| ip_address | Client IP |
| user_agent | Device metadata |
| endpoint | API endpoint |
| created_at | Timestamp |

---

## 🧩 Module Structure

```

app/
│
├── api/
│   └── v1/
│       └── auth_router.py
│
├── core/
│   ├── config.py
│   ├── database.py
│   ├── security.py
│   ├── enums.py
│   └── constants.py
│
├── models/
│   ├── base.py
│   ├── mixins.py
│   ├── user.py
│   ├── otp.py
│   ├── refresh_token.py
│   └── access_log.py
│
├── schemas/
│   └── auth_schema.py
│
├── services/
│   ├── auth_service.py
│   ├── otp_service.py
│   └── token_service.py
│
├── oauth/
│   ├── oauth.py
│   └── google.py
│
└── main.py

```

---

## 🔒 Security Design

### Password Security

- Hashed using bcrypt (via Passlib)
- No plain-text storage

### JWT Security

- Signed using secret key (HS256)
- Includes:
  - `sub` (user_id)
  - `email`
  - `role`

### OAuth Security

- Uses `state` parameter for CSRF protection
- Session-based validation using middleware
- OpenID scopes: `openid email profile`

---

## 🔄 API Gateway Integration

- Gateway handles:
  - Request routing
  - JWT validation (future)
- Auth service handles:
  - Token issuance
  - OAuth flows (direct access required)

```

Frontend → Auth Service (OAuth) -> Protected APIs
Frontend → API Gateway → Auth Service (Email + Password) -> Protected APIs

```

---

## ⚠️ Key Design Decisions

### OAuth handled outside API Gateway

- Prevents session mismatch issues
- Ensures proper CSRF state validation

### Refresh Token stored in DB

- Enables logout & revocation
- Improves security control

### Async-first architecture

- High performance and scalability
- Non-blocking DB operations

---
