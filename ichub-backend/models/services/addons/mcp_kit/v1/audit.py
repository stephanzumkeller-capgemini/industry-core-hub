#################################################################################
# Industry Core Hub - MCP Addon
#
# Copyright (c) 2026 Capgemini
#
#################################################################################

from typing import Optional
from pydantic import BaseModel


class AuditRecord(BaseModel):
    """One structured audit log entry per MCP tool call."""

    timestamp: str
    mcp_session_id: str
    mcp_tool_name: str
    redacted_args: dict
    end_user_sub: str
    outcome: str  # "success" | "error"
    duration_ms: int
    downstream_ids: list[str]
    error_message: Optional[str] = None
