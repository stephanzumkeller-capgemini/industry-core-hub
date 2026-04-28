#################################################################################
# Industry Core Hub - MCP Addon Tests
#
# Copyright (c) 2026 Capgemini
#
#################################################################################

import pytest
from unittest.mock import AsyncMock, patch

from models.services.addons.mcp_kit.v1.session import PendingConfirmation
from managers.addons_service.mcp_kit.v1.session import InMemorySessionStore
from managers.addons_service.mcp_kit.v1.confirmation import (
    confirm_or_execute,
    _compute_args_hash,
)


class TestComputeArgsHash:
    """Tests for deterministic hashing of tool name + args."""

    def test_same_args_produce_same_hash(self):
        h1 = _compute_args_hash("create_catalog_part", {"name": "Sensor", "id": "123"})
        h2 = _compute_args_hash("create_catalog_part", {"name": "Sensor", "id": "123"})
        assert h1 == h2

    def test_different_args_produce_different_hash(self):
        h1 = _compute_args_hash("create_catalog_part", {"name": "Sensor"})
        h2 = _compute_args_hash("create_catalog_part", {"name": "Battery"})
        assert h1 != h2

    def test_different_tool_names_produce_different_hash(self):
        h1 = _compute_args_hash("create_catalog_part", {"name": "Sensor"})
        h2 = _compute_args_hash("update_catalog_part", {"name": "Sensor"})
        assert h1 != h2

    def test_key_order_does_not_matter(self):
        h1 = _compute_args_hash("tool", {"a": 1, "b": 2})
        h2 = _compute_args_hash("tool", {"b": 2, "a": 1})
        assert h1 == h2


class TestConfirmOrExecute:
    """Tests for the preview/confirm state machine."""

    def setup_method(self):
        self.store = InMemorySessionStore(ttl_seconds=3600)
        self.session_id = "test-session-1"
        self.tool_name = "create_catalog_part"
        self.args = {"manufacturer_id": "BPNL000000000001", "name": "Sensor"}
        self.preview_summary = "Create catalog part 'Sensor'"

    @pytest.mark.asyncio
    async def test_first_call_returns_preview(self):
        """First call should return a preview, not execute."""
        execute_fn = AsyncMock(return_value={"catalog_part_id": "X::Y"})

        executed, result = await confirm_or_execute(
            self.store, self.session_id, self.tool_name, self.args,
            self.preview_summary, execute_fn,
        )

        assert executed is False
        assert result["status"] == "preview"
        assert result["tool"] == self.tool_name
        assert result["summary"] == self.preview_summary
        execute_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_second_identical_call_executes(self):
        """Second call with identical args should execute."""
        execute_fn = AsyncMock(return_value={"catalog_part_id": "X::Y"})

        # First call — preview
        await confirm_or_execute(
            self.store, self.session_id, self.tool_name, self.args,
            self.preview_summary, execute_fn,
        )

        # Second call — execute
        executed, result = await confirm_or_execute(
            self.store, self.session_id, self.tool_name, self.args,
            self.preview_summary, execute_fn,
        )

        assert executed is True
        assert result == {"catalog_part_id": "X::Y"}
        execute_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_args_re_previews(self):
        """Second call with different args should discard previous and re-preview."""
        execute_fn = AsyncMock(return_value={"catalog_part_id": "X::Y"})

        # First call — preview
        await confirm_or_execute(
            self.store, self.session_id, self.tool_name, self.args,
            self.preview_summary, execute_fn,
        )

        # Second call with different args — should re-preview
        different_args = {"manufacturer_id": "BPNL000000000002", "name": "Battery"}
        executed, result = await confirm_or_execute(
            self.store, self.session_id, self.tool_name, different_args,
            "Create catalog part 'Battery'", execute_fn,
        )

        assert executed is False
        assert result["status"] == "preview"
        assert result["summary"] == "Create catalog part 'Battery'"
        execute_fn.assert_not_called()

    @pytest.mark.asyncio
    @patch("managers.addons_service.mcp_kit.v1.confirmation._require_confirmation", return_value=False)
    async def test_confirmation_disabled_executes_immediately(self, mock_conf):
        """When confirmation is disabled, execute immediately on first call."""
        execute_fn = AsyncMock(return_value={"catalog_part_id": "X::Y"})

        executed, result = await confirm_or_execute(
            self.store, self.session_id, self.tool_name, self.args,
            self.preview_summary, execute_fn,
        )

        assert executed is True
        assert result == {"catalog_part_id": "X::Y"}
        execute_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_pending_cleared_after_execution(self):
        """After executing, the pending confirmation should be cleared."""
        execute_fn = AsyncMock(return_value={"ok": True})

        await confirm_or_execute(
            self.store, self.session_id, self.tool_name, self.args,
            self.preview_summary, execute_fn,
        )
        await confirm_or_execute(
            self.store, self.session_id, self.tool_name, self.args,
            self.preview_summary, execute_fn,
        )

        state = self.store.get(self.session_id)
        args_hash = _compute_args_hash(self.tool_name, self.args)
        assert args_hash not in state.pending_confirmations


class TestSessionStorePendingConfirmation:
    """Tests for the pending confirmation methods on InMemorySessionStore."""

    def setup_method(self):
        self.store = InMemorySessionStore(ttl_seconds=3600)
        self.session_id = "test-session-2"

    def test_set_and_get_pending_confirmation(self):
        pending = PendingConfirmation(
            tool_name="create_catalog_part",
            args_hash="abc123",
            preview_summary="Create part",
        )
        self.store.set_pending_confirmation(self.session_id, pending)
        state = self.store.get(self.session_id)
        assert state is not None
        assert state.pending_confirmations["abc123"].tool_name == "create_catalog_part"
        assert state.pending_confirmations["abc123"].args_hash == "abc123"

    def test_clear_pending_confirmation(self):
        pending = PendingConfirmation(
            tool_name="share_catalog_part",
            args_hash="xyz789",
            preview_summary="Share part",
        )
        self.store.set_pending_confirmation(self.session_id, pending)
        self.store.clear_pending_confirmation(self.session_id, "xyz789")
        state = self.store.get(self.session_id)
        assert "xyz789" not in state.pending_confirmations

    def test_clear_nonexistent_session_is_noop(self):
        self.store.clear_pending_confirmation("nonexistent-session", "somehash")
        # Should not raise
