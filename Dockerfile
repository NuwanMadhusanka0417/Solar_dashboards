# One image that serves the API + built dashboard and can run process_data.py.
# Data lives in a volume mounted at /app/data; run download/process as scheduled jobs.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
ENV PVDASH_HOST=0.0.0.0 PVDASH_PORT=8000
EXPOSE 8000
WORKDIR /app/backend
CMD ["python", "api_server.py"]
