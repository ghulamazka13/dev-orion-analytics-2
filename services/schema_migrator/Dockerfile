FROM python:3.11-slim

WORKDIR /app

COPY services/schema_migrator/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/schema_migrator/schema_migrator /app/schema_migrator

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "schema_migrator"]
