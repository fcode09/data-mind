"""Official MCP client, with a server-selected tenant and a bounded call timeout."""

import os
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from data_mind.contracts import Scope


async def call_tool(name: str, scope: Scope, **kwargs) -> dict:
    headers = {
        "Authorization": "Bearer " + os.environ["MCP_INTERNAL_TOKEN"],
        "X-Tenant-ID": str(scope.tenant_id),
    }
    async with asyncio.timeout(20):
        async with streamablehttp_client(
            os.getenv("MCP_URL", "http://127.0.0.1:8101/mcp"), headers=headers
        ) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                result = await client.call_tool(
                    name, {"scope": scope.model_dump(mode="json"), **kwargs}
                )
                if result.isError:
                    raise RuntimeError("Data tool failed; no answer can be verified")
                if result.structuredContent is not None:
                    return result.structuredContent
                import json

                return json.loads(result.content[0].text)
