FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# All Python packages live in a virtual environment, also inside the image.
RUN python -m venv /opt/venv

COPY pyproject.toml ./
RUN mkdir -p app seed && touch app/__init__.py seed/__init__.py \
    && pip install --upgrade pip \
    && pip install -e ".[dev]"

COPY . .

RUN useradd --create-home --uid 1000 careledger && chown -R careledger /app
USER careledger

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
