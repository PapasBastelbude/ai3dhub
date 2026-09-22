from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Form, Header
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
import secrets
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from PIL import Image

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

class Setting(Base):
    # Einfacher Key/Value-Speicher für App-Einstellungen (z.B. den API-Key)
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)

Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------
# 2. FastAPI App Initialisierung & Ordner
# ---------------------------------------------------------

UPLOAD_DIR = Path("uploads")
TEMP_DIR = UPLOAD_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

def safe_folder_name(internal_title: str) -> str:
    """ Macht den Projekttitel ordner-tauglich (Sonderzeichen entfernen) """
    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', internal_title or "").strip('_')
    return safe_title or "projekt"

def resolve_project_file(project_dir: Path, relative_name: str) -> Path | None:
    """ Findet eine Datei im Projektordner. Unterstützt relative Pfade (z.B. 'v2/bild.jpg')
    und fällt für alte Einträge auf den reinen Dateinamen zurück. Verlässt nie den Projektordner. """
    base = project_dir.resolve()
    for candidate in (relative_name, os.path.basename(relative_name)):
        if not candidate:
            continue
        path = (project_dir / candidate).resolve()
        if path.is_relative_to(base) and path.is_file():
            return path
    return None

def create_thumbnail(image_path: Path, force: bool = False) -> bool:
    """ Legt 'thumb_<name>' neben dem Bild an. Gibt False zurück, wenn es nicht geklappt hat. """
    thumb_path = image_path.with_name(f"thumb_{image_path.name}")
    if thumb_path.exists() and not force:
        return True
    try:
        with Image.open(image_path) as img:
            # Falls Bild Transparenzen hat, beim Speichern als JPG in RGB wandeln
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.thumbnail((400, 400))
            img.save(thumb_path)
        return True
    except Exception:
        return False

def generate_missing_thumbnails(force: bool = False):
    db = SessionLocal()
    try:
        projects = db.query(Project).all()
        for project in projects:
            if not project.cover_image or not project.internal_title:
                continue

            target_dir = UPLOAD_DIR / safe_folder_name(project.internal_title)

            # Cover kann ein relativer Pfad (Import mit Unterordnern) oder bei alten Einträgen ein voller Pfad sein
            target_path = resolve_project_file(target_dir, project.cover_image)

            # Prüfen, ob das Originalbild überhaupt im Ordner existiert
            if target_path is None:
                print(f"[Warnung] Projekt '{project.internal_title}': Originalbild '{project.cover_image}' nicht gefunden in {target_dir}")
                continue

            thumb_path = target_path.with_name(f"thumb_{target_path.name}")
            if force or not thumb_path.exists():
                print(f"[Info] Projekt '{project.internal_title}': Generiere Thumbnail für {target_path.name}...")
                if create_thumbnail(target_path, force=True):
                    print(f"[Erfolg] Projekt '{project.internal_title}': Thumbnail erfolgreich erstellt!")
                else:
                    print(f"[Fehler] Projekt '{project.internal_title}': Konnte Thumbnail nicht erstellen")
            elif thumb_path.exists() and not force:
                # Das kann nützlich sein, um zu sehen, ob er Projekte überspringt
                print(f"[Info] Projekt '{project.internal_title}': Thumbnail existiert bereits, überspringe.")
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("Starte Anwendung und prüfe Thumbnails...")
    generate_missing_thumbnails()
    db = SessionLocal()
    try:
        get_or_create_api_key(db)
    finally:
        db.close()
    yield
    # Shutdown logic

app = FastAPI(title="AI-3D-Hub API", lifespan=lifespan)

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

# ---------------------------------------------------------
# API-Key (für Skripte wie den API Importer)
# ---------------------------------------------------------
API_KEY_SETTING = "api_key"

def _set_api_key(db: Session) -> str:
    new_key = secrets.token_urlsafe(32)
    setting = db.get(Setting, API_KEY_SETTING)
    if setting:
        setting.value = new_key
    else:
        db.add(Setting(key=API_KEY_SETTING, value=new_key))
    db.commit()
    return new_key

def get_or_create_api_key(db: Session) -> str:
    """ Die App erzeugt ihren API-Key selbst, sobald er zum ersten Mal gebraucht wird. """
    setting = db.get(Setting, API_KEY_SETTING)
    if setting and setting.value:
        return setting.value
    print("[Info] Neuer API-Key erzeugt (sichtbar in der WebUI unter 'API-Zugang').")
    return _set_api_key(db)

def require_api_key(x_api_key: str | None = Header(None), db: Session = Depends(get_db)):
    expected = get_or_create_api_key(db)
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Ungültiger oder fehlender API-Key (Header 'X-API-Key')")

# Hilfsfunktion: Verschiebt Temp-Dateien in den echten Projektordner
def process_project_files(internal_title: str, files_json_str: str, cover_image: str | None = None):
    if not files_json_str or files_json_str == "[]":
        return files_json_str

    try:
        files = json.loads(files_json_str)
    except:
        return files_json_str

    safe_title = safe_folder_name(internal_title)
    target_dir = UPLOAD_DIR / safe_title
    target_dir.mkdir(exist_ok=True)

    for file in files:
        path_str = file.get("path", "")
        filename = os.path.basename(file.get("filename", ""))
        if not filename:
            continue

        target_path = target_dir / filename

        # Wenn die Datei noch im Temp-Ordner liegt, verschieben wir sie
        if "/uploads/temp/" in path_str:
            source_path = TEMP_DIR / filename

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

        # Thumbnail generieren wenn es das Coverbild ist (auch für existierende Bilder ohne Verschieben).
        # Importierte Dateien können in Unterordnern liegen, daher der relative Pfad aus 'filename'.
        if cover_image and (file.get("filename") == cover_image or filename == os.path.basename(cover_image)):
            cover_path = resolve_project_file(target_dir, file.get("filename", ""))
            if cover_path:
                create_thumbnail(cover_path)

    return json.dumps(files)

# ---------------------------------------------------------
# 4. API Routen
# ---------------------------------------------------------

@app.post("/api/upload")
def upload_files(files: list[UploadFile] = File(...)):
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
def get_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()

@app.post("/api/projects")
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    try:
        # Dateien verschieben, bevor wir in die DB speichern!
        project.files_json = process_project_files(project.internal_title, project.files_json, project.cover_image)

        db_project = Project(**project.model_dump())
        db.add(db_project)
        db.commit()
        db.refresh(db_project)
        return {"message": "Projekt erfolgreich gespeichert", "project_id": db_project.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Datenbankfehler: {str(e)}")

@app.put("/api/projects/{project_id}")
def update_project(project_id: int, project: ProjectCreate, db: Session = Depends(get_db)):
    try:
        db_project = db.query(Project).filter(Project.id == project_id).first()
        if not db_project:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

        # Dateien verschieben, bevor wir in die DB speichern!
        project.files_json = process_project_files(project.internal_title, project.files_json, project.cover_image)

        for key, value in project.model_dump().items():
            setattr(db_project, key, value)

        db.commit()
        return {"message": "Projekt erfolgreich aktualisiert"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Datenbankfehler beim Update: {str(e)}")

# NEU: DELETE Route für Projekte und deren Ordner
@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    try:
        db_project = db.query(Project).filter(Project.id == project_id).first()
        if not db_project:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

        # Festplatten-Ordner löschen
        target_dir = UPLOAD_DIR / safe_folder_name(db_project.internal_title)
        if target_dir.exists() and target_dir.is_dir():
            shutil.rmtree(target_dir) # Löscht den Ordner und alle Inhalte

        # Datenbankeintrag löschen
        db.delete(db_project)
        db.commit()
        return {"message": "Projekt erfolgreich gelöscht"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Fehler beim Löschen: {str(e)}")


@app.post("/api/thumbnails/refresh")
def refresh_thumbnails():
    try:
        print("=== Manuelles Thumbnail Refresh gestartet ===")
        generate_missing_thumbnails(force=True)
        return {"message": "Thumbnails successfully refreshed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating thumbnails: {str(e)}")


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


# ---------------------------------------------------------
# 5. API-Zugang & Import (für den API Importer / Skripte)
# ---------------------------------------------------------

@app.get("/api/settings/api-key")
def get_api_key(db: Session = Depends(get_db)):
    """ Liefert den API-Key für die Anzeige in der WebUI """
    return {"api_key": get_or_create_api_key(db)}

@app.post("/api/settings/api-key/regenerate")
def regenerate_api_key(db: Session = Depends(get_db)):
    """ Erzeugt einen neuen API-Key, der alte wird sofort ungültig """
    return {"api_key": _set_api_key(db)}

def normalize_relative_path(raw: str) -> str:
    """ Wandelt z.B. 'v2\\teil.stl' in 'v2/teil.stl' um und lehnt alles ab,
    was aus dem Projektordner ausbrechen könnte ('..', absolute Pfade, Laufwerke). """
    parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or raw.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail=f"Ungültiger Dateipfad: '{raw}'")
    for part in parts:
        if part == ".." or ":" in part or "\x00" in part:
            raise HTTPException(status_code=400, detail=f"Ungültiger Dateipfad: '{raw}'")
    return "/".join(parts)

def folder_is_taken(db: Session, folder: str) -> bool:
    # Mehrere Titel können auf denselben Ordner abgebildet werden ("Projekt 1" / "Projekt_1"),
    # deshalb vergleichen wir die Ordnernamen und nicht nur die Titel.
    if (UPLOAD_DIR / folder).exists():
        return True
    return any(safe_folder_name(t) == folder for (t,) in db.query(Project.internal_title).all())

@app.get("/api/import/check")
def import_check(title: str | None = None, db: Session = Depends(get_db), _: None = Depends(require_api_key)):
    """ Verbindungs- und Key-Test für Skripte. Mit ?title=... zusätzlich: gibt es das Projekt schon? """
    result = {"ok": True}
    if title is not None:
        result["exists"] = folder_is_taken(db, safe_folder_name(title.strip()))
    return result

@app.post("/api/import", status_code=201)
def import_project(
    title: str = Form(...),
    files: list[UploadFile] = File(...),
    paths: list[str] | None = Form(None),
    status: str | None = Form(None),
    tags: str | None = Form(None),
    category: str | None = Form(None),
    on_conflict: Literal["skip", "suffix"] = Form("skip"),
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    """ Legt in einem Schritt ein komplettes Projekt inkl. Dateien an.
    'paths' enthält pro Datei den relativen Pfad im Projekt (Unterordner bleiben erhalten). """
    title = title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titel fehlt")

    if paths is not None and len(paths) != len(files):
        raise HTTPException(status_code=400, detail="Anzahl von 'paths' und 'files' stimmt nicht überein")
    relative_paths = [normalize_relative_path(p) for p in (paths or [f.filename or "" for f in files])]
    if len(set(p.lower() for p in relative_paths)) != len(relative_paths):
        raise HTTPException(status_code=400, detail="Doppelte Dateipfade im Upload")

    # Konflikte: gleicher Ordner = gleiches Projekt. Nie in einen bestehenden Ordner schreiben!
    final_title = title
    if folder_is_taken(db, safe_folder_name(final_title)):
        if on_conflict == "skip":
            raise HTTPException(status_code=409, detail=f"Projekt '{title}' existiert bereits")
        n = 2
        while folder_is_taken(db, safe_folder_name(f"{title} ({n})")):
            n += 1
        final_title = f"{title} ({n})"

    folder = safe_folder_name(final_title)
    target_dir = UPLOAD_DIR / folder

    # Erst komplett in einen Staging-Ordner schreiben, dann in einem Rutsch umbenennen.
    # So entsteht nie ein halb befüllter Projektordner.
    staging_dir = TEMP_DIR / f"import_{uuid.uuid4().hex}"
    staging_root = staging_dir.resolve()
    try:
        staging_dir.mkdir(parents=True)
        files_meta = []
        for upload, rel in zip(files, relative_paths):
            dest = (staging_dir / rel).resolve()
            if not dest.is_relative_to(staging_root):
                raise HTTPException(status_code=400, detail=f"Ungültiger Dateipfad: '{rel}'")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as out:
                shutil.copyfileobj(upload.file, out)
            files_meta.append({
                "filename": rel,
                "path": f"/uploads/{folder}/{quote(rel)}",
                "size_mb": round(dest.stat().st_size / (1024 * 1024), 2),
            })

        staging_dir.rename(target_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    # Coverbild: das erste Bild, bevorzugt aus der obersten Ordnerebene
    images = sorted(
        (m["filename"] for m in files_meta if Path(m["filename"]).suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda rel: (rel.count("/"), rel.lower()),
    )
    cover_image = images[0] if images else None
    if cover_image:
        create_thumbnail(target_dir / cover_image)

    try:
        db_project = Project(
            internal_title=final_title,
            status=status or None,
            tags=tags or None,
            category=category or "Allgemein",
            cover_image=cover_image,
            files_json=json.dumps(files_meta),
        )
        db.add(db_project)
        db.commit()
        db.refresh(db_project)
    except Exception as e:
        db.rollback()
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Datenbankfehler: {str(e)}")

    return {
        "message": "Projekt erfolgreich importiert",
        "project_id": db_project.id,
        "title": final_title,
        "folder": folder,
        "files": len(files_meta),
        "cover_image": cover_image,
    }


# WICHTIG: Die Frontend-Routen MÜSSEN ganz unten stehen!
# Macht FastAPI zu unserem Webserver für HTML/JS/CSS
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
