#!/bin/sh
set -e
nginx -g 'daemon off;' &
exec uvicorn server.main:app --host 0.0.0.0 --port 8000 --proxy-headers
