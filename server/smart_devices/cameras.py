"""
Módulo de cámaras IP.
Soporta ONVIF (descubrimiento WS-Discovery) y RTSP (verificación de stream).
"""

from __future__ import annotations
import asyncio
import socket
import struct
import uuid

import httpx


# Mensaje WS-Discovery para buscar dispositivos ONVIF en la red
_WS_DISCOVERY_MSG = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{msg_id}</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe>
  </e:Body>
</e:Envelope>"""


async def discover_onvif(timeout: float = 3.0) -> list[dict]:
    """
    Envía WS-Discovery multicast y recoge respuestas ONVIF.
    Retorna lista de {ip, xaddr, types}.
    """
    MCAST_ADDR = "239.255.255.250"
    MCAST_PORT = 3702
    msg = _WS_DISCOVERY_MSG.format(msg_id=str(uuid.uuid4())).encode()

    results: list[dict] = []

    def _run():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
            sock.settimeout(timeout)
            sock.sendto(msg, (MCAST_ADDR, MCAST_PORT))

            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                try:
                    data, addr = sock.recvfrom(4096)
                    text = data.decode(errors="ignore")
                    xaddrs = _extract_xml_tag(text, "XAddrs")
                    types = _extract_xml_tag(text, "Types")
                    results.append(
                        {
                            "ip": addr[0],
                            "xaddr": (
                                xaddrs.split()[0]
                                if xaddrs
                                else f"http://{addr[0]}/onvif/device_service"
                            ),
                            "types": types,
                        }
                    )
                except socket.timeout:
                    break
            sock.close()
        except Exception:
            pass

    await asyncio.to_thread(_run)
    return results


def _extract_xml_tag(text: str, tag: str) -> str:
    import re

    m = re.search(rf"<[^>]*{tag}[^>]*>(.*?)<", text, re.DOTALL)
    return m.group(1).strip() if m else ""


async def probe_onvif(
    ip: str, port: int = 80, user: str = "", password: str = ""
) -> dict:
    """
    Consulta la descripción ONVIF de una cámara (GetDeviceInformation).
    Retorna {manufacturer, model, firmware, serial, supported: bool}.
    """
    url = f"http://{ip}:{port}/onvif/device_service"
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <s:Body><tds:GetDeviceInformation/></s:Body>
</s:Envelope>"""

    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "SOAPAction": '"http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation"',
    }

    auth = None
    if user:
        auth = (user, password)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, content=body, headers=headers, auth=auth)
            text = resp.text
            return {
                "manufacturer": _extract_xml_tag(text, "Manufacturer"),
                "model": _extract_xml_tag(text, "Model"),
                "firmware": _extract_xml_tag(text, "FirmwareVersion"),
                "serial": _extract_xml_tag(text, "SerialNumber"),
                "supported": resp.status_code == 200,
                "error": None,
            }
    except Exception as e:
        return {"supported": False, "error": str(e)}


async def probe_rtsp(
    ip: str, port: int = 554, path: str = "/", timeout: float = 3.0
) -> dict:
    """
    Verifica si un stream RTSP está disponible enviando OPTIONS.
    Retorna {available, url, methods}.
    """
    url = f"rtsp://{ip}:{port}{path}"
    request = (
        f"OPTIONS {url} RTSP/1.0\r\n" f"CSeq: 1\r\n" f"User-Agent: Daniel/1.0\r\n\r\n"
    ).encode()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.write(request)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(512), timeout=timeout)
        writer.close()

        text = data.decode(errors="ignore")
        ok = "RTSP/1.0 200" in text
        methods = ""
        for line in text.splitlines():
            if line.startswith("Public:"):
                methods = line.split(":", 1)[1].strip()

        return {"available": ok, "url": url, "methods": methods}
    except Exception as e:
        return {"available": False, "url": url, "error": str(e)}


# Rutas RTSP comunes por fabricante
RTSP_PATHS = [
    "/",
    "/stream1",
    "/stream2",
    "/live",
    "/live/ch0",
    "/h264",
    "/h264/ch1/main/av_stream",  # Hikvision
    "/cam/realmonitor?channel=1&subtype=0",  # Dahua
    "/live/0/MAIN",
    "/video1",
    "/Streaming/Channels/101",  # Hikvision
    "/onvif1",
    "/mediainput/h264",
]


async def find_rtsp_stream(
    ip: str, port: int = 554, user: str = "", password: str = ""
) -> str:
    """Prueba rutas RTSP comunes y retorna la primera que funcione."""
    for path in RTSP_PATHS:
        result = await probe_rtsp(ip, port, path)
        if result.get("available"):
            if user:
                return f"rtsp://{user}:{password}@{ip}:{port}{path}"
            return f"rtsp://{ip}:{port}{path}"
    return ""
