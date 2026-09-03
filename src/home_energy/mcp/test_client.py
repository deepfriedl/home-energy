"""Test client for the Home Energy MCP server."""

import asyncio
from datetime import date, timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "http://127.0.0.1:8000/mcp"


async def main() -> None:
    """Connect to the MCP server and test its tools."""
    print(f"Connecting to {MCP_URL}...")

    async with streamable_http_client(MCP_URL) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            await session.initialize()

            print("Connected to MCP server.")
            print()

            tools_result = await session.list_tools()

            print("Available tools:")

            for tool in tools_result.tools:
                print(f"  {tool.name}: {tool.description}")

            print()

            print("Calling get_status()...")

            status_result = await session.call_tool(
                "get_status",
                {},
            )

            print()
            print("Status result:")
            print(status_result)

            print()
            print("Calling get_fpl_current_usage()...")

            current_result = await session.call_tool(
                "get_fpl_current_usage",
                {},
            )

            print()
            print("Current usage result:")
            print(current_result)

            usage_date = date.today() - timedelta(days=1)

            print()
            print(
                "Calling get_fpl_hourly_usage("
                f"{usage_date.isoformat()})..."
            )

            hourly_result = await session.call_tool(
                "get_fpl_hourly_usage",
                {
                    "usage_date": usage_date.isoformat(),
                },
            )

            print()
            print("Hourly usage result:")
            print(hourly_result)

            print()
            print("Calling get_fpl_appliance_usage()...")

            appliance_result = await session.call_tool(
                "get_fpl_appliance_usage",
                {},
            )

            print()
            print("Appliance usage result:")
            print(appliance_result)


if __name__ == "__main__":
    asyncio.run(main())