<div align="center">

<img src="https://img.shields.io/badge/Python-3.12+-blue?logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
<img src="https://img.shields.io/badge/SQLite-WAL_Mode-003B57?logo=sqlite&logoColor=white" alt="SQLite">
<img src="https://img.shields.io/badge/Docker-OK-2496ED?logo=docker&logoColor=white" alt="Docker">
<img src="https://github.com/michael-ebering/resgov/actions/workflows/ci.yml/badge.svg" alt="CI Build Status">
<img src="https://img.shields.io/badge/License-BSL_1.1-orange" alt="License">
<a href="https://github.com/michael-ebering/resgov/stargazers"><img src="https://img.shields.io/github/stars/michael-ebering/resgov?style=social" alt="Stars"></a>

# Das Resource Governance Framework (RGF) f\u00fcr Multi-Agenten-Umgebungen

**Die fehlende Schaltkreissicherung zwischen deinen autonomen Agenten und deiner Kreditkarte.**
_LASS runaway-Agenten-Schleifen nicht \u00fcber Nacht dein API-Budget vernichten._

> **Hinweis:** Dies ist ein unabh\u00e4ngiges privates Open-Source-Projekt von Michael Ebering. Nicht mit einem Arbeitgeber verbunden oder von einem solchen unterst\u00fctzt.

ResGov ist eine leichtgewichtige Ultra-Latenz-Proxy- und Governance-Engine. Es erg\u00e4nzt MCP und A2A um eine strenge \u00f6konomische Schicht: Verhinderung von Kostenexplosionen durch Echtzeit-Quota-Durchsetzung, Budgetverfolgung pro Agenten und streamsichere Kostengovernance.

\ud83d\udce1 [Live-Demo](https://resgov.silentops.cloud) · [Quick Start](#-quick-start) · [Governance als Code](#-governance-als-code-die-rgf-datei) · [Architektur](#-architektur--produktionsdesign) · [API-Referenz](#-governance-api-reference) · [Dokumentation](docs/)

</div>

---

## \u26a1 Warum ResGov (RGF) existiert

### Das Problem
Deine Agenten tausende autonome API-Aufrufe. In dem Moment, in dem sie in einer rekursiven Schleife stecken, w\u00e4hrend du schl\u00e4fst, generieren sie katastrophale API-Rechnungen. Moderne LLM-Anbieter bieten Billing-Alerts, aber **keine granulare, Echtzeit-Budget-Durchsetzung auf Ausf\u00fchrungsebene**.

### Der Multi-Agenten-Stack
- **MCP** (Model Context Protocol) \u2192 Definiert _wie Agenten mit Tools sprechen_.
- **A2A** (Agent-to-Agent) \u2192 Definiert _wie Agenten Aufgaben delegieren_.
- **RGF** (Resource Governance Framework) \u2192 Definiert _wie Agenten **dein Geld ausgeben**_.

ResGov ist die erste Open-Source-L\u00f6sung der Industrie f\u00fcr die RGF-Schicht.

---

## \ud83d\udd27 Kernfunktionen

- **Transparenter LLM-Proxy:** Drop-in-Ersatz f\u00fcr OpenAI/Anthropic/OpenRouter-Endpunkte. Einfach den `base_url` deines Frameworks \u00e4ndern.
- **Atomar Pre-Commit & Finalize:** Reserviert eine pessimistische `max_cost` w\u00e4hrend einer Millisekunde DB-Lock zu Streamstart, streamt lockfree und erstattet die Differenz sofort nach Streamende. Zero Deadlocks.
- **Governance als Code (`.rgf`):** Definiere Limits, erlaubte Modelle und Tools \u00fcber eine todf einfache Konfigurationsdatei direkt in deinem Git-Repo.
- **Nicht-LLM-Reservierung (`/api/v1/book`):** Eine einheitliche Kontrollebene zum Drosseln und Auditen von bezahlten Web-Scrapern, Search-APIs oder Dateioperationen.
- **Multi-Tenant-Isolierung:** Echtweltbereit mit Organisation-Scoped und sicherer Zeilen-Datenisolierung.
- **Pr\u00e4diktive Budgetvorhersage:** Kosten\u00fcberschreitungen proaktiv verhindern mit KI-gest\u00fctzten Ausgabenvorhersagen.

---

## \ud83d\udcdd Governance als Code (Die `.rgf`-Datei)

\u00dcberspringe komplexe Dashboard-Konfigurationen f\u00fcr lokale oder Einzelinstanz-Setups. ResGov l\u00e4sst dich Budgets \u00fcber eine einfache, deklarative `.rgf`-Datei (TOML) in deinem Projektwurzel steuern.

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

## \ud83d\udcdd Pr\u00e4diktive Budgetvorhersage

ResGov nutzt historische Ausgabemuster um vorherzusagen, wann ein Agent sein Budget wahrscheinlich ersch\u00f6pfen wird. Das gibt dir Zeit zum Eingreifen _bevor_\u00fcberschreitungen auftreten.

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
Wenn ein Agent versucht, sein zugewiesenes .rgf-Budget zu \u00fcberschreiten, bricht ResGov den Aufruf sofort ab, bevor es den Upstream-Anbieter erreicht, und gibt einen sauberen 403 Forbidden zur\u00fcck:
```json
{
  "error": {
    "type": "budget_exceeded",
    "message": "Tagesbudget \u00fcberschritten. Limit: $3.00, Ausgegeben: $2.98, Ben\u00f6tigt: $0.15",
    "agent_id": "hermes",
    "reason": "daily_budget_exceeded"
  }
}
```

## \ud83d\udce1 Governance API-Referenz

**Interaktive API-Doku:** `GET /docs` (Swagger UI) · `GET /redoc` (ReDoc)

F\u00fcr Nicht-LLM-transaktionelle Jobs (z.B. Custom-Tool-Ausf\u00fchrungen, bezahltes Data-Scraping):
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

# Admin-Operationen (ben\u00f6tigt X-Admin-Token)
POST   /api/v1/admin/reset-daily     \u2192 Alle Tagesallokationen zur\u00fccksetzen
POST   /api/v1/admin/generate-key    \u2192 Neuen sicheren API-Schl\u00fcssel ausstellen
GET    /api/v1/audit                 \u2192 Paginierter System-Audit-Trail
GET    /metrics                      \u2192 Native Prometheus-Metrics
```

## \ud83d\uddc4\ufe0f Architektur & Produktionsdesign
```
                    \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
                    \u2502          RGF Broker              \u2502
                    \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2528
                                   \u2502
            \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
            \u2502          \u2502           \u2502           \u2502              \u2502
     \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2528\u250c\u2500\u2500\u2500\u25bc\u2500\u2500\u2500\u2500\u2500\u2528\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u25bc\u2500\u2500\u2500\u2500\u2500\u2528\u250c\u2500\u2500\u2500\u25bc\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2528\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2528
     \u2502   Auth    \u2502\u2502Budget \u2502\u2502  LLM    \u2502\u2502Webhooks\u2502\u2502 Prometheus \u2502
     \u2502   Layer   \u2502\u2502Engine \u2502\u2502  Proxy  \u2502\u2502Discord/\u2502\u2502  /metrics  \u2502
     \u2502 API Keys  \u2502\u2502       \u2502\u2502Reserve \u2502\u2502Slack    \u2502\u2502            \u2502
     \u2502 Admin Tok \u2502\u2502       \u2502\u2502Stream   \u2502\u2502HMAC     \u2502\u2502            \u2502
     \u2518\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2528\u2534\u2500\u2500\u2500\u25bc\u2500\u2500\u2500\u2500\u2500\u2528\u2502Finalize\u2502\u2518\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
                       \u2502     \u2502\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
                \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u25bc\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
                \u2502    SQLite (WAL)     \u2502
                \u2518\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
```

*   **SQLite-WAL-Core:** Nutzt gleichzeitige Lesevorg\u00e4nge und serialisierte Schnellschreibvorg\u00e4nge. Perfekt f\u00fcr Zero-Konfigurations-Einzelinstanzumgebungen und Edge-Infrastruktur.
*   **Pessimistische Stream-Reservation:** L\u00f6st Concurrency-Doppelabzug durch sofortiges Pr\u00fcfen und Abziehen der potenziellen `max_cost`. Die kostenintensive Streaming-Phase l\u00e4uft komplett lockfrei.
*   **Crash-Recovery-Guard:** H\u00e4ngende Reservationen verfallen und stellen sich nach 5 Minuten automatisch wieder her, wenn ein Agent mid-stream abst\u00fcrzt.

## \ud83d\uddfa\u00fe0f Roadmap

- [Developer-Onboarding](ONBOARDING.md) · [Deployment-Guide](DEPLOYMENT.md) · [.rgf-Beispiele](docs/rgf-examples.md)

### v0.5 (N\u00e4chstes)
*   [ ] Redis/Dragonfly-Backend f\u00fcr horizontale Multi-Instance-Proxy-Skalierung.
*   [ ] Out-of-the-box-Slack- & Discord-Alert-Layout-Engine-Integration.
*   [x] Pr\u00e4diktive Budgetvorhersage (Ausgaben-Geschwindigkeit-Heuristik).

### v0.6
*   [ ] Open Policy Agent (OPA) deklarative Engine-Integration.
*   [ ] Offizieller Terraform-Provider und Kubernetes-Helm-Charts.

### v1.0
*   [ ] Multi-tenant Managed Cloud SaaS (resgov.silentops.cloud).
*   [ ] Enterprise SSO / SAML & granulare rollenbasierte Zugangskontrolle (RBAC).

## \ud83d\udcdd Lizenz
Dieses Projekt ist unter der Business Source License 1.1 (BSL-1.1) lizenziert.
*   F\u00fcr immer kostenlos f\u00fcr pers\u00f6nliche Nutzung, Tests und interne nicht-kommerzielle Setups.
*   F\u00fcr immer kostenlos f\u00fcrs Produktions-Setup in Unternehmen mit &lt; $1M ARR.
*   \u00c4nderungsdatum: Automatischer \u00fcbergang in eine Open-Source-Apache-2.0-Lizenz am 1. Januar 2029.

<div align="center">
<sub>Gebaut von SilentOps mit starkem Fokus auf Korrektheit, Geschwindigkeit und Kostensicherungen.</sub>
\u2b50 Stern dieses Repo, wenn es dein API-Budget gerettet hat.
</div>
