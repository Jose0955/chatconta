"""
Motor de IA de PoConta (sin Streamlit, para poder usarlo también en las pruebas).

- Prueba varios modelos de Groq en cadena: si uno llega a su límite (429), es
  demasiado grande (413) o no está disponible (404), pasa al siguiente.
- Puede darle a la IA "herramientas" (calculos_tributarios.py): la IA pide el
  cálculo, Python lo hace con exactitud y la IA solo lo explica (function calling).
"""
import json

from calculos_tributarios import HERRAMIENTAS_SCHEMA, ejecutar_herramienta

MODELOS_CHAT = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

_SENALES_LIMITE = (
    "429", "rate_limit", "rate limit", "413", "too large",
    "404", "model_not_found", "decommissioned", "does not exist", "not found",
)
_SENALES_HERRAMIENTAS = ("tool", "function")


def _crear(client, modelo, mensajes, herramientas, max_tokens):
    """Una llamada a Groq. En modelos gpt-oss pide razonamiento 'bajo' (más barato);
    si el modelo no acepta ese parámetro, reintenta sin él."""
    intentos = [{"reasoning_effort": "low"}, {}] if modelo.startswith("openai/gpt-oss") else [{}]
    ultimo = None
    for extra in intentos:
        try:
            parametros = dict(model=modelo, messages=mensajes, max_tokens=max_tokens)
            if herramientas:
                parametros["tools"] = herramientas
                parametros["tool_choice"] = "auto"
            if extra:
                parametros["extra_body"] = extra
            return client.chat.completions.create(**parametros)
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if extra and "reasoning" in str(e).lower():
                continue
            raise
    raise ultimo


def _intentar(client, modelo, mensajes, con_herramientas, max_tokens, max_rondas, info):
    """Conversa con UN modelo; si pide herramientas, las ejecuta y le devuelve los
    resultados hasta obtener la respuesta final de texto."""
    msgs = list(mensajes)
    herramientas = HERRAMIENTAS_SCHEMA if con_herramientas else None
    for ronda in range(max_rondas + 1):
        r = _crear(client, modelo, msgs, herramientas if ronda < max_rondas else None, max_tokens)
        m = r.choices[0].message
        llamadas = (getattr(m, "tool_calls", None) or []) if herramientas else []
        if llamadas:
            msgs.append({
                "role": "assistant",
                "content": m.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in llamadas
                ],
            })
            for tc in llamadas:
                try:
                    argumentos = json.loads(tc.function.arguments or "{}")
                    resultado = ejecutar_herramienta(tc.function.name, argumentos)
                except Exception as e:  # noqa: BLE001
                    resultado = {"error": f"Argumentos inválidos: {e}"}
                info["herramientas"].append(tc.function.name)
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(resultado, ensure_ascii=False),
                })
            continue
        texto = (m.content or "").strip()
        if texto:
            info["modelo"] = modelo
            return texto
        raise RuntimeError("respuesta vacía")
    raise RuntimeError("sin respuesta final tras las rondas de herramientas")


def responder(client, mensajes, modelos=None, usar_herramientas=False, max_tokens=1500, max_rondas=4):
    """Devuelve (texto, info). info = {"modelo", "herramientas": [...], "avisos": n}.
    Lanza la última excepción si todos los modelos fallan."""
    modelos = modelos or MODELOS_CHAT
    info = {"modelo": None, "herramientas": [], "avisos": 0}
    ultimo_error = None
    for modelo in modelos:
        variantes = [True, False] if usar_herramientas else [False]
        for con_herramientas in variantes:
            try:
                info["herramientas"] = []
                texto = _intentar(client, modelo, mensajes, con_herramientas, max_tokens, max_rondas, info)
                return texto, info
            except Exception as e:  # noqa: BLE001
                ultimo_error = e
                msg = str(e).lower()
                if any(s in msg for s in _SENALES_LIMITE) or "respuesta vacía" in msg:
                    info["avisos"] += 1
                    break  # siguiente modelo
                if con_herramientas and any(s in msg for s in _SENALES_HERRAMIENTAS):
                    continue  # mismo modelo, pero sin herramientas
                raise
    raise ultimo_error if ultimo_error else RuntimeError("Sin modelos disponibles")
