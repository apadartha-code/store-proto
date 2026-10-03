FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

ENV STORAGE_PATH=/data
ENV LISTEN_PORT=5000
ENV FRAGMENT_SIZE_KB=64
ENV MAX_UPLOAD_KB=1000
ENV LOG_SYSLOG=false

VOLUME ["/data"]
EXPOSE 5000
# Mount host syslog socket when LOG_SYSLOG=true, e.g. -v /dev/log:/dev/log

CMD ["python", "run.py"]
