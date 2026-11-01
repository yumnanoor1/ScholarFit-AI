FROM python:3.11-slim

WORKDIR /app

# System dependencies install karo (psycopg2 ke liye zaroori)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Requirements copy aur install karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki code copy karo
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]