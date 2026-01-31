FROM python:3.11-slim

WORKDIR /app

COPY services/datapipeline_manager/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/datapipeline_manager /app
COPY services/schema_migrator/schema_migrator /app/schema_migrator

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["streamlit", "run", "Dashboard.py", "--server.port=8081", "--server.address=0.0.0.0"]
