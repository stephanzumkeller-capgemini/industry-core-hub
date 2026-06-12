#################################################################################
# Industry Core Hub - MCP Addon
#
# Copyright (c) 2026 Capgemini
#
#################################################################################

# MCP KIT top-level router.

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from managers.config.config_manager import ConfigManager

router = APIRouter(
    prefix="/mcp-kit",
    tags=["MCP KIT Microservices"],
)


@router.get("/health", include_in_schema=True)
async def health():
    """Liveness check for the MCP KIT add-on."""
    return JSONResponse({"status": "ok", "addon": "mcp_kit"})


if ConfigManager.get_config("addons.mcp_kit.audit.expose_admin_endpoint", True):

    @router.get("/audit", include_in_schema=True)
    async def get_audit_log(limit: int = Query(default=50, ge=1, le=500)):
        """Return recent MCP KIT tool-call audit records (newest last).

        Each record contains mcp_tool_name, mcp_session_id, end_user_sub,
        outcome, duration_ms, downstream_ids, and timestamp.
        """
        from managers.addons_service.mcp_kit.v1.audit import audit_logger
        records = audit_logger.get_recent(limit)
        return JSONResponse([r.model_dump() for r in records])
