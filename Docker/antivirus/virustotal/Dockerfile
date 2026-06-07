FROM python:3.12-alpine

RUN pip install --no-cache-dir vt-py

COPY scan.py /scan.py

CMD ["tail", "-f", "/dev/null"]
