<!--

Eclipse Tractus-X - Industry Core Hub Backend

Copyright (c) 2025 Contributors to the Eclipse Foundation

See the NOTICE file(s) distributed with this work for additional
information regarding copyright ownership.

This work is made available under the terms of the
Creative Commons Attribution 4.0 International (CC-BY-4.0) license,
which is available at
https://creativecommons.org/licenses/by/4.0/legalcode.

SPDX-License-Identifier: CC-BY-4.0

-->

# 5. MCP KIT Add-On

Date: 2026-06-11

## Status

Accepted

## Context

AI clients such as Claude Desktop and Microsoft Copilot Studio speak the
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/), an emerging
open standard that lets language models call typed tools exposed by a server.
IC-Hub already contains all the orchestration logic needed to discover partners,
browse digital twins, provision catalog parts, and exchange submodels in the
Tractus-X dataspace. The MCP KIT add-on surfaces that logic as high-level,
use-case-oriented MCP tools so that non-technical users can interact with the
dataspace via natural-language chat without writing code or understanding
EDC/DTR internals.

## Decision

Add a new in-process add-on (`mcp_kit`) that mirrors the structure of the
existing EcoPass KIT and mounts a
[FastMCP](https://gofastmcp.com/) ASGI sub-application at
`/addons/mcp-kit/mcp`. The add-on is enabled by default
(`addons.mcp_kit.enabled: true`) and introduces no behavioural change for
existing users when disabled.

### Placement and layer conventions

The MCP KIT is a peer of the EcoPass KIT at Layer 4 (Use Case Add-ons):

```
controllers/fastapi/routers/addons/
  ├── ecopass_kit/…
  └── mcp_kit/           ← new — mounts FastMCP at /addons/mcp-kit/mcp

managers/addons_service/
  ├── ecopass_kit/…
  └── mcp_kit/           ← new — server, session, auth, audit, adapters

models/services/addons/
  ├── ecopass_kit/…
  └── mcp_kit/           ← new — tool I/O and session DTOs
```

No changes to Layer 3 (IC-Hub orchestration managers) or below.

### Auth model

MCP clients authenticate via Bearer token or OAuth 2.1 against IC-Hub's existing Keycloak
realm. IC-Hub uses its own credentials for all downstream calls to EDC, DTR,
and submodel servers. End-user identity is recorded in IC-Hub's audit log but
is **not** impersonated into the dataspace.

Because the MCP ASGI sub-application is mounted directly on the FastAPI app
via `app.mount()` (bypassing the router dependency-injection system), auth is
enforced inside FastMCP via the `auth=` parameter, independent of the
`get_authentication_dependency()` guard used by the REST API.

#### Operating modes

| `authorization.enabled` | `authorization.keycloak.enabled` | MCP auth behaviour                                               |
|-------------------------|----------------------------------|------------------------------------------------------------------|
| `false`                 | any                              | No auth — endpoint publicly accessible (dev/test only)           |
| `true`                  | `true`                           | `KeycloakAuthProvider` (DCR + JWT validation + API-key fallback) |
| `true`                  | `false`                          | API-key Bearer fallback only; OAuth browser flow unavailable     |

#### Keycloak setup

The `KeycloakAuthProvider` uses **Dynamic Client Registration (DCR)** so that
MCP clients (Claude Desktop, Copilot Studio) can register themselves
automatically on first connect without any manual Keycloak client setup.

**Prerequisites:**

1. **Keycloak ≥ 26.6.0** — earlier versions have a DCR incompatibility with
   MCP clients (fixed in [keycloak#45309](https://github.com/keycloak/keycloak/pull/45309)).

2. **Enable DCR on the realm** — in Keycloak Admin Console:
    - Realm Settings → Client Registration → Anonymous access → Enabled
    - This allows MCP clients to register without pre-shared credentials.

3. **Set `hostname` in `configuration.yml`** to the publicly accessible URL of
   IC-Hub (e.g. `https://ichub.example.com`). The MCP endpoint URL is derived
   from this: `{hostname}/addons/mcp-kit/mcp`.

4. **IC-Hub configuration:**
   ```yaml
   authorization:
     enabled: true
     keycloak:
       enabled: true
       auth_url: "https://keycloak.example.com"
       realm: "ICHub"
   addons:
     mcp_kit:
       enabled: true
       oauth_enabled: true
   hostname: "https://ichub.example.com"
   ```

#### API-key Bearer fallback

System-to-system callers (scripts, CI pipelines) can pass IC-Hub's configured
API key as a Bearer token:

```
Authorization: Bearer <value-of-authorization.api_key.value>
```

This is accepted alongside Keycloak JWTs; the combined verifier tries both in
order.

#### Token validation logic

`managers/addons_service/mcp_kit/v1/auth.py` builds a `CombinedTokenVerifier`
that tries verifiers in order:

1. `JWTVerifier` — validates Keycloak-issued JWTs via the JWKS endpoint at
   `{keycloak_auth_url}/realms/{realm}/protocol/openid-connect/certs`
2. `ApiKeyTokenVerifier` — checks the raw token string against the configured
   API key value

The combined verifier is passed as `token_verifier` to `KeycloakAuthProvider`,
which also wires the DCR and token-exchange proxy endpoints.

### Session state

Per-MCP-session state is held in-process (optionally Redis for multi-replica).
No new Postgres tables and no Alembic migrations are introduced.

### Write-tool confirmation gate

Write tools (create, update, share) return a preview on the first call and
execute only when called a second time with identical arguments. This behaviour
is controlled by `addons.mcp_kit.require_confirmation_for_writes` (default
`true`); set it to `false` to execute write tools on the first call. The state
machine lives in `managers/addons_service/mcp_kit/v1/confirmation.py`.

### Deviation — calling `SharingService` directly

Most add-on tools delegate to managers, as EcoPass does. The single exception
is `share_catalog_part`: the atomic "submodel store + DTR shell + EDC asset +
policy + contract" sequence exists only in
`services/provider/sharing_service.py`. Duplicating it inside the MCP KIT
would fork critical business logic.

**Decision**: `adapters/industry_core.py` calls `SharingService` directly.
This is a deliberate, narrow exception, annotated at the call site. Step 7
shipped with this direct-call approach.

**Alternative still open with maintainers**: extract a `SharingManager`
that both `SharingService` and the MCP adapter depend on. This preserves the
no-direct-service-call convention but requires a larger refactor. It can be
applied later without changing the MCP tool surface.

## Consequences

- A new optional dependency (`fastmcp`) is added to `requirements.txt`.
- All new packages are importable with the add-on disabled; no existing
  behaviour changes.
- Operators do **not** need to pre-register a Keycloak client: MCP clients
  self-register via Dynamic Client Registration (DCR). Operators only enable
  anonymous client registration on the realm and set `hostname` (see Keycloak
  setup above).
- The `SharingService` deviation shipped in step 7 with the direct-call
  approach; the optional `SharingManager` refactor remains open with
  maintainers and does not affect the MCP tool surface.
