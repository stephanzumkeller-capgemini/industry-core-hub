#################################################################################
# Industry Core Hub - MCP Addon
#
# Copyright (c) 2026 Capgemini
#
#################################################################################

from pydantic import BaseModel, Field
from typing import Optional


class PendingConfirmation(BaseModel):
    """A staged write-tool invocation awaiting the user's second call.

    Populated by the confirmation state machine (Step 6).
    """

    tool_name: str
    args_hash: str
    preview_summary: str


class SessionState(BaseModel):
    """IC-Hub domain state held for one MCP session.

    Populated incrementally by tool calls so the LLM can refer back to
    previously seen entities (e.g. "the battery part", "the BMW twin").
    """

    session_id: str

    # Discovery — known partner BPNLs returned by list_known_partners /
    # find_partner_by_bpn (populated in Steps 1-4).
    bpnls: list[str] = Field(default_factory=list)

    # Consumption — twin IDs seen in list_partner_twins / get_twin_details
    # (populated in Step 4).
    twin_ids: list[str] = Field(default_factory=list)

    # Provision — catalog-part IDs seen in list_my_catalog_parts /
    # create_catalog_part (populated in Steps 6-7).
    catalog_part_ids: list[str] = Field(default_factory=list)

    # Write-tool confirmation — pending writes keyed by args_hash, awaiting
    # user re-invocation with identical args (populated in Step 6).
    pending_confirmations: dict[str, PendingConfirmation] = Field(default_factory=dict)
