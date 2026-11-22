FROM ghcr.io/astral-sh/uv:0.9.18 AS uv
FROM python:3.13-slim

COPY --from=uv /uv /uvx /usr/local/bin/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    ARTIFACT_DIR=/tmp/sap-artifacts \
    MCP_ATLASSIAN_EXECUTABLE=/opt/atlassian/bin/mcp-atlassian \
    HOME=/home/app

WORKDIR /app
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt \
    && uv venv /opt/atlassian \
    && uv pip install --no-cache --python /opt/atlassian/bin/python mcp-atlassian==0.24.6 \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /tmp/sap-artifacts \
    && chown app:app /tmp/sap-artifacts

COPY app.py demo_backend.py prompts.py ./
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/_stcore/health', timeout=3)"
CMD ["sh", "-c", "exec streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-8080} --server.headless=true --browser.gatherUsageStats=false --server.enableCORS=true --server.enableXsrfProtection=true"]