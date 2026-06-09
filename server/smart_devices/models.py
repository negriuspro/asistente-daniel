"""
Modelos de datos para el módulo Dispositivos Inteligentes.
Todos los dispositivos heredan de SmartDevice base.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
import time


DEVICE_TYPES = [
    "camera",
    "tv",
    "plug",
    "ir_controller",
    "computer",
    "phone",
    "router",
    "unknown",
]

PROTOCOLS = [
    "http",
    "https",
    "rtsp",
    "onvif",
    "mqtt",
    "websocket",
    "ssh",
    "telnet",
    "matter",
    "zigbee",
    "zwave",
    "esphome",
    "tasmota",
    "tuya_local",
    "home_assistant",
]

CONTROL_PRIORITY = [
    "local_api",
    "local_http",
    "home_assistant",
    "mqtt",
    "manufacturer_cloud",
]


@dataclass
class SmartDevice:
    id: str  # mac_address o ip como fallback
    ip: str
    device_type: str = "unknown"
    name: str = ""
    manufacturer: str = ""
    model: str = ""
    hostname: str = ""
    mac: str = ""
    open_ports: list[int] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    credentials: dict[str, str] = field(default_factory=dict)
    control_method: str = ""  # método de control activo
    state: dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)
    added_at: float = field(default_factory=time.time)
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # No enviar credenciales al frontend
        d.pop("credentials", None)
        return d

    def to_dict_full(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SmartDevice:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class ScanResult:
    ip: str
    mac: str = ""
    hostname: str = ""
    manufacturer: str = ""
    open_ports: list[int] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)
    device_type: str = "unknown"
    response_ms: float = 0.0
