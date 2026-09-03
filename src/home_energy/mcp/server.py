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
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    """Create and authenticate the FPL client for the server lifetime."""
    client = FplClient()
    await client.connect()
    try:
        accounts = await client.get_accounts()
        if not accounts:
            raise FplClientError("No open FPL accounts were found.")
        yield AppContext(fpl_client=client, account=accounts[0])
    finally:
        try:
            await client.logout()
        finally:
            await client.close()


mcp = MCPServer("Home Energy", lifespan=app_lifespan)


def _serialize(value: Any) -> Any:
    """Convert FPL data into JSON-compatible values."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _number(value: Any) -> float | None:
    """Convert an optional numeric FPL value to a float."""
    return None if value is None else float(value)


def _percentage_change(first: float | None, second: float | None) -> float | None:
    """Return the percent change from first to second when meaningful."""
    if first in (None, 0) or second is None:
        return None
    return (second - first) / first * 100


def _parse_date(value: str) -> date | None:
    """Parse an ISO date, returning None for invalid user input."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _hourly_usage_summary(usage_date: date, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize readings and calculate their daily high and low usage."""
    kwh_values = [float(row.get("kwh") or 0.0) for row in readings]
    total_kwh = sum(kwh_values)
    result: dict[str, Any] = {
        "date": usage_date.isoformat(),
        "readings": _serialize(readings),
        "reading_count": len(readings),
        "total_kwh": total_kwh,
        "average_hourly_kwh": total_kwh / len(readings) if readings else None,
        "peak_hour": None,
        "lowest_use_hour": None,
    }
    if readings:
        peak_index = max(range(len(readings)), key=lambda index: kwh_values[index])
        low_index = min(range(len(readings)), key=lambda index: kwh_values[index])
        result["peak_hour"] = _serialize(readings[peak_index])
        result["lowest_use_hour"] = _serialize(readings[low_index])
    return result


def _latest_daily_date(current_usage: dict[str, Any]) -> date | None:
    """Extract the date covered by the latest daily FPL reading."""
    latest_daily_usage = current_usage.get("latest_daily_usage")
    if not isinstance(latest_daily_usage, dict):
        return None
    read_time = latest_daily_usage.get("read_time")
    if isinstance(read_time, datetime):
        return read_time.date()
    if isinstance(read_time, date):
        return read_time
    if isinstance(read_time, str):
        try:
            return datetime.fromisoformat(read_time).date()
        except ValueError:
            return None
    return None


def _normalize_appliance_period(period: dict[str, Any]) -> dict[str, Any]:
    """Normalize one FPL appliance billing period."""
    return {
        "start_date": period.get("startDate"),
        "end_date": period.get("endDate"),
        "billing_days": int(period["billingDays"]) if period.get("billingDays") is not None else None,
        "kwh": _number(period.get("kwh")),
        "cost": _number(period.get("dollars")),
        "categories": _serialize(period.get("categories") or []),
    }


def _normalize_appliance_usage(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the FPL appliance usage response."""
    periods = data.get("billPeriods") or []
    if not periods:
        return {"latest_period": None, "historical_periods": []}
    latest_index = next((index for index, period in enumerate(periods) if str(period.get("billPeriod")) == "1"), 0)
    return {
        "latest_period": _normalize_appliance_period(periods[latest_index]),
        "historical_periods": [_normalize_appliance_period(period) for index, period in enumerate(periods) if index != latest_index],
    }


def _appliance_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten the latest appliance period into compact category summaries."""
    latest_period = _normalize_appliance_usage(data)["latest_period"]
    if latest_period is None:
        return {"period": None, "appliances": []}
    appliances = []
    for category in latest_period["categories"]:
        if isinstance(category, dict):
            appliances.append({
                "name": category.get("category"),
                "kwh": _number(category.get("kwh2", category.get("kwh"))),
                "cost": _number(category.get("cost")),
                "percentage": _number(category.get("percentage2", category.get("percentage"))),
            })
    return {
        "period": {key: value for key, value in latest_period.items() if key != "categories"},
        "appliances": appliances,
    }


def _bill_summary(current_usage: dict[str, Any]) -> dict[str, Any]:
    """Return the billing fields most useful for a concise bill overview."""
    keys = ("bill_to_date", "projected_bill", "bill_to_date_kwh", "projected_kwh", "daily_average_kwh", "daily_average_cost", "bill_start_date", "bill_end_date", "as_of_days", "remaining_days", "service_days")
    result = {key: current_usage.get(key) for key in keys}
    result["days_elapsed"] = result.pop("as_of_days")
    return _serialize(result)


def _comparison(first: dict[str, Any], second: dict[str, Any], label: str) -> dict[str, Any]:
    """Compare two usage totals using a consistent response shape."""
    first_kwh = _number(first.get("total_kwh", first.get("kwh")))
    second_kwh = _number(second.get("total_kwh", second.get("kwh")))
    first_cost = _number(first.get("total_cost", first.get("cost")))
    second_cost = _number(second.get("total_cost", second.get("cost")))
    return {
        "comparison_type": label,
        "first": _serialize(first), "second": _serialize(second),
        "kwh_delta": None if first_kwh is None or second_kwh is None else second_kwh - first_kwh,
        "kwh_percent_change": _percentage_change(first_kwh, second_kwh),
        "cost_delta": None if first_cost is None or second_cost is None else second_cost - first_cost,
        "cost_percent_change": _percentage_change(first_cost, second_cost),
    }


def _context(ctx: Context[AppContext]) -> AppContext:
    """Return the typed application context for a tool request."""
    return ctx.request_context.lifespan_context


@mcp.tool()
def get_status() -> str:
    """Return the status of the Home Energy MCP server."""
    return "Home Energy MCP server is running."


@mcp.tool()
async def get_fpl_current_usage(ctx: Context[AppContext]) -> dict[str, Any]:
    """Return current FPL billing-cycle and latest daily usage data."""
    app_context = _context(ctx)
    return _serialize(await app_context.fpl_client.get_current_usage(app_context.account))


@mcp.tool()
async def get_fpl_hourly_usage(usage_date: str, ctx: Context[AppContext]) -> dict[str, Any]:
    """Return FPL hourly energy usage for a date in YYYY-MM-DD format."""
    parsed_date = _parse_date(usage_date)
    if parsed_date is None:
        return {"error": "Invalid date. Use YYYY-MM-DD format."}
    app_context = _context(ctx)
    readings = await app_context.fpl_client.get_hourly_usage(app_context.account, parsed_date)
    return _hourly_usage_summary(parsed_date, readings)


@mcp.tool()
async def get_fpl_usage_for_date(usage_date: str, ctx: Context[AppContext]) -> dict[str, Any]:
    """Return normalized hourly readings and totals for one FPL usage date."""
    return await get_fpl_hourly_usage(usage_date, ctx)


@mcp.tool()
async def get_fpl_usage_range(start_date: str, end_date: str, ctx: Context[AppContext]) -> dict[str, Any]:
    """Return daily FPL usage totals for an inclusive date range of up to 366 days."""
    start, end = _parse_date(start_date), _parse_date(end_date)
    if start is None or end is None:
        return {"error": "Invalid date. Use YYYY-MM-DD format for start_date and end_date."}
    if end < start:
        return {"error": "end_date must be on or after start_date."}
    if (end - start).days > 365:
        return {"error": "Date range may not exceed 366 days."}
    app_context = _context(ctx)
    daily_usage = []
    cursor = start
    while cursor <= end:
        readings = await app_context.fpl_client.get_hourly_usage(app_context.account, cursor)
        summary = _hourly_usage_summary(cursor, readings)
        daily_usage.append({"date": summary["date"], "total_kwh": summary["total_kwh"], "total_cost": sum(float(row.get("billing_charge") or 0.0) for row in readings)})
        cursor = date.fromordinal(cursor.toordinal() + 1)
    total_kwh = sum(day["total_kwh"] for day in daily_usage)
    return {"start_date": start.isoformat(), "end_date": end.isoformat(), "day_count": len(daily_usage), "daily_usage": daily_usage, "total_kwh": total_kwh, "average_daily_kwh": total_kwh / len(daily_usage), "total_cost": sum(day["total_cost"] for day in daily_usage)}


@mcp.tool()
async def get_fpl_peak_hours(usage_date: str, top_n: int, ctx: Context[AppContext]) -> dict[str, Any]:
    """Return the highest-use FPL hours for a date, ordered by kWh."""
    parsed_date = _parse_date(usage_date)
    if parsed_date is None:
        return {"error": "Invalid date. Use YYYY-MM-DD format."}
    if top_n < 1:
        return {"error": "top_n must be at least 1."}
    app_context = _context(ctx)
    readings = await app_context.fpl_client.get_hourly_usage(app_context.account, parsed_date)
    peak_hours = sorted(readings, key=lambda row: float(row.get("kwh") or 0.0), reverse=True)[:top_n]
    return {"date": parsed_date.isoformat(), "requested_count": top_n, "peak_hours": _serialize(peak_hours)}


@mcp.tool()
async def get_fpl_daily_summary(ctx: Context[AppContext]) -> dict[str, Any]:
    """Summarize the latest available daily FPL usage and its hourly context."""
    app_context = _context(ctx)
    current_usage = await app_context.fpl_client.get_current_usage(app_context.account)
    latest_daily_usage = current_usage.get("latest_daily_usage")
    usage_date = _latest_daily_date(current_usage)
    if usage_date is None or not isinstance(latest_daily_usage, dict):
        return {"error": "FPL did not provide a latest daily usage reading."}
    readings = await app_context.fpl_client.get_hourly_usage(app_context.account, usage_date)
    hourly_summary = _hourly_usage_summary(usage_date, readings)
    daily_kwh = _number(latest_daily_usage.get("kwh_actual"))
    daily_cost = _number(latest_daily_usage.get("billing_charge"))
    billing_average = _number(current_usage.get("daily_average_kwh"))
    return {"date": usage_date.isoformat(), "kwh": daily_kwh, "cost": daily_cost, "billing_cycle_daily_average_kwh": billing_average, "kwh_vs_billing_cycle_daily_average": None if daily_kwh is None or billing_average is None else daily_kwh - billing_average, "percent_vs_billing_cycle_daily_average": _percentage_change(billing_average, daily_kwh), "peak_hour": hourly_summary["peak_hour"], "lowest_use_hour": hourly_summary["lowest_use_hour"]}


@mcp.tool()
async def get_fpl_appliance_usage(ctx: Context[AppContext]) -> dict[str, Any]:
    """Return normalized FPL appliance-level energy usage."""
    app_context = _context(ctx)
    return _normalize_appliance_usage(await app_context.fpl_client.get_appliance_usage(app_context.account))


@mcp.tool()
async def get_fpl_appliance_summary(ctx: Context[AppContext]) -> dict[str, Any]:
    """Return a compact appliance-category summary for the latest billing period."""
    app_context = _context(ctx)
    return _appliance_summary(await app_context.fpl_client.get_appliance_usage(app_context.account))


@mcp.tool()
async def get_fpl_bill_summary(ctx: Context[AppContext]) -> dict[str, Any]:
    """Return a concise current FPL bill-to-date and projection summary."""
    app_context = _context(ctx)
    return _bill_summary(await app_context.fpl_client.get_current_usage(app_context.account))


@mcp.tool()
async def get_fpl_account_status(ctx: Context[AppContext]) -> dict[str, Any]:
    """Confirm authenticated account access, premise availability, and latest data date."""
    app_context = _context(ctx)
    account_info = await app_context.fpl_client.get_account_info(app_context.account)
    current_usage = await app_context.fpl_client.get_current_usage(app_context.account)
    return {"authentication": "authenticated", "selected_account": app_context.account, "premise_available": bool(account_info.get("premise")), "latest_data_date": _serialize(_latest_daily_date(current_usage)), "bill_start_date": _serialize(account_info.get("current_bill_date")), "bill_end_date": _serialize(account_info.get("next_bill_date"))}


@mcp.tool()
async def get_fpl_usage_comparison(first: str, second: str, comparison_type: str, ctx: Context[AppContext]) -> dict[str, Any]:
    """Compare two usage dates or appliance billing periods (for example, 1 and 2)."""
    app_context = _context(ctx)
    if comparison_type == "dates":
        first_date, second_date = _parse_date(first), _parse_date(second)
        if first_date is None or second_date is None:
            return {"error": "For dates, first and second must use YYYY-MM-DD format."}
        first_readings = await app_context.fpl_client.get_hourly_usage(app_context.account, first_date)
        second_readings = await app_context.fpl_client.get_hourly_usage(app_context.account, second_date)
        first_summary = _hourly_usage_summary(first_date, first_readings)
        second_summary = _hourly_usage_summary(second_date, second_readings)
        first_summary["total_cost"] = sum(float(row.get("billing_charge") or 0.0) for row in first_readings)
        second_summary["total_cost"] = sum(float(row.get("billing_charge") or 0.0) for row in second_readings)
        return _comparison(first_summary, second_summary, "dates")
    if comparison_type == "billing_periods":
        data = await app_context.fpl_client.get_appliance_usage(app_context.account)
        periods = data.get("billPeriods") or []
        periods_by_id = {str(period.get("billPeriod")): _normalize_appliance_period(period) for period in periods}
        if first not in periods_by_id or second not in periods_by_id:
            return {"error": "For billing_periods, first and second must identify available FPL bill periods."}
        return _comparison(periods_by_id[first], periods_by_id[second], "billing_periods")
    return {"error": "comparison_type must be either dates or billing_periods."}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
