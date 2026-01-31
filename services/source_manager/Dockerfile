FROM python:3.11-slim

WORKDIR /app

COPY services/source_manager/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/source_manager/source_manager /app/source_manager
COPY services/schema_migrator/schema_migrator /app/schema_migrator

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "-m", "source_manager"]
