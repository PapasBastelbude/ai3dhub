AI-3D-Hub: Project Overview & Code Review Handover

1. Projekt-Zusammenfassung

AI-3D-Hub ist ein leichtgewichtiges, self-hosted Digital Asset Management (DAM) Tool speziell für 3D-Druck-Dateien (STL, 3MF, F3D, Bilder).
Das Ziel: Eine effiziente, lokale Alternative zu schwerfälligen Tools wie Manyfold. Der Fokus liegt auf Geschwindigkeit, lokaler Datenhaltung und integrierter KI-Unterstützung (via Anthropic) zur automatischen Generierung von SEO-optimierten Titeln und Beschreibungen für Plattformen wie Makerworld.

2. Tech Stack

Backend: Python 3.11+, FastAPI, SQLAlchemy, Uvicorn.

Datenbank: SQLite (lokal, File-basiert via data/ai3dhub.db).

Frontend: Vanilla HTML5, JavaScript, Tailwind CSS (via CDN), Lucide Icons. (Single-Page-Application Ansatz ohne Frameworks wie React).

KI-Integration: Anthropic API (claude-haiku-4-5-20251001).

Deployment: Docker & Docker-Compose.

3. Verzeichnisstruktur

ai3dhub/
├── main.py                 # FastAPI Backend & API-Routen
├── frontend/
│   ├── index.html          # Komplette UI & Frontend-Logik (Vanilla JS)
│   └── logo.jpg            # Statisches Logo
├── data/                   # SQLite DB-Ordner (Docker Volume)
│   └── ai3dhub.db
├── uploads/                # Physischer Dateispeicher (Docker Volume)
│   ├── temp/               # Temporärer Upload-Ordner
│   └── [Projekt_Titel]/    # Projekt-spezifische Datei-Ordner
├── requirements.txt        # Python Abhängigkeiten
├── Dockerfile              # Container-Bauplan
├── docker-compose.yml      # Service Definition (Mounts & Ports)
├── .env.example            # Template für ANTHROPIC_API_KEY
└── .gitignore


4. Kernfunktionen & Workflows

Dateien (Upload-Flow): 1. Frontend sendet Dateien via POST /api/upload (multipart/form-data).
2. Backend speichert sie im uploads/temp/ Ordner.
3. Beim Speichern (POST /api/projects oder PUT) liest das Backend das files_json aus, erstellt einen bereinigten Ordner (uploads/[Safe_Project_Name]) und verschiebt die Dateien aus temp dorthin.

Status-Manager: Der User kann im Frontend dynamische Status (inkl. Hex-Farben) anlegen. Speicherung erfolgt im localStorage des Browsers. Nur der String-Name des Status wandert in die DB.

KI-Generierung: Das Frontend schickt Kontext (Problem, Zielgruppe, Nutzen, Prompt) an POST /api/generate-texts. Das Backend fragt Claude ab und parst die Antwort in "Titel" und "Beschreibung".

I18n & Theme: Umschaltung zwischen Dark/Light Mode und DE/EN erfolgt rein im Frontend via JS und localStorage.

5. Datenbank-Schema (Project)

id (Integer, PK)

internal_title (String) -> Dient als Basis für den Datei-Ordnernamen.

public_title, description, tags, material, hardware, category, status, notes (Strings/Text)

cover_image (String) -> Dateiname des ausgewählten Titelbildes.

files_json (Text) -> JSON-String mit Array aller zugehörigen Dateien inkl. relativen Pfaden.

6. Review-Fokus für Jules (Bitte hierauf besonders achten!)

Bitte analysiere die Architektur und den Code auf folgende Punkte:

Security & Path Traversal: Werden die Dateinamen beim Upload und Verschieben (process_project_files) ausreichend sanitisiert? Besteht Gefahr durch Directory Traversal Angriffe bei files_json Manipulationen?

XSS (Cross-Site Scripting): Das Frontend nutzt insertAdjacentHTML und innerHTML um Projekt-Karten, Tags und Status zu rendern. Sind wir hier anfällig für XSS, falls ein Nutzer bösartige HTML-Strings als Tag oder Titel eingibt? (Bitte um Vorschlag für eine simple Vanilla-JS Escape-Funktion).

Error Handling & Edge Cases: * Was passiert, wenn zwei Projekte denselben internal_title haben? Werden Ordner unsauber gemerged?

Was passiert bei verwaisten Dateien im temp-Ordner (z.B. wenn der Upload klappt, aber der User den Browser schließt)? Brauchen wir einen Cleanup-Cronjob?

Code Quality: Gibt es in der main.py oder der index.html Quick-Wins, um die Performance oder Lesbarkeit zu steigern, ohne neue Frameworks einführen zu müssen?

Start your review based on the provided codebase and architecture.