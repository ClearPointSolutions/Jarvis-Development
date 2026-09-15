FROM mcr.microsoft.com/playwright:v1.63.0-noble
# Browser and application share one container/loopback namespace. Runtime uses
# Docker network=none, so host, LAN, metadata, and public egress stay unavailable.
USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 \
    && ln -s /usr/bin/python3 /usr/local/bin/python \
    && groupadd --gid 10001 verifier \
    && useradd --uid 10001 --gid 10001 --no-create-home verifier \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/python"]
