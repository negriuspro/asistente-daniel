import hashlib
import hmac
import time
import uuid
import requests

ACCESS_ID     = "wyf9yd4wtjvd9jq3kg47"
ACCESS_SECRET = "4588e64c92aa42f099e18c0722105011"
BASE_URL      = "https://openapi.tuyaus.com"

EMPTY_HASH = hashlib.sha256(b"").hexdigest()

DEVICE_IDS = [
    ("enchufe pc",         "ebe19fbbc69edc72263tx7"),
    ("control remoto",     "eb2db2dcf004768da5kiko"),
    ("luz led",            "eb310d448a4ef0252an5bx"),
    ("aire acondicionado", "eb9df4516b8a2e7a391qth"),
]


def _sign(secret: str, msg: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest().upper()


def get_token() -> str | None:
    t     = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    url   = "/v1.0/token?grant_type=1"
    msg   = ACCESS_ID + t + nonce + "GET\n" + EMPTY_HASH + "\n\n" + url
    sign  = _sign(ACCESS_SECRET, msg)
    r = requests.get(
        BASE_URL + url,
        headers={
            "client_id":   ACCESS_ID,
            "sign":        sign,
            "t":           t,
            "nonce":       nonce,
            "sign_method": "HMAC-SHA256",
        },
        timeout=10,
    )
    data = r.json()
    if not data.get("success"):
        print("Error obteniendo token:", data)
        return None
    return data["result"]["access_token"]


def get_device(token: str, device_id: str) -> dict:
    t     = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    url   = f"/v1.0/devices/{device_id}"
    msg   = ACCESS_ID + token + t + nonce + "GET\n" + EMPTY_HASH + "\n\n" + url
    sign  = _sign(ACCESS_SECRET, msg)
    r = requests.get(
        BASE_URL + url,
        headers={
            "client_id":    ACCESS_ID,
            "access_token": token,
            "sign":         sign,
            "t":            t,
            "nonce":        nonce,
            "sign_method":  "HMAC-SHA256",
        },
        timeout=10,
    )
    return r.json()


token = get_token()
if not token:
    raise SystemExit("No se pudo autenticar.")

print(f"Token OK\n{'='*50}")

for name, did in DEVICE_IDS:
    data = get_device(token, did)
    if data.get("success"):
        res = data["result"]
        print(f"\n{name}")
        print(f"  device_id : {did}")
        print(f"  local_key : {res.get('local_key', 'N/A')}")
        print(f"  ip        : {res.get('ip', 'N/A')}")
        print(f"  version   : {res.get('protocol_version', 'N/A')}")
    else:
        print(f"\n{name}: ERROR → {data}")
