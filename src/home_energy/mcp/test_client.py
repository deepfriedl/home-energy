"""Manual smoke test for the Home Energy MCP server.

This utility intentionally reports only operation status. MCP responses can
contain account identifiers and household energy data, so use a debugger or a
private, access-controlled environment when inspecting response bodies.
"""

import asyncio
from datetime import date, timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "http://127.0.0.1:8000/mcp"


async def main() -> None:
    """Exercise core MCP tools without writing customer data to stdout."""
    async with streamable_http_client(MCP_URL) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = {tool.name for tool in tools_result.tools}

            required_tools = {
                "get_status",
                "get_fpl_current_usage",
                "get_fpl_hourly_usage",
                "get_fpl_appliance_usage",
            }
            missing_tools = required_tools - tool_names
            if missing_tools:
                raise RuntimeError(
                    "MCP server is missing expected tools: "
                    + ", ".join(sorted(missing_tools))
                )

            await session.call_tool("get_status", {})
            await session.call_tool("get_fpl_current_usage", {})
            await session.call_tool(
                "get_fpl_hourly_usage",
                {"usage_date": (date.today() - timedelta(days=1)).isoformat()},
            )
            await session.call_tool("get_fpl_appliance_usage", {})

    print("MCP smoke test completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
