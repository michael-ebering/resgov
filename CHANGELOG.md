# CHANGELOG

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