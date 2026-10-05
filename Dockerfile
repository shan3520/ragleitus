FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/ragforge

# Install dependencies first so code changes don't reinstall them. The code
# itself runs from this directory (uvicorn and alembic put it on sys.path).
COPY pyproject.toml README.md ./
# The optional evaluators (Ragas, DeepEval) are included.
RUN mkdir app && pip install ".[ragas,deepeval]" && rmdir app

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN useradd --create-home --uid 1000 ragforge \
    && mkdir -p /data/models \
    && chown -R ragforge /data \
    && chmod +x /usr/local/bin/entrypoint.sh

USER ragforge
# The embedding model is downloaded here on first use; mount a volume to keep it.
ENV EMBEDDING_CACHE_DIR=/data/models
EXPOSE 8000

ENTRYPOINT ["entrypoint.sh"]
# --no-proxy-headers: uvicorn would otherwise rewrite the client address from
# X-Forwarded-For before the app sees it. The app decides which proxies to
# believe itself (TRUSTED_PROXIES).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
