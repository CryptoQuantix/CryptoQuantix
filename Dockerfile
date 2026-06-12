# Coinmaker Quant — Dockerfile (multi-arch: amd64 + arm64/Raspberry Pi)
# Stessa immagine per i 3 servizi (bot, dashboard, collector): cambia solo
# il command nel docker-compose.yml.

# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# gcc/g++ servono solo se manca una wheel aarch64 e pip compila da sorgente
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# TZ Europe/Rome: il reset giornaliero del kill switch usa date.today()
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Rome \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN useradd -m -u 1000 -s /bin/bash botuser && \
    chown -R botuser:botuser /app

# data/ e logs/ sono BIND MOUNT dal host (persistenza fuori dal container)
RUN mkdir -p logs data && \
    chown -R botuser:botuser logs data

COPY --chown=botuser:botuser src/ ./src/
COPY --chown=botuser:botuser config.py .
COPY --chown=botuser:botuser main.py .
COPY --chown=botuser:botuser scripts/ ./scripts/

USER botuser

# Porta dashboard Streamlit (esposta solo su localhost dal compose;
# l'accesso esterno passa da Cloudflare Tunnel + Access)
EXPOSE 8501

# Default: bot async. Gli altri servizi sovrascrivono il command.
CMD ["python", "-m", "src.async_trading_bot"]
