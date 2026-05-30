# Compilar APK Jarvis — WebView

## Pre-requisitos
- Android Studio Hedgehog (2023.1) o superior
- Android SDK 34 instalado

## Pasos

1. Abrir Android Studio → **Open** → seleccionar esta carpeta `JarvisApp/`
2. Esperar a que Gradle sincronice (~2 min primera vez)
3. Editar la IP del servidor en:
   `app/src/main/java/com/jarvis/app/MainActivity.kt`
   Línea: `private val SERVER_URL = "http://192.168.1.100:8000"`
   → Reemplazar con la IP local de tu PC (ej. `192.168.0.105`)
4. Conectar la tablet por USB con depuración USB activada
5. **Run** → seleccionar la tablet → instalar

## Encontrar tu IP local (PC)

```powershell
ipconfig | findstr "IPv4"
```

Busca la línea de tu adaptador Wi-Fi, ej: `192.168.1.105`

## Notas
- `android:usesCleartextTraffic="true"` permite HTTP (no HTTPS) en Android 9+
- El APK solicita permiso de micrófono en el primer arranque
- El WebView se reconecta automáticamente si el servidor no está disponible
- Para generar APK de distribución: Build → Generate Signed APK
