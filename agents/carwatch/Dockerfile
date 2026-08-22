FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY config/ ./config/

RUN uv pip install --system --no-cache .

ENTRYPOINT ["carwatch"]
CMD ["--help"]
