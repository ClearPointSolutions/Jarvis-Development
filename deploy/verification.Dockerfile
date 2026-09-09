FROM python:3.12.14-slim-bookworm
# Credential-free initial Python profile; no Core application or SSH/Git client.
COPY deploy/verification-requirements.lock /tmp/verification-requirements.lock
RUN python -m pip install --no-cache-dir -r /tmp/verification-requirements.lock \
    && rm /tmp/verification-requirements.lock \
    && groupadd --gid 10001 verifier \
    && useradd --uid 10001 --gid 10001 --no-create-home verifier
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/python"]
