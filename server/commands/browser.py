import urllib.parse
import webbrowser

_SITES: dict[str, str] = {
    "google":     "https://google.com",
    "youtube":    "https://youtube.com",
    "discord":    "https://discord.com",
    "twitter":    "https://twitter.com",
    "facebook":   "https://facebook.com",
    "instagram":  "https://instagram.com",
    "github":     "https://github.com",
    "netflix":    "https://netflix.com",
    "gmail":      "https://mail.google.com",
    "maps":       "https://maps.google.com",
    "wikipedia":  "https://wikipedia.org",
    "whatsapp":   "https://web.whatsapp.com",
    "chatgpt":    "https://chat.openai.com",
    "claude":     "https://claude.ai",
}


def match(text: str) -> str | None:
    if text.startswith("abre "):
        target = text[5:].strip()
        url = _SITES.get(target)
        if url:
            webbrowser.open(url)
            return f"Abriendo {target}"
        if "." in target:
            webbrowser.open(f"https://{target}")
            return f"Abriendo {target}"

    elif text.startswith("busca ") or text.startswith("buscar "):
        query = text.split(" ", 1)[1].strip()
        webbrowser.open(f"https://google.com/search?q={urllib.parse.quote(query)}")
        return f"Buscando: {query}"

    return None
