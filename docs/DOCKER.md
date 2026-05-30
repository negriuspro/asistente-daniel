# Jarvis Docker Deployment

This project is configured for Docker Engine running inside WSL Ubuntu, without Docker Desktop.

## Architecture

Tablet or browser -> `nginx` on port `3000` -> static web frontend and FastAPI backend -> Docker SDK -> Docker Engine socket.

The Docker socket is the only host mount in the backend:

```yaml
/var/run/docker.sock:/var/run/docker.sock
```

The frontend never talks to Docker directly. The backend exposes only list, inspect, start, stop, restart, logs, and metrics endpoints under `/api/docker`. Those endpoints require `X-Jarvis-Admin-Token`; if `JARVIS_ADMIN_TOKEN` is empty, Docker controls are disabled.

## First Setup

From WSL Ubuntu:

```bash
cd /mnt/c/Users/je416/Desktop/proyectos\ con\ ia/jarvis
cp .env.docker.example .env
nano .env
```

Set at least:

```env
APP_HOST=0.0.0.0
APP_PORT=3000
GROQ_API_KEY=your_key
JARVIS_ADMIN_TOKEN=a_long_random_admin_token
```

## Build

```bash
docker compose build
```

## Start

```bash
docker compose up -d
```

Production access is through Nginx only:

```text
http://localhost:3000
http://<wsl-or-windows-lan-ip>:3000
```

## Stop

```bash
docker compose down
```

## Restart

```bash
docker compose restart
```

Restart one service:

```bash
docker compose restart backend
```

## Logs

All logs:

```bash
docker compose logs -f
```

One service:

```bash
docker compose logs -f backend
docker compose logs -f nginx
```

## Update Containers

```bash
docker compose pull
docker compose up -d --build
```

For this local app, `--build` is the important part after source changes.

## Rebuild After Changes

```bash
docker compose up -d --build
```

For development:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

The development override exposes the backend on `127.0.0.1:8000` for local debugging and runs Uvicorn with reload, while keeping production traffic on Nginx port `3000`.

## LAN Access From Tablets

Bind the public service to all WSL interfaces:

```env
APP_HOST=0.0.0.0
APP_PORT=3000
```

Find the Windows LAN IP from PowerShell:

```powershell
ipconfig
```

Use the IPv4 address of your Wi-Fi or Ethernet adapter, for example:

```text
http://192.168.1.50:3000
```

If the tablet cannot connect, allow inbound TCP `3000` in Windows Firewall.

## WSL Networking Notes

Docker is running inside WSL, so run Docker commands from Ubuntu:

```bash
wsl
cd /mnt/c/Users/je416/Desktop/proyectos\ con\ ia/jarvis
docker ps
docker compose up -d
```

Modern WSL forwards ports bound to `0.0.0.0` to Windows. If LAN devices still cannot reach the app, use a Windows portproxy from an elevated PowerShell:

```powershell
$wslIp = wsl hostname -I
$wslIp = $wslIp.Trim().Split(" ")[0]
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=3000 connectaddress=$wslIp connectport=3000
New-NetFirewallRule -DisplayName "Jarvis 3000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3000
```

Remove the portproxy if needed:

```powershell
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=3000
```

## WebSockets

The browser connects to:

```javascript
ws://${location.host}/ws
```

Nginx proxies `/ws` to `backend:8000` with `Upgrade` and `Connection` headers, long read timeouts, and buffering disabled.

## Flutter Web

The current repository contains a static `client/` web app, not a Flutter project. The active production image serves that static app through Nginx.

When `client/pubspec.yaml` exists, switch the frontend build to the included Flutter multi-stage Dockerfile:

```yaml
frontend:
  build:
    context: .
    dockerfile: Dockerfile.frontend.flutter
```

That image runs `flutter build web --release` and serves `build/web` with Nginx.
