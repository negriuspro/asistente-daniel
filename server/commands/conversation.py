import random

_RESPONSES: dict[str, list[str]] = {
    "hola":         ["Hola, ¿en qué te puedo ayudar?", "Hola. Estoy listo.", "¡Hola!"],
    "buenas":       ["Buenas, ¿en qué te ayudo?", "Hola, aquí estoy."],
    "cómo estás":   ["Operando al cien por ciento.", "Todo en orden.", "Listo para ayudar."],
    "como estas":   ["Operando al cien por ciento.", "Todo en orden.", "Listo para ayudar."],
    "gracias":      ["De nada.", "Para eso estoy.", "Con gusto."],
    "quién eres":   ["Soy Jarvis, tu asistente personal.", "Me llamo Jarvis."],
    "quien eres":   ["Soy Jarvis, tu asistente personal.", "Me llamo Jarvis."],
    "qué puedes":   ["Puedo abrir apps, buscar en internet y decirte la hora."],
    "que puedes":   ["Puedo abrir apps, buscar en internet y decirte la hora."],
    "ayuda":        ["Di 'jarvis abre [app]', 'jarvis busca [algo]' o 'jarvis qué hora es'."],
    "adiós":        ["Hasta luego.", "Adiós."],
    "adios":        ["Hasta luego.", "Adiós."],
    "silencio":     ["Entendido."],
    "para":         ["De acuerdo."],
}


def match(text: str) -> str | None:
    for key, responses in _RESPONSES.items():
        if key in text:
            return random.choice(responses)
    return None


def default_response(_: str) -> str:
    return "No entendí ese comando. Intenta de nuevo."
