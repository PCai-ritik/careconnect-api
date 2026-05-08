# CareConnect API — Implementation Plan

## Infrastructure (✅ Done)
- PostgreSQL connection pool with RLS session variable reset on checkout
- `pool_size=20`, `max_overflow=30`, `pool_pre_ping=True`
- JWT auth (access/refresh tokens) + role-based guards
- RLS policies on all 12 tables

## Auth & Patient CRUD (✅ Done)
- `POST /auth/register/doctor` — creates User + Doctor stub
- `POST /auth/register/caregiver` — creates User + Caregiver profile
- `POST /auth/login` — JWT access token + refresh cookie
- `GET /api/me` — identity check
- `GET /doctors/profile`, `PUT /doctors/onboarding`, `PUT /doctors/availability`
- `POST /patients`, `GET /patients`

---

## Phase 1 — Clinical DB Routes

### Module 1: Appointments
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/appointments` | Book a consultation |
| `GET` | `/appointments` | List appointments (RLS-filtered) |
| `GET` | `/appointments/{id}` | Get single appointment |
| `PATCH` | `/appointments/{id}/status` | Update status (PENDING → CONFIRMED → COMPLETED) |

### Module 2: Medical Records & Prescriptions
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/medical-records` | Create record after consultation |
| `GET` | `/patients/{id}/records` | Patient's medical history |
| `GET` | `/medical-records/{id}` | Single record detail |
| `POST` | `/medical-records/{id}/prescriptions` | Add medications to a record |

---

## Phase 2 — External API Integrations

### Video Sessions
| Method | Endpoint | Integration |
|---|---|---|
| `POST` | `/appointments/{id}/start-session` | LiveKit/Agora — real room + tokens |
| `GET` | `/appointments/{id}/join` | Return join tokens |

### Transactions
| Method | Endpoint | Integration |
|---|---|---|
| `POST` | `/transactions` | Razorpay/Stripe order creation |
| `GET` | `/doctors/earnings` | Earnings history |
| `POST` | `/payments/webhook` | Payment confirmation webhook |

### Post-Call Summaries
| Method | Endpoint | Integration |
|---|---|---|
| `POST` | `/appointments/{id}/summary` | OpenAI/Gemini AI summarization |
| `GET` | `/appointments/{id}/summary` | Retrieve summary |

---

## Phase 3 — Frontend Wiring
- Replace all mock data imports in mobile + web apps
- Wire service layer (`services/api.ts`, `lib/api.ts`) to real API endpoints
- Spec-driven UI corrections (rename "Patient Registration" → "Caregiver Registration", add `whatsapp_number` field)
