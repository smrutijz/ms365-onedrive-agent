# MS365 OneDrive Agent

A FastAPI service that exposes the full native Microsoft OneDrive feature set as a REST API, with secure token management via Azure Key Vault.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Two-App Identity Model](#two-app-identity-model)
- [Token Lifecycle](#token-lifecycle)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Getting Started](#getting-started)
- [API Endpoints](#api-endpoints)

---

## Overview

This service wraps the Microsoft Graph API and exposes all core OneDrive operations over a simple REST interface:

- Browse, search, and navigate files and folders
- Upload (simple and large file resumable), download, delete
- Create folders, rename, move, copy items
- Manage sharing links and permissions
- View and restore file version history
- Secure OAuth 2.0 token management — **login once, runs indefinitely**

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLIENT / USER                              │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTP
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                   FastAPI Application (:8000)                     │
│                        src/main.py                                │
└──────┬──────────────────────────────────────────┬────────────────┘
       │                                          │
       ▼                                          ▼
┌─────────────────┐                   ┌───────────────────────────┐
│  Token Manager  │                   │       Graph Client         │
│ token_manager   │                   │   oneDriveHelper.py        │
│     .py         │                   │                           │
│                 │                   │  All OneDrive operations   │
│ get_access_     │                   │  via Microsoft Graph v1.0  │
│   token()       │                   └──────────────┬────────────┘
│ refresh_access_ │                                  │ Bearer token
│   token()       │                                  ▼
└──────┬──────────┘                   ┌───────────────────────────┐
       │                              │   Microsoft Graph API      │
       ▼                              │  graph.microsoft.com/v1.0  │
┌─────────────────┐                   └───────────────────────────┘
│  Azure Key Vault│
│  keyvault.py    │
│                 │
│ access_token    │
│ refresh_token   │
│ token_expiry    │
└─────────────────┘
       ▲
       │ ClientSecretCredential
┌─────────────────┐
│ Service Principal│
│ SP_APP_CLIENT_* │
└─────────────────┘
```

---

## Two-App Identity Model

The service uses two separate Azure AD app registrations with distinct responsibilities:

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                      │
│   SERVICE PRINCIPAL APP            GRAPH DELEGATED APP               │
│   (SP_APP_CLIENT_*)                (GRAPH_APP_CLIENT_*)              │
│                                                                      │
│   Auth type:                       Auth type:                        │
│   client_credentials               authorization_code (first login)  │
│   (app-only, no user)              refresh_token (all subsequent)    │
│                                                                      │
│   Purpose:                         Purpose:                          │
│   Authenticate to Key Vault        Act on behalf of the user         │
│   Read / write secrets             Access user's OneDrive files      │
│                                    Delegated permission scope        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

| | Service Principal | Graph Delegated |
|---|---|---|
| Accesses | Azure Key Vault | Microsoft Graph / OneDrive |
| User consent | Not required | Required once (via `/login`) |
| Config vars | `SP_APP_CLIENT_*` | `GRAPH_APP_CLIENT_*` |

---

## Token Lifecycle

This is the most important thing to understand about how the service works.

### You only need to log in once

When you visit `/login` and complete the OAuth flow, Microsoft issues two tokens:

| Token | Lifetime | Stored in Key Vault |
|---|---|---|
| `access_token` | ~1 hour | `onedrive-access-token` |
| `refresh_token` | up to 90 days* | `onedrive-refresh-token` |
| expiry timestamp | — | `onedrive-token-expiry` |

> *Microsoft personal accounts: refresh token stays valid as long as it is used at least once every 90 days.

### What happens on every API request

```
Request arrives at any /drive/* endpoint
            ↓
token_manager.get_access_token()
            ↓
    Read onedrive-token-expiry from Key Vault
            ↓
    Is current time > expiry?
       /            \
     YES             NO
      ↓               ↓
refresh_access_    Return stored
  token()          access_token
      ↓
  POST to Microsoft
  grant_type=refresh_token
      ↓
  New access_token + expiry
  saved to Key Vault
      ↓
  Return new token
            ↓
GraphClient uses token as Bearer header
            ↓
Microsoft Graph API call succeeds ✅
```

### Why offline_access scope matters

```
GRAPH_APP_SCOPES=Files.ReadWrite offline_access
                                  ↑
                    This scope is what instructs Microsoft
                    to issue a refresh_token alongside the
                    access_token. Without it, you would need
                    to log in again every hour.
```

### When you DO need to log in again

- First time setup (no tokens in Key Vault yet)
- Refresh token expired (90 days of complete inactivity)
- User revokes app permissions in their Microsoft account settings

---

## Project Structure

```
ms365-onedrive-agent/
├── src/
│   ├── main.py                  FastAPI app — all REST endpoints
│   ├── core/
│   │   └── config.py            Thread-safe singleton config; validates
│   │                            required env vars at startup
│   ├── utils/
│   │   ├── keyvault.py          Azure Key Vault client (get/set secrets)
│   │   └── token_manager.py     Token lifecycle — expiry check, auto-refresh,
│   │                            module-level singleton
│   └── clients/
│       └── oneDriveHelper.py    Microsoft Graph API wrapper —
│                                all OneDrive operations
├── Dockerfile
├── docker-compose.yml           Dev (with hot reload)
├── docker-compose.prod.yml      Production
├── requirements.txt
└── .env
```

### Service dependency chain

```
config (singleton, validates env vars at startup)
    ↓
KeyVaultClient (Azure SDK — uses SP credentials)
    ↓
TokenManager (singleton — expiry check + auto-refresh)
    ↓
GraphClient (per-request — uses fresh token)
    ↓
Microsoft Graph API
```

---

## Configuration

Copy `.env.example` to `.env` and fill in all values. The app will refuse to start if any required variable is missing.

| Variable | Required | Description |
|---|---|---|
| `SP_APP_CLIENT_ID` | ✅ | Service Principal app client ID |
| `SP_APP_CLIENT_SECRET` | ✅ | Service Principal client secret |
| `SP_APP_TENANT_ID` | ✅ | Azure AD tenant ID |
| `KEY_VAULT_URL` | ✅ | `https://<name>.vault.azure.net/` |
| `GRAPH_APP_CLIENT_ID` | ✅ | Graph app (delegated) client ID |
| `GRAPH_APP_CLIENT_SECRET` | ✅ | Graph app client secret |
| `GRAPH_APP_REDIRECT_URI` | | Default: `http://localhost:8000/callback` |
| `GRAPH_APP_SCOPES` | | Default: `Files.ReadWrite offline_access` |
| `GRAPH_APP_TENANT` | | Default: `consumers` |
| `GRAPH_APP_AUTHORITY_URL` | | Default: `https://login.microsoftonline.com` |

---

## Getting Started

### Run with Docker (recommended)

```bash
# Copy and fill in env vars
cp .env.example .env

# Start
docker compose up -d

# View logs
docker compose logs -f sharepoint-agent
```

### Run locally

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### First-time login (one-time only)

```
1. Open http://localhost:8000/login in a browser
2. Sign in with your Microsoft account
3. Grant the requested permissions
4. You are redirected back — tokens are now stored in Key Vault
5. All future requests auto-refresh silently — no further login needed
```

### Swagger UI

```
http://localhost:8000/docs
```

---

## API Endpoints

### Auth
| Method | Path | Description |
|---|---|---|
| `GET` | `/login` | Redirect to Microsoft OAuth login (one-time setup) |
| `GET` | `/callback` | OAuth callback — stores tokens in Key Vault |

### Drive
| Method | Path | Description |
|---|---|---|
| `GET` | `/drive` | Drive metadata and storage quota |

### Browse
| Method | Path | Description |
|---|---|---|
| `GET` | `/drive/root` | List items at the OneDrive root |
| `GET` | `/drive/folder/{folder_id}` | List contents of a folder by ID |
| `GET` | `/drive/folder-by-path?path=` | List contents of a folder by path |

### Items
| Method | Path | Description |
|---|---|---|
| `GET` | `/drive/items/{item_id}` | Get item metadata by ID |
| `GET` | `/drive/item-by-path?path=` | Get item metadata by path |
| `PATCH` | `/drive/items/{item_id}/rename` | Rename a file or folder |
| `PATCH` | `/drive/items/{item_id}/move` | Move item to a different folder |
| `POST` | `/drive/items/{item_id}/copy` | Copy item (returns async monitor URL) |
| `DELETE` | `/drive/items/{item_id}` | Permanently delete a file or folder |

### Search & Discovery
| Method | Path | Description |
|---|---|---|
| `GET` | `/drive/search?q=` | Search OneDrive by keyword |
| `GET` | `/drive/recent` | Recently accessed files |
| `GET` | `/drive/shared-with-me` | Files shared with the signed-in user |

### Download
| Method | Path | Description |
|---|---|---|
| `GET` | `/drive/items/{item_id}/download` | Download file content |
| `GET` | `/drive/items/{item_id}/download-url` | Get a short-lived direct download URL |

### Upload
| Method | Path | Description |
|---|---|---|
| `POST` | `/drive/upload?path=` | Simple upload ≤ 4 MB |
| `POST` | `/drive/upload-large?path=` | Resumable chunked upload > 4 MB |

### Folders
| Method | Path | Description |
|---|---|---|
| `POST` | `/drive/folders` | Create a new folder |

### Sharing & Permissions
| Method | Path | Description |
|---|---|---|
| `POST` | `/drive/items/{item_id}/share` | Create a sharing link (view/edit, anonymous/org) |
| `GET` | `/drive/items/{item_id}/permissions` | List all permissions on an item |
| `DELETE` | `/drive/items/{item_id}/permissions/{permission_id}` | Revoke a permission |

### Thumbnails
| Method | Path | Description |
|---|---|---|
| `GET` | `/drive/items/{item_id}/thumbnails` | Get thumbnail URLs for an item |

### Version History
| Method | Path | Description |
|---|---|---|
| `GET` | `/drive/items/{item_id}/versions` | List version history of a file |
| `POST` | `/drive/items/{item_id}/versions/{version_id}/restore` | Restore a previous version |
