FROM python:3.12-slim
LABEL org.opencontainers.image.source=https://github.com/chriopter/pspdx-shelf
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shelf ./shelf
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "shelf"]
