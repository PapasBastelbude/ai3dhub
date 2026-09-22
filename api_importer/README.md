# AI-3D-Hub API Importer

Lädt jeden Unterordner eines lokalen Ordners automatisch als eigenes Projekt in AI-3D-Hub hoch.

```
3D Modelle/                    <- IMPORT_DIR
├── Projekt 1/                 -> Projekt "Projekt 1"
│   ├── Bilder/render.png      -> wird automatisch Titelbild
│   └── v2/teil.stl            -> Unterordner bleiben erhalten
├── Halterung/                 -> Projekt "Halterung"
└── Uploaded_Alt/              <- bereits hochgeladen, wird ignoriert
```

## Einrichtung

1. **Python 3.10+** installieren (Windows: bei der Installation „Add python.exe to PATH“ anhaken). Weitere Pakete sind nicht nötig.
2. `.env.example` in `.env` umbenennen bzw. kopieren und ausfüllen:
   - `AI3DHUB_URL`: z.B. `http://192.168.1.10:8787` (Port aus dem Unraid-Template)
   - `AI3DHUB_API_KEY`: in der WebUI über das Schlüssel-Symbol oben rechts („API-Zugang“)
   - `IMPORT_DIR`: dein Ordner mit den Projektordnern
3. Erst testen, dabei wird nichts hochgeladen oder verändert:
   ```
   python api_importer.py --dry-run
   ```
4. Import starten:
   - **Windows:** Doppelklick auf `API Importer starten.bat`
   - **Mac/Linux:** `python3 api_importer.py`

## Optionen in der `.env`

| Einstellung | Werte | Bedeutung |
|---|---|---|
| `STATUS` | Text, Standard `AutoUpload` | Status der neuen Projekte. Lege denselben Status in der WebUI an, damit er eine Farbe bekommt. |
| `TAGS`, `CATEGORY` | Text, optional | Tags (Komma-getrennt) bzw. Kategorie für neue Projekte |
| `ON_CONFLICT` | `skip` / `suffix` | Projekt existiert bereits: überspringen oder als „Projekt 1 (2)“ anlegen |
| `AFTER_UPLOAD` | `rename` / `delete` / `keep` | Lokaler Ordner nach Erfolg: `DONE_PREFIX` voranstellen, löschen oder belassen |
| `DONE_PREFIX` | Standard `Uploaded_` | Ordner mit diesem Präfix werden bei jedem Lauf ignoriert |
| `VERIFY_SSL` | `true` / `false` | Nur bei https mit selbstsigniertem Zertifikat auf `false` setzen |

`AFTER_UPLOAD=delete` löscht endgültig, ohne Papierkorb. Der Ordner wird aber nur gelöscht, wenn der Server den Import bestätigt hat. Übersprungene oder fehlgeschlagene Ordner bleiben immer unangetastet.

## Hinweise

- Dateien wie `Thumbs.db`, `desktop.ini` und `.DS_Store` werden ignoriert, leere Ordner übersprungen.
- Der Server legt ein Projekt ganz oder gar nicht an. Bricht ein Upload ab, bleibt kein halber Projektordner zurück.
- Für die Aufgabenplanung (Windows) `python api_importer.py` direkt aufrufen. Die `.bat` wartet am Ende auf einen Tastendruck.
- Über `http` wird der API-Key unverschlüsselt übertragen. Im Heimnetz ist das meist okay. Von außen nur über https (Reverse Proxy) zugreifen.
- Exit-Codes: `0` = ok, `1` = mindestens ein Projekt fehlgeschlagen, `2` = Konfigurations- oder Verbindungsfehler.
