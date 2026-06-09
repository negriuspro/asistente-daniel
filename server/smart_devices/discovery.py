"""
Descubrimiento de dispositivos en la red local.
Escanea IPs, detecta puertos, MAC, fabricante y clasifica el dispositivo.
Prioriza control local sobre nube.
"""

from __future__ import annotations
import asyncio
import ipaddress
import re
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from .models import ScanResult

# Puertos clave para clasificar dispositivos
_PORT_PROFILES: dict[int, list[str]] = {
    22: ["ssh"],
    23: ["telnet"],
    80: ["http"],
    443: ["https"],
    554: ["rtsp"],
    1883: ["mqtt"],
    4433: ["https"],
    5000: ["http"],
    7000: ["http"],
    8080: ["http"],
    8443: ["https"],
    8883: ["mqtt"],
    8888: ["http"],
    9090: ["http"],
    3000: ["http"],
    3001: ["http"],
    4357: ["home_assistant"],
    8123: ["home_assistant"],
    3702: ["onvif"],
    5353: ["mdns"],
    34567: ["hikvision"],
    37777: ["dahua"],
    49153: ["upnp"],
}

# OUI prefixes → fabricante (primeros 8 chars del MAC en minúsculas)
_OUI_MAP: dict[str, str] = {
    "d8:bb:c1": "TP-Link",
    "50:c7:bf": "TP-Link",
    "14:cc:20": "TP-Link",
    "b0:be:76": "TP-Link",
    "ac:84:c6": "TP-Link",
    "ec:08:6b": "TP-Link",
    "a8:57:4e": "Samsung",
    "8c:79:f0": "Samsung",
    "30:cd:a7": "Samsung",
    "78:bd:bc": "Samsung",
    "00:1d:f6": "LG",
    "a8:23:fe": "LG",
    "cc:2d:8c": "LG",
    "64:1c:b0": "LG",
    "d0:03:df": "Sony",
    "40:2b:a1": "Sony",
    "b0:d5:9d": "Sony",
    "dc:a6:32": "Raspberry Pi",
    "b8:27:eb": "Raspberry Pi",
    "e4:5f:01": "Raspberry Pi",
    "30:ae:a4": "Espressif",  # ESP32
    "d8:a0:1d": "Espressif",  # ESP32
    "ec:94:cb": "Espressif",
    "60:01:94": "Espressif",
    "24:6f:28": "Espressif",
    "84:cc:a8": "Espressif",
    "18:fe:34": "Espressif",  # ESP8266
    "2c:f4:32": "Espressif",
    "5c:cf:7f": "Espressif",
    "00:e0:4c": "Realtek",
    "4c:ed:fb": "Xiaomi",
    "78:11:dc": "Xiaomi",
    "ac:f7:f3": "Xiaomi",
    "f4:f5:d8": "Google",
    "54:60:09": "Google",
    "3c:5a:b4": "Google",
    "00:17:88": "Philips Hue",
    "ec:b5:fa": "Philips Hue",
    "00:1a:22": "Belkin",
    "94:10:3e": "Belkin",
    "b4:75:0e": "Tuya",
    "7c:49:eb": "Tuya",
    "48:e1:e9": "Tuya",
}


# Clasificación por puerto y fabricante
def _classify(ports: list[int], manufacturer: str, hostname: str) -> str:
    mfr = manufacturer.lower()
    host = hostname.lower()

    if (
        any(p in ports for p in [554, 3702, 34567, 37777])
        or "camera" in host
        or "cam" in host
    ):
        return "camera"
    if any(p in ports for p in [4357, 8123]):
        return "home_assistant"
    if "samsung" in mfr or "lg" in mfr or "sony" in mfr or "tv" in host:
        return "tv"
    if "espressif" in mfr or "tuya" in mfr or "plug" in host or "socket" in host:
        return "plug"
    if "raspberry" in mfr or "broadlink" in mfr or "ir" in host:
        return "ir_controller"
    if 22 in ports and "router" not in host:
        return "computer"
    if "phone" in host or "android" in host or "iphone" in host:
        return "phone"
    if 23 in ports or "router" in host or "gateway" in host or "ap" in host:
        return "router"
    return "unknown"


def _get_mac_from_arp(ip: str) -> str:
    try:
        out = subprocess.check_output(
            ["arp", "-a", ip], timeout=3, stderr=subprocess.DEVNULL
        ).decode()
        m = re.search(r"([\da-fA-F]{2}[:-]){5}[\da-fA-F]{2}", out)
        return m.group(0).lower().replace("-", ":") if m else ""
    except Exception:
        return ""


def _get_manufacturer(mac: str) -> str:
    if not mac:
        return ""
    prefix = mac[:8].lower()
    return _OUI_MAP.get(prefix, "")


def _scan_ports(ip: str, ports: list[int], timeout: float = 0.5) -> list[int]:
    open_ports = []
    for port in ports:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                open_ports.append(port)
        except (OSError, ConnectionRefusedError, TimeoutError):
            pass
    return open_ports


def _resolve_hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def _ping(ip: str, timeout: float = 0.5) -> float:
    """Retorna latencia en ms, -1 si no responde."""
    try:
        t0 = time.monotonic()
        with socket.create_connection((ip, 80), timeout=timeout):
            pass
        return (time.monotonic() - t0) * 1000
    except Exception:
        pass
    # Fallback: intentar ICMP via socket raw
    try:
        t0 = time.monotonic()
        socket.setdefaulttimeout(timeout)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, 1))
        s.close()
        elapsed = (time.monotonic() - t0) * 1000
        # Si no se rechaza inmediatamente, el host existe
        if elapsed < timeout * 1000:
            return elapsed
    except Exception:
        pass
    return -1.0


def _scan_single(ip: str) -> ScanResult | None:
    """Escanea un único host. Retorna None si no responde."""
    ports_to_check = list(_PORT_PROFILES.keys())
    open_ports = _scan_ports(ip, ports_to_check, timeout=0.4)

    if not open_ports:
        # Intentar ping básico
        latency = _ping(ip, timeout=0.3)
        if latency < 0:
            return None

    mac = _get_mac_from_arp(ip)
    manufacturer = _get_manufacturer(mac)
    hostname = _resolve_hostname(ip)

    protocols: list[str] = []
    for port in open_ports:
        protocols.extend(_PORT_PROFILES.get(port, []))
    protocols = list(dict.fromkeys(protocols))  # dedup preservando orden

    device_type = _classify(open_ports, manufacturer, hostname)

    return ScanResult(
        ip=ip,
        mac=mac,
        hostname=hostname,
        manufacturer=manufacturer,
        open_ports=open_ports,
        protocols=protocols,
        device_type=device_type,
    )


# Estado global del escaneo (una sola operación a la vez)
_scan_state: dict = {
    "running": False,
    "progress": 0,
    "total": 0,
    "results": [],
    "started_at": 0.0,
    "finished_at": 0.0,
}


def get_scan_state() -> dict:
    return dict(_scan_state)


async def scan_network(
    subnet: str = "",
    on_found: Callable[[ScanResult], None] | None = None,
) -> list[ScanResult]:
    """
    Escanea la subred local. Si subnet está vacío, lo detecta automáticamente.
    on_found se llama por cada dispositivo encontrado (para streaming).
    """
    global _scan_state

    if _scan_state["running"]:
        return []

    if not subnet:
        subnet = _detect_local_subnet()

    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return []

    hosts = [str(h) for h in network.hosts()]
    _scan_state.update(
        {
            "running": True,
            "progress": 0,
            "total": len(hosts),
            "results": [],
            "started_at": time.time(),
            "finished_at": 0.0,
        }
    )

    results: list[ScanResult] = []

    def _worker(ip: str) -> ScanResult | None:
        result = _scan_single(ip)
        _scan_state["progress"] += 1
        if result:
            _scan_state["results"].append(result.__dict__)
            if on_found:
                on_found(result)
        return result

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=64) as executor:
        futures = [loop.run_in_executor(executor, _worker, ip) for ip in hosts]
        done = await asyncio.gather(*futures)

    results = [r for r in done if r is not None]
    _scan_state.update(
        {
            "running": False,
            "finished_at": time.time(),
            "results": [r.__dict__ for r in results],
        }
    )
    return results


def _detect_local_subnet() -> str:
    """Detecta la subred local del host."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        # Asumir /24
        parts = local_ip.rsplit(".", 1)
        return f"{parts[0]}.0/24"
    except Exception:
        return "192.168.1.0/24"


async def probe_compatibility(ip: str) -> dict[str, bool]:
    """Verifica qué protocolos están disponibles en una IP específica."""
    checks = {
        "http": (ip, 80),
        "https": (ip, 443),
        "rtsp": (ip, 554),
        "onvif": (ip, 3702),
        "mqtt": (ip, 1883),
        "mqtt_tls": (ip, 8883),
        "ssh": (ip, 22),
        "telnet": (ip, 23),
        "home_assistant": (ip, 8123),
        "esphome": (ip, 6052),
        "websocket": (ip, 8080),
    }

    async def _check(proto: str, host: str, port: int) -> tuple[str, bool]:
        try:
            _, w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=1.0
            )
            w.close()
            return proto, True
        except Exception:
            return proto, False

    tasks = [_check(p, h, port) for p, (h, port) in checks.items()]
    results = await asyncio.gather(*tasks)
    return dict(results)
