"""Client for accessing FPL customer and energy data."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import aiohttp
from dotenv import load_dotenv

API_HOST = "https://www.fpl.com"

LOGIN_URL = (
    API_HOST
    + "/cs/customer/v1/registration/"
    "loginAndUseMigration?migrationToggle=Y&view=LoginMini"
)

ACCOUNTS_URL = API_HOST + "/cs/customer/v1/resources/account"

ACCOUNT_INFO_URL = (
    API_HOST
    + "/cs/customer/v1/accountservices/resources/"
    "account/{account}/select?view=account-lander"
)

ENERGY_USAGE_URL = (
    API_HOST
    + "/cs/customer/v1/energydashboard/resources/"
    "energy-usage/account/{account}/mobile-energy-service"
)

HOURLY_USAGE_URL = (
    API_HOST
    + "/cs/customer/v1/energydashboard/resources/"
    "energy-usage/account/{account}/mobile-hourly-usage"
)

APPLIANCE_USAGE_URL = (
    API_HOST
    + "/cs/customer/v1/energyanalyzer/resources/"
    "{account}/getDisaggResp"
)

LOGOUT_URL = API_HOST + "/api/resources/logout"

TIMEOUT_SECONDS = 30


class FplClientError(Exception):
    """Base exception for FPL client errors."""


class FplAuthenticationError(FplClientError):
    """Raised when authentication with FPL fails."""


class FplClient:
    """Client for the FPL main-region customer API."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize the FPL client."""
        load_dotenv()

        self.username = (
            username or os.getenv("FPL_USERNAME") or ""
        ).strip().lower()
        self.password = password or os.getenv("FPL_PASSWORD") or ""

        if not self.username or not self.password:
            raise FplClientError(
                "FPL_USERNAME and FPL_PASSWORD must be provided."
            )

        self.session: aiohttp.ClientSession | None = None
        self.jwt_token: str | None = None

    async def connect(self) -> None:
        """Create the HTTP session and authenticate with FPL."""
        if self.session is not None and not self.session.closed:
            return

        self.session = aiohttp.ClientSession()

        try:
            await self.login()
        except Exception:
            await self.close()
            raise

    async def __aenter__(self) -> "FplClient":
        """Create the HTTP session and authenticate with FPL."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        """Close the HTTP session."""
        await self.close()

    async def close(self) -> None:
        """Close the HTTP session."""
        if self.session is not None and not self.session.closed:
            await self.session.close()

        self.session = None
        self.jwt_token = None

    def _require_session(self) -> aiohttp.ClientSession:
        """Return the HTTP session or raise an error."""
        if self.session is None or self.session.closed:
            raise FplClientError(
                "FPL client is not connected. "
                "Call connect() before using it."
            )

        return self.session

    def _headers(self) -> dict[str, str]:
        """Return headers for authenticated requests."""
        headers: dict[str, str] = {}

        if self.jwt_token:
            headers["jwttoken"] = self.jwt_token

        return headers

    async def login(self) -> None:
        """Authenticate with FPL and store the JWT token."""
        session = self._require_session()

        auth = aiohttp.BasicAuth(
            self.username,
            self.password,
        )

        async with session.get(
            LOGIN_URL,
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
        ) as response:
            if response.status == 200:
                self.jwt_token = response.headers.get("jwttoken")

                if not self.jwt_token:
                    raise FplAuthenticationError(
                        "FPL login succeeded but no JWT token was returned."
                    )

                return

            response_text = await response.text()

            raise FplAuthenticationError(
                f"FPL login failed with HTTP {response.status}: "
                f"{response_text}"
            )

    async def get_accounts(self) -> list[str]:
        """Return open FPL account numbers."""
        session = self._require_session()

        accounts: list[str] = []
        start = 1
        page_size = 10

        while True:
            params = {
                "sortBy": "status",
                "count": str(page_size),
                "start": str(start),
            }

            async with session.get(
                ACCOUNTS_URL,
                headers=self._headers(),
                params=params,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
            ) as response:
                if response.status != 200:
                    raise FplClientError(
                        f"Account list request failed with "
                        f"HTTP {response.status}."
                    )

                payload = await response.json()

            account_page = payload.get("data", [])

            if not account_page:
                break

            for account in account_page:
                if account.get("statusCategory") == "OPEN":
                    account_number = account.get("accountNumber")

                    if account_number:
                        accounts.append(account_number)

            if not payload.get("hasMore"):
                break

            start += payload.get("count", page_size)

        return accounts

    async def get_account_info(
        self,
        account: str,
    ) -> dict[str, Any]:
        """Return account metadata needed for energy requests."""
        session = self._require_session()

        url = ACCOUNT_INFO_URL.format(account=account)

        async with session.get(
            url,
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
        ) as response:
            if response.status != 200:
                raise FplClientError(
                    f"Account information request failed with "
                    f"HTTP {response.status}."
                )

            try:
                payload = await response.json()
            except Exception as error:
                raise FplClientError(
                    "FPL account information response was not valid JSON."
                ) from error

        account_data = payload.get("data")

        if not isinstance(account_data, dict):
            raise FplClientError(
                "FPL account response did not contain account data."
            )

        result: dict[str, Any] = {}

        premise_number = account_data.get("premiseNumber")

        if premise_number:
            result["premise"] = str(premise_number).zfill(9)

        if account_data.get("meterSerialNo") is not None:
            result["meter_serial_number"] = account_data["meterSerialNo"]

        if account_data.get("meterNo") is not None:
            result["meter_number"] = account_data["meterNo"]

        current_bill_date_raw = account_data.get("currentBillDate")
        next_bill_date_raw = account_data.get("nextBillDate")

        if current_bill_date_raw and next_bill_date_raw:
            current_bill_date = datetime.strptime(
                current_bill_date_raw.replace("-", "").split("T")[0],
                "%Y%m%d",
            ).date()

            next_bill_date = datetime.strptime(
                next_bill_date_raw.replace("-", "").split("T")[0],
                "%Y%m%d",
            ).date()

            today = date.today()

            result["current_bill_date"] = current_bill_date
            result["next_bill_date"] = next_bill_date
            result["service_days"] = (
                next_bill_date - current_bill_date
            ).days
            result["as_of_days"] = (today - current_bill_date).days
            result["remaining_days"] = (next_bill_date - today).days

        return result

    async def get_current_usage(
        self,
        account: str,
    ) -> dict[str, Any]:
        """Return current billing-cycle and latest daily usage."""
        account_info = await self.get_account_info(account)

        premise = account_info.get("premise")
        meter_number = account_info.get("meter_number")
        last_billed_date = account_info.get("current_bill_date")

        if not premise:
            raise FplClientError(
                "FPL account did not provide a premise number."
            )

        if not meter_number:
            raise FplClientError(
                "FPL account did not provide a meter number."
            )

        if not isinstance(last_billed_date, date):
            raise FplClientError(
                "FPL account did not provide a current bill date."
            )

        session = self._require_session()

        request_body = {
            "status": "2",
            "accountType": "RESIDENTIAL",
            "premiseNumber": premise,
            "lastBilledDate": last_billed_date.strftime("%m%d%Y"),
            "amrFlag": "Y",
            "revCode": "1",
            "meterNo": meter_number,
        }

        url = ENERGY_USAGE_URL.format(account=account)

        async with session.post(
            url,
            json=request_body,
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
        ) as response:
            if response.status != 200:
                raise FplClientError(
                    f"Energy usage request failed with "
                    f"HTTP {response.status}."
                )

            response_data = await response.json()

        json_data = response_data.get("data") or {}
        result: dict[str, Any] = {}

        current_usage = json_data.get("CurrentUsage") or {}

        if isinstance(current_usage, dict):
            exception = current_usage.get("exceptionDetails")

            if not (
                isinstance(exception, dict)
                and exception.get("requestStatus") == "Failed"
            ):
                if current_usage.get("projectedKWH") is not None:
                    result["projected_kwh"] = int(
                        current_usage["projectedKWH"]
                    )

                if current_usage.get("dailyAverageKWH") is not None:
                    result["daily_average_kwh"] = float(
                        current_usage["dailyAverageKWH"]
                    )

                if current_usage.get("billToDate") is not None:
                    result["bill_to_date"] = float(
                        current_usage["billToDate"]
                    )

                if current_usage.get("projectedBill") is not None:
                    result["projected_bill"] = float(
                        current_usage["projectedBill"]
                    )

                if current_usage.get("dailyAvg") is not None:
                    result["daily_average_cost"] = float(
                        current_usage["dailyAvg"]
                    )

                if current_usage.get("avgHighTemp") is not None:
                    result["average_high_temperature"] = int(
                        current_usage["avgHighTemp"]
                    )

                if current_usage.get("billToDateKWH") is not None:
                    result["bill_to_date_kwh"] = float(
                        current_usage["billToDateKWH"]
                    )

                result["received_meter_reading"] = int(
                    current_usage.get("recMtrReading") or 0
                )

                result["delivered_meter_reading"] = int(
                    current_usage.get("delMtrReading") or 0
                )

                if current_usage.get("billStartDate"):
                    result["bill_start_date"] = datetime.strptime(
                        current_usage["billStartDate"],
                        "%m-%d-%Y",
                    ).date()

                if current_usage.get("billEndDate"):
                    result["bill_end_date"] = datetime.strptime(
                        current_usage["billEndDate"],
                        "%m-%d-%Y",
                    ).date()

        daily_usage = json_data.get("DailyUsage") or {}

        if isinstance(daily_usage, dict):
            exception = daily_usage.get("exceptionDetails")

            if not (
                isinstance(exception, dict)
                and exception.get("requestStatus") == "Failed"
            ):
                daily_rows = daily_usage.get("data") or []

                selected_row = None
                end_date = daily_usage.get("endDate")

                if end_date:
                    for row in daily_rows:
                        if row.get("date") == end_date:
                            selected_row = row
                            break

                if selected_row is None and daily_rows:
                    selected_row = daily_rows[-1]

                if selected_row:
                    read_time_raw = selected_row.get("readTime")

                    if read_time_raw:
                        result["latest_daily_usage"] = {
                            "kwh_actual": float(
                                selected_row.get("kwhActual") or 0
                            ),
                            "billing_charge": float(
                                selected_row.get("billingCharge") or 0
                            ),
                            "read_time": datetime.fromisoformat(
                                read_time_raw
                            ),
                            "reading": float(
                                selected_row.get("reading") or 0
                            ),
                            "net_delivered_kwh": float(
                                selected_row.get("netDeliveredKwh") or 0
                            ),
                            "net_delivered_reading": float(
                                selected_row.get("netDeliveredReading") or 0
                            ),
                        }

        return {
            **account_info,
            **result,
        }

    async def get_hourly_usage(
        self,
        account: str,
        usage_date: date,
    ) -> list[dict[str, Any]]:
        """Return hourly energy usage for a specific date."""
        account_info = await self.get_account_info(account)

        premise = account_info.get("premise")

        if not premise:
            raise FplClientError(
                "FPL account did not provide a premise number."
            )

        session = self._require_session()

        request_body = {
            "premiseNumber": premise,
            "startDate": usage_date.strftime("%m-%d-%Y"),
        }

        url = HOURLY_USAGE_URL.format(account=account)

        async with session.post(
            url,
            json=request_body,
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
        ) as response:
            if response.status != 200:
                raise FplClientError(
                    f"Hourly usage request failed with "
                    f"HTTP {response.status}."
                )

            response_data = await response.json()

        json_data = response_data.get("data") or {}
        hourly_usage_block = json_data.get("HourlyUsage")

        if isinstance(hourly_usage_block, list):
            hourly_usage = hourly_usage_block
        elif isinstance(hourly_usage_block, dict):
            hourly_usage = hourly_usage_block.get("data") or []
        else:
            hourly_usage = []

        result: list[dict[str, Any]] = []

        for row in hourly_usage:
            if not isinstance(row, dict):
                continue

            read_time_raw = row.get("readTime")

            if read_time_raw is None:
                continue

            result.append(
                {
                    "hour": row.get("hour"),
                    "read_time": datetime.fromisoformat(
                        read_time_raw
                    ),
                    "billing_charge": row.get("billingCharged"),
                    "kwh": row.get("kwhActual"),
                    "meter_reading": row.get("reading"),
                }
            )

        return result

    async def get_appliance_usage(
        self,
        account: str,
    ) -> dict[str, Any]:
        """Return FPL's appliance usage estimates."""
        account_info = await self.get_account_info(account)

        premise = account_info.get("premise")

        if not premise:
            raise FplClientError(
                "FPL account did not provide a premise number."
            )

        session = self._require_session()

        request_body = {
            "premiseId": premise,
            "accountNumber": account,
        }

        url = APPLIANCE_USAGE_URL.format(account=account)

        async with session.post(
            url,
            json=request_body,
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
        ) as response:
            if response.status != 200:
                response_text = await response.text()

                raise FplClientError(
                    f"Appliance usage request failed with "
                    f"HTTP {response.status}: {response_text}"
                )

            response_data = await response.json()

        return response_data.get("data") or {}

    async def logout(self) -> None:
        """Log out from FPL."""
        if self.session is None or self.session.closed:
            self.jwt_token = None
            return

        try:
            async with self.session.get(
                LOGOUT_URL,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
            ):
                pass
        finally:
            self.jwt_token = None
