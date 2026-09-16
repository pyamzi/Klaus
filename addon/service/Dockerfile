FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY klausplus ./klausplus
RUN pip install --no-cache-dir .
ENV DATABASE_PATH=/data/klausplus.sqlite3
EXPOSE 8080
CMD ["uvicorn", "klausplus.main:app", "--host", "0.0.0.0", "--port", "8080"]
