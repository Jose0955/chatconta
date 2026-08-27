import streamlit as st
from google import genai
from google.genai import types

# =========================================================
# CONFIGURACIÓN GENERAL DE LA PÁGINA
# =========================================================
st.set_page_config(
    page_title="ChatConta - Tutor Contable BGU",
    page_icon="📊",
    layout="centered"
)

st.title("📊 ChatConta: Tutor Virtual de Contabilidad")
st.write(
    "¡Hola! Soy tu asistente de contabilidad para Bachillerato Técnico. "
    "Elige tu nivel en el panel de la izquierda y pregúntame lo que necesites."
)

# =========================================================
# 1. VALIDACIÓN DE API KEY
# =========================================================
api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.error(
        "⚠️ No se encontró la API Key de Gemini.\n\n"
        "Ve a la configuración de tu app en Streamlit Cloud → **Settings → Secrets** "
        "y agrega:\n\n`GEMINI_API_KEY = \"tu_clave_aqui\"`"
    )
    st.stop()

client = genai.Client(api_key=api_key)

# Nombre del modelo (capa gratuita de Google AI Studio)
MODEL_NAME = "gemini-2.5-flash"

# =========================================================
# 2. BARRA LATERAL: SELECCIÓN DE NIVEL Y OPCIONES
# =========================================================
with st.sidebar:
    st.header("⚙️ Opciones")

    nivel = st.radio(
        "Selecciona tu nivel:",
        [
            "1.º Bachillerato",
            "2.º Bachillerato",
            "3.º Bachillerato",
        ],
        index=0,
    )

    st.markdown("---")
    st.caption(
        "**1.º:** Conceptos básicos, ecuación contable, asientos simples.\n\n"
        "**2.º:** Ajustes, depreciaciones, IVA, retenciones, balances.\n\n"
        "**3.º:** Costos, Kardex (PEPS/Promedio), rol de pagos."
    )

    st.markdown("---")
    if st.button("🗑️ Borrar conversación"):
        st.session_state.messages = []
        st.session_state.chat_session = None
        st.rerun()

# =========================================================
# 3. PROMPT DEL SISTEMA (se adapta según el nivel elegido)
# =========================================================
TEMAS_POR_NIVEL = {
    "1.º Bachillerato": """
- Conceptos básicos: ¿Qué es contabilidad?, Ecuación contable (Activo = Pasivo + Patrimonio).
- Clasificación y naturaleza de cuentas (Debe / Haber, Saldo Deudor / Acreedor).
- Asientos contables básicos de comercio (compras, ventas al contado y crédito).
""",
    "2.º Bachillerato": """
- Ajustes contables, depreciaciones de activos fijos y amortizaciones.
- Retenciones en la fuente e IVA en compras y ventas.
- Balance de comprobación y Estado de Resultados.
""",
    "3.º Bachillerato": """
- Contabilidad de Costos (Materia prima, Mano de obra, CIF).
- Conciliaciones bancarias y control de inventarios (Kardex: PEPS, Promedio Ponderado).
- Rol de pagos, beneficios sociales y liquidaciones.
""",
}

SYSTEM_PROMPT = f"""
Eres "ChatConta", un tutor virtual de Inteligencia Artificial especializado en Contabilidad
para Bachillerato Técnico. El estudiante que te habla está actualmente en: {nivel}.

TEMAS PRIORITARIOS PARA ESTE NIVEL:
{TEMAS_POR_NIVEL[nivel]}

Puedes ayudar con temas de otros niveles si el estudiante lo pide explícitamente,
pero por defecto enfoca tus explicaciones y ejemplos en el nivel indicado arriba.

CÓMO DEBES RESPONDER A DUDAS Y REGISTROS EN LIBROS CONTABLES:
1. Si el estudiante te pide ayuda para registrar una transacción:
   - Muéstrale la estructura del asiento contable en formato de tabla (Libro Diario).
   - Explícale paso a paso por qué va en el DEBE y por qué va en el HABER.
   - Usa el método socrático: guíalo con preguntas en lugar de darle todo hecho si busca aprender.
2. Ejemplo de formato de Libro Diario que debes usar en tus respuestas:
   | Fecha | Detalle / Cuentas | Debe | Haber |
   | --- | --- | --- | --- |
   | DD/MM | **Caja / Bancos** | $XXX | |
   | | **Ventas** | | $XXX |
   | | **IVA Ventas (Pagar)** | | $XXX |
   | | *v/r Registro de venta de mercadería al contado* | | |
3. Usa un lenguaje claro, motivador y adaptable al nivel escolar.
"""

# =========================================================
# 4. INICIALIZAR HISTORIAL Y SESIÓN DE CHAT
# =========================================================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

if "nivel_actual" not in st.session_state:
    st.session_state.nivel_actual = nivel

# Si el usuario cambia de nivel, reiniciamos la sesión de chat
# para que el nuevo prompt de sistema se aplique.
if st.session_state.nivel_actual != nivel:
    st.session_state.nivel_actual = nivel
    st.session_state.chat_session = None

# =========================================================
# 5. MOSTRAR HISTORIAL GUARDADO
# =========================================================
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# =========================================================
# 6. PROCESAR ENTRADA DEL USUARIO
# =========================================================
if user_input := st.chat_input("Ejemplo: ¿Cómo registro una compra de mercadería al contado por $100?"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                # Creamos la sesión de chat solo una vez (o si cambió el nivel)
                if st.session_state.chat_session is None:
                    st.session_state.chat_session = client.chats.create(
                        model=MODEL_NAME,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                        ),
                    )

                response = st.session_state.chat_session.send_message(user_input)
                st.markdown(response.text)
                st.session_state.messages.append(
                    {"role": "assistant", "content": response.text}
                )

            except Exception as e:
                error_msg = str(e)
                st.error(f"DEBUG - Error completo: {error_msg}")
                if "404" in error_msg:
                    st.error(
                        "❌ El modelo de IA no está disponible. "
                        "Puede que Google haya cambiado el nombre del modelo. "
                        "Revisa la variable MODEL_NAME en el código."
                    )
                elif "403" in error_msg or "API key" in error_msg:
                    st.error(
                        "❌ Tu API Key no es válida o no tiene permisos. "
                        "Genera una nueva en Google AI Studio."
                    )
                elif "429" in error_msg:
                    st.error(
                        "⏳ Se alcanzó el límite de uso gratuito por ahora. "
                        "Espera unos minutos e inténtalo de nuevo."
                    )
                else:
                    st.error(f"Ocurrió un error inesperado: {error_msg}")
