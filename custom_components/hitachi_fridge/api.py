"""Hitachi Fridge Cloud API client with automatic session credential renewal."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta, tzinfo
import logging
from typing import Any

import aiohttp

from .const import (
    ACCOUNT_API_BASE_URL,
    APP_ID,
    APPLIANCE_API_URL,
    CtrlCode,
)
from .crypto import (
    WEB_BOOTSTRAP_IV,
    WEB_BOOTSTRAP_KEY,
    decrypt_aes_cbc_zero_pad,
    encrypt_aes_cbc_zero_pad,
    format_time_decimal_15,
    parse_dual_response,
    serialize_query_map,
)
from .models import (
    AlarmHistoryEntry,
    ApplianceDevice,
    CloudSessionData,
    DailyDoorStat,
    FirmwareStatus,
    FridgeTelemetry,
    extract_cloud_moveinf_hex,
    parse_alarm_history,
    parse_door_history_csv,
)

_LOGGER = logging.getLogger(__name__)

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"

SessionRenewedCallback = Callable[[CloudSessionData, list[ApplianceDevice]], None]

CLOUD_CTRLINS_ERRORS: dict[str, str] = {
    "1": "Refrigerator operation failed (E0013).",
    "2": "Refrigerator operation failed (E0013).",
    "3": "The refrigerator is currently being operated by another user (M0025).",
    "4": "Not accessible because a refrigerator software update is in progress (E0042).",
    "5": "Unable to access while pairing is in progress (E0041).",
}


class HitachiFridgeError(Exception):
    """Base exception for Hitachi Fridge API errors."""


class HitachiAuthError(HitachiFridgeError):
    """Raised when account credentials (email/password) are invalid or rejected."""


class HitachiTermsNotAcceptedError(HitachiAuthError):
    """Raised when the Hitachi account has not yet accepted Terms of Use."""


class HitachiConnectionError(HitachiFridgeError):
    """Raised when Hitachi Cloud endpoints cannot be reached."""


class HitachiCommandError(HitachiFridgeError):
    """Raised when the refrigerator or cloud rejects an operation."""


class HitachiCloudApiClient:
    """Async client for Hitachi Account Cloud and Appliance Control Cloud.

    Automatically renews `ckdn_token`, `ckdn_key`, `ckdn_iv`, and per-appliance
    `ckdn_device_key` credentials via `/my/api/login2` whenever session validation
    or decryption fails, invoking `on_session_renewed` to persist fresh keys.
    """

    def __init__(
        self,
        http_session: aiohttp.ClientSession,
        email: str | None = None,
        password: str | None = None,
        session_data: CloudSessionData | None = None,
        on_session_renewed: SessionRenewedCallback | None = None,
    ) -> None:
        self._http = http_session
        self._email = email
        self._password = password
        self.session_data = session_data
        self._on_session_renewed = on_session_renewed
        self._renew_lock = asyncio.Lock()

    @property
    def can_auto_renew(self) -> bool:
        """Return True if stored account credentials allow automatic renewal."""
        return bool(self._email and self._password)

    async def async_login(
        self,
        email: str | None = None,
        password: str | None = None,
    ) -> CloudSessionData:
        """Authenticate with `POST https://kadenfan.hitachi.co.jp/my/api/login2` (`wsGetHid`)."""
        login_email = email if email is not None else self._email
        login_password = password if password is not None else self._password
        if not login_email or not login_password:
            raise HitachiAuthError("Missing Hitachi account email or password")

        query = serialize_query_map(
            {
                "email": login_email,
                "password": login_password,
                "app_id": APP_ID,
                "scheme": "",
            }
        )
        body = encrypt_aes_cbc_zero_pad(WEB_BOOTSTRAP_KEY, WEB_BOOTSTRAP_IV, query)
        headers = {"Content-Type": FORM_CONTENT_TYPE}

        try:
            async with self._http.post(
                f"{ACCOUNT_API_BASE_URL}login2",
                data=body,
                headers=headers,
                timeout=HTTP_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise HitachiAuthError(
                        f"Hitachi login HTTP status {resp.status}"
                    )
                if resp.status >= 400:
                    raise HitachiConnectionError(
                        f"Hitachi login server error: HTTP {resp.status}"
                    )
                raw_reply = await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HitachiConnectionError(
                f"Failed to connect to Hitachi Account server: {err}"
            ) from err

        try:
            decrypted = decrypt_aes_cbc_zero_pad(
                WEB_BOOTSTRAP_KEY, WEB_BOOTSTRAP_IV, raw_reply
            )
            payload = parse_dual_response(decrypted)
        except (ValueError, UnicodeDecodeError) as err:
            raise HitachiConnectionError(
                f"Failed to decode Hitachi login response: {err}"
            ) from err

        status = str(payload.get("status", ""))
        if status != "0":
            raise HitachiAuthError(
                f"Hitachi login rejected credentials (status={status!r})"
            )

        agree_cd = str(payload.get("agree_cd") or "")
        if agree_cd != "1":
            raise HitachiTermsNotAcceptedError(
                "Please sign in once in the official Hitachi Fridge mobile app to accept the Terms of Use."
            )

        cspf_id = str(payload.get("cspf_id") or "")
        ckdn_token = str(payload.get("ckdn_token") or "")
        ckdn_key = str(payload.get("ckdn_key") or "")
        ckdn_iv = str(payload.get("ckdn_iv") or "")

        if not (cspf_id and ckdn_token and ckdn_key and ckdn_iv):
            raise HitachiAuthError(
                "Hitachi login2 succeeded but did not return appliance session keys"
            )

        udp_keys: dict[str, tuple[str, str]] = {}
        raw_dev_keys = str(payload.get("ckdn_device_key") or "")
        for row in raw_dev_keys.split("|"):
            cols = row.strip().split(",")
            if len(cols) >= 3 and cols[0]:
                udp_keys[cols[0]] = (cols[1], cols[2])

        session = CloudSessionData(
            cspf_id=cspf_id,
            ckdn_token=ckdn_token,
            ckdn_key_hex=ckdn_key,
            ckdn_iv_hex=ckdn_iv,
            login_datetime=str(payload.get("login_datetime") or ""),
            udp_keys_by_dst=udp_keys,
        )
        self._email = login_email
        self._password = login_password
        self.session_data = session
        return session

    async def async_renew_session(self) -> list[ApplianceDevice]:
        """Re-authenticate using stored email/password and refresh device credentials."""
        async with self._renew_lock:
            _LOGGER.info("Renewing Hitachi Fridge Cloud session credentials")
            session = await self.async_login()
            devices = await self._async_fetch_devices_raw()
            if self._on_session_renewed is not None:
                self._on_session_renewed(session, devices)
            return devices

    async def _async_post_appliance_cmd(
        self,
        params: dict[str, str],
        *,
        allow_renew: bool = True,
    ) -> dict[str, Any]:
        """Execute an encrypted request against `ap_outer_ctrl_filter2.cgi`.

        Automatically renews the session once if `ckdn_token` or `ckdn_key` has expired.
        """
        if self.session_data is None:
            if not self.can_auto_renew:
                raise HitachiAuthError("Hitachi Cloud session is not configured")
            await self.async_renew_session()
        assert self.session_data is not None

        plaintext = serialize_query_map(params)
        ciphertext = encrypt_aes_cbc_zero_pad(
            self.session_data.ckdn_key,
            self.session_data.ckdn_iv,
            plaintext,
        )
        # CRITICAL (`HttpMethods.lambda$new$0`): `ckdn_token` MUST be sent as `User-Agent`
        headers = {
            "User-Agent": self.session_data.ckdn_token,
            "Content-Type": FORM_CONTENT_TYPE,
        }

        try:
            async with self._http.post(
                APPLIANCE_API_URL,
                data=ciphertext,
                headers=headers,
                timeout=HTTP_TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403):
                    if allow_renew and self.can_auto_renew:
                        await self.async_renew_session()
                        return await self._async_post_appliance_cmd(
                            params, allow_renew=False
                        )
                    if resp.status in (401, 403):
                        raise HitachiAuthError(
                            f"Appliance Cloud rejected session token (HTTP {resp.status})"
                        )
                if resp.status >= 400:
                    raise HitachiConnectionError(
                        f"Appliance Cloud HTTP error {resp.status} for CMD={params.get('CMD')}"
                    )
                raw_reply = await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HitachiConnectionError(
                f"Failed to reach Hitachi Appliance Cloud: {err}"
            ) from err

        try:
            decrypted = decrypt_aes_cbc_zero_pad(
                self.session_data.ckdn_key,
                self.session_data.ckdn_iv,
                raw_reply,
            )
            parsed = parse_dual_response(decrypted)
        except (ValueError, UnicodeDecodeError) as err:
            if allow_renew and self.can_auto_renew:
                _LOGGER.debug(
                    "Cloud response decryption failed (%s); renewing session and retrying",
                    err,
                )
                await self.async_renew_session()
                return await self._async_post_appliance_cmd(params, allow_renew=False)
            raise HitachiConnectionError(
                f"Failed to decrypt Appliance Cloud response: {err}"
            ) from err

        # Check server maintenance sentinel (`-2130444266`)
        if str(parsed.get("DATA")) == "-2130444266":
            raise HitachiConnectionError("Hitachi Cloud server is under maintenance")

        return parsed

    def _parse_devinfo_list(self, devinfo_str: str) -> list[ApplianceDevice]:
        """Parse `ResGetDevIdHid.DEVINFO` into `ApplianceDevice` instances (`DevInfo.java`).

        `DevInfo(src, userName, dst, nickName, language)` unpacks columns as:
        `cols[0]=src`, `cols[1]=username`, `cols[2]=dst`, `cols[3]=nickname`, `cols[4]=lang`.
        """
        assert self.session_data is not None
        devices: list[ApplianceDevice] = []
        for entry in devinfo_str.split("|"):
            if not entry.strip():
                continue
            cols = entry.split(",")
            if len(cols) < 4:
                continue
            src, username, dst, nickname = cols[0], cols[1], cols[2], cols[3]
            lang = cols[4] if len(cols) >= 5 else "EN"
            key_hex, iv_hex = self.session_data.udp_keys_by_dst.get(dst, ("", ""))
            devices.append(
                ApplianceDevice(
                    dst=dst,
                    src=src,
                    nickname=nickname or "Hitachi Fridge",
                    username=username,
                    lang=lang,
                    device_key_hex=key_hex,
                    device_iv_hex=iv_hex,
                )
            )
        return devices

    async def _async_fetch_devices_raw(self) -> list[ApplianceDevice]:
        """Fetch paired refrigerators via `CMD=GETDEVIDHID` without triggering recursive renewal."""
        assert self.session_data is not None
        res = await self._async_post_appliance_cmd(
            {
                "CMD": "GETDEVIDHID",
                "HID": self.session_data.cspf_id,
                "APPTYPE": APP_ID,
                "NEEDLANG": "1",
            },
            allow_renew=False,
        )
        return self._parse_devinfo_list(str(res.get("DEVINFO") or ""))

    async def async_get_devices(self) -> list[ApplianceDevice]:
        """List paired refrigerators (`CMD=GETDEVIDHID`) with auto-renewal."""
        if self.session_data is None:
            await self.async_login()
        assert self.session_data is not None
        res = await self._async_post_appliance_cmd(
            {
                "CMD": "GETDEVIDHID",
                "HID": self.session_data.cspf_id,
                "APPTYPE": APP_ID,
                "NEEDLANG": "1",
            }
        )
        return self._parse_devinfo_list(str(res.get("DEVINFO") or ""))

    async def async_ensure_session_valid(self) -> None:
        """Check session via `CMD=LOGINCHK` (`LoginCheckService`) and renew if expired."""
        if self.session_data is None:
            if self.can_auto_renew:
                await self.async_renew_session()
            return

        res = await self._async_post_appliance_cmd(
            {
                "CMD": "LOGINCHK",
                "cspf_id": self.session_data.cspf_id,
                "login_datetime": self.session_data.login_datetime,
                "app_id": APP_ID,
            }
        )
        status = str(res.get("status") or "")
        if status != "0" and self.can_auto_renew:
            if status == "E4":
                _LOGGER.info(
                    "Hitachi LOGINCHK returned E4 (session reset after refrigerator firmware update); renewing session"
                )
            else:
                _LOGGER.debug(
                    "Hitachi LOGINCHK returned status=%r; renewing session automatically",
                    status,
                )
            await self.async_renew_session()

    async def async_get_telemetry(
        self,
        dst: str,
        src: str,
        tz: tzinfo | None = None,
    ) -> FridgeTelemetry:
        """Fetch 45-byte telemetry via Cloud (`CMD=MOVEINF`, `HR00300Fragment.java:1847`)."""
        res = await self._async_post_appliance_cmd(
            {"CMD": "MOVEINF", "SRC": src, "DST": dst}
        )
        grp = str(res.get("GRP") or "")
        if grp == "4":
            raise HitachiConnectionError(
                "Refrigerator firmware update is currently in progress (GRP=4)"
            )
        hex_payload = extract_cloud_moveinf_hex(str(res.get("DATA") or ""))
        if grp not in ("0", "3") or len(hex_payload) < 74:
            if self.can_auto_renew:
                await self.async_renew_session()
                res = await self._async_post_appliance_cmd(
                    {"CMD": "MOVEINF", "SRC": src, "DST": dst}, allow_renew=False
                )
                grp = str(res.get("GRP") or "")
                if grp == "4":
                    raise HitachiConnectionError(
                        "Refrigerator firmware update is currently in progress (GRP=4)"
                    )
                hex_payload = extract_cloud_moveinf_hex(str(res.get("DATA") or ""))
            if len(hex_payload) < 74:
                raise HitachiConnectionError(
                    f"Cloud MOVEINF returned invalid DATA (GRP={grp!r}, len={len(hex_payload)})"
                )
        return FridgeTelemetry.from_moveinf_hex(hex_payload, dst, tz=tz)

    async def async_send_control(
        self,
        dst: str,
        src: str,
        ctrl_code: CtrlCode | str,
        ctrl_data: str,
    ) -> None:
        """Send a remote control instruction via Cloud (`CMD=CTRLINS`, `HR00300Fragment.java:2001`)."""
        code_str = ctrl_code.value if isinstance(ctrl_code, CtrlCode) else str(ctrl_code)
        res = await self._async_post_appliance_cmd(
            {
                "CMD": "CTRLINS",
                "SRC": src,
                "DST": dst,
                "TIME": format_time_decimal_15(),
                "CTRLC": code_str,
                "CTRLD": ctrl_data,
            }
        )
        success = str(res.get("SUCCESS") or "")
        data_val = str(res.get("DATA") or "")
        if success != "0":
            if success in CLOUD_CTRLINS_ERRORS:
                raise HitachiCommandError(CLOUD_CTRLINS_ERRORS[success])
            if data_val == "-2130444285":
                raise HitachiCommandError(
                    "The refrigerator is currently busy or being operated by another user."
                )
            raise HitachiCommandError(
                f"Cloud CTRLINS ({code_str}={ctrl_data}) failed: {res}"
            )
        if data_val == "FF":
            raise HitachiCommandError(
                "Operation rejected by refrigerator (door is open, ice maker/cleaning is active, or unit is under maintenance)."
            )

    async def async_get_door_history(
        self,
        dst: str,
        src: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, DailyDoorStat]:
        """Fetch 10-day historical door-open statistics (`CMD=DELIVERY`)."""
        today = date.today()
        start = start_date or (today - timedelta(days=8))
        end = end_date or (today - timedelta(days=1))
        res = await self._async_post_appliance_cmd(
            {
                "CMD": "DELIVERY",
                "SRC": src,
                "DST": dst,
                "START": start.strftime("%Y%m%d"),
                "END": end.strftime("%Y%m%d"),
            }
        )
        return parse_door_history_csv(str(res.get("DATA") or ""))

    async def async_get_firmware_info(
        self, dst: str, src: str
    ) -> FirmwareStatus | None:
        """Query firmware version, update availability, and auto-update mode (`CMD=FWINFO`)."""
        res = await self._async_post_appliance_cmd(
            {"CMD": "FWINFO", "SRC": src, "DST": dst}
        )
        grp = str(res.get("GRP") or "")
        if grp not in ("0", "4"):
            return None
        fw_ver = str(res.get("FWVER") or "").strip()
        fw_mode = str(res.get("FWMODE") or "0").strip()
        fw_sts = str(res.get("FWSTS") or "0").strip()
        if not fw_ver:
            return None
        return FirmwareStatus(
            version=fw_ver,
            auto_update_enabled=(fw_mode != "0"),
            update_available=fw_sts in ("1", "2"),
            update_in_progress=(fw_sts == "2" or grp == "4"),
            raw_status=fw_sts,
            raw_mode=fw_mode,
        )

    async def async_set_firmware_auto_update(
        self, dst: str, src: str, enabled: bool
    ) -> None:
        """Enable or disable automatic firmware updates (`CMD=FWSETTING`)."""
        now_hhmm = datetime.now().strftime("%H%M")
        res = await self._async_post_appliance_cmd(
            {
                "CMD": "FWSETTING",
                "SRC": src,
                "DST": dst,
                "FWMODE": "1" if enabled else "0",
                "FWTIME": now_hhmm,
            }
        )
        if str(res.get("SUCCESS")) != "0":
            raise HitachiCommandError(f"Failed to update FWSETTING: {res}")

    async def async_execute_firmware_update(self, dst: str, src: str) -> None:
        """Trigger appliance firmware update installation (`CMD=FWEXE`, `ResFwExe.getGRP()`)."""
        res = await self._async_post_appliance_cmd(
            {"CMD": "FWEXE", "SRC": src, "DST": dst}
        )
        grp = str(res.get("GRP") or "")
        success = str(res.get("SUCCESS") or "")
        if grp != "0" and success not in ("0", "ACK"):
            raise HitachiCommandError(f"Failed to start firmware update: {res}")

    async def async_get_alarm_history(
        self, dst: str, src: str
    ) -> list[AlarmHistoryEntry]:
        """Fetch recent error and notification history (`CMD=HISTORY`)."""
        res = await self._async_post_appliance_cmd(
            {"CMD": "HISTORY", "SRC": src, "DST": dst}
        )
        return parse_alarm_history(str(res.get("DATA") or ""))

    async def async_get_disabled_push_notifications(self, src: str) -> set[str]:
        """Fetch muted notification IDs (`CMD=PUSHINF`)."""
        res = await self._async_post_appliance_cmd({"CMD": "PUSHINF", "SRC": src})
        if str(res.get("SUCCESS", "0")) != "0":
            raise HitachiCommandError(f"Failed to query PUSHINF: {res}")
        raw = str(res.get("PUSHINF") or "")
        return {item.strip() for item in raw.split(",") if item.strip()}

    async def async_set_disabled_push_notifications(
        self, src: str, disabled_ids: set[str]
    ) -> None:
        """Update muted notification IDs (`CMD=PUSHREG`)."""
        ordered = ",".join(sorted(disabled_ids))
        res = await self._async_post_appliance_cmd(
            {"CMD": "PUSHREG", "SRC": src, "PUSHINF": ordered}
        )
        if str(res.get("SUCCESS")) != "0":
            raise HitachiCommandError(f"Failed to update PUSHREG: {res}")

    async def async_set_device_nickname(
        self, dst: str, src: str, nickname: str
    ) -> None:
        """Update the refrigerator's display nickname (`CMD=SETDEVNAME`)."""
        res = await self._async_post_appliance_cmd(
            {"CMD": "SETDEVNAME", "SRC": src, "DST": dst, "NAME": nickname}
        )
        if str(res.get("SUCCESS", "0")) != "0":
            raise HitachiCommandError(f"Failed to set device nickname: {res}")
