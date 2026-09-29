FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sandbox_agent.py .

RUN mkdir -p /workspace
ENV SANDBOX_AGENT_RUNTIME=aca
ENV PYTHONUNBUFFERED=1
WORKDIR /workspace
CMD ["sleep", "infinity"]