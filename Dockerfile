# Offizielles, schlankes Python-Image als Basis
FROM python:3.11-slim

# Arbeitsverzeichnis im Container festlegen
WORKDIR /app

# Requirements kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Den restlichen Code ins Image kopieren
COPY . .

# Wichtige Ordner vorab erstellen, damit es keine Rechte-Probleme gibt
RUN mkdir -p uploads/temp data frontend

# Port nach außen freigeben
EXPOSE 8000

# Startbefehl für den FastAPI Server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]