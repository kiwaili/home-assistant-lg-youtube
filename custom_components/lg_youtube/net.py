"""Host, MAC, and Wake-on-LAN helpers. No Home Assistant imports."""

from __future__ import annotations

from urllib.parse import urlparse
import socket

_HEX = set("0123456789abcdef")


def normalize_host(value: str) -> str:
    """Return a bare host from an IP, hostname, or pasted URL."""
    text = value.strip()
    if not text:
        return ""
    if "://" in text:
        text = urlparse(text).hostname or ""
    else:
        text = text.split("/")[0]
        if "@" in text:
            text = text.rsplit("@", 1)[-1]
    return text.strip().strip("[]")


def normalize_mac(value: str) -> str:
    """Return a lowercase colon-separated MAC, or raise ValueError."""
    hexdigits = value.strip().lower().replace(":", "").replace("-", "").replace(".", "")
    if len(hexdigits) != 12 or any(char not in _HEX for char in hexdigits):
        raise ValueError(f"Invalid MAC address: {value.strip()}")
    return ":".join(hexdigits[index : index + 2] for index in range(0, 12, 2))


def send_wake_on_lan(mac: str, ip_address: str | None = None) -> None:
    """Broadcast a Wake-on-LAN magic packet, and unicast it to the TV IP."""
    payload = bytes.fromhex(normalize_mac(mac).replace(":", ""))
    packet = b"\xff" * 6 + payload * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, ("255.255.255.255", 9))
        if ip_address:
            sock.sendto(packet, (ip_address, 9))
