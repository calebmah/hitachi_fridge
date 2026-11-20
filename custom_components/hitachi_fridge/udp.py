"""Shared Local LAN UDP port 50000 manager and per-appliance local transport.

Hitachi smart refrigerators ignore the sender's ephemeral UDP source port and
always transmit unicast replies to `<client_ip>:50000` (`UDPUtils.receive`).
`HitachiSharedUdpManager` binds `0.0.0.0:50000` once and multiplexes replies
across all configured refrigerators by matching `(SRC == dst, DST == src)`.
"""

from __future__ import annotations

import asyncio
from datetime import tzinfo
import logging
import socket

from .const import CtrlCode, UDP_BROADCAST_ADDR, UDP_PORT, UDP_TIMEOUT_SECONDS
from .crypto import decrypt_udp_packet, encrypt_udp_packet, format_time_hex_16
from .models import ApplianceDevice, FridgeTelemetry

_LOGGER = logging.getLogger(__name__)


class _SharedUdpProtocol(asyncio.DatagramProtocol):
    """Asyncio datagram listener fanning incoming port 50000 packets to active waiters."""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self._queues: set[asyncio.Queue[tuple[bytes, tuple[str, int]]]] = set()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        for queue in list(self._queues):
            try:
                queue.put_nowait((data, addr))
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue[tuple[bytes, tuple[str, int]]]:
        queue: asyncio.Queue[tuple[bytes, tuple[str, int]]] = asyncio.Queue(maxsize=64)
        self._queues.add(queue)
        return queue

    def unsubscribe(
        self, queue: asyncio.Queue[tuple[bytes, tuple[str, int]]]
    ) -> None:
        self._queues.discard(queue)


class HitachiSharedUdpManager:
    """Reference-counted UDP port 50000 endpoint shared across config entries."""

    def __init__(self) -> None:
        self._protocol: _SharedUdpProtocol | None = None
        self._ref_count: int = 0
        self._bind_lock = asyncio.Lock()
        self._bind_failed_logged: bool = False

    @property
    def is_available(self) -> bool:
        """Return True if UDP port 50000 is currently bound."""
        return self._protocol is not None and self._protocol.transport is not None

    async def _async_ensure_bound_locked(self) -> bool:
        """Bind UDP `:50000` while holding `self._bind_lock`."""
        if self.is_available:
            return True

        sock: socket.socket | None = None
        try:
            sock = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setblocking(False)
            sock.bind(("0.0.0.0", UDP_PORT))
            loop = asyncio.get_running_loop()
            _, protocol = await loop.create_datagram_endpoint(
                _SharedUdpProtocol, sock=sock
            )
            self._protocol = protocol
            self._bind_failed_logged = False
            _LOGGER.debug(
                "Bound shared Hitachi Local UDP listener on 0.0.0.0:%s", UDP_PORT
            )
            return True
        except OSError as err:
            if sock is not None:
                sock.close()
            if not self._bind_failed_logged:
                _LOGGER.warning(
                    "Could not bind UDP port %s (%s); falling back to Hitachi Cloud polling. "
                    "If running Home Assistant in Docker, use host networking or publish %s:%s/udp",
                    UDP_PORT,
                    err,
                    UDP_PORT,
                    UDP_PORT,
                )
                self._bind_failed_logged = True
            return False

    async def async_acquire(self) -> bool:
        """Acquire a reference to the shared UDP `:50000` listener."""
        async with self._bind_lock:
            self._ref_count += 1
            return await self._async_ensure_bound_locked()

    async def async_release(self) -> None:
        """Release a reference and close UDP `:50000` when no entries remain."""
        async with self._bind_lock:
            self._ref_count = max(0, self._ref_count - 1)
            if self._ref_count == 0 and self._protocol is not None:
                if self._protocol.transport is not None:
                    self._protocol.transport.close()
                self._protocol = None
                _LOGGER.debug("Closed shared Hitachi Local UDP listener on port %s", UDP_PORT)

    async def async_send_and_receive(
        self,
        appliance: ApplianceDevice,
        target_ip: str,
        frame: str,
        timeout: float = UDP_TIMEOUT_SECONDS,
    ) -> tuple[dict[str, str], str]:
        """Transmit an encrypted UDP request and await the matching appliance reply."""
        if not self.is_available:
            async with self._bind_lock:
                await self._async_ensure_bound_locked()
        if self._protocol is None or self._protocol.transport is None:
            raise OSError(f"Local UDP port {UDP_PORT} is not available")

        packet = encrypt_udp_packet(
            frame=frame,
            device_key=appliance.device_key,
            device_iv=appliance.device_iv,
            dst=appliance.dst,
        )
        queue = self._protocol.subscribe()
        try:
            deadline = asyncio.get_running_loop().time() + timeout
            self._protocol.transport.sendto(packet, (target_ip, UDP_PORT))

            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out waiting for UDP reply from {target_ip}:{UDP_PORT}"
                    )
                raw_reply, (sender_ip, _) = await asyncio.wait_for(
                    queue.get(), timeout=remaining
                )
                try:
                    parsed = decrypt_udp_packet(
                        packet=raw_reply,
                        device_key=appliance.device_key,
                        device_iv=appliance.device_iv,
                        dst=appliance.dst,
                    )
                except ValueError:
                    continue

                # Ignore broadcast loopback of our own request (`GRP=REQ`)
                if parsed.get("GRP") == "REQ":
                    continue
                if (
                    parsed.get("SRC") == appliance.dst
                    and parsed.get("DST") == appliance.src
                ):
                    return parsed, sender_ip
        finally:
            self._protocol.unsubscribe(queue)


class HitachiApplianceLocalClient:
    """Per-appliance Local LAN UDP client backed by `HitachiSharedUdpManager`."""

    def __init__(
        self,
        udp_manager: HitachiSharedUdpManager,
        appliance: ApplianceDevice,
    ) -> None:
        self._udp = udp_manager
        self.appliance = appliance
        self._seq: int = 0
        self._lock = asyncio.Lock()

    def _next_seq(self) -> str:
        """Return 2-digit uppercase hex sequence `01`..`FF` (`SequenceUtils.getSeq`)."""
        self._seq = (self._seq % 255) + 1
        return f"{self._seq:02X}"

    def _build_frame(self, cmd: str, data: str | None = None) -> str:
        seq = self._next_seq()
        if data is None:
            return (
                f"SEQ={seq}&SRC={self.appliance.src}&DST={self.appliance.dst}"
                f"&GRP=REQ&CMD={cmd}&"
            )
        return (
            f"SEQ={seq}&SRC={self.appliance.src}&DST={self.appliance.dst}"
            f"&GRP=REQ&CMD={cmd}&DATA={data}&"
        )

    async def async_discover_ip(
        self,
        broadcast_addr: str = UDP_BROADCAST_ADDR,
        timeout: float = UDP_TIMEOUT_SECONDS,
    ) -> str:
        """Broadcast `CMD=SEARCH` on `:50000` to discover the refrigerator's LAN IP."""
        async with self._lock:
            frame = self._build_frame("SEARCH")
            parsed, sender_ip = await self._udp.async_send_and_receive(
                appliance=self.appliance,
                target_ip=broadcast_addr,
                frame=frame,
                timeout=timeout,
            )
            if parsed.get("GRP") != "ACK":
                raise RuntimeError(f"UDP SEARCH rejected: {parsed}")
            self.appliance.fridge_ip = sender_ip
            return sender_ip

    async def async_get_telemetry(
        self,
        target_ip: str | None = None,
        tz: tzinfo | None = None,
    ) -> tuple[FridgeTelemetry, str]:
        """Poll real-time 45-byte telemetry via Local UDP (`CMD=MOVEINF`)."""
        ip_addr = target_ip or self.appliance.fridge_ip
        if not ip_addr:
            ip_addr = await self.async_discover_ip()

        async with self._lock:
            frame = self._build_frame("MOVEINF")
            parsed, sender_ip = await self._udp.async_send_and_receive(
                appliance=self.appliance,
                target_ip=ip_addr,
                frame=frame,
            )
            if parsed.get("GRP") != "ACK":
                raise RuntimeError(f"UDP MOVEINF rejected: {parsed}")
            data_field = parsed.get("DATA", "")
            # Local UDP MOVEINF returns `DATA=<retCode>,<90-hex-char>`
            parts = data_field.split(",")
            hex_payload = parts[1] if len(parts) >= 2 else parts[0]
            telemetry = FridgeTelemetry.from_moveinf_hex(
                hex_payload, self.appliance.dst, tz=tz
            )
            return telemetry, sender_ip

    async def async_send_control(
        self,
        ctrl_code: CtrlCode | str,
        ctrl_data: str,
        target_ip: str | None = None,
    ) -> None:
        """Send a `CTRLINS` command via Local UDP."""
        ip_addr = target_ip or self.appliance.fridge_ip
        if not ip_addr:
            ip_addr = await self.async_discover_ip()

        code_str = ctrl_code.value if isinstance(ctrl_code, CtrlCode) else str(ctrl_code)
        data_arg = f"{format_time_hex_16()},{code_str},{ctrl_data}"

        async with self._lock:
            frame = self._build_frame("CTRLINS", data_arg)
            parsed, _ = await self._udp.async_send_and_receive(
                appliance=self.appliance,
                target_ip=ip_addr,
                frame=frame,
            )
            data_code = (parsed.get("DATA") or "").split(",")[0].strip()
            if parsed.get("GRP") != "ACK" or data_code in ("01", "02", "03", "FF"):
                if data_code == "01":
                    raise ValueError("Unable to access while pairing is in progress (E0041).")
                if data_code == "02":
                    raise ValueError(
                        "Not accessible because a refrigerator software update is in progress (E0042)."
                    )
                if data_code == "03":
                    raise ValueError(
                        "The refrigerator is currently being operated by another user (M0025)."
                    )
                if data_code == "FF":
                    raise ValueError(
                        "Operation rejected by refrigerator (door is open, ice maker/cleaning is active, or unit is under maintenance)."
                    )
                raise RuntimeError(
                    f"UDP CTRLINS ({code_str}={ctrl_data}) rejected: {parsed}"
                )
