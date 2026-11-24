FROM node:24-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ERROR_DODGE_STATIC_DIR=/opt/error-dodge/web
WORKDIR /opt/error-dodge/backend
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && useradd --system --uid 10001 --create-home error-dodge \
    && mkdir -p /opt/error-dodge/.data \
    && chown error-dodge /opt/error-dodge/.data
COPY backend/ ./
COPY --from=frontend /src/dist /opt/error-dodge/web
USER error-dodge
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
