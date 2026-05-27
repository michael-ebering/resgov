# CHANGELOG

## v0.4.4 - 2026-05-28

### Hinzugefügt

- **[BudgetEngine]** Implementierung der Methode `get_budget_prediction` zur prädiktiven Vorhersage der Budgeterschöpfung von Agenten.
- **[API]** Neuer API-Endpunkt `GET /api/v1/agents/{agent_id}/prediction` zur Abfrage der Budget-Prognosen.
- **[Dashboard]** Integration der Budget-Prognose für jeden Agenten in die Dashboard-Ansicht (`dash/index.html`).
- **[Tests]** Umfassende Testfälle (`tests/test_predictions.py`) für die `get_budget_prediction`-Methode und den zugehörigen API-Endpunkt.

### Geändert

- **[BudgetEngine]** `BudgetEngine.__init__` erweitert, um eine explizite DB-Verbindung für Testzwecke zu akzeptieren.
- **[BudgetEngine]** Korrektur der `remaining_time_seconds`-Berechnung in `get_budget_prediction` für präzisere Prognosen.
- **[Tests]** `tests/test_predictions.py` Fixtures und Helferfunktionen angepasst, um die `BudgetEngine` und den FastAPI `TestClient` korrekt zu initialisieren und Datenbank-Overrides zu verwenden.

## v0.4.3 - 2026-05-28

### Hinzugefügt

- **[.rgf file]** Unterstützung für lokale `.rgf`-Konfigurationsdateien im TOML-Format, inspiriert von `.gitignore`.
- **[BudgetEngine]** Die `BudgetEngine` berücksichtigt nun `daily_budget`, `monthly_budget`, `allowed_models` und `max_tokens_per_request` aus der `.rgf`-Datei. `.rgf`-Regeln können über die API gesetzte Limits verschärfen.
- **[LLM Proxy]** Implementierung der `fail_safe_action` aus der `.rgf`-Konfiguration, um das Verhalten des LLM-Proxys bei Ausfall des Budget-Systems zu definieren (`allow` oder `deny`).
- **[Core]** Neues `src/config.py`-Modul zum Laden und Parsen der `.rgf`-Datei.

### Geändert

- **[API]** `BudgetEngine` Initialisierung in `src/api.py` aktualisiert, um `rgf_config` zu übergeben.
- **[BudgetEngine]** `reserve_budget`-Methode in `src/engine.py` akzeptiert nun `model` und `max_tokens` zur detaillierteren Überprüfung durch `.rgf`-Regeln.

## v0.4.2 - 2026-05-28

### Hinzugefügt

- **[API]** Neue Endpunkte `/api/v1/user/keys` (GET) und `/api/v1/user/keys/{key_id}` (DELETE) zum Verwalten von API-Schlüsseln auf Organisationsebene.
- **[Dashboard]** Ein neues Dashboard-Modul zur API-Schlüsselverwaltung in `dash/index.html`, das Nutzern das Anzeigen und Widerrufen ihrer eigenen API-Schlüssel ermöglicht.
- **[Dashboard]** Visuelle Verbesserungen für API-Schlüssel-Statustablellen und Aktions-Buttons.

## v0.4.1 - 2026-05-28

### Gefeatured

- `llm_call` wurde zur Liste der erlaubten `resource_type` in `BookingRequest` hinzugefügt, was Flexibilität bei der Ressourcenzuweisung erhöht.

### Gefixt

- **[api.py]** Doppelte Definition von `list_agents` entfernt, um Code-Redundanz und potenzielle Fehler zu vermeiden.
- **[api.py]** `httpx.AsyncClient` wurde für Connection Pooling global initialisiert und in den `lifespan`-Kontextmanager verschoben, um Socket-Erschöpfung zu verhindern.
- **[api.py]** Korrektur der Streaming-Proxy-Nutzungsberechnung: Fallback auf `max_tokens` bei fehlendem Token-Usage aus Streaming-Chunks, um akkurate Kostenschätzungen zu gewährleisten.
- **[api.py]** Verbesserte Fehlerbehandlung für `finalize_budget` bei Upstream-Fehlern, um das Blockieren von Prozessen zu verhindern und eine korrekte Protokollierung sicherzustellen.
- **[engine.py]** Ersetzte `last_insert_rowid()` durch `RETURNING id` für thread-sichere ID-Abrufe in SQLite 3.35+, um mögliche Race Conditions zu vermeiden.