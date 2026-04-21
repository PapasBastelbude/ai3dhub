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
