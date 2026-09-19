FROM docker:27-cli AS docker-cli
FROM python:3.12-slim
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /app
COPY backend /app/backend
COPY benchmarks /app/benchmarks
RUN pip install --no-cache-dir ./backend
ENV PYTHONPATH=/app/backend BENCHMARK_ROOT=/app/benchmarks ARTIFACT_ROOT=/app/artifacts
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
