FROM python:3.13-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY build_db.py .
COPY data/vehicles.csv.bz2 data/vehicles.csv.bz2
# Gera o SQLite durante o build (evita versionar 286 MB de banco)
RUN python build_db.py && rm data/vehicles.csv.bz2
COPY app app
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
