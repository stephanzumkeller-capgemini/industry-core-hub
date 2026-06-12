#################################################################################
# Industry Core Hub - MCP Addon
#
# Copyright (c) 2026 Capgemini
#
#################################################################################

# Keycloak OAuth 2.1 resource-server bridge for MCP clients.
#
# Reuses IC-Hub's existing Keycloak configuration (authorization.keycloak).
# Two operating modes:
#
#   1. Keycloak enabled (production / staging)
#      Uses KeycloakAuthProvider, which acts as an OAuth 2.1 proxy:
#      - Exposes the OAuth 2.1 metadata endpoints required by the MCP spec
#        (/.well-known/oauth-protected-resource, token/authorize proxying)
#      - MCP clients (Claude Desktop, Copilot) auto-register via Dynamic
#        Client Registration (DCR) — requires Keycloak ≥ 26.6.0
#      - Validates incoming Bearer tokens against Keycloak's JWKS endpoint
#      - Also accepts IC-Hub's configured API key as a Bearer token (API-key
#        fallback for system-to-system callers that don't speak OAuth)
#
#   2. Authorization disabled (addons.authorization.enabled: false)
#      Returns None — MCP endpoint is publicly accessible (dev/test only).
#
# The IC-Hub REST API guards its own endpoints via get_authentication_dependency()
# in auth_api.py. That FastAPI dependency does NOT cover the MCP sub-app (which
# is mounted directly on the FastAPI app via app.mount(), bypassing the router
# dependency injection system). Auth for the MCP endpoint must therefore be
# handled entirely inside FastMCP via the auth= parameter.

import logging

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.auth.providers.keycloak import KeycloakAuthProvider

from managers.config.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class ApiKeyTokenVerifier(TokenVerifier):
    """Accepts IC-Hub's configured REST API key as a Bearer token.

    Allows system-to-system clients to reuse the same X-Api-Key credential
    they use for the REST endpoints, passing it as a Bearer token to the
    MCP endpoint instead.  The token value must match exactly.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != self._api_key:
            return None
        return AccessToken(
            token=token,
            client_id="api-key-client",
            scopes=["openid"],
            expires_at=None,
            claims={"sub": "api-key-client", "client_id": "api-key-client"},
        )


class CombinedTokenVerifier(TokenVerifier):
    """Tries multiple TokenVerifiers in order; returns the first success."""

    def __init__(self, *verifiers: TokenVerifier) -> None:
        super().__init__()
        self._verifiers = verifiers

    async def verify_token(self, token: str) -> AccessToken | None:
        for v in self._verifiers:
            result = await v.verify_token(token)
            if result is not None:
                return result
        return None


def create_mcp_auth_provider(mcp_server_url: str):
    """Build the FastMCP auth provider from IC-Hub's authorization config.

    Args:
        mcp_server_url: Publicly accessible base URL of the MCP endpoint
            (e.g. ``http://localhost:9000/addons/mcp-kit/mcp``).  Used to
            construct the OAuth 2.1 protected-resource metadata URL that
            MCP clients discover via ``/.well-known/oauth-protected-resource``.

    Returns:
        A FastMCP ``AuthProvider`` (or a bare ``TokenVerifier``) when
        authorization is enabled, or ``None`` when it is disabled.
    """
    if not ConfigManager.get_config("authorization.enabled", False):
        logger.warning(
            "[MCP KIT] Authorization is DISABLED — the MCP endpoint is publicly "
            "accessible. Enable authorization in configuration.yml for production use."
        )
        return None

    keycloak_cfg = ConfigManager.get_config("authorization.keycloak") or {}
    api_key = ConfigManager.get_config("authorization.api_key.value") or ""

    verifiers: list[TokenVerifier] = []
    realm_url: str | None = None

    # --- Keycloak JWT verifier (gated by addons.mcp_kit.oauth_enabled) ---
    mcp_oauth_enabled = ConfigManager.get_config("addons.mcp_kit.oauth_enabled", True)
    if mcp_oauth_enabled and keycloak_cfg.get("enabled"):
        auth_url = str(keycloak_cfg.get("auth_url", "")).rstrip("/")
        realm = keycloak_cfg.get("realm", "")
        if auth_url and realm:
            realm_url = f"{auth_url}/realms/{realm}"
            expected_audience = (
                ConfigManager.get_config("addons.mcp_kit.expected_audience")
                or ConfigManager.get_config("authorization.keycloak.client_id", "industry-core-hub-api")
            )
            logger.info(
                "[MCP KIT] Keycloak JWT verifier → %s (expected audience: %s)",
                realm_url,
                expected_audience,
            )
            verifiers.append(
                JWTVerifier(
                    jwks_uri=f"{realm_url}/protocol/openid-connect/certs",
                    issuer=realm_url,
                    algorithm="RS256",
                    audience=expected_audience,
                )
            )

    # --- API-key fallback verifier ---
    _placeholder = "<<example>>"
    if api_key and api_key != _placeholder:
        verifiers.append(ApiKeyTokenVerifier(api_key))
        logger.info("[MCP KIT] API-key Bearer fallback verifier registered.")

    if not verifiers:
        logger.error(
            "[MCP KIT] Authorization is enabled but no verifiers are configured "
            "(Keycloak disabled and no API key set). "
            "All MCP requests will be rejected."
        )
        return None

    token_verifier: TokenVerifier = (
        verifiers[0] if len(verifiers) == 1 else CombinedTokenVerifier(*verifiers)
    )

    if mcp_oauth_enabled and realm_url:
        # Full OAuth 2.1 proxy mode: IC-Hub fronts Keycloak for MCP clients.
        # DCR lets Claude Desktop / Copilot auto-register without any manual
        # Keycloak client setup.  Requires Keycloak ≥ 26.6.0.
        logger.info(
            "[MCP KIT] KeycloakAuthProvider configured — base_url=%s realm=%s",
            mcp_server_url,
            realm_url,
        )
        return KeycloakAuthProvider(
            realm_url=realm_url,
            base_url=mcp_server_url,
            token_verifier=token_verifier,
        )

    # No Keycloak — resource-server-only mode.
    # Token validation works; MCP OAuth discovery endpoints are NOT exposed,
    # so clients that rely on auto-discovery won't work.
    logger.warning(
        "[MCP KIT] Keycloak is disabled. OAuth 2.1 browser-based flow will not "
        "work for MCP clients. Only Bearer-token (API-key) requests accepted."
    )
    return token_verifier
