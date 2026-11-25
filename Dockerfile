# --- build the React frontend
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# --- Flask API serving the built frontend
FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend .
COPY --from=web /web/dist /app/frontend/dist
ENV PORT=8080
EXPOSE 8080
# gthread workers: many concurrent users per worker, since requests mostly wait on I/O
CMD gunicorn -w 2 -k gthread --threads 32 -b 0.0.0.0:$PORT wsgi:app
