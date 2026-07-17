FROM python:3.12-slim

WORKDIR /app

# System deps some of your libs may need (audio/video processing libs often need these)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
