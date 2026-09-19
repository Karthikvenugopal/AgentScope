FROM python:3.12-slim-bookworm

ARG RUNNER_UID=10001
ARG RUNNER_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --gid "${RUNNER_GID}" runner \
    && useradd --uid "${RUNNER_UID}" --gid runner --create-home runner \
    && apt-get update \
    && apt-get install --yes --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir "pytest==8.3.5"

WORKDIR /workspace
USER runner

CMD ["sleep", "infinity"]
