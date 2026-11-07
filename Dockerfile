FROM python:3.12-slim

# ffmpeg is only for the on-demand ICON1.PMF -> MP4 job in the UI. Build
# with --build-arg WITH_FFMPEG=0 for a small image without it.
ARG WITH_FFMPEG=1
RUN if [ "$WITH_FFMPEG" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY umdlibrary ./umdlibrary
COPY tests ./tests
COPY pytest.ini .

ENV PYTHONUNBUFFERED=1 \
    UMD_DATA_DIR=/data \
    UMD_LIBRARY_DIR=/isos \
    UMD_OUTPUT_DIR=/out \
    UMD_HTTP_PORT=8080

EXPOSE 8080
VOLUME ["/data", "/out"]
CMD ["python", "-m", "umdlibrary"]
