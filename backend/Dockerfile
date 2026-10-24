FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario sin privilegios: el contenedor no corre como root
RUN useradd --create-home --uid 1000 app && chown -R app:app /app \
    && mkdir -p /data/documents && chown app:app /data/documents
USER app

EXPOSE 5000
# Hilos (gthread): una respuesta del copiloto en streaming ocupa un hilo, no un proceso entero.
# 2 procesos x 8 hilos = 16 peticiones a la vez. El timeout cubre el streaming más largo.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--worker-class", "gthread", "--threads", "8", \
     "--timeout", "300", "wsgi:app"]
