FROM python:3.12-slim

# System deps (needed for some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create persistent directories (will be mounted as volumes)
RUN mkdir -p trades data_cache backtest_results charts

# Dashboard port
EXPOSE 5000

# Single worker to keep _bot_process state in one process
CMD ["gunicorn", "--workers=1", "--bind=0.0.0.0:5000", "--timeout=180", "--access-logfile=-", "app:app"]
