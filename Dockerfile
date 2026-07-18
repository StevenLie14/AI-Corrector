FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

# Jalan sebagai non-root (best practice keamanan container).
RUN useradd --create-home appuser && chown -R appuser /code
USER appuser

EXPOSE 3100

CMD ["gunicorn", "main:app", "--config", "gunicorn.conf.py"]
