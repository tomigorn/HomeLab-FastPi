FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev build-essential && rm -rf /var/lib/apt/lists/*
COPY main.py config.yml /app/
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx python-wakeonlan pyyaml
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--loop", "asyncio"]
