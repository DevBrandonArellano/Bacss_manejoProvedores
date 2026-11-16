FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Se instalan también las dependencias de pruebas para poder ejecutar pytest dentro del contenedor.
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY app ./app
COPY tests ./tests
COPY pytest.ini ./

# La app no corre como root. /bd es el volumen de la base de datos y /respaldos la carpeta montada del equipo.
RUN useradd --create-home --uid 10001 proveedores \
    && mkdir -p /bd /respaldos \
    && chown -R proveedores:proveedores /bd /respaldos

USER proveedores

ENV RUTA_BD=/bd/proveedores.db \
    RUTA_RESPALDOS=/respaldos \
    RUTA_EXCEL=/app/datos/proveedores.xlsx

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=3)"

# Un solo proceso: la tarea diaria (respaldo y alarmas) vive dentro de la app y no debe duplicarse.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
