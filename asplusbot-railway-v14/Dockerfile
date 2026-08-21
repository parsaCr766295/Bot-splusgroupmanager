FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir ".[soroush]" \
    && python -c "import soropy; print('soropy dependency installed')"

COPY railway_entrypoint.py ./

CMD ["python", "railway_entrypoint.py"]
