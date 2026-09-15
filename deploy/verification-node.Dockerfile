FROM node:20.20.2-bookworm-slim
# Credential-free Node build/unit profile. The Python binary runs only the
# broker-owned source bootstrap; project commands remain an argv allowlist.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 \
    && ln -s /usr/bin/python3 /usr/local/bin/python \
    && groupadd --gid 10001 verifier \
    && useradd --uid 10001 --gid 10001 --no-create-home verifier \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/python"]
