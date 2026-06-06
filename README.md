# MS365 OneDrive Agent

An intelligent, LLM-powered file discovery and navigation system for Microsoft 365 OneDrive, built with FastAPI, LangGraph, and Azure services.

---

## Table of Contents

- [Overview](#overview)
- [Architecture Overview](#architecture-overview)
- [Service Principal & Delegation Architecture](#service-principal--delegation-architecture)
- [Authentication Flow](#authentication-flow)
- [Component Breakdown](#component-breakdown)
- [Agent Orchestration](#agent-orchestration)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)

---

## Overview

This project provides an AI agent that can **intelligently navigate and discover files** within a Microsoft 365 OneDrive. Given a natural language query (e.g., *"find the Q3 budget spreadsheet"*), the agent traverses the OneDrive folder tree, uses an LLM to make navigation decisions, and returns the most relevant file — including its extracted content.

**Key capabilities:**
- OAuth 2.0 delegated authentication against Microsoft Graph API
- Secure secret management via Azure Key Vault
- LLM-guided folder tree traversal using LangGraph
- Universal document content extraction (PDF, DOCX, PPTX, XLSX, and more)
- REST API via FastAPI

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CLIENT / USER                                   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ HTTP
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                               │
│                         src/main.py (:8000)                              │
│                                                                          │
│   GET /login        GET /callback      GET /drive/root                   │
│   GET /drive/folder/{id}               GET /drive/search?q=...           │
└──────┬─────────────────┬───────────────────────────┬────────────────────┘
       │                 │                           │
       ▼                 ▼                           ▼
┌────────────┐  ┌─────────────────┐       ┌──────────────────────────────┐
│   OAuth    │  │  Token Manager  │       │        LangGraph Agent        │
│  Redirect  │  │  token_manager  │       │     (onedrive_agent.py)       │
│  (MS Login)│  │    .py          │       │                              │
└────┬───────┘  └──────┬──────────┘       └──────────────┬───────────────┘
     │                 │                                  │
     │                 ▼                                  │
     │       ┌──────────────────┐                        │
     │       │  Azure Key Vault │                        │
     │       │  (keyvault.py)   │                        │
     │       │                  │                        │
     │       │  access_token    │                        │
     │       │  refresh_token   │                        │
     │       └──────────────────┘                        │
     │                                                   │
     │              Service Principal Auth               │
     │              (SP_APP_CLIENT_*)                    │
     │                                                   ▼
     │                                    ┌──────────────────────────────┐
     │                                    │      Graph API Client         │
     │                                    │   (oneDriveHelper.py)         │
     │                                    │                              │
     │                                    │  list_root()                 │
     │                                    │  list_folder(id)             │
     │                                    │  search(query)               │
     │                                    │  download_file(id)           │
     └──────────────────────────────────► │  upload_file(path, bytes)    │
                                          │  delete_item(id)             │
                                          └──────────────┬───────────────┘
                                                         │ HTTPS + Bearer Token
                                                         ▼
                                          ┌──────────────────────────────┐
                                          │   Microsoft Graph API v1.0   │
                                          │  graph.microsoft.com         │
                                          │                              │
                                          │  /me/drive/root/children     │
                                          │  /me/drive/items/{id}        │
                                          │  /me/drive/search(q=...)     │
                                          └──────────────────────────────┘
```

---

## Service Principal & Delegation Architecture

This project uses **two separate Azure AD app registrations** to cleanly separate concerns between infrastructure access and user data access.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     TWO-APP IDENTITY ARCHITECTURE                            │
│                                                                              │
│  ┌──────────────────────────────┐    ┌──────────────────────────────────┐   │
│  │   SERVICE PRINCIPAL APP      │    │       GRAPH DELEGATED APP        │   │
│  │   (SP_APP_CLIENT_*)          │    │       (GRAPH_APP_CLIENT_*)        │   │
│  │                              │    │                                  │   │
│  │  grant_type:                 │    │  grant_type:                     │   │
│  │    client_credentials        │    │    authorization_code (first)    │   │
│  │                              │    │    refresh_token (subsequent)    │   │
│  │  Purpose:                    │    │                                  │   │
│  │  ✓ Authenticate to           │    │  Purpose:                        │   │
│  │    Azure Key Vault           │    │  ✓ Act on behalf of a user       │   │
│  │  ✓ Read/write secrets        │    │  ✓ Access user's OneDrive        │   │
│  │  ✓ No user interaction       │    │  ✓ Delegated permission scope    │   │
│  │    needed                    │    │    Files.ReadWrite               │   │
│  │                              │    │    offline_access                │   │
│  └──────────────┬───────────────┘    └──────────────┬───────────────────┘   │
│                 │                                   │                        │
│                 │ ClientSecretCredential            │ OAuth2 Auth Code Flow  │
│                 ▼                                   ▼                        │
│       ┌──────────────────┐             ┌──────────────────────┐             │
│       │  Azure Key Vault │             │  Microsoft Identity   │             │
│       │                  │             │  Platform (AAD)       │             │
│       └──────────────────┘             └──────────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why Two Apps?

| Concern | Service Principal App | Graph Delegated App |
|---|---|---|
| **What it accesses** | Azure Key Vault | Microsoft Graph / OneDrive |
| **Auth type** | Client credentials (app-only) | Delegated (on behalf of user) |
| **User consent needed** | No | Yes (once via /login) |
| **Secrets stored** | None (IS the identity) | Tokens stored in Key Vault |
| **Config vars** | `SP_APP_CLIENT_*` | `GRAPH_APP_CLIENT_*` |

### Token Lifecycle & Delegation Flow

```
┌───────────────────────────────────────────────────────────────────────────┐
│                       TOKEN LIFECYCLE DIAGRAM                              │
│                                                                            │
│  STEP 1 – User Login (one-time)                                            │
│  ─────────────────────────────                                             │
│  User visits /login                                                        │
│       │                                                                    │
│       ▼                                                                    │
│  Redirect to Microsoft login (AUTH_URL with client_id, scopes, redirect)  │
│       │                                                                    │
│       ▼                                                                    │
│  User consents → Microsoft returns ?code=AUTH_CODE to /callback           │
│       │                                                                    │
│       ▼                                                                    │
│  Exchange code at TOKEN_URL for:                                           │
│    ├─ access_token  (short-lived ~1hr)  → stored in Key Vault              │
│    └─ refresh_token (long-lived)        → stored in Key Vault              │
│                                                                            │
│  STEP 2 – Subsequent API Calls                                             │
│  ─────────────────────────────                                             │
│  TokenManager.get_access_token()                                           │
│       │                                                                    │
│       ├─ Try Key Vault → get access_token                                  │
│       │       │                                                            │
│       │       ├─ Valid?  → Return token ──────────────────────────────┐   │
│       │       │                                                        │   │
│       │       └─ Expired / Missing?                                    │   │
│       │               │                                                │   │
│       │               ▼                                                │   │
│       └─ refresh_access_token()                                        │   │
│               │                                                        │   │
│               ├─ POST TOKEN_URL grant_type=refresh_token               │   │
│               │                                                        │   │
│               ├─ Update access_token in Key Vault                      │   │
│               └─ Update refresh_token in Key Vault → Return token ────┘   │
│                                                                            │
│  STEP 3 – Graph API Call                                                   │
│  ────────────────────────                                                  │
│  GraphClient uses token in Authorization: Bearer <access_token> header    │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

```
src/
├── main.py                    FastAPI app — REST endpoints, OAuth callback
│
├── core/
│   └── config.py              Thread-safe Singleton; loads .env vars,
│                              exposes AUTH_URL / TOKEN_URL derived properties
│
├── utils/
│   ├── keyvault.py            Thin wrapper around Azure SecretClient
│   │                          Uses SP credentials to authenticate to vault
│   └── token_manager.py       Manages token freshness; auto-refresh on expiry
│
├── clients/
│   ├── oneDriveHelper.py      GraphClient — all Microsoft Graph v1.0 calls
│   │                          list_root, list_folder, search, download,
│   │                          upload, delete, get_item
│   ├── graphAPIBetaSearch.py  Advanced Graph Beta search with KQL & pagination
│   └── docling.py             Universal file content extractor — supports
│                              PDF, DOCX, PPTX, XLSX, CSV, ZIP, code files,
│                              audio/video (returns JSON struct + Markdown)
│
└── agent-dev/
    ├── mainagent.py           Agent v1: query-refinement loop
    ├── new.py                 Agent v2: simplified tree traversal
    └── onedrive_agent.py      Agent v3 (production): full traversal
                               with decision tracing & rejection logging
```

### Service Dependency Graph

```
         Config
           │
    ┌──────┴──────┐
    │             │
KeyVaultClient   (env vars)
    │
TokenManager
    │
GraphClient ◄──── onedrive_agent (injected via LangGraph configurable)
    │
Microsoft Graph API
```

---

## Agent Orchestration

The LangGraph agent (v3: `onedrive_agent.py`) traverses the OneDrive folder tree using LLM-guided decisions.

### Agent State Machine

```
                         ┌──────────────┐
                         │ resolve_start │
                         │              │
                         │ Determine    │
                         │ starting     │
                         │ folder/root  │
                         └──────┬───────┘
                                │
                                ▼
                    ┌──────────────────────┐
                ┌──►│    list_children     │◄──────────────────────┐
                │   │                      │                        │
                │   │ Fetch folder items   │                        │
                │   │ via GraphClient      │                        │
                │   └──────────┬───────────┘                        │
                │              │                                    │
                │              ▼                                    │
                │   ┌──────────────────────┐                        │
                │   │     decide_next      │                        │
                │   │                      │                        │
                │   │ LLM receives:        │                        │
                │   │  - query             │                        │
                │   │  - current items     │                        │
                │   │  - visited history   │                        │
                │   │  - rejected paths    │                        │
                │   │                      │                        │
                │   │ LLM outputs Decision │                        │
                │   │  action:             │                        │
                │   │   enter_folder  ─────┼────────────────────────┘
                │   │   select_file   ─────┼──────┐
                │   └──────────────────────┘      │
                │                                 ▼
                │                    ┌────────────────────────┐
                │                    │  download_and_verify   │
                │                    │                        │
                │                    │ 1. Download file bytes │
                │                    │ 2. Extract content     │
                │                    │    (Docling)           │
                │                    │ 3. LLM scores          │
                │                    │    relevance:          │
                │                    │    0.0 / 0.5 / 1.0    │
                │                    │                        │
                │   score < 1.0 ─────┤                        │
                └───────────────────-┤  score == 1.0          │
                                     └──────────┬─────────────┘
                                                │
                                                ▼
                                           ┌────────┐
                                           │  END   │
                                           │        │
                                           │ Return │
                                           │ found  │
                                           │ file   │
                                           └────────┘

  Max attempts (default 3) reached at any node → END
```

### LLM Decision Tools

```python
# trustcall extracts a structured Decision from the LLM
extractor = trustcall.create_extractor(
    llm,
    tools=[Decision],
    tool_choice="Decision"
)

class Decision(BaseModel):
    action: Literal["enter_folder", "select_file"]
    target_id: str
    target_name: str
    reasoning: str
```

### Agent State Model

```python
class AgentState(TypedDict):
    query: str                      # User's search query
    current_folder_id: str          # Active folder being explored
    current_items: list[dict]       # Items in current folder
    visited_items: set[str]         # IDs already seen (append reducer)
    decision_trace: list[DecisionStep]  # Full audit log (append reducer)
    rejected_paths: list[RejectedPath]  # Dead ends logged (append reducer)
    found_file: FoundFile | None    # Final result
    done: bool                      # Terminal flag
    attempt: int                    # Iteration counter
    max_attempts: int               # Configurable limit (default 3)
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Docker (optional)
- Azure subscription with:
  - Key Vault
  - Two App Registrations (see [Configuration](#configuration))
- OpenAI API key

### Run Locally

```bash
# 1. Clone and install dependencies
git clone <repo>
cd ms365-onedrive-agent
pip install -r requirements.txt

# 2. Copy and fill in environment variables
cp .env.example .env
# edit .env with your values

# 3. Start the server
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### Run with Docker

```bash
# Development (with hot reload)
docker compose up

# Production
docker compose -f docker-compose.prod.yml up
```

### Authorize OneDrive Access (First Time)

```
1. Open http://localhost:8000/login in a browser
2. Sign in with your Microsoft account
3. Grant the requested permissions
4. You will be redirected back — tokens are now stored in Key Vault
```

---

## Configuration

| Variable | Description | Used By |
|---|---|---|
| `SP_APP_CLIENT_ID` | Service Principal app client ID | Key Vault auth |
| `SP_APP_CLIENT_SECRET` | Service Principal client secret | Key Vault auth |
| `SP_APP_TENANT_ID` | Azure AD tenant ID | Key Vault auth |
| `KEY_VAULT_URL` | `https://<name>.vault.azure.net/` | KeyVaultClient |
| `GRAPH_APP_CLIENT_ID` | Graph app client ID | OAuth login, token refresh |
| `GRAPH_APP_CLIENT_SECRET` | Graph app client secret | OAuth token exchange |
| `GRAPH_APP_REDIRECT_URI` | `http://localhost:8000/callback` | OAuth callback |
| `GRAPH_APP_SCOPES` | `Files.ReadWrite offline_access` | OAuth consent |
| `GRAPH_APP_TENANT` | `consumers` or tenant ID | OAuth authority |
| `GRAPH_APP_AUTHORITY_URL` | `https://login.microsoftonline.com` | OAuth URLs |
| `OPENAI_API_KEY` | OpenAI API key | LangGraph agent |
| `OPENAI_MODEL` | e.g. `gpt-4o-mini` | LangGraph agent |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/login` | Redirect to Microsoft OAuth login |
| `GET` | `/callback` | OAuth callback — exchanges code for tokens |
| `GET` | `/drive/root` | List OneDrive root items |
| `GET` | `/drive/folder/{folder_id}` | List contents of a specific folder |
| `GET` | `/drive/search?q={query}` | Search OneDrive by keyword |

---

## Project Structure Summary

```
ms365-onedrive-agent/
├── src/
│   ├── main.py                 FastAPI app entry point
│   ├── core/config.py          Singleton configuration manager
│   ├── utils/
│   │   ├── keyvault.py         Azure Key Vault client
│   │   └── token_manager.py    OAuth token refresh logic
│   ├── clients/
│   │   ├── oneDriveHelper.py   Microsoft Graph API wrapper
│   │   ├── graphAPIBetaSearch.py  Advanced KQL search client
│   │   └── docling.py          Universal document content extractor
│   └── agent-dev/
│       ├── mainagent.py        Agent v1 — query refinement loop
│       ├── new.py              Agent v2 — tree traversal (simplified)
│       └── onedrive_agent.py   Agent v3 — production agent with tracing
├── tests/
│   └── test_keyvault.py        Unit tests
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── requirements.txt
└── .env.example
```
