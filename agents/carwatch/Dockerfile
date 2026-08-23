FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY config/ ./config/

RUN uv pip install --system --no-cache .

# `carwatch` is installed non-editably into site-packages, so cli.py cannot
# infer config/ and migrations/ from its own __file__ — point it at WORKDIR,
# where both directories were COPYed above.
ENV CARWATCH_ROOT=/app

ENTRYPOINT ["carwatch"]
CMD ["--help"]
