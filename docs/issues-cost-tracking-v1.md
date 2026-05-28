# RGF Cost Tracking — Issues & Plan v1.0
> Erstellt: 2026-05-28 | Zustand: Draft | Owner: Michael

---

## Analyse: Aktueller Zustand

### Wie Kosten jetzt berechnet werden
1. **Preis-Tabelle** (`DEFAULT_PRICE_TABLE` in `api.py`): 8 Modelle hardcoded mit input/output Preis pro Token
2. **Token-Schätzung**: `len(prompt) // 4` = grobe Input-Token-Schätzung + `max_tokens` als Worst-Case-Output
3. **Kostenreservierung**: `reserve_budget()` deckt `input_tokens * input_price + max_tokens * output_price`
4. **Finalisierung**: `finalize_budget()` — Non-Stream nutzt `response.usage.total_tokens`; Stream extrahiert aus Chunks

### Identifizierte Bugs
| # | Bug | Schwere | Datei |
|---|-----|---------|-------|
| B1 | Non-Stream verwendet `total_tokens * output_price` statt `(input * input_price) + (output * output_price)` | Hoch | api.py:532 |
| B2 | Stream-Finalisierung nutzt `actual_tokens * output_price` — falsche Berechnung | Hoch | api.py:508 |
| B3 | Token-Extraktion misst nur OpenAI `data:` Format. Anthropic `event:` wird ignoriert | Mittel | api.py:384 |
| B4 | Preise werden nie aktualisiert — veraltet bei Preisänderungen | Mittel | api.py:347 |
| B5 | Prompt/4 Heuristik ist für Deutsch/Formatierung ungenau (Faktor 2-5x) | Mittel | api.py:378 |
| B6 | Keine Unterscheidung Input vs Output Tokens bei Finalisierung | Mittel | api.py:508,532 |

---

## Issues

### I1: Dynamic Price Table
**Problem:** `DEFAULT_PRICE_TABLE` wird nie aktualisiert. Provider ändern Preise regelmäßig.

**Lösung:**
- OpenRouter `/models` Endpoint (`GET https://openrouter.ai/api/v1/models`) alle 6 Stunden abrufen
- Response enthält `pricing.input` und `pricing.pro output` pro Modell
- In SQLite `price_cache` Tabelle speichern (`model, input_price, output_price, fetched_at`)
- `DEFAULT_PRICE_TABLE` als Fallback wenn API nicht erreichbar
- Env-Override `RESGOV_PRICE_TABLE` hat immer Priorität

**Acceptance Criteria:**
- [ ] `price_cache` Tabelle in `init_db()` erstellt
- [ ] Background-Job (alle 6h) ruft OpenRouter /models ab
- [ ] `_get_price_table()` checkt zuerst Cache (älter als 6h → refresh), dann ENV, dann DEFAULT
- [ ] Test: Cache wird bei Preisanfrage genutzt
- [ ] Test: Fallback zu DEFAULT wenn OpenRouter nicht erreichbar
- [ ] Test: ENV-Override hat Priorität

**Aufwand:** 2-3 Stunden

---

### I2: Provider-spezifische Token-Extraktion
**Problem:** `_extract_usage_from_chunk()` unterstützt nur OpenAI `data:` Stream-Format.

**Lösung: `src/providers.py` — 1-Datei pro Provider:**
```python
def extract_openai_usage(chunk) -> dict:  # data: {"usage": {...}}
def extract_anthropic_usage(chunk) -> dict:  # event: content_block_delta -> usage  
def extract_google_usage(chunk) -> dict:  # data: {...} mit usageMetadata
def extract_deepseek_usage(chunk) -> dict:  # OpenAI-kompatibel (verifizieren)
```

Dispatcher wählt anhand des `model`-Prefixes:
- `openai/*` → OpenAI-Extraktor
- `anthropic/*` → Anthropic-Extraktor
- `deepseek/*` → Deepseek-Extraktor
- `google/*` → Google-Extraktor
- Fallback → OpenAI-Extraktor

**Acceptance Criteria:**
- [ ] `src/providers.py` mit 4 Extraktor-Funktionen erstellt
- [ ] Dispatcher-Funktion `extract_usage(chunk, model) → dict`
- [ ] Test: OpenAI-Format korrekt extrahiert
- [ ] Test: Anthropic `event:` Format korrekt extrahiert
- [ ] Test: Unbekanntes Format gibt `{}` zurück (kein Crash)
- [ ] Integration: `api.py` nutzt statt `_extract_usage_from_chunk` den neuen Dispatcher

**Aufwand:** 2-3 Stunden

---

### I3: Actual vs Estimated Cost Tracking
**Problem:** CTO sieht nur `total_spent` pro Agent — keine Differenz zwischen geschätzt und tatsächlich.

**Lösung:**
- `bookings`-Tabelle erweitert: `estimated_cost REAL, actual_cost REAL` (nullable)
- `reserve_budget()` schreibt in `estimated_cost`
- `finalize_budget()` schreibt in `actual_cost` + `refund`
- `GET /api/v1/usage/{agent_id}` gibt pro Booking zurück: `{estimated, actual, refund}`

**DB-Migration:**
```sql
ALTER TABLE bookings ADD COLUMN estimated_cost REAL;
ALTER TABLE bookings ADD COLUMN actual_cost REAL;
```

**Acceptance Criteria:**
- [ ] Migration in `init_db()` eingebaut (nullable, rückwärtskompatibel)
- [ ] `reserve_budget()` speichert `estimated_cost`
- [ ] `finalize_budget()` speichert `actual_cost` + `refund`
- [ ] `get_usage()` gibt pro Booking `{estimated, actual, refund, diff_percent}` zurück
- [ ] Test: Reserve → Finalize → Booking zeigt korrekte estimated/actual/refund
- [ ] Test: Actual > Reserved (Underpayment) wird korrekt gebucht und geloggt

**Aufwand:** 1-2 Stunden

---

### I4: Non-Stream Finalisierung reparieren
**Problem:** Non-Stream Finalisierung in `api.py:532` nutzt falsche Formel.

**Fix:**
```python
# ALT (falsch):
actual_cost = round(actual_tokens * price_table[model]["output"], 6)

# NEU (korrekt):
usage = resp_data.get("usage", {})
input_tokens = usage.get("prompt_tokens", 0)
output_tokens = usage.get("completion_tokens", 0)
if not input_tokens:
    input_tokens = usage.get("input_tokens", len(prompt) // 4)
if not output_tokens:
    output_tokens = usage.get("output_tokens", max_tokens)
input_cost = input_tokens * pricing["input"]
output_cost = output_tokens * pricing["output"]
actual_cost = round(input_cost + output_cost, 6)
```

**Acceptance Criteria:**
- [ ] Input/Output Tokens werden separat aus Provider-Response extrahiert
- [ ] Input/Output Kosten werden separat berechnet
- [ ] Fallback zu Schätzung wenn Provider keine Usage-Daten liefert
- [ ] Test: GPT-4o Non-Stream → korrekte Kosten (input 1000t * 2.5e-6 + output 500t * 1e-5 = 0.0075)
- [ ] Test: Provider ohne Usage-Fallback nutzt Schätzung

**Aufwand:** 1 Stunde

---

### I5: Token-Schätzung verbessern
**Problem:** `len(prompt) // 4` ist grob. Deutsche Texte, JSON, Code haben andere Token/Char-Verhältnisse.

**Lösung (Stufe 1 — kein tiktoken nötig):**
```python
def estimate_token_count(text: str) -> int:
    """Improved token estimation.
    - English prose: ~4 chars/token
    - German text: ~3.2 chars/token (more compound words → more tokens)
    - JSON/Code: ~2.5 chars/token (special chars, brackets)
    - Mixed: weighted average
    """
    text_len = len(text)
    if not text_len:
        return 128  # default minimum
    
    # Heuristic: count special characters to determine content type
    special_ratio = sum(1 for c in text if c in '{[]}()=:;') / max(text_len, 1)
    german_ratio = sum(1 for c in text.lower() if c in 'äöüß') / max(text_len, 1)
    
    if special_ratio > 0.05:
        return max(text_len // 3, 128)  # Code/JSON
    elif german_ratio > 0.02:
        return max(text_len // 3, 128)  # German text
    else:
        return max(text_len // 4, 128)  # English/default
```

**Stufe 2 (optional, höhere Genauigkeit):** Optional `tiktoken` installieren und bei Verfügbarkeit nutzen.

**Acceptance Criteria:**
- [ ] `estimate_token_count()` mit Content-Type-Heuristik implementiert
- [ ] Test: Englischer Text (4000 chars → ~1000 tokens)
- [ ] Test: Deutscher Text (4000 chars → ~1250 tokens)
- [ ] Test: JSON (4000 chars → ~1300 tokens)
- [ ] Test: Leerer Text → 128 (default)
- [ ] `api.py` nutzt neue Funktion statt `len(prompt) // 4`

**Aufwand:** 1 Stunde

---

### I6: API-Key pro Provider Mapping
**Problem:** Ein Agent bekommt aktuell einen universel妥 API-Key. Wenn der Agent verschiedene Provider nutzt (z.B. OpenAI für Chat, Deepseek für Code), wird nicht welcher Key für welchen Provider verwendet wurde.

**Lösung:**
1. `api_keys`-Tabelle erweitert: `provider TEXT DEFAULT 'all'` (oder NULL für alle)
2. `create_api_key()` um `provider`-Parameter ergänzt
3. `GET /api/v1/admin/provider-keys` Endpoint — gibt pro Provider den Key zurück
4. LLM-Proxy wählt Upstream-Key basierend auf dem `model`-Prefix

**DB-Migration:**
```sql
ALTER TABLE api_keys ADD COLUMN provider TEXT DEFAULT 'all';
```

**Acceptance Criteria:**
- [ ] Migration in `init_db()` (nullable, rückwärtskompatibel)
- [ ] `create_api_key()` akzeptiert `provider`-Parameter
- [ ] `verify_api_key()` validiert Provider-Zuordnung
- [ ] Test: Agent mit `provider="openai"` → Deepseek-Request wird abgelehten
- [ ] Test: Agent mit `provider="all"` (oder NULL) → alle Providers erlaubt
- [ ] Test: `GET /api/v1/admin/provider-keys` gibt {openai: "**rgv_...", deepseek: "**rgv_..."}

**Aufwand:** 2 Stunden

---

### I7: Umfangreiche Test-Abdeckung

**Test-Level:**
1. **Unit-Tests**: Pro Provider-Extraktor, pro Schätzfunktion, pro DB-Migration
2. **Integrationstests**: Reserve→Finalize-Zyklus mit echten Memory-DB
3. **E2E-Tests**: Simulierte OpenRouter API (Mock) + Vollständiger Proxy-Durchlauf

**Testfälle pro Feature:**

| Feature | Testfälle | Nachweis |
|---------|-----------|----------|
| I1 Dynamic Price Cache | Cache-Miss, Cache-Hit, Stale-Cache-Refresh, Fallback | `tests/test_price_cache.py` |
| I2 Provider-Dispatcher | OpenAI-Chunk, Anthropic-Chunk, Unknown-Chunk, Empty-Chunk | `tests/test_providers.py` |
| I3 Actual vs Estimated | Booking nach Reserve/Finalize, Overpayment, Underpayment | `tests/test_cost_tracking.py` |
| I4 Non-Stream Fix | GPT-4o-Response, Anthropic-Response, No-Usage-Fallback | `tests/test_llm_proxy.py` |
| I5 Token-Schätzung | English, German, JSON, Empty, Very-Long | `tests/test_token_estimation.py` |
| I6 Provider Keys | Key-per-Provider, Universal-Key, Wrong-Provider-Deny | `tests/test_provider_keys.py` |

**Acceptance Criteria:**
- [ ] Alle Testfälle implementiert und grün
- [ ] Mindestens 90% Coverage für `api.py`, `providers.py`, `token_estimation.py`
- [ ] Kein Test schlägt fehl wenn OpenRouter nicht erreichbar ist (Mock)
- [ ] CI läuft durch (44+ Tests grün bei PR)

---

## Priorisierung und Reihenfolge (Eisenhower-Matrix)

| Prio | Issue | Warum | Impact |
|------|-------|-------|--------|
| **P0 Sofort** | I4: Non-Stream Fix | Bug — falsche Kostenberechnung. CTO sieht falsche Zahlen | Hoch — Vertrauensverlust |
| **P0 Sofort** | I3: Actual vs Estimated | Bugs B1+B2 — Grundlage für korrekte Kosten | hoch — Datenqualität |
| **P1 Diese Woche** | I2: Provider-Extraktion | Feature-Gap — ohne das funktioniert Stream-Tracking nur für OpenAI | Mittel |
| **P1 Diese Woche** | I5: Token-Schätzung | Iterative Verbesserung — Senkt Overestimation um ~30% | Mittel |
| **P2 Nächste Woche** | I1: Dynamic Price Cache | Wartbar — Verhindert manuelle Updates bei Preisänderungen | Niedrig-Mittel |
| **P2 Nächste Woche** | I6: Provider Keys | Multi-Provider-Support | Niedrig |
| **Parallel** | I7: Tests | Kontinuierlich während aller anderen Issues | Kritisch für Qualität |

**Geschätzter Gesamtaufwand:** 10-12 Stunden (+ Testzeit)

---

## Abnahmekriterien (Testabnahme durch Michael)

### Testprotokoll

| # | Test | Erwartetes Ergebnis | Status |
|---|------|---------------------|--------|
| T1 | Agent A mit GPT-4o Non-Stream Request (1000 input, 500 output tokens) | Cost ≈ (1000 × 2.5e-6) + (500 × 1.0e-5) = $0.0075 | ⬜ |
| T2 | Agent A mit Claude Sonnet Content-type Non-Stream | Cost = (input × 3e-6) + (output × 1.5e-5) ≠ total_tokens × output_price | ⬜ |
| T3 | Agent A tägliches Budget $5, nach 3 Requests mit unterschiedlichen Actual vs Estimated | `GET /usage/A` zeigt estimated_sum ≥ actual_sum | ⬜ |
| T4 | Preis-Update bei OpenRouter → Preise werden nach spätestens 6h automatisch aktualisiert | `GET /api/v1/admin/price-cache` zeigt neue Preise | ⬜ |
| T5 | Agent mit `provider="openai"` → Deepseek Request | 403 Fehlermeldung, kein Kosteneintrag in Bookings | ⬜ |
| T6 | Budget $0.01, Request kostet $0.007 (geschätzt $0.015) | Request wird reserviert → Finalize mit $0.007 → $0.008 refund | ⬜ |

**Sign-off:** Michael bestätigt alle 6 Tests als bestanden → Release v0.5.0.
