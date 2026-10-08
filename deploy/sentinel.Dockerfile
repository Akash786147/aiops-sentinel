# AIOps Sentinel control plane.
# Runs as root because it drives the Docker socket to build and run the monitored services.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SENTINEL_RUNTIME=docker SENTINEL_HOME=/srv/sentinel SENTINEL_NETWORK=sentinel

WORKDIR /opt/sentinel
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN git config --global --add safe.directory '*'

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"
CMD ["python", "-m", "controlplane", "--host", "0.0.0.0", "--port", "8000"]
