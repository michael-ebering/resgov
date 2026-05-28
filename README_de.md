<div align="center">

<img src="https://img.shields.io/badge/Python-3.12+-blue?logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
<img src="https://img.shields.io/badge/SQLite-WAL_Mode-003B57?logo=sqlite&logoColor=white" alt="SQLite">
<img src="https://img.shields.io/badge/Docker-OK-2496ED?logo=docker&logoColor=white" alt="Docker">
<img src="https://github.com/michael-ebering/resgov/actions/workflows/ci.yml/badge.svg" alt="CI Build Status">
<img src="https://img.shields.io/badge/License-BSL_1.1-orange" alt="License">
<a href="https://github.com/michael-ebering/resgov/stargazers"><img src="https://img.shields.io/github/stars/michael-ebering/resgov?style=social" alt="Stars"></a>

# Das Resource Governance Framework (RGF) für Multi-Agenten-Umgebungen

**Die fehlende Schaltkreissicherung zwischen deinen autonomen Agenten und deiner Kreditkarte.**
_LASS runaway-Agenten-Schleifen nicht über Nacht dein API-Budget vernichten._

> **Hinweis:** Dies ist ein unabhängiges privates Open-Source-Projekt von Michael Ebering. Nicht mit einem Arbeitgeber verbunden oder von einem solchen unterstützt.

ResGov ist eine leichtgewichtige Ultra-Latenz-Proxy- und Governance-Engine. Es ergänzt MCP und A2A um eine strenge ökonomische Schicht: Verhinderung von Kostenexplosionen durch Echtzeit-Quota-Durchsetzung, Budgetverfolgung pro Agenten und streamsichere Kostengovernance.

\ud83d\udce1 [Live-Demo](https://resgov.silentops.cloud) · [Quick Start](#-quick-start) · [Governance als Code](#-governance-als-code-die-rgf-datei) · [Architektur](#-architektur--produktionsdesign) · [API-Referenz](#-governance-api-reference) · [Dokumentation](docs/)

</div>

---

## ⚡ Warum ResGov (RGF) existiert

### Das Problem
Deine Agenten tausende autonome API-Aufrufe. In dem Moment, in dem sie in einer rekursiven Schleife stecken, während du schläfst, generieren sie katastrophale API-Rechnungen. Moderne LLM-Anbieter bieten Billing-Alerts, aber **keine granulare, Echtzeit-Budget-Durchsetzung auf Ausführungsebene**.

### Der Multi-Agenten-Stack
- **MCP** (Model Context Protocol) → Definiert _wie Agenten mit Tools sprechen_.
- **A2A** (Agent-to-Agent) → Definiert _wie Agenten Aufgaben delegieren_.
- **RGF** (Resource Governance Framework) → Definiert _wie Agenten **dein Geld ausgeben**_.

ResGov ist die erste Open-Source-Lösung der Industrie für die RGF-Schicht.

---

## \ud83d\udd27 Kernfunktionen

- **Transparenter LLM-Proxy:** Drop-in-Ersatz für OpenAI/Anthropic/OpenRouter-Endpunkte. Einfach den `base_url` deines Frameworks ändern.
- **Atomar Pre-Commit & Finalize:** Reserviert eine pessimistische `max_cost` während einer Millisekunde DB-Lock zu Streamstart, streamt lockfree und erstattet die Differenz sofort nach Streamende. Zero Deadlocks.
- **Governance als Code (`.rgf`):** Definiere Limits, erlaubte Modelle und Tools über eine todf einfache Konfigurationsdatei direkt in deinem Git-Repo.
- **Nicht-LLM-Reservierung (`/api/v1/book`):** Eine einheitliche Kontrollebene zum Drosseln und Auditen von bezahlten Web-Scrapern, Search-APIs oder Dateioperationen.
- **Multi-Tenant-Isolierung:** Echtweltbereit mit Organisation-Scoped und sicherer Zeilen-Datenisolierung.
- **Prädiktive Budgetvorhersage:** Kostenüberschreitungen proaktiv verhindern mit KI-gestützten Ausgabenvorhersagen.

---

## \ud83d\udcdd Governance als Code (Die `.rgf`-Datei)

Überspringe komplexe Dashboard-Konfigurationen für lokale oder Einzelinstanz-Setups. ResGov lässt dich Budgets über eine einfache, deklarative `.rgf`-Datei (TOML) in deinem Projektwurzel steuern.

```toml
# .rgf - Resource Governance Rules
# Doku: https://github.com/michael-ebering/resgov/blob/main/docs/rgf-examples.md

[global]
currency = "USD"
fail_safe_action = "deny" # Hard-Block bei Proxy-Ausfall

[agents.hermes]
daily_budget = 3.00
max_tokens_per_request = 4096
allowed_models = [
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/deepseek/deepseek-v4-flash"
]

[agents.research-bot]
daily_budget = 1.00
allowed_models = [
    "openrouter/openai/gpt-5-4-mini"
]
allowed_tools = ["web-scraper", "pexels_search"]
```

---

## \ud83d\udcdd Prädiktive Budgetvorhersage

ResGov nutzt historische Ausgabemuster um vorherzusagen, wann ein Agent sein Budget wahrscheinlich erschöpfen wird. Das gibt dir Zeit zum Eingreifen _bevor_überschreitungen auftreten.

Abfrage der Vorhersage-API:
```http
GET /api/v1/agents/my-agent-01/prediction?period=daily&lookback_hours=6
```

Beispiel-Antwort:
```json
{
  "status": "ok",
  "message": "Vorhersage erfolgreich.",
  "remaining_budget": 42.15,
  "rate_usd_per_hour": 1.75,
  "prediction_timestamp": "2026-05-29T14:30:00Z",
  "remaining_time_seconds": 86400.0
}
```

---

## \ud83d\ude80 Quick Start

### 1. Broker via Docker starten
```bash
git clone https://github.com/michael-ebering/resgov.git
cd resgov
cp .env.example .env          # RESGOV_ADMIN_TOKEN setzen
docker compose up -d

# Core Proxy API: http://localhost:8080/v1
# Dashboard:      http://localhost:8080/dash
# API Docs:       http://localhost:8080/docs
# Health V2:      http://localhost:8080/health
```

### 2. In dein Framework einbinden (Kein Custom Code)

#### CrewAI
```python
from crewai import Agent, LLM

llm = LLM(
    model="openai/anthropic/claude-sonnet-4-6",
    base_url="http://localhost:8080/v1", # Routet durch ResGov
    api_key="dein-rgf-api-key",
    extra_headers={"X-ResGov-Agent-ID": "hermes"},
)

agent = Agent(role="Analyst", llm=llm, goal="Streams verarbeiten...")
```

#### LangChain
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="anthropic/claude-sonnet-4-6",
    base_url="http://localhost:8080/v1",
    api_key="dein-rgf-api-key",
    default_headers={"X-ResGov-Agent-ID": "hermes"},
)
```

### \ud83d\uded1 Budget-verweigert-Interzeption
Wenn ein Agent versucht, sein zugewiesenes .rgf-Budget zu überschreiten, bricht ResGov den Aufruf sofort ab, bevor es den Upstream-Anbieter erreicht, und gibt einen sauberen 403 Forbidden zurück:
```json
{
  "error": {
    "type": "budget_exceeded",
    "message": "Tagesbudget überschritten. Limit: $3.00, Ausgegeben: $2.98, Benötigt: $0.15",
    "agent_id": "hermes",
    "reason": "daily_budget_exceeded"
  }
}
```

## \ud83d\udce1 Governance API-Referenz

**Interaktive API-Doku:** `GET /docs` (Swagger UI) · `GET /redoc` (ReDoc)

Für Nicht-LLM-transaktionelle Jobs (z.B. Custom-Tool-Ausführungen, bezahltes Data-Scraping):
```http
# Nicht-LLM-Ressource allokieren
POST /api/v1/book
{
    "agent_id": "research-bot",
    "resource_type": "api_call",
    "action": "pexels_search",
    "cost": 0.05,
    "metadata": {"query": "infrastructure"}
}

# Admin-Operationen (benötigt X-Admin-Token)
POST   /api/v1/admin/reset-daily     → Alle Tagesallokationen zurücksetzen
POST   /api/v1/admin/generate-key    → Neuen sicheren API-Schlüssel ausstellen
GET    /api/v1/audit                 → Paginierter System-Audit-Trail
GET    /metrics                      → Native Prometheus-Metrics
```

## 🏗️ Architektur & Produktionsdesign
```
                    ┌──────────────────────────────────┐
                    │          RGF Broker              │
                    └──────────────┬───────────────────┘
                                   │
            ┌──────────┬───────────┼───────────┬──────────────┐
            │          │           │           │              │
     ┌──────▼────┐ ┌───▼───┐ ┌────▼────┐ ┌───▼─────┐ ┌─────▼──────┐
     │   Auth    │ │Budget │ │  LLM    │ │Webhooks │ │ Prometheus │
     │   Layer   │ │Engine │ │  Proxy  │ │Discord/ │ │  /metrics  │
     │ API Keys  │ │       │ │Reserve  │ │Slack    │ │            │
     │ Admin Tok │ │       │ │Finalize │ │HMAC     │ │            │
     └───────────┘ └───┬───┘ └─────────┘ └─────────┘ └────────────┘
                       │
                ┌──────▼──────────────┐
                │    SQLite (WAL)     │
                └─────────────────────┘
```

*   **SQLite-WAL-Core:** Nutzt gleichzeitige Lesevorgänge und serialisierte Schnellschreibvorgänge. Perfekt für Zero-Konfigurations-Einzelinstanzumgebungen und Edge-Infrastruktur.
*   **Pessimistische Stream-Reservation:** Löst Concurrency-Doppelabzug durch sofortiges Prüfen und Abziehen der potenziellen `max_cost`. Die kostenintensive Streaming-Phase läuft komplett lockfrei.
*   **Crash-Recovery-Guard:** Hängende Reservationen verfallen und stellen sich nach 5 Minuten automatisch wieder her, wenn ein Agent mid-stream abstürzt.

## 🗺️ Roadmap

- [Developer-Onboarding](ONBOARDING.md) · [Deployment-Guide](DEPLOYMENT.md) · [.rgf-Beispiele](docs/rgf-examples.md)

### v0.5 (Nächstes)
*   [ ] Redis/Dragonfly-Backend für horizontale Multi-Instance-Proxy-Skalierung.
*   [ ] Out-of-the-box-Slack- & Discord-Alert-Layout-Engine-Integration.
*   [x] Prädiktive Budgetvorhersage (Ausgaben-Geschwindigkeit-Heuristik).

### v0.6
*   [ ] Open Policy Agent (OPA) deklarative Engine-Integration.
*   [ ] Offizieller Terraform-Provider und Kubernetes-Helm-Charts.

### v1.0
*   [ ] Multi-tenant Managed Cloud SaaS (resgov.silentops.cloud).
*   [ ] Enterprise SSO / SAML & granulare rollenbasierte Zugangskontrolle (RBAC).

## 📄 Lizenz
Dieses Projekt ist unter der Business Source License 1.1 (BSL-1.1) lizenziert.
*   Für immer kostenlos für persönliche Nutzung, Tests und interne nicht-kommerzielle Setups.
*   Für immer kostenlos fürs Produktions-Setup in Unternehmen mit &lt; $1M ARR.
*   Änderungsdatum: Automatischer übergang in eine Open-Source-Apache-2.0-Lizenz am 1. Januar 2029.

<div align="center">
<sub>Gebaut von SilentOps mit starkem Fokus auf Korrektheit, Geschwindigkeit und Kostensicherungen.</sub>
⭐ Stern dieses Repo, wenn es dein API-Budget gerettet hat.
</div>
