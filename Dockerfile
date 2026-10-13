FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY crier ./crier
RUN pip install --no-cache-dir '.[webull]' && useradd --uid 10001 --create-home crier && mkdir /app/data && chown -R crier:crier /app
USER crier
EXPOSE 8765
CMD ["python", "-m", "crier", "serve", "--host", "0.0.0.0"]
