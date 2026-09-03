"""MCP server for FPL home energy data."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from home_energy.fpl.client import FplClient, FplClientError


@dataclass
class AppContext:
    """Application resources shared by MCP tools."""

    fpl_client: FplClient
    account: str


@asynccontextmanager
async def app_lifespan(
    server: MCPServer,
) -> AsyncIterator[AppContext]:
    """Create and authenticate the FPL client for the server lifetime."""
    client = FplClient()

    await client.connect()

    try:
        accounts = await client.get_accounts()

        if not accounts:
            raise FplClientError(
                "No open FPL accounts were found."
            )

        account = accounts[0]

        yield AppContext(
            fpl_client=client,
            account=account,
        )
    finally:
        try:
            await client.logout()
        finally:
            await client.close()


mcp = MCPServer(
    "Home Energy",
    lifespan=app_lifespan,
)


def _serialize(value: Any) -> Any:
    """Convert FPL data into JSON-compatible values."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            key: _serialize(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [_serialize(item) for item in value]

    return value


def _normalize_appliance_period(
    period: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one FPL appliance billing period."""
    return {
        "start_date": period.get("startDate"),
        "end_date": period.get("endDate"),
        "billing_days": int(period["billingDays"])
        if period.get("billingDays") is not None
        else None,
        "kwh": float(period["kwh"])
        if period.get("kwh") is not None
        else None,
        "cost": float(period["dollars"])
        if period.get("dollars") is not None
        else None,
        "categories": _serialize(
            period.get("categories") or []
        ),
    }


def _normalize_appliance_usage(
    data: dict[str, Any],
) -> dict[str, Any]:
    """Normalize the FPL appliance usage response."""
    periods = data.get("billPeriods") or []

    if not periods:
        return {
            "latest_period": None,
            "historical_periods": [],
        }

    latest_index = next(
        (
            index
            for index, period in enumerate(periods)
            if str(period.get("billPeriod")) == "1"
        ),
        0,
    )

    latest_period = _normalize_appliance_period(
        periods[latest_index]
    )

    historical_periods = [
        _normalize_appliance_period(period)
        for index, period in enumerate(periods)
        if index != latest_index
    ]

    return {
        "latest_period": latest_period,
        "historical_periods": historical_periods,
    }


@mcp.tool()
def get_status() -> str:
    """Return the status of the Home Energy MCP server."""
    return "Home Energy MCP server is running."


@mcp.tool()
async def get_fpl_current_usage(
    ctx: Context[AppContext],
) -> dict[str, Any]:
    """Return current FPL billing-cycle and latest daily usage data."""
    app_context = ctx.request_context.lifespan_context
    client = app_context.fpl_client
    account = app_context.account

    result = await client.get_current_usage(account)

    return _serialize(result)


@mcp.tool()
async def get_fpl_hourly_usage(
    usage_date: str,
    ctx: Context[AppContext],
) -> dict[str, Any]:
    """Return FPL hourly energy usage for a date in YYYY-MM-DD format."""
    try:
        parsed_date = date.fromisoformat(usage_date)
    except ValueError:
        return {
            "error": (
                "Invalid date. Use YYYY-MM-DD format."
            ),
        }

    app_context = ctx.request_context.lifespan_context
    client = app_context.fpl_client
    account = app_context.account

    readings = await client.get_hourly_usage(
        account,
        parsed_date,
    )

    total_kwh = sum(
        float(row.get("kwh") or 0.0)
        for row in readings
    )

    return {
        "date": parsed_date.isoformat(),
        "readings": _serialize(readings),
        "reading_count": len(readings),
        "total_kwh": total_kwh,
    }


@mcp.tool()
async def get_fpl_appliance_usage(
    ctx: Context[AppContext],
) -> dict[str, Any]:
    """Return normalized FPL appliance-level energy usage."""
    app_context = ctx.request_context.lifespan_context
    client = app_context.fpl_client
    account = app_context.account

    data = await client.get_appliance_usage(account)

    return _normalize_appliance_usage(data)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")