# CareConnect API

The **CareConnect API** is the core backend engine that powers both the administrative web platform and the multi-tenant mobile applications. Built entirely in Python using the high-performance FastAPI framework, it handles secure JWT authentication, multi-tenant data partitioning via PostgreSQL, and real-time telehealth room generation via the LiveKit server API. Additionally, it features a robust asynchronous AI pipeline that utilizes Deepgram and Sarvam to instantly transcribe and summarize medical consultations into bilingual clinical notes the moment a call ends.

**Tech Stack**: Python 3.11+, FastAPI, SQLAlchemy, Alembic (Migrations), PostgreSQL, LiveKit SDK, Boto3 (AWS S3 Storage), and LangChain/Groq for AI pipelines.

## Quick Start & Development

To run the backend API server locally, you must first start the database and apply the schema migrations:

1. **Start the PostgreSQL Database:**
   Ensure Docker is running, then spin up the local database container in the background:
   ```bash
   docker compose up -d
   ```

2. **Activate the virtual environment & install dependencies:**
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Run Database Migrations (Mandatory for fresh setups):**
   Since the Postgres container starts completely empty, you must run Alembic to generate all the database tables:
   ```bash
   alembic upgrade head
   ```

4. **Start the Uvicorn development server:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

The interactive API documentation will be available at `http://localhost:8000/docs`.

## Ngrok Setup

Because your mobile phone cannot reach your PCs `localhost` directly, you must tunnel your local port to the public internet using **ngrok**:

1. Run the ngrok HTTP tunnel on port 8000:
   ```bash
   ngrok http 8000
   ```
2. Copy the forwarding URL (e.g., `https://<random-id>.ngrok-free.app`).
3. Finally, update the `EXPO_PUBLIC_API_URL` inside the mobile app's `.env.local` to point to this ngrok URL so your phone can reach the API.
