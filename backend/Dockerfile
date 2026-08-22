FROM python:3.12-slim AS runtime

ARG HEALTHSCOPE_RELEASE_SHA=development

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HEALTHSCOPE_RELEASE_SHA=${HEALTHSCOPE_RELEASE_SHA}

WORKDIR /app

RUN addgroup --system healthscope && adduser --system --ingroup healthscope healthscope

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

USER healthscope
EXPOSE 8000

CMD ["uvicorn", "healthscope.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
