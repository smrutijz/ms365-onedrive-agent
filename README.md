# MS365 Agent — OneDrive & Mail

A FastAPI service that exposes Microsoft OneDrive and Outlook/Hotmail mail as a REST API, with multi-user JWT authentication and secure token management via Azure Key Vault.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Two-App Identity Model](#two-app-identity-model)
- [Authentication — Two Token Layers](#authentication--two-token-layers)
- [Token Lifecycle](#token-lifecycle)
- [Multi-User Support](#multi-user-support)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Getting Started](#getting-started)
- [API Endpoints](#api-endpoints)

---

## Overview

This service wraps the Microsoft Graph API and exposes core OneDrive and Outlook/Hotmail mail operations over a simple REST interface:

**OneDrive**
- Browse, search, and navigate files and folders
- Upload (simple and large file resumable), download, delete
- Create folders, rename, move, copy items
- Manage sharing links and permissions
- View file version history

**Mail (Outlook / Hotmail)**
- Browse mail folders and messages, search the mailbox
- Send, reply, reply-all, and forward email
- Mark as read/unread, move, and delete messages
- List and fetch attachments

**Shared across both**
- Multi-user JWT auth — each user logs in once, gets a Bearer token, uses it on every request

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          CLIENT / USER                                │
│                                                                       │
│  1. GET /login  →  browser OAuth flow  →  get JWT                    │
│  2. All /drive/* and /mail/* requests: Authorization: Bearer <jwt>   │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ HTTPS
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    FastAPI Application (:8000)                        │
│                src/main.py + src/api/v1/* routers                     │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  JWT Auth Layer  (every /drive/* and /mail/* request)       │     │
│  │                                                              │     │
│  │  get_current_user()                                          │     │
│  │    → decode & verify JWT signature (JWT_SECRET)             │     │
│  │    → check expiry                                            │     │
│  │    → return user email                                       │     │
│  └──────────────────────────┬──────────────────────────────────┘     │
│                             │ email                                   │
│                             ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  get_graph_client() / get_mail_client()                      │     │
│  │    → token_manager.get_access_token(email)                  │     │
│  │    → returns a client with a fresh Graph Bearer token       │     │
│  └──────────────────────────┬──────────────────────────────────┘     │
└─────────────────────────────┼────────────────────────────────────────┘
                              │
              ┌───────────────┴──────────────┐
              ▼                              ▼
┌─────────────────────┐         ┌───────────────────────────┐
│   Token Manager     │         │     Graph / Mail Clients   │
│  token_manager.py   │         │   oneDriveHelper.py        │
│                     │         │   mailHelper.py            │
│  Per-user secrets   │         │                            │
│  in Key Vault:      │         │  OneDrive + Mail operations│
│  {key}-access-token │         │  via Microsoft Graph v1.0  │
│  {key}-refresh-token│         └──────────────┬────────────┘
│  {key}-token-expiry │                        │ Bearer token
└──────────┬──────────┘                        ▼
           │                    ┌───────────────────────────┐
           │                    │   Microsoft Graph API      │
           ▼                    │  graph.microsoft.com/v1.0  │
┌─────────────────────┐         └───────────────────────────┘
│   Azure Key Vault   │
│    keyvault.py      │
└──────────┬──────────┘
           │ ClientSecretCredential
           ▼
┌─────────────────────┐
│  Service Principal  │
│  SP_APP_CLIENT_*    │
└─────────────────────┘
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
│   Read / write secrets             Access user's OneDrive & mailbox  │
│                                    Delegated permission scope        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

| | Service Principal | Graph Delegated |
|---|---|---|
| Accesses | Azure Key Vault | Microsoft Graph / OneDrive / Mail |
| User consent | Not required | Required once (via `/login`) |
| Config vars | `SP_APP_CLIENT_*` | `GRAPH_APP_CLIENT_*` |

---

## Authentication — Two Token Layers

There are two completely separate token systems in play. Understanding the difference is important.

### Layer 1 — JWT (API authentication)

This is the token **you** hold and send to this API.

```
User logs in at /login
        ↓
Microsoft OAuth flow completes
        ↓
/callback issues a signed JWT:
{
  "access_token": "eyJ...",   ← this is the JWT
  "token_type": "bearer",
  "expires_at_utc": "2026-06-07T05:30:00Z",
  "user": "you@example.com"
}
        ↓
You send it on every /drive/* call:
Authorization: Bearer eyJ...
        ↓
API validates:
  1. Signature correct (JWT_SECRET)?
  2. Not expired (1 hour)?
```

**JWT payload:**
```json
{ "email": "you@example.com", "exp": 1781342229 }
```

- `email` — identifies the user; used to look up their Graph tokens in Key Vault
- `exp` — expiry timestamp (1 hour from issue)

### Layer 2 — Microsoft Graph tokens (OneDrive + Mail access)

These are tokens the API holds on your behalf. You never see them. The same delegated Graph token is used for both `/drive/*` and `/mail/*` calls — there's only one token pair per user, scoped to cover Files and Mail permissions together.

```
Stored in Azure Key Vault per user:
  {email-key}-access-token    ← used to call Microsoft Graph API
  {email-key}-refresh-token   ← used to get new access tokens silently
  {email-key}-token-expiry    ← Unix timestamp when access token expires
```

`email-key` is the email with all non-alphanumeric characters replaced by hyphens:
`smrutijz@outlook.com` → `smrutijz-outlook-com`

---

## Token Lifecycle

### What happens on every /drive/* or /mail/* request

```
Incoming request: GET /drive/root  (or GET /mail/messages)
Authorization: Bearer <jwt>
            ↓
── JWT Validation ──────────────────────────────────────
  Decode JWT with JWT_SECRET
  Check exp → not expired?
            ↓
── Graph Token Fetch ───────────────────────────────────
  Read {email-key}-token-expiry from Key Vault
            ↓
     Is current time > expiry?
        /               \
      YES                NO
       ↓                  ↓
  POST to Microsoft    Return stored
  grant_type=          access-token
  refresh_token
       ↓
  New access_token
  + new expiry
  saved to Key Vault
       ↓
── Graph API Call ──────────────────────────────────────
  GraphClient / MailClient calls graph.microsoft.com/v1.0
  with fresh Bearer access_token
            ↓
  Response returned to caller ✅
```

### Why offline_access scope matters

```
GRAPH_APP_SCOPES=User.Read Files.ReadWrite Mail.ReadWrite Mail.Send offline_access
                                                                     ↑
                    This scope instructs Microsoft to issue
                    a refresh_token alongside the access_token.
                    Without it, the access_token expires in ~1 hour
                    and you must log in again manually.
                    With it, the refresh_token silently gets a new
                    access_token for up to 90 days.
```

### When you need to log in again

| Reason | What happens |
|---|---|
| First time setup | No tokens in Key Vault yet |
| JWT expired | 1 hour has passed — get a new JWT at `/login`, or call `POST /refresh` with your current (still-valid) JWT to skip the redirect flow |
| Refresh token expired | 90 days of complete inactivity — Microsoft requires re-auth |
| User revoked app permissions | Microsoft invalidates all tokens |
| Logged out (`POST /logout`) | Graph tokens deleted from Key Vault — `/drive/*`/`/mail/*` calls fail until you `/login` again |

Logging in again issues a brand-new JWT — it doesn't invalidate JWTs issued
by previous logins, which simply expire on their own (within an hour, by
default). `POST /logout` doesn't invalidate your current JWT either (JWTs are
stateless and self-expiring) — it only revokes the underlying Microsoft Graph
tokens, so the JWT stops being useful for `/drive/*`/`/mail/*` calls until you
authenticate again.

---

## Multi-User Support

Multiple users can use the same deployed API instance independently. Each user:

1. Visits `/login` and signs in with their own Microsoft account
2. Gets their own JWT
3. Has their own set of secrets in Key Vault under their email prefix
4. Can only access their own OneDrive and mailbox — the JWT and Key Vault secrets are tied to their email

```
Key Vault secrets layout (example — two users):

smrutijz-outlook-com-access-token
smrutijz-outlook-com-refresh-token
smrutijz-outlook-com-token-expiry

alice-contoso-com-access-token
alice-contoso-com-refresh-token
alice-contoso-com-token-expiry
```

---

## Project Structure

```
ms365-onedrive-agent/
├── src/
│   ├── main.py                  FastAPI app — creates the app, includes routers
│   ├── api/
│   │   ├── deps.py              Shared dependencies — get_current_user,
│   │   │                        get_graph_client, get_mail_client
│   │   └── v1/
│   │       ├── auth.py          /login, /callback, /refresh, /logout
│   │       ├── onedrive.py      All /drive/* routes + request bodies
│   │       └── mail.py          All /mail/* routes + request bodies
│   ├── core/
│   │   └── config.py            Thread-safe singleton config; validates
│   │                            required env vars at startup
│   ├── utils/
│   │   ├── keyvault.py          Azure Key Vault client (get/set secrets)
│   │   └── token_manager.py     Per-user token lifecycle — expiry check,
│   │                            auto-refresh, singleton
│   └── clients/
│       ├── oneDriveHelper.py    Microsoft Graph API wrapper —
│       │                        all OneDrive operations
│       └── mailHelper.py        Microsoft Graph API wrapper —
│                                Outlook/Hotmail mail operations
├── tests/                       Test suite (pytest)
├── Dockerfile
├── docker-compose.yml           Dev (with hot reload)
├── docker-compose.prod.yml      Production
├── requirements.txt
├── .env.example                 Template — copy to .env and fill in
└── .env                         Your local secrets (gitignored)
```

### Service dependency chain

```
config (singleton, validates env vars at startup)
    ↓
KeyVaultClient (Azure SDK — uses SP credentials)
    ↓
TokenManager (singleton — per-user expiry check, auto-refresh)
    ↓
JWT validation (get_current_user) → email extracted from token
    ↓
GraphClient / MailClient (per-request — uses fresh Graph access token)
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
| `JWT_SECRET` | ✅ | Secret key used to sign and verify Bearer JWTs |
| `GRAPH_APP_REDIRECT_URI` | | Default: `http://localhost:8000/callback` |
| `GRAPH_APP_SCOPES` | | Default: `User.Read Files.ReadWrite Mail.ReadWrite Mail.Send offline_access` |
| `GRAPH_APP_TENANT` | | Default: `consumers` |
| `GRAPH_APP_AUTHORITY_URL` | | Default: `https://login.microsoftonline.com` |
| `JWT_EXPIRY_HOURS` | | Default: `1` — how long issued Bearer JWTs remain valid |

> Generate a strong `JWT_SECRET` with: `python -c "import secrets; print(secrets.token_hex(32))"`

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

### Login and get your Bearer token

```
1. Open http://localhost:8000/login in a browser
2. Sign in with your Microsoft account
3. Grant the requested permissions
4. You are redirected to /callback — Graph tokens (covering both OneDrive
   and Mail) are stored in Key Vault and a signed JWT is returned:

   {
     "access_token": "<your-bearer-jwt>",
     "token_type": "bearer",
     "expires_at_utc": "2026-06-07T05:30:00Z",
     "user": "you@example.com"
   }

5. Copy the access_token value. Use it on every /drive/* and /mail/* request:
   Authorization: Bearer <your-bearer-jwt>

6. Graph tokens auto-refresh silently — no further login needed
   unless the JWT expires (1 hour) or you log in again on another device.
   Before it expires, call POST /refresh (with your current JWT as the
   Bearer token) to get a fresh one without the /login redirect. Once it
   has expired, hit /login again instead.
7. Done with a session? POST /logout revokes your stored Graph tokens —
   /drive/* and /mail/* calls will then require logging in again.
```

### Swagger UI

```
http://localhost:8000/docs
```

Click **Authorize** (top right), paste just `<your-jwt>` (no `Bearer ` prefix — Swagger adds it automatically) to test authenticated endpoints directly from the browser.

---

## API Endpoints

All `/drive/*` and `/mail/*` endpoints require: `Authorization: Bearer <jwt>`

### Auth
| Method | Path | Description |
|---|---|---|
| `GET` | `/login` | Redirect to Microsoft OAuth login |
| `GET` | `/callback` | OAuth callback — stores Graph tokens (OneDrive + Mail) in Key Vault, returns JWT |
| `POST` | `/refresh` | Re-issue a fresh JWT for an already-authenticated user (requires valid Bearer JWT) |
| `POST` | `/logout` | Revoke the user's stored Graph tokens in Key Vault (requires valid Bearer JWT) |

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

---

### Mail Folders
| Method | Path | Description |
|---|---|---|
| `GET` | `/mail/folders` | List mail folders (Inbox, Sent Items, Drafts, etc.) |
| `GET` | `/mail/folders/{folder_id}/messages` | List messages in a specific folder |

### Mail Messages
| Method | Path | Description |
|---|---|---|
| `GET` | `/mail/messages` | List messages across the mailbox |
| `GET` | `/mail/messages/{message_id}` | Get full metadata and body for a message |
| `PATCH` | `/mail/messages/{message_id}` | Update message properties (e.g. mark read/unread) |
| `DELETE` | `/mail/messages/{message_id}` | Permanently delete a message |
| `PATCH` | `/mail/messages/{message_id}/move` | Move a message to a different folder |

### Mail Search
| Method | Path | Description |
|---|---|---|
| `GET` | `/mail/search?q=` | Search messages by keyword |

### Mail Send
| Method | Path | Description |
|---|---|---|
| `POST` | `/mail/send` | Compose and send a new email |
| `POST` | `/mail/messages/{message_id}/reply` | Reply to the sender of a message |
| `POST` | `/mail/messages/{message_id}/reply-all` | Reply to all recipients of a message |
| `POST` | `/mail/messages/{message_id}/forward` | Forward a message to new recipients |

### Mail Attachments
| Method | Path | Description |
|---|---|---|
| `GET` | `/mail/messages/{message_id}/attachments` | List attachments on a message |
| `GET` | `/mail/messages/{message_id}/attachments/{attachment_id}` | Get a single attachment (incl. base64 content) |
