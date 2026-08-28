FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/usr/local

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
