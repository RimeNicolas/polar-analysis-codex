FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MCP_AUTH_MODE=auth0 MCP_HOST=0.0.0.0
CMD ["sh", "-c", "python polar_mcp_server.py --transport streamable-http --host 0.0.0.0 --port ${PORT:-8000}"]
