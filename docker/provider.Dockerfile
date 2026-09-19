FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && apt-get update && apt-get install -y --no-install-recommends git ripgrep ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @openai/codex@0.154.0 @anthropic-ai/claude-code@2.1.220 \
    && pip install --no-cache-dir pytest==8.3.5
COPY docker/provider_entry.py /opt/agentscope/provider_entry.py
WORKDIR /workspace
CMD ["sleep", "infinity"]
