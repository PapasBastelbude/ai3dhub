from fastapi import FastAPI, HTTPException, File, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import anthropic
import os
import shutil
import json
import re
from pathlib import Path

# ---------------------------------------------------------
# 1. Datenbank Setup (SQLite via SQLAlchemy)
# ---------------------------------------------------------
# NEU: Wir packen die DB in den 'data' Ordner für Docker-Volumes
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
SQLALCHEMY_DATABASE_URL = "sqlite:///./data/ai3dhub.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    internal_title = Column(String, index=True)
    public_title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(String, nullable=True)
    material = Column(String, nullable=True)
    hardware = Column(Text, nullable=True)
    category = Column(String, nullable=True, default="Allgemein")
    status = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    cover_image = Column(String, nullable=True)
    files_json = Column(Text, nullable=True, default="[]")

Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------
# 2. FastAPI App Initialisierung & Ordner
# ---------------------------------------------------------
app = FastAPI(title="AI-3D-Hub API")

UPLOAD_DIR = Path("uploads")
TEMP_DIR = UPLOAD_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Uploads für Downloads/Bilder freigeben
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 3. Pydantic Modelle & DB Helper
# ---------------------------------------------------------
class AIGenerationRequest(BaseModel):
    problem: str
    target_audience: str
    features: str
    prompt_template: str

class ProjectCreate(BaseModel):
    internal_title: str
    public_title: str | None = None
    tags: str | None = None
    material: str | None = None
    hardware: str | None = None
    description: str | None = None
    category: str | None = "Allgemein"
    status: str | None = None
    notes: str | None = None
    cover_image: str | None = None
    files_json: str | None = "[]"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Hilfsfunktion: Verschiebt Temp-Dateien in den echten Projektordner
def process_project_files(internal_title: str, files_json_str: str):
    if not files_json_str or files_json_str == "[]":
        return files_json_str

    try:
        files = json.loads(files_json_str)
    except:
        return files_json_str

    # Mache den Projekttitel ordner-tauglich (Sonderzeichen entfernen)
    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', internal_title).strip('_')
    if not safe_title:
        safe_title = "projekt"

    target_dir = UPLOAD_DIR / safe_title
    target_dir.mkdir(exist_ok=True)

    for file in files:
        path_str = file.get("path", "")
        # Wenn die Datei noch im Temp-Ordner liegt, verschieben wir sie
        if "/uploads/temp/" in path_str:
            # Saniert den Dateinamen um Path-Traversal zu verhindern
            filename = os.path.basename(file.get("filename", ""))
            if not filename:
                continue

            source_path = TEMP_DIR / filename
            target_path = target_dir / filename

            if source_path.exists() and source_path.is_file():
                # Zielpfad explizit löschen, falls er bereits existiert (wichtig für Windows-Overwrite)
                if target_path.exists() and target_path.is_file():
                    try:
                        target_path.unlink(missing_ok=True)
                    except OSError:
                        pass

                try:
                    shutil.move(str(source_path), str(target_path))
                except Exception:
                    # Falls das Verschieben fehlschlägt (z.B. Berechtigungen), überspringen wir diesen Eintrag
                    continue

            # Pfad für die Datenbank und das Frontend anpassen
            file["filename"] = filename
            file["path"] = f"/uploads/{safe_title}/{filename}"

    return json.dumps(files)

# ---------------------------------------------------------
# 4. API Routen
# ---------------------------------------------------------

@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """ Speichert Dateien vorübergehend im temp Ordner """
    uploaded_data = []
    for file in files:
        # Saniert den Dateinamen um Path-Traversal zu verhindern
        filename = os.path.basename(file.filename)
        if not filename:
            continue

        file_location = TEMP_DIR / filename
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)

        size_mb = round(os.path.getsize(file_location) / (1024 * 1024), 2)

        uploaded_data.append({
            "filename": filename,
            "path": f"/uploads/temp/{filename}",
            "size_mb": size_mb
        })
    return {"uploaded": uploaded_data}

@app.get("/api/projects")
async def get_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()

@app.post("/api/projects")
async def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    try:
        # Dateien verschieben, bevor wir in die DB speichern!
        project.files_json = process_project_files(project.internal_title, project.files_json)

        db_project = Project(**project.model_dump())
        db.add(db_project)
        db.commit()
        db.refresh(db_project)
        return {"message": "Projekt erfolgreich gespeichert", "project_id": db_project.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Datenbankfehler: {str(e)}")

@app.put("/api/projects/{project_id}")
async def update_project(project_id: int, project: ProjectCreate, db: Session = Depends(get_db)):
    try:
        db_project = db.query(Project).filter(Project.id == project_id).first()
        if not db_project:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

        # Dateien verschieben, bevor wir in die DB speichern!
        project.files_json = process_project_files(project.internal_title, project.files_json)

        for key, value in project.model_dump().items():
            setattr(db_project, key, value)

        db.commit()
        return {"message": "Projekt erfolgreich aktualisiert"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Datenbankfehler beim Update: {str(e)}")

# NEU: DELETE Route für Projekte und deren Ordner
@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    try:
        db_project = db.query(Project).filter(Project.id == project_id).first()
        if not db_project:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

        # Festplatten-Ordner löschen
        safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', db_project.internal_title).strip('_')
        if not safe_title:
            safe_title = "projekt"

        target_dir = UPLOAD_DIR / safe_title
        if target_dir.exists() and target_dir.is_dir():
            shutil.rmtree(target_dir) # Löscht den Ordner und alle Inhalte

        # Datenbankeintrag löschen
        db.delete(db_project)
        db.commit()
        return {"message": "Projekt erfolgreich gelöscht"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Fehler beim Löschen: {str(e)}")


@app.post("/api/generate-texts")
async def generate_texts_with_claude(request: AIGenerationRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API Key fehlt")

    client = anthropic.Anthropic(api_key=api_key)
    full_prompt = f"""{request.prompt_template}\n\nKONTEXT ZUM 3D-MODELL:\n- Gelöstes Problem: {request.problem}\n- Zielgruppe: {request.target_audience}\n- Besondere Nutzenargumente: {request.features}\n\nBitte antworte ausschließlich im folgenden Format:\nTITEL: [Dein generierter Titel]\nBESCHREIBUNG:\n[Deine generierte Beschreibung]"""

    response = client.messages.create(
        # model="claude-haiku-4-5-20251001",
        model="claude-sonnet-4-6",
        max_tokens=2000,
        temperature=0.7,
        messages=[{"role": "user", "content": full_prompt}]
    )
    parts = response.content[0].text.split("BESCHREIBUNG:")
    return {"title": parts[0].replace("TITEL:", "").strip(), "description": parts[1].strip() if len(parts) > 1 else ""}


# WICHTIG: Die Frontend-Routen MÜSSEN ganz unten stehen!
# Macht FastAPI zu unserem Webserver für HTML/JS/CSS
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")