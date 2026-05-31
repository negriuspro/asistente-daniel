"""Spotify control via spotipy Web API."""
import logging
import os

log = logging.getLogger("jarvis.spotify")


def _client():
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")

    if not client_id or not client_secret:
        return None

    scope = (
        "user-read-playback-state "
        "user-modify-playback-state "
        "user-read-currently-playing "
        "streaming"
    )
    try:
        sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
                cache_path=os.path.join(os.path.dirname(__file__), ".spotify_cache"),
                open_browser=False,
            )
        )
        return sp
    except Exception as e:
        log.warning("Spotify auth falló: %s", e)
        return None


def handle_spotify(action: str, query: str = "", volume: int = -1) -> str:
    sp = _client()
    if sp is None:
        return (
            "Spotify no configurado. Agrega SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET "
            "en el archivo .env. Obtén las credenciales en developer.spotify.com."
        )

    try:
        if action == "now_playing":
            return _now_playing(sp)
        elif action == "pause":
            sp.pause_playback()
            return "Pausado."
        elif action == "play":
            sp.start_playback()
            return "Reproduciendo."
        elif action == "next":
            sp.next_track()
            return "Siguiente canción."
        elif action in ("prev", "previous", "anterior"):
            sp.previous_track()
            return "Canción anterior."
        elif action == "volume" and volume >= 0:
            sp.volume(min(100, max(0, volume)))
            return f"Volumen Spotify al {volume}%."
        elif action == "search" and query:
            return _search_and_play(sp, query)
        else:
            return _now_playing(sp)
    except Exception as e:
        log.warning("Spotify error (%s): %s", action, e)
        return f"Error de Spotify: {e}"


def _now_playing(sp) -> str:
    current = sp.current_playback()
    if not current or not current.get("is_playing"):
        return "Spotify no está reproduciendo nada ahora mismo."
    item = current.get("item", {})
    track = item.get("name", "?")
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    progress_ms = current.get("progress_ms", 0)
    duration_ms = item.get("duration_ms", 1)
    mins = progress_ms // 60000
    secs = (progress_ms % 60000) // 1000
    return f"Suena: {track} — {artists} ({mins}:{secs:02d})"


def _search_and_play(sp, query: str) -> str:
    results = sp.search(q=query, limit=1, type="track")
    tracks = results.get("tracks", {}).get("items", [])
    if not tracks:
        return f"No encontré '{query}' en Spotify."
    track = tracks[0]
    uri = track["uri"]
    name = track["name"]
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    try:
        sp.start_playback(uris=[uri])
        return f"Poniendo: {name} — {artists}"
    except Exception:
        url = f"https://open.spotify.com/track/{track['id']}"
        return f"Abre Spotify manualmente: {url}"
