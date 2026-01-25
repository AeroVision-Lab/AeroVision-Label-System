FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IMAGES_DIR=/app/images \
    LABELED_DIR=/app/labeled \
    DATABASE_PATH=/app/data/labels.db \
    AI_CONFIG_PATH=/app/config.yaml \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY database.py .
COPY data/ ./data/
COPY config.yaml ./config.yaml
COPY ai_service/ ./ai_service/
COPY /frontend/dist/ ./frontend/dist/

RUN mkdir -p /app/images /app/labeled /app/data /app/models

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2", "--timeout", "300", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
