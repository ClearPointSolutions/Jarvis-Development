FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 jarvis && useradd --uid 10001 --gid 10001 --create-home jarvis
WORKDIR /app
COPY requirements.lock pyproject.toml README.md ./
RUN sed '/^-e \.$/d' requirements.lock > /tmp/dependencies.lock \
    && python -m pip install --no-cache-dir -r /tmp/dependencies.lock
COPY api ./api
COPY orchestrator ./orchestrator
COPY packages ./packages
COPY scripts ./scripts
COPY alembic.ini ./
RUN python -m pip install --no-deps --no-build-isolation .
RUN mkdir -p /var/lib/jarvis-v1/artifacts /var/lib/jarvis-v1/source \
    && chown -R 10001:10001 /var/lib/jarvis-v1
USER 10001:10001
CMD ["python", "-m", "jarvis_api.main"]
