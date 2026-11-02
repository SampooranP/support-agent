# The agent API (agent/api.py), which starts the MCP server (mcp-server/server.py) itself over stdio.
#   docker build -t support-agent-api .
#   docker run --env-file .env -p 8000:8000 support-agent-api
# Configuration comes from environment variables (see .env.example); no .env file is copied in.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY ingestion/ ingestion/
COPY mcp-server/ mcp-server/
COPY agent/ agent/

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# One worker: conversation locks, rate limits and resume scheduling live in this process's memory.
CMD ["uvicorn", "agent.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
