@echo off
title JARVIS
cd /d "%~dp0"

echo.
echo  =========================================
echo     J A R V I S  Assistant  v2.0  [AI]
echo  =========================================
echo.

:: Verificar que existe .env
if not exist .env (
    echo  [ERROR] No se encontro el archivo .env
    echo  Ejecuta: copy .env.example .env
    echo  Luego agrega tu GROQ_API_KEY en ese archivo.
    echo.
    pause
    exit /b 1
)

:: Mostrar IP local para conectar la tablet
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set IP=%%a
    goto :found
)
:found
set IP=%IP: =%
echo  URL del servidor:
echo    PC    : http://localhost:8000
echo    Tablet: http://%IP%:8000
echo.
echo  Presiona Ctrl+C para detener.
echo.

python -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir server

echo.
echo  Servidor detenido.
pause
