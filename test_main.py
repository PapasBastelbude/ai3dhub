import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from main import app, Base, get_db
import main
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

# Use an in-memory database with StaticPool to share connection across threads
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_and_teardown(monkeypatch):
    # Use a safe temporary directory for uploads instead of main UPLOAD_DIR
    temp_dir = TemporaryDirectory()
    safe_upload_dir = Path(temp_dir.name)
    safe_temp_dir = safe_upload_dir / "temp"
    safe_temp_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(main, "UPLOAD_DIR", safe_upload_dir)
    monkeypatch.setattr(main, "TEMP_DIR", safe_temp_dir)

    # Ensure fresh DB state for each test
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    yield safe_upload_dir, safe_temp_dir

    # Teardown
    Base.metadata.drop_all(bind=engine)
    temp_dir.cleanup()

def test_create_project(setup_and_teardown):
    safe_upload_dir, safe_temp_dir = setup_and_teardown
    project_data = {
        "internal_title": "Test Project",
        "public_title": "Public Test",
        "category": "Test",
        "files_json": json.dumps([{"filename": "test.txt", "path": "/uploads/temp/test.txt"}])
    }
    with open(safe_temp_dir / "test.txt", "w") as f:
        f.write("test")

    response = client.post("/api/projects", json=project_data)
    assert response.status_code == 200, response.json()
    assert response.json()["message"] == "Projekt erfolgreich gespeichert"
    assert "project_id" in response.json()

    # Check directory created
    assert (safe_upload_dir / "Test_Project").exists()
    assert (safe_upload_dir / "Test_Project" / "test.txt").exists()

def test_upload_file(setup_and_teardown):
    safe_upload_dir, safe_temp_dir = setup_and_teardown
    with open("dummy.txt", "w") as f:
        f.write("test content")

    with open("dummy.txt", "rb") as f:
        response = client.post("/api/upload", files={"files": ("dummy.txt", f, "text/plain")})

    assert response.status_code == 200
    assert len(response.json()["uploaded"]) == 1
    assert response.json()["uploaded"][0]["filename"] == "dummy.txt"
    assert (safe_temp_dir / "dummy.txt").exists()
    os.remove("dummy.txt")

def test_get_projects(setup_and_teardown):
    safe_upload_dir, safe_temp_dir = setup_and_teardown
    project_data = {
        "internal_title": "Get Test Project",
        "public_title": "Public Test",
        "category": "Test"
    }
    client.post("/api/projects", json=project_data)

    response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["internal_title"] == "Get Test Project"

def test_delete_project(setup_and_teardown):
    safe_upload_dir, safe_temp_dir = setup_and_teardown
    project_data = {
        "internal_title": "Delete Project",
        "public_title": "Public Test",
        "category": "Test",
        "files_json": json.dumps([{"filename": "test.txt", "path": "/uploads/temp/test.txt"}])
    }
    with open(safe_temp_dir / "test.txt", "w") as f:
        f.write("test")

    create_response = client.post("/api/projects", json=project_data)
    project_id = create_response.json()["project_id"]

    assert (safe_upload_dir / "Delete_Project").exists()

    delete_response = client.delete(f"/api/projects/{project_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Projekt erfolgreich gelöscht"

    # Verify project directory was deleted
    assert not (safe_upload_dir / "Delete_Project").exists()


# ---------------------------------------------------------
# API Import
# ---------------------------------------------------------
import io
from PIL import Image as PILImage

def _api_key():
    return client.get("/api/settings/api-key").json()["api_key"]

def _png_bytes():
    buf = io.BytesIO()
    PILImage.new("RGB", (800, 600), "red").save(buf, format="PNG")
    return buf.getvalue()

def _import(title, entries, key=None, **fields):
    """ entries: Liste von (relativer_pfad, bytes) """
    data = {"title": title, "paths": [rel for rel, _ in entries], **fields}
    files = [("files", (os.path.basename(rel), content)) for rel, content in entries]
    headers = {"X-API-Key": key if key is not None else _api_key()}
    return client.post("/api/import", data=data, files=files, headers=headers)

def test_api_key_is_generated_and_stable():
    key = _api_key()
    assert len(key) >= 32
    assert _api_key() == key

def test_import_requires_valid_key(setup_and_teardown):
    assert client.get("/api/import/check").status_code == 401
    assert client.get("/api/import/check", headers={"X-API-Key": "falsch"}).status_code == 401
    assert client.get("/api/import/check", headers={"X-API-Key": _api_key()}).status_code == 200
    assert _import("Projekt", [("a.stl", b"x")], key="falsch").status_code == 401

def test_regenerate_invalidates_old_key(setup_and_teardown):
    old = _api_key()
    new = client.post("/api/settings/api-key/regenerate").json()["api_key"]
    assert new != old
    assert client.get("/api/import/check", headers={"X-API-Key": old}).status_code == 401
    assert client.get("/api/import/check", headers={"X-API-Key": new}).status_code == 200

def test_import_keeps_structure_and_sets_metadata(setup_and_teardown):
    safe_upload_dir, _ = setup_and_teardown
    response = _import(
        "Projekt 1",
        [("Base.stl", b"solid"), ("v2\\Base.stl", b"solid v2"), ("bilder/render.png", _png_bytes())],
        status="AutoUpload",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["folder"] == "Projekt_1"
    assert body["cover_image"] == "bilder/render.png"

    project_dir = safe_upload_dir / "Projekt_1"
    assert (project_dir / "Base.stl").read_bytes() == b"solid"
    assert (project_dir / "v2" / "Base.stl").read_bytes() == b"solid v2"
    assert (project_dir / "bilder" / "thumb_render.png").exists()

    project = client.get("/api/projects").json()[0]
    assert project["status"] == "AutoUpload"
    files = {f["filename"]: f["path"] for f in json.loads(project["files_json"])}
    assert files["v2/Base.stl"] == "/uploads/Projekt_1/v2/Base.stl"

def test_import_conflict_skip_and_suffix(setup_and_teardown):
    safe_upload_dir, _ = setup_and_teardown
    assert _import("Projekt 1", [("a.stl", b"1")]).status_code == 201
    # "Projekt_1" landet im selben Ordner wie "Projekt 1" -> ebenfalls Konflikt
    assert _import("Projekt_1", [("a.stl", b"2")]).status_code == 409

    response = _import("Projekt 1", [("a.stl", b"3")], on_conflict="suffix")
    assert response.status_code == 201
    assert response.json()["title"] == "Projekt 1 (2)"

    check = lambda t: client.get("/api/import/check", params={"title": t}, headers={"X-API-Key": _api_key()}).json()["exists"]
    assert check("Projekt 1") and check("Projekt_1") and not check("Projekt 7")
    assert (safe_upload_dir / "Projekt_1" / "a.stl").read_bytes() == b"1"
    assert (safe_upload_dir / "Projekt_1__2" / "a.stl").read_bytes() == b"3"

@pytest.mark.parametrize("bad_path", ["../evil.stl", "a/../../evil.stl", "/etc/passwd", "C:/evil.stl", "..\\evil.stl"])
def test_import_rejects_path_traversal(setup_and_teardown, bad_path):
    safe_upload_dir, safe_temp_dir = setup_and_teardown
    assert _import("Projekt", [(bad_path, b"x")]).status_code == 400
    assert not (safe_upload_dir / "Projekt").exists()
    assert list(safe_temp_dir.iterdir()) == []

def test_edit_imported_project_keeps_subfolder_cover(setup_and_teardown):
    safe_upload_dir, _ = setup_and_teardown
    body = _import("Projekt", [("bilder/render.png", _png_bytes())]).json()
    thumb = safe_upload_dir / "Projekt" / "bilder" / "thumb_render.png"
    thumb.unlink()

    project = client.get("/api/projects").json()[0]
    payload = {k: project[k] for k in ("internal_title", "status", "cover_image", "files_json")}
    assert client.put(f"/api/projects/{body['project_id']}", json=payload).status_code == 200
    assert thumb.exists()
