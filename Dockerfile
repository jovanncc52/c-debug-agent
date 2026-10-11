# Sandbox u kojem agent kompajlira i pokreće kod.
# Build: docker build -t c-agent-sandbox .
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev make valgrind gdb \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work
