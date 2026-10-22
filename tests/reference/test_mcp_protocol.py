"""Real MCP SDK handshake and tool calls over local HTTP, with an explicit fake repository."""

import asyncio
import os
import threading
import socket
import time
from datetime import date, datetime, timezone
from contextlib import contextmanager
import pytest
import uvicorn
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from data_mind.contracts import Evidence, Scope
from apps.mcp import server as module


class FakeRepository:
    def incidents_summary(self, scope, group_by, limit, **kwargs):
        return Evidence(
            query_id="fixture",
            dataset_version="fixture-v1",
            effective_scope=scope,
            as_of=datetime.now(timezone.utc),
            total_matching=5,
            returned_rows=1,
            rows=[{"category": "lighting", "count": 5}],
        )


@pytest.mark.asyncio
async def test_real_mcp_roundtrip(monkeypatch):
    monkeypatch.setenv("MCP_INTERNAL_TOKEN", "unit-test-internal-token")
    monkeypatch.setattr(module, "repository", lambda: FakeRepository())
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(module.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.02)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        async with httpx.AsyncClient() as client:
            assert (await client.post(url, json={})).status_code == 401
        headers = {
            "Authorization": "Bearer unit-test-internal-token",
            "X-Tenant-ID": "1",
        }
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                listing = await client.list_tools()
                assert len(listing.tools) == 7
                scope = Scope(
                    tenant_id=1,
                    from_date=date(2026, 1, 1),
                    to_date_exclusive=date(2026, 2, 1),
                )
                result = await client.call_tool(
                    "incidents_summary", {"scope": scope.model_dump(mode="json")}
                )
                assert not result.isError
                assert result.structuredContent["total_matching"] == 5
                scope.tenant_id = 2
                denied = await client.call_tool(
                    "incidents_summary", {"scope": scope.model_dump(mode="json")}
                )
                assert denied.isError
    finally:
        server.should_exit = True
        thread.join(timeout=5)
