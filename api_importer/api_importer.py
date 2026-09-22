#!/usr/bin/env python3
"""
AI-3D-Hub API Importer

Lädt jeden Unterordner von IMPORT_DIR als eigenes Projekt in AI-3D-Hub hoch.
Unterordner innerhalb eines Projekts bleiben erhalten.

Konfiguration über die .env neben diesem Skript (siehe .env.example).
Benötigt nur Python 3.10+, keine zusätzlichen Pakete.

Aufruf:
    python api_importer.py             # Import starten
    python api_importer.py --dry-run   # nur anzeigen, was passieren würde
    python api_importer.py --env pfad/zur/.env
"""
import argparse
import json
import shutil
import ssl
import sys
import uuid
from pathlib import Path
from urllib import error, request
from urllib.parse import quote

# Dateien, die Betriebssysteme gerne selbst anlegen und die niemand im Hub braucht
IGNORED_FILES = {"thumbs.db", "desktop.ini", ".ds_store"}
CHUNK_SIZE = 1024 * 1024


class ImporterError(Exception):
    pass


# ---------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------
def load_env(path: Path) -> dict:
    if not path.is_file():
        raise ImporterError(f".env nicht gefunden: {path}\nKopiere .env.example nach .env und passe sie an.")
    env = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def build_config(env: dict) -> dict:
    def choice(name, allowed, default):
        value = (env.get(name) or default).strip().lower()
        if value not in allowed:
            raise ImporterError(f"{name}={value} ist ungültig. Erlaubt: {', '.join(allowed)}")
        return value

    url = env.get("AI3DHUB_URL", "").strip().rstrip("/")
    api_key = env.get("AI3DHUB_API_KEY", "").strip()
    import_dir = env.get("IMPORT_DIR", "").strip()
    if not url.startswith(("http://", "https://")):
        raise ImporterError("AI3DHUB_URL fehlt oder beginnt nicht mit http:// bzw. https://")
    if not api_key:
        raise ImporterError("AI3DHUB_API_KEY fehlt (zu finden in der WebUI unter 'API-Zugang')")
    if not import_dir or not Path(import_dir).is_dir():
        raise ImporterError(f"IMPORT_DIR existiert nicht: '{import_dir}'")

    config = {
        "url": url,
        "api_key": api_key,
        "import_dir": Path(import_dir),
        "status": env.get("STATUS", "AutoUpload").strip(),
        "tags": env.get("TAGS", "").strip(),
        "category": env.get("CATEGORY", "").strip(),
        "on_conflict": choice("ON_CONFLICT", ("skip", "suffix"), "skip"),
        "after_upload": choice("AFTER_UPLOAD", ("rename", "delete", "keep"), "rename"),
        "done_prefix": env.get("DONE_PREFIX", "Uploaded_"),
        "verify_ssl": choice("VERIFY_SSL", ("true", "false"), "true") == "true",
    }
    if config["after_upload"] == "rename" and not config["done_prefix"]:
        raise ImporterError("AFTER_UPLOAD=rename braucht ein DONE_PREFIX")
    return config


# ---------------------------------------------------------
# HTTP
# ---------------------------------------------------------
def ssl_context(config):
    if config["url"].startswith("https://") and not config["verify_ssl"]:
        return ssl._create_unverified_context()
    return None


def send(config, method, path, body=None, headers=None):
    """ Gibt (status, json) zurück. HTTP-Fehler werden nicht als Exception geworfen. """
    req = request.Request(config["url"] + path, data=body, method=method,
                          headers={"X-API-Key": config["api_key"], **(headers or {})})
    try:
        with request.urlopen(req, context=ssl_context(config), timeout=600) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail", e.reason)
        except Exception:
            detail = e.reason
        return e.code, {"detail": detail}
    except error.URLError as e:
        raise ImporterError(f"Server nicht erreichbar ({config['url']}): {e.reason}")


class MultipartBody:
    """ Multipart-Body, der Dateien stückweise liest, statt alles in den Speicher zu laden. """

    def __init__(self, fields, files):
        self.boundary = uuid.uuid4().hex
        self.parts = []  # bytes oder Path
        for name, value in fields:
            self.parts.append(self._header(name) + value.encode("utf-8") + b"\r\n")
        for name, file_path in files:
            self.parts.append(self._header(name, quote(file_path.name)))
            self.parts.append(file_path)
            self.parts.append(b"\r\n")
        self.parts.append(f"--{self.boundary}--\r\n".encode())

    def _header(self, name, filename=None):
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        header = f"--{self.boundary}\r\nContent-Disposition: {disposition}\r\n"
        if filename is not None:
            header += "Content-Type: application/octet-stream\r\n"
        return (header + "\r\n").encode()

    @property
    def content_type(self):
        return f"multipart/form-data; boundary={self.boundary}"

    def __len__(self):
        return sum(p.stat().st_size if isinstance(p, Path) else len(p) for p in self.parts)

    def __iter__(self):
        for part in self.parts:
            if isinstance(part, Path):
                with open(part, "rb") as f:
                    while chunk := f.read(CHUNK_SIZE):
                        yield chunk
            else:
                yield part


# ---------------------------------------------------------
# Import-Logik
# ---------------------------------------------------------
def collect_files(project_dir: Path) -> list[tuple[str, Path]]:
    files = []
    for path in sorted(project_dir.rglob("*")):
        if path.is_file() and path.name.lower() not in IGNORED_FILES:
            files.append((path.relative_to(project_dir).as_posix(), path))
    return files


def project_folders(config) -> list[Path]:
    folders = []
    for entry in sorted(config["import_dir"].iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if config["done_prefix"] and entry.name.startswith(config["done_prefix"]):
            continue
        folders.append(entry)
    return folders


def upload_project(config, project_dir: Path, files) -> tuple[int, dict]:
    fields = [("title", project_dir.name), ("on_conflict", config["on_conflict"])]
    for key in ("status", "tags", "category"):
        if config[key]:
            fields.append((key, config[key]))
    fields += [("paths", rel) for rel, _ in files]
    body = MultipartBody(fields, [("files", path) for _, path in files])
    return send(config, "POST", "/api/import", body=iter(body),
                headers={"Content-Type": body.content_type, "Content-Length": str(len(body))})


def finish_folder(config, project_dir: Path):
    if config["after_upload"] == "delete":
        shutil.rmtree(project_dir)
        return "gelöscht"
    if config["after_upload"] == "rename":
        target = project_dir.with_name(config["done_prefix"] + project_dir.name)
        n = 2
        while target.exists():
            target = project_dir.with_name(f"{config['done_prefix']}{project_dir.name} ({n})")
            n += 1
        project_dir.rename(target)
        return f"umbenannt in '{target.name}'"
    return "belassen"


def run(config, dry_run: bool) -> int:
    status, body = send(config, "GET", "/api/import/check")
    if status == 401:
        raise ImporterError("API-Key wurde abgelehnt. Bitte in der WebUI unter 'API-Zugang' prüfen.")
    if status != 200:
        raise ImporterError(f"Verbindungstest fehlgeschlagen (HTTP {status}): {body.get('detail')}")

    folders = project_folders(config)
    print(f"Verbunden mit {config['url']}. {len(folders)} Projektordner in '{config['import_dir']}'.")
    if dry_run:
        print("DRY RUN: es wird nichts hochgeladen oder verändert.\n")

    counts = {"importiert": 0, "übersprungen": 0, "leer": 0, "fehler": 0}
    for project_dir in folders:
        files = collect_files(project_dir)
        size_mb = sum(p.stat().st_size for _, p in files) / (1024 * 1024)
        prefix = f"[{project_dir.name}]"
        if not files:
            print(f"{prefix} leer, übersprungen")
            counts["leer"] += 1
            continue
        if dry_run:
            print(f"{prefix} {len(files)} Dateien, {size_mb:.1f} MB")
            for rel, _ in files:
                print(f"    {rel}")
            continue

        # Bei "skip" vorher fragen, statt erst alles hochzuladen und dann abgewiesen zu werden
        if config["on_conflict"] == "skip":
            status, body = send(config, "GET", "/api/import/check?title=" + quote(project_dir.name))
            if status == 200 and body.get("exists"):
                print(f"{prefix} übersprungen: existiert bereits im Hub")
                counts["übersprungen"] += 1
                continue

        print(f"{prefix} lade {len(files)} Dateien hoch ({size_mb:.1f} MB) ...", flush=True)
        try:
            status, body = upload_project(config, project_dir, files)
        except OSError as e:
            status, body = 0, {"detail": str(e)}

        if status == 201:
            action = finish_folder(config, project_dir)
            print(f"{prefix} OK: Projekt '{body['title']}' (ID {body['project_id']}), Ordner {action}")
            counts["importiert"] += 1
        elif status == 409:
            print(f"{prefix} übersprungen: {body.get('detail')}")
            counts["übersprungen"] += 1
        elif status == 401:
            raise ImporterError("API-Key wurde während des Imports abgelehnt (neu generiert?).")
        else:
            print(f"{prefix} FEHLER (HTTP {status}): {body.get('detail')}")
            counts["fehler"] += 1

    if not dry_run:
        print("\nFertig: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return 1 if counts["fehler"] else 0


def main():
    # Umlaute in der Windows-Konsole nicht mit einem UnicodeError quittieren
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description="Lädt Projektordner per API in AI-3D-Hub hoch.")
    parser.add_argument("--env", type=Path, default=Path(__file__).resolve().parent / ".env",
                        help="Pfad zur .env (Standard: neben diesem Skript)")
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts hochladen")
    args = parser.parse_args()

    try:
        config = build_config(load_env(args.env))
        sys.exit(run(config, args.dry_run))
    except ImporterError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
