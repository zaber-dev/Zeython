# syntax=docker/dockerfile:1
#
# Multi-stage build: the `builder` stage installs dependencies into a venv;
# the final stage copies just that venv plus the app source, so the shipped
# image doesn't carry pip's build cache or dev tooling. See docs/docker.md.

FROM python:3.12-slim AS builder

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# A local wheel directory pip should also check, in addition to the default
# index -- for a private index/vendored dependency not published there.
# Unused (and harmless to leave unset) once every dependency, including
# zeython itself, is on a real index.
ARG PIP_FIND_LINKS=
COPY . .
RUN pip install --no-cache-dir ${PIP_FIND_LINKS:+--find-links "$PIP_FIND_LINKS"} .


FROM python:3.12-slim

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY . .
RUN chown -R appuser:appuser /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request as u,sys; sys.exit(0 if u.urlopen('http://localhost:8000/up').status==200 else 1)"

# Migrate, then serve. A real deployment with more than one replica usually
# splits the migration into its own one-shot job so N containers starting
# together don't all race to run it -- this is the simplest thing that
# works for a single container.
CMD ["sh", "-c", "python -m alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
