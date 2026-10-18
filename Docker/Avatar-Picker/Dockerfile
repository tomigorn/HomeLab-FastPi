FROM python:3.13-alpine
RUN adduser -D -u 1000 picker
WORKDIR /app
COPY app/ /app/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]
