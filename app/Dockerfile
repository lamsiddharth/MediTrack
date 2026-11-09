# Single-stage: the whole application is Python and server-rendered HTML, so
# there is no frontend toolchain and nothing to compile. The image builds in
# well under a minute even on a 1 GiB instance.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /srv

# Dependencies first, so a change to application code reuses this layer.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      "fastapi==0.120.1" \
      "uvicorn==0.38.0" \
      "jinja2==3.1.6" \
      "sqlalchemy==2.0.44" \
      "python-multipart==0.0.20" \
      "itsdangerous==2.2.0" \
      "bcrypt==5.0.0" \
      "boto3==1.40.49" \
      "psycopg[binary]==3.2.12"

COPY meditrack ./meditrack

# Run as a non-root user. The data directory is owned by it so SQLite can
# write there when the volume is mounted.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /data /srv
USER app

VOLUME ["/data"]
EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9000/healthz', timeout=4).status==200 else 1)"

CMD ["uvicorn", "meditrack.main:app", "--host", "0.0.0.0", "--port", "9000", "--proxy-headers"]
