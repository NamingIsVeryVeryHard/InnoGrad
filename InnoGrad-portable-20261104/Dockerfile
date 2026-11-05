FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 PYTHONPATH=/app/backend
WORKDIR /app/backend
COPY backend/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements.lock.txt
COPY backend /app/backend
COPY frontend /app/frontend
COPY agent-skills /app/agent-skills
COPY deploy /app/deploy
RUN useradd --uid 10001 --create-home innograd && mkdir -p /data/files /data/agent-locks && chown -R innograd:innograd /data /app
USER innograd
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
