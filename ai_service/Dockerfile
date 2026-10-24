FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_CACHE_DIR=/models

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modelo de embeddings local (~220 MB) descargado al construir la imagen, para que
# el servicio no dependa de internet al arrancar (ADR-011). Si la descarga falla,
# la imagen se construye igual y el modelo se descarga en el primer uso.
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN useradd --create-home --uid 1000 app && mkdir -p /models \
    && (python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${EMBEDDING_MODEL}', cache_dir='/models')" \
        || echo "AVISO: no se ha podido descargar el modelo de embeddings; se intentará al arrancar") \
    && chown -R app:app /models

COPY app ./app
RUN chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
