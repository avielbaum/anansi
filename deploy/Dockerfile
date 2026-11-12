# Gateway image. Build from the repo root: docker build -f deploy/Dockerfile -t anansi-gateway .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway ./gateway
RUN useradd -r anansi && mkdir /data && chown anansi /data
USER anansi
VOLUME /data
ENV ANANSI_ENV=production
ENV ANANSI_CONFIG=/etc/anansi/config.json
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "gateway.app:make_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
