# Coinmaker Trading Bot - Dockerfile
# Multi-stage build for optimized image size

# Build stage
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Rome

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash botuser && \
    chown -R botuser:botuser /app

# Create necessary directories
RUN mkdir -p logs data && \
    chown -R botuser:botuser logs data

# Copy application code
COPY --chown=botuser:botuser src/ ./src/
COPY --chown=botuser:botuser config.py .
COPY --chown=botuser:botuser test_connection.py .

# Copy scripts
COPY --chown=botuser:botuser main.py .
COPY --chown=botuser:botuser scripts/ ./scripts/

# Switch to non-root user
USER botuser

# Health check
HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command
CMD ["python", "main.py"]
