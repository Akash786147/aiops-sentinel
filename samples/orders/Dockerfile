# Sample service monitored by AIOps Sentinel.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SENTINEL_LOG_DIR=/app/logs
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 app && mkdir -p /app/logs && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=2s --start-period=5s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "orders.app:app", "--host", "0.0.0.0", "--port", "8000"]
