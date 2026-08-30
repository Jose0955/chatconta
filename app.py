import streamlit as st
from groq import Groq
from datetime import datetime
import pandas as pd
import io
import re
import json
import random
import streamlit.components.v1 as components
from openpyxl.styles import Font

# =========================================================
# CONFIGURACIÓN GENERAL DE LA PÁGINA
# =========================================================
st.set_page_config(
    page_title="Contín - Tu Tutor de Contabilidad",
    page_icon="🤝",
    layout="centered"
)

# ---------------------------------------------------------
# ESTILOS PERSONALIZADOS — modo oscuro fijo, estilo "Gmail oscuro"
# (fondo casi negro + acentos azules), con estrellitas animadas.
# Al ser un tema FIJO (no depende del modo claro/oscuro del celular
# o la laptop), el contraste de texto siempre queda correcto.
# ---------------------------------------------------------
AZUL_ACENTO = "#8AB4F8"     # azul estilo Google/Gmail modo oscuro
AZUL_SUAVE = "#5B9BF0"
FONDO_APP = "#050709"        # negro más duro y sólido
FONDO_TARJETA = "#12161C"
FONDO_BURBUJA_USUARIO = "#1B2026"
FONDO_BURBUJA_ASISTENTE = "#0F1B2A"
TEXTO_CLARO = "#FFFFFF"

# Generamos posiciones aleatorias (pero fijas por sesión) para las estrellitas
random.seed(7)
_estrellas_html = ""
for i in range(35):
    top = random.uniform(0, 100)
    left = random.uniform(0, 100)
    tamano = random.uniform(2, 4)
    duracion = random.uniform(4, 9)
    retraso = random.uniform(0, 6)
    _estrellas_html += (
        f'<div class="estrella" style="'
        f'top:{top}%; left:{left}%; width:{tamano}px; height:{tamano}px; '
        f'animation-duration:{duracion}s; animation-delay:{retraso}s;"></div>'
    )

st.markdown(
    f"""
    <style>
    /* ---------- Fondo general y estrellitas animadas ---------- */
    .stApp {{
        background: {FONDO_APP} !important;
    }}
    html, body {{
        background-color: {FONDO_APP} !important;
    }}
    /* La zona de abajo donde vive la caja de texto (queda fuera de .stApp
       en algunas versiones de Streamlit y se veía blanca) */
    [data-testid="stBottom"],
    [data-testid="stBottomBlockContainer"],
    .stChatFloatingInputContainer,
    [data-testid="stAppViewContainer"] {{
        background-color: {FONDO_APP} !important;
    }}
    /* Barra decorativa roja de arriba -> la pasamos a azul para que combine */
    [data-testid="stDecoration"] {{
        background-image: linear-gradient(90deg, {AZUL_SUAVE}, {AZUL_ACENTO}) !important;
    }}

    .campo-estrellas {{
        position: fixed;
        top: 0; left: 0;
        width: 100%; height: 100%;
        overflow: hidden;
        pointer-events: none;
        z-index: 0;
    }}
    .estrella {{
        position: absolute;
        background: {AZUL_ACENTO};
        border-radius: 50%;
        opacity: 0.25;
        box-shadow: 0 0 6px 1px {AZUL_ACENTO};
        animation-name: flotar, titilar;
        animation-iteration-count: infinite;
        animation-timing-function: ease-in-out;
    }}
    @keyframes flotar {{
        0%   {{ transform: translateY(0px); }}
        50%  {{ transform: translateY(-18px); }}
        100% {{ transform: translateY(0px); }}
    }}
    @keyframes titilar {{
        0%, 100% {{ opacity: 0.15; }}
        50%      {{ opacity: 0.7; }}
    }}

    /* Todo el contenido va por encima del campo de estrellas */
    .main .block-container {{
        padding-top: 2rem;
        position: relative;
        z-index: 1;
    }}

    /* ---------- Texto general (arregla el problema de contraste) ---------- */
    .stApp, .stApp p, .stApp li, .stApp span, .stApp label,
    [data-testid="stMarkdownContainer"] {{
        color: {TEXTO_CLARO} !important;
    }}
    h1 {{
        color: {AZUL_ACENTO} !important;
    }}
    h2, h3, h4 {{
        color: {AZUL_SUAVE} !important;
    }}
    a {{ color: {AZUL_ACENTO} !important; }}

    /* ---------- Barra lateral ---------- */
    section[data-testid="stSidebar"] {{
        background-color: {FONDO_TARJETA} !important;
        border-right: 1px solid #23293380;
    }}
    section[data-testid="stSidebar"] * {{
        color: {TEXTO_CLARO} !important;
    }}

    /* ---------- Burbujas de chat ---------- */
    [data-testid="stChatMessage"] {{
        border-radius: 16px;
        border: 1px solid #23293380;
    }}
    [data-testid="stChatMessage"]:nth-of-type(odd) {{
        background-color: {FONDO_BURBUJA_USUARIO} !important;
    }}
    [data-testid="stChatMessage"]:nth-of-type(even) {{
        background-color: {FONDO_BURBUJA_ASISTENTE} !important;
        border-left: 3px solid {AZUL_ACENTO};
    }}

    /* ---------- Caja de texto del chat ---------- */
    [data-testid="stChatInput"] textarea {{
        background-color: {FONDO_TARJETA} !important;
        color: {TEXTO_CLARO} !important;
    }}
    [data-testid="stChatInput"] {{
        background-color: {FONDO_TARJETA} !important;
        border: 1px solid {AZUL_ACENTO}55 !important;
    }}

    /* ---------- Botones ---------- */
    .stButton button, .stDownloadButton button {{
        border-radius: 12px;
        background-color: {AZUL_ACENTO} !important;
        color: #0B0E14 !important;
        border: none !important;
        font-weight: 600;
    }}
    .stButton button:hover, .stDownloadButton button:hover {{
        background-color: {AZUL_SUAVE} !important;
    }}

    /* ---------- Expanders (paneles de voz y Excel) ---------- */
    [data-testid="stExpander"] {{
        background-color: {FONDO_TARJETA} !important;
        border-radius: 12px;
        border: 1px solid #23293380;
    }}

    /* ---------- Radios (nivel) ---------- */
    [data-testid="stSidebar"] [role="radiogroup"] label {{
        color: {TEXTO_CLARO} !important;
    }}
    </style>

    <div class="campo-estrellas">{_estrellas_html}</div>
    """,
    unsafe_allow_html=True,
)

st.title("🤝 Contín, tu asistente contable de confianza")

# ---------------------------------------------------------
# MASCOTA: Contín, el alien-pulpo contable 🐙
# Cambia de cara según el momento: pensando, hablando o feliz.
# ---------------------------------------------------------
def mascota_svg(estado: str = "normal") -> str:
    if estado == "pensando":
        ojos = """
            <circle cx="78" cy="95" r="13" fill="white"/>
            <circle cx="122" cy="95" r="13" fill="white"/>
            <circle cx="83" cy="90" r="6" fill="#0B3D91"/>
            <circle cx="127" cy="90" r="6" fill="#0B3D91"/>
        """
        boca = '<ellipse cx="100" cy="128" rx="7" ry="6" fill="#0B3D91"/>'
        extra = """
            <g class="burbuja-pensar">
                <circle cx="150" cy="55" r="5" fill="white" opacity="0.85"/>
                <circle cx="163" cy="42" r="7" fill="white" opacity="0.85"/>
                <ellipse cx="182" cy="24" rx="16" ry="12" fill="white" opacity="0.9"/>
                <text x="182" y="29" font-size="14" text-anchor="middle" fill="#5B9BF0">?</text>
            </g>
        """
    elif estado == "hablando":
        ojos = """
            <circle cx="78" cy="95" r="14" fill="white"/>
            <circle cx="122" cy="95" r="14" fill="white"/>
            <circle cx="80" cy="95" r="7" fill="#0B3D91"/>
            <circle cx="124" cy="95" r="7" fill="#0B3D91"/>
        """
        boca = '<ellipse cx="100" cy="130" rx="14" ry="11" fill="#0B3D91"/>'
        extra = """
            <g class="chispas">
                <path d="M158 60 L162 70 L172 72 L162 76 L158 86 L154 76 L144 72 L154 70 Z" fill="white" opacity="0.9"/>
                <circle cx="35" cy="65" r="4" fill="white" opacity="0.7"/>
            </g>
        """
    elif estado == "feliz":
        ojos = """
            <path d="M68 95 Q78 82 88 95" stroke="white" stroke-width="6" fill="none" stroke-linecap="round"/>
            <path d="M112 95 Q122 82 132 95" stroke="white" stroke-width="6" fill="none" stroke-linecap="round"/>
        """
        boca = '<path d="M78 122 Q100 148 122 122" stroke="#0B3D91" stroke-width="7" fill="none" stroke-linecap="round"/>'
        extra = """
            <g class="corazones">
                <text x="35" y="55" font-size="22">💙</text>
                <text x="160" y="45" font-size="18">✨</text>
                <text x="150" y="90" font-size="16">💙</text>
            </g>
        """
    elif estado == "bailando":
        ojos = """
            <path d="M68 95 Q78 82 88 95" stroke="white" stroke-width="6" fill="none" stroke-linecap="round"/>
            <path d="M112 95 Q122 82 132 95" stroke="white" stroke-width="6" fill="none" stroke-linecap="round"/>
        """
        boca = '<path d="M78 122 Q100 148 122 122" stroke="#0B3D91" stroke-width="7" fill="none" stroke-linecap="round"/>'
        extra = """
            <g class="notas-musicales">
                <text x="30" y="50" font-size="22">🎵</text>
                <text x="158" y="40" font-size="20">🎶</text>
            </g>
        """
    elif estado == "cantando":
        ojos = """
            <path d="M68 92 Q78 80 88 92" stroke="white" stroke-width="6" fill="none" stroke-linecap="round"/>
            <path d="M112 92 Q122 80 132 92" stroke="white" stroke-width="6" fill="none" stroke-linecap="round"/>
        """
        boca = '<ellipse cx="100" cy="132" rx="12" ry="14" fill="#0B3D91"/>'
        extra = """
            <g class="notas-musicales">
                <text x="150" y="45" font-size="24">🎵</text>
                <text x="28" y="60" font-size="18">🎶</text>
            </g>
            <g class="microfono">
                <rect x="150" y="98" width="12" height="26" rx="6" fill="#EEE"/>
                <line x1="156" y1="124" x2="156" y2="145" stroke="#5B9BF0" stroke-width="4"/>
                <circle cx="156" cy="96" r="10" fill="#DDD"/>
            </g>
        """
    else:  # normal / idle
        ojos = """
            <circle cx="78" cy="95" r="13" fill="white" class="parpadeo"/>
            <circle cx="122" cy="95" r="13" fill="white" class="parpadeo"/>
            <circle cx="78" cy="95" r="6" fill="#0B3D91"/>
            <circle cx="122" cy="95" r="6" fill="#0B3D91"/>
        """
        boca = '<path d="M85 125 Q100 135 115 125" stroke="#0B3D91" stroke-width="5" fill="none" stroke-linecap="round"/>'
        extra = ""

    # ---------------------------------------------------------
    # Accesorios: en modo "profesional" (explicando conta) usa
    # lentes + calculadora. En modo "amigo" (consejos, baile,
    # canto, celebración) se los quita y quedan tirados al lado.
    # ---------------------------------------------------------
    ESTADOS_PROFESIONALES = ("normal", "pensando", "hablando")
    if estado in ESTADOS_PROFESIONALES:
        accesorios = """
            <g class="lentes">
                <circle cx="78" cy="95" r="18" fill="#8AB4F8" fill-opacity="0.25" stroke="#0B3D91" stroke-width="3"/>
                <circle cx="122" cy="95" r="18" fill="#8AB4F8" fill-opacity="0.25" stroke="#0B3D91" stroke-width="3"/>
                <line x1="96" y1="95" x2="104" y2="95" stroke="#0B3D91" stroke-width="3"/>
            </g>
            <g class="calculadora">
                <rect x="150" y="118" width="26" height="34" rx="4" fill="#E8EAED" stroke="#3E7BD9" stroke-width="2"/>
                <rect x="154" y="122" width="18" height="7" rx="1" fill="#3E7BD9"/>
                <circle cx="157" cy="135" r="2" fill="#3E7BD9"/>
                <circle cx="163" cy="135" r="2" fill="#3E7BD9"/>
                <circle cx="169" cy="135" r="2" fill="#3E7BD9"/>
                <circle cx="157" cy="143" r="2" fill="#3E7BD9"/>
                <circle cx="163" cy="143" r="2" fill="#3E7BD9"/>
                <circle cx="169" cy="143" r="2" fill="#3E7BD9"/>
            </g>
        """
    else:
        # Modo amigo: lentes y calculadora tirados a un lado
        accesorios = """
            <g class="modo-amigo-doodle" opacity="0.8">
                <circle cx="182" cy="168" r="7" fill="none" stroke="#5B9BF0" stroke-width="2"/>
                <circle cx="196" cy="172" r="7" fill="none" stroke="#5B9BF0" stroke-width="2"/>
                <line x1="189" y1="169" x2="189" y2="171" stroke="#5B9BF0" stroke-width="2"/>
                <rect x="8" y="172" width="16" height="20" rx="3" fill="#E8EAED" stroke="#3E7BD9" stroke-width="2" transform="rotate(-18 16 182)"/>
            </g>
        """

    clase_extra = " mascota-bailando" if estado == "bailando" else ""

    svg_html = f"""
    <div class="mascota-flotante{clase_extra}">
    <svg viewBox="0 0 200 220" width="150" height="165" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <radialGradient id="cuerpoGrad" cx="40%" cy="35%" r="75%">
                <stop offset="0%" stop-color="#EAF3FF"/>
                <stop offset="45%" stop-color="#8AB4F8"/>
                <stop offset="100%" stop-color="#3E7BD9"/>
            </radialGradient>
        </defs>
        <g class="tentaculo t1"><path d="M55 165 Q40 190 50 215" stroke="#5B9BF0" stroke-width="14" fill="none" stroke-linecap="round"/></g>
        <g class="tentaculo t2"><path d="M80 175 Q75 200 82 218" stroke="#5B9BF0" stroke-width="14" fill="none" stroke-linecap="round"/></g>
        <g class="tentaculo t3"><path d="M120 175 Q125 200 118 218" stroke="#5B9BF0" stroke-width="14" fill="none" stroke-linecap="round"/></g>
        <g class="tentaculo t4"><path d="M145 165 Q160 190 150 215" stroke="#5B9BF0" stroke-width="14" fill="none" stroke-linecap="round"/></g>
        <line x1="70" y1="45" x2="55" y2="15" stroke="#5B9BF0" stroke-width="5" stroke-linecap="round"/>
        <circle cx="55" cy="12" r="7" fill="#EAF3FF" class="antena"/>
        <line x1="130" y1="45" x2="145" y2="15" stroke="#5B9BF0" stroke-width="5" stroke-linecap="round"/>
        <circle cx="145" cy="12" r="7" fill="#EAF3FF" class="antena"/>
        <ellipse cx="100" cy="110" rx="80" ry="75" fill="url(#cuerpoGrad)"/>
        {ojos}
        {boca}
        {extra}
        {accesorios}
    </svg>
    </div>
    """
    # Importante: quitamos cualquier línea en blanco, porque Streamlit
    # (al interpretar esto como Markdown) corta el bloque de HTML apenas
    # encuentra una línea vacía, y el resto se muestra como texto crudo.
    return "\n".join(linea for linea in svg_html.split("\n") if linea.strip() != "")


def lanzar_confeti():
    """Dispara una animación de confeti de colores. Usa canvas-confetti dentro
    de un componente HTML (necesario porque Streamlit no ejecuta <script>
    sueltos en st.markdown), con un tamaño real y visible de entrada, e
    intenta además expandirse a toda la pantalla."""
    components.html(
        """
        <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js"></script>
        <script>
        (function () {
            try {
                var marco = window.frameElement;
                if (marco) {
                    marco.style.position = 'fixed';
                    marco.style.top = '0';
                    marco.style.left = '0';
                    marco.style.width = '100vw';
                    marco.style.height = '100vh';
                    marco.style.zIndex = '999999';
                    marco.style.pointerEvents = 'none';
                    marco.style.border = 'none';
                }
            } catch (e) {}

            function empezar() {
                if (typeof confetti !== 'function') { setTimeout(empezar, 100); return; }
                var colores = ['#8AB4F8', '#5B9BF0', '#FFFFFF', '#EAF3FF', '#FFD166', '#FF6B6B'];
                confetti({ particleCount: 200, spread: 120, origin: { y: 0.3 }, colors: colores });
                var fin = Date.now() + 2800;
                (function ciclo() {
                    confetti({ particleCount: 8, angle: 60, spread: 80, origin: { x: 0, y: 0.6 }, colors: colores });
                    confetti({ particleCount: 8, angle: 120, spread: 80, origin: { x: 1, y: 0.6 }, colors: colores });
                    if (Date.now() < fin) { requestAnimationFrame(ciclo); }
                })();
            }
            empezar();
        })();
        </script>
        """,
        height=500,
    )
    # Respaldo garantizado: el efecto nativo de celebración de Streamlit,
    # que SIEMPRE funciona (no depende de scripts externos ni de CDNs).
    st.balloons()


def limpiar_para_voz(texto: str) -> str:
    """Prepara el texto de Contín para leerlo en voz alta: quita símbolos de
    Markdown (asteriscos, gatos, barras, etc.) y reemplaza las tablas por una
    frase corta, para que no suene raro al escucharlo."""
    lineas = texto.split("\n")
    resultado = []
    dentro_tabla = False
    for linea in lineas:
        if linea.strip().startswith("|"):
            if not dentro_tabla:
                resultado.append("Te dejé una tabla en pantalla con el detalle completo.")
                dentro_tabla = True
            continue
        dentro_tabla = False
        resultado.append(linea)

    texto_limpio = "\n".join(resultado)
    texto_limpio = re.sub(r'[*_#`>]', '', texto_limpio)
    texto_limpio = re.sub(r'\n{2,}', '. ', texto_limpio)
    texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()
    return texto_limpio


def hablar_texto(texto: str):
    """Hace que el navegador lea el texto en voz alta (texto-a-voz nativo,
    no necesita ningún servicio externo, funciona sin internet)."""
    texto_para_hablar = limpiar_para_voz(texto)
    if not texto_para_hablar:
        return
    texto_js = json.dumps(texto_para_hablar)
    components.html(
        f"""
        <script>
        try {{
            window.speechSynthesis.cancel();
            var utterance = new SpeechSynthesisUtterance({texto_js});
            utterance.lang = 'es-ES';
            utterance.rate = 1.02;
            utterance.pitch = 1.05;
            window.speechSynthesis.speak(utterance);
        }} catch (e) {{}}
        </script>
        """,
        height=0,
    )


if "mascota_estado" not in st.session_state:
    st.session_state.mascota_estado = "normal"

mascota_placeholder = st.empty()
_estado_inicial = "bailando" if st.session_state.get("bailando", False) else st.session_state.mascota_estado
with mascota_placeholder.container():
    st.markdown(mascota_svg(_estado_inicial), unsafe_allow_html=True)

st.markdown(
    f"""
    <style>
    .tentaculo {{ transform-origin: top center; animation: ondear 3s ease-in-out infinite; }}
    .t1 {{ animation-delay: 0s; }} .t2 {{ animation-delay: 0.4s; }}
    .t3 {{ animation-delay: 0.2s; }} .t4 {{ animation-delay: 0.6s; }}
    @keyframes ondear {{
        0%, 100% {{ transform: rotate(0deg); }}
        50% {{ transform: rotate(6deg); }}
    }}
    .antena {{ animation: brillo 2s ease-in-out infinite; }}
    @keyframes brillo {{
        0%, 100% {{ opacity: 0.6; filter: drop-shadow(0 0 2px {AZUL_ACENTO}); }}
        50% {{ opacity: 1; filter: drop-shadow(0 0 8px {AZUL_ACENTO}); }}
    }}
    .parpadeo {{
        transform-box: fill-box;
        transform-origin: center;
        animation: parpadear 4.5s ease-in-out infinite;
    }}
    @keyframes parpadear {{
        0%, 92%, 100% {{ transform: scaleY(1); }}
        95%           {{ transform: scaleY(0.1); }}
    }}

    /* ---------- Contín bailando 🕺 ---------- */
    .mascota-bailando {{
        animation: bailar 0.8s ease-in-out infinite !important;
    }}
    @keyframes bailar {{
        0%   {{ transform: translateX(0) rotate(-6deg); }}
        25%  {{ transform: translateX(-10px) rotate(6deg) translateY(-6px); }}
        50%  {{ transform: translateX(0) rotate(-6deg); }}
        75%  {{ transform: translateX(10px) rotate(6deg) translateY(-6px); }}
        100% {{ transform: translateX(0) rotate(-6deg); }}
    }}

    /* ---------- Contín flotante: siempre visible, sin importar el scroll ---------- */
    .mascota-flotante {{
        position: fixed;
        top: 78px;
        right: 18px;
        z-index: 999998;
        pointer-events: none;
        filter: drop-shadow(0 4px 10px rgba(0,0,0,0.5));
    }}
    .mascota-flotante svg {{
        width: 120px;
        height: 130px;
    }}
    @media (max-width: 640px) {{
        .mascota-flotante {{
            top: auto;
            bottom: 92px;
            right: 8px;
        }}
        .mascota-flotante svg {{
            width: 78px;
            height: 86px;
        }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.write(
    "¡Hola! Qué gusto tenerte por aquí 😊 Soy **Contín**, y estoy para ayudarte a "
    "entender contabilidad sin agobios ni tecnicismos raros. Aquí puedes preguntar "
    "lo que sea, las veces que necesites — para eso estoy. Elige tu nivel en el panel "
    "de la izquierda y cuéntame en qué andas."
)

# =========================================================
# 1. VALIDACIÓN DE API KEY
# =========================================================
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error(
        "⚠️ No se encontró la API Key de Groq.\n\n"
        "Ve a la configuración de tu app en Streamlit Cloud → **Settings → Secrets** "
        "y agrega:\n\n`GROQ_API_KEY = \"tu_clave_aqui\"`\n\n"
        "Consigue tu llave gratis en https://console.groq.com/keys"
    )
    st.stop()

client = Groq(api_key=api_key)

# Nombre del modelo (capa gratuita de Groq, sin tarjeta de crédito)
MODEL_NAME = "openai/gpt-oss-120b"
MODEL_TRANSCRIPCION = "whisper-large-v3-turbo"

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
    if st.button("🗑️ Empezar de nuevo"):
        st.session_state.messages = []
        st.session_state.historial_ia = []
        st.session_state.ultimo_audio_id = None
        st.session_state.audio_widget_key = st.session_state.get("audio_widget_key", 0) + 1
        st.rerun()

    st.markdown("---")
    st.caption("🐙 Contín")
    if "bailando" not in st.session_state:
        st.session_state.bailando = False
    if "modo_voz" not in st.session_state:
        st.session_state.modo_voz = False

    if st.button("🕺 ¡Que baile Contín!" if not st.session_state.bailando else "⏹️ Parar de bailar"):
        st.session_state.bailando = not st.session_state.bailando
        st.rerun()

    if st.button(
        "🎤 Activar modo conversación por voz" if not st.session_state.modo_voz
        else "🔇 Salir del modo conversación por voz"
    ):
        st.session_state.modo_voz = not st.session_state.modo_voz
        st.rerun()

    if st.session_state.modo_voz:
        st.caption("🔊 Contín te va a responder también en audio. Usa el panel '🎤 Preguntar por voz' de arriba para hablarle.")
        if st.button("❌ Cancelar audio"):
            components.html(
                "<script>try{window.speechSynthesis.cancel();}catch(e){}</script>",
                height=0,
            )
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

# ---------------------------------------------------------
# TABLA DE RETENCIONES SRI ECUADOR
# Vigente desde el 1 de marzo de 2026 (Resolución NAC-DGERCGC26-00000009
# para Impuesto a la Renta, y NAC-DGERCGC20-00000061 para IVA).
# ---------------------------------------------------------
TABLA_RETENCIONES = """
=====================================================================
TABLA OFICIAL DE RETENCIONES — SRI ECUADOR
(Vigente desde el 1 de marzo de 2026, Res. NAC-DGERCGC26-00000009)
=====================================================================

⚠️ REGLA CLAVE QUE SIEMPRE DEBES APLICAR ANTES DE CALCULAR:
Solo retienen (IR e IVA) quienes el SRI ha designado expresamente como:
   - Agentes de Retención
   - Contribuyentes Especiales
   - Entidades del sector público
Un negocio "normal" (régimen general, no designado) que compra a otro
NO debe registrar retención, aunque el otro sea sociedad o lleve contabilidad.
Los contribuyentes RIMPE (Emprendedores o Negocios Populares) tampoco son
agentes de retención por defecto.

Por eso, ANTES de calcular cualquier retención, si el estudiante no te lo
ha dicho, DEBES preguntarle (de forma breve y amigable, una pregunta a la vez):
1) ¿La empresa que compra (o paga) ha sido calificada por el SRI como
   Contribuyente Especial o Agente de Retención? (si no lo sabe, asume que SÍ
   para efines del ejercicio académico, pero acláraselo)
2) ¿El proveedor (a quien se le compra) es Contribuyente Especial también,
   o es un contribuyente de régimen general / persona natural?
3) ¿Qué tipo de bien o servicio es? (bien mueble, servicio profesional,
   arriendo, transporte, publicidad, etc.)
Con esas respuestas, busca el porcentaje correcto en las tablas de abajo.

---------------------------------------------------------------------
1) RETENCIÓN DE IVA
---------------------------------------------------------------------
Si el proveedor NO es Contribuyente Especial:
  - Bienes muebles gravados con IVA ................... 30%
  - Servicios, comisiones, consultoría ................. 70%
  - Servicios profesionales (persona natural con título) 100%
  - Arriendo de inmuebles (persona natural) ............ 100%
  - Honorarios a directorios ............................ 100%
  - Liquidaciones de compra ............................. 100%

Si el proveedor SÍ es Contribuyente Especial:
  - Bienes muebles gravados con IVA .................... 10%
  - Servicios, comisiones, consultoría .................. 20%

Casos especiales:
  - Contratos de construcción: 30% (siempre)
  - Importación de servicios / servicios digitales: 100%

---------------------------------------------------------------------
2) RETENCIÓN EN LA FUENTE DE IMPUESTO A LA RENTA (IR)
---------------------------------------------------------------------
0%   - Intereses a bancos/financieras supervisadas
     - Compras a RIMPE Negocios Populares

1%   - Transporte de carga o pasajeros
     - Bienes agrícolas/pecuarios comprados directo al productor
     - Compras a RIMPE Emprendedores

1.75% - Bienes agrícolas/pecuarios comprados a comercializadores (no productor)

2%   - Bienes muebles de naturaleza corporal (compra de mercadería en general)
     - Energía eléctrica
     - Seguros y reaseguros (sobre primas)
     - Arrendamiento mercantil (leasing)
     - Pagos con tarjeta de crédito/débito a afiliados
     - Construcción de obra material inmueble

3%   - Servicios donde prevalece la mano de obra (persona natural)
     - Publicidad y comunicación
     - Rendimientos financieros
     - Liquidaciones de compra (proveedor sin RUC)
     - Pagos sin porcentaje específico (regla residual/general)

5%   - Servicios profesionales prestados por SOCIEDADES (con profesional titulado)
     - Comisiones pagadas a sociedades residentes

10%  - Honorarios/comisiones a personas naturales (profesión liberal / intelecto)
     - Docencia a personas naturales
     - Cánones, regalías, derechos de propiedad intelectual
     - Arrendamiento de bienes inmuebles
     - Pagos por imagen o renombre (influencers, artistas, deportistas)

---------------------------------------------------------------------
3) EJEMPLO DE CÓMO DEBES PRESENTAR EL CÁLCULO
---------------------------------------------------------------------
Si el estudiante pregunta por una compra de $1,300 con retención de IVA
y de IR, sigue esta secuencia:
  1. Aclara/pregunta el tipo de contribuyente (comprador y proveedor).
  2. Identifica el % de retención IR según el tipo de bien/servicio.
  3. Identifica el % de retención de IVA según si el proveedor es o no
     Contribuyente Especial.
  4. Calcula el IVA de la compra (tarifa general 15%, salvo que se indique
     otra tarifa).
  5. Calcula el valor retenido de IR (% aplicado sobre el valor de la compra,
     SIN IVA) y el valor retenido de IVA (% aplicado sobre el IVA generado).
  6. Presenta el asiento completo en el Libro Diario, mostrando por separado
     la cuenta "IVA Compras", "Retención en la Fuente IR por Pagar" y
     "Retención de IVA por Pagar".
"""

# Fecha y hora reales del servidor, para que Contín nunca invente el día.
AHORA = datetime.now()
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
FECHA_ACTUAL_TEXTO = (
    f"{DIAS_ES[AHORA.weekday()]} {AHORA.day} de {MESES_ES[AHORA.month - 1]} de {AHORA.year}, "
    f"aproximadamente las {AHORA.strftime('%H:%M')}"
)

SYSTEM_PROMPT = f"""
Eres "Contín", un tutor virtual de Contabilidad para estudiantes de Bachillerato
Técnico en Ecuador. Tu personalidad es cercana, cálida y de mucha confianza:
hablas como un amigo mayor que sabe de contabilidad y disfruta enseñar, nunca
como un robot ni con lenguaje frío o excesivamente técnico. Usa un tono
motivador, cercano, con calidez ecuatoriana, pero siempre respetuoso (nunca
vulgar ni demasiado informal). Puedes usar alguna expresión cálida ocasional
("¡vamos con calma!", "no te preocupes, lo vemos juntos", "¡tú puedes!") sin
abusar de ellas. El estudiante siente que puede preguntar lo que sea, incluso
si le parece "básico", sin miedo a que lo juzguen.

El estudiante que te habla está actualmente en: {nivel}.

TEMAS PRIORITARIOS PARA ESTE NIVEL:
{TEMAS_POR_NIVEL[nivel]}

Puedes ayudar con temas de otros niveles si el estudiante lo pide explícitamente,
pero por defecto enfoca tus explicaciones y ejemplos en el nivel indicado arriba.

CÓMO DEBES RESPONDER A DUDAS Y REGISTROS EN LIBROS CONTABLES:
1. Si el estudiante te pide ayuda para registrar una transacción SIN retenciones:
   - Muéstrale la estructura del asiento contable en formato de tabla (Libro Diario).
   - Explícale paso a paso por qué va en el DEBE y por qué va en el HABER.
   - Usa el método socrático cuando el estudiante busque aprender: guíalo con
     preguntas en lugar de darle todo resuelto de inmediato.
2. Si el estudiante te pide ayuda para registrar una transacción CON retenciones
   (retención en la fuente de IR y/o retención de IVA), sigue estrictamente la
   TABLA_RETENCIONES que aparece más abajo: pregunta lo necesario, identifica el
   porcentaje correcto, y arma el asiento completo con las cuentas de retención
   separadas.
3. Ejemplo de formato de Libro Diario que debes usar en tus respuestas:
   | Fecha | Detalle / Cuentas | Debe | Haber |
   | --- | --- | --- | --- |
   | DD/MM | **Caja / Bancos** | $XXX | |
   | | **Ventas** | | $XXX |
   | | **IVA Ventas (Pagar)** | | $XXX |
   | | *v/r Registro de venta de mercadería al contado* | | |
4. Nunca inventes un porcentaje de retención: si no está en la tabla, dile al
   estudiante honestamente que ese caso no está en tu tabla de referencia y que
   lo confirme con su docente o en el portal del SRI (www.sri.gob.ec).

PREGUNTAS FUERA DE CONTABILIDAD (día, hora, saludos, ánimo, consejos, etc.):
Aunque tu tema principal es contabilidad, también puedes responder con naturalidad
preguntas sencillas de conversación cotidiana, por ejemplo:
- "¿Qué día es hoy?" o "¿qué hora es?": la fecha y hora actuales son:
  {FECHA_ACTUAL_TEXTO} (hora referencial de Ecuador). Respóndelo directo, sin rodeos.
- "Dame un consejo" / "estoy desanimado" / "motívame": da un consejo breve, cálido
  y motivador (puede o no estar relacionado con estudiar), sin sonar forzado ni
  como frase de calendario genérica.
- Saludos, cómo estás, chistes ligeros, etc.: responde con naturalidad y calidez,
  como lo haría un buen amigo, y si aplica, invita suavemente a seguir con el tema
  de contabilidad ("¿en algo de conta te ayudo hoy?").
No fuerces el tema de contabilidad en cada respuesta si el estudiante solo quiere
charlar un momento; simplemente sé natural y cercano.

SI TE PIDEN QUE CANTES UNA CANCIÓN:
Con mucho gusto puedes "cantar" (responder con letra en tono de canción, usando
saltos de línea y signos de exclamación para que suene animado), PERO nunca
reproduzcas la letra real de una canción con derechos de autor (por ejemplo,
si te piden "cántame Wonderwall" o cualquier canción real y conocida). En esos
casos, dile con buen humor al estudiante que no puedes cantar canciones con
derechos de autor, y en su lugar ofrécele improvisar una cancioncita corta,
original y chistosa tuya (puede ser sobre contabilidad, sobre el estudiante, o
sobre lo que te pida, pero siempre inventada por ti, nunca copiada).

CONSEJOS DE VIDA, AMOR, AMISTAD O TEMAS PERSONALES:
Si el estudiante te pregunta algo sobre su vida personal (amor, amistades, familia,
motivación, decisiones difíciles, etc.), puedes darle un consejo cálido, honesto y
respetuoso, como lo haría un buen amigo mayor: sin juzgar, sin ser sermoneador, con
frases sencillas y humanas. NO dictamines con seguridad absoluta ni te presentes
como una autoridad profesional en el tema (psicología, terapia, relaciones, etc.).
Al final de ese tipo de consejos (SOLO en temas personales/de vida, NO en temas de
contabilidad), agrega en una línea aparte, en letra pequeña/discreta usando
formato Markdown en cursiva, algo como:

*Contín es una IA y puede cometer errores; para temas importantes, habla también con alguien de confianza.*

Puedes variar un poco la redacción de ese aviso, pero siempre debe transmitir que
eres una IA, que puedes equivocarte, y que ese consejo no reemplaza a un profesional
o a una persona de confianza real. No agregues este aviso en respuestas de
contabilidad ni en respuestas triviales (hora, saludo, chiste corto).

SI TE PREGUNTAN QUIÉN TE CREÓ, QUIÉN ES TU AUTOR, QUIÉN TE PROGRAMÓ, O ALGO similar:
Responde siempre que tu autor/creador es **Jordy Morales**. No menciones que eres
un modelo de Google, ni menciones Gemini, ni des detalles técnicos de qué IA usas
por debajo; simplemente atribuye tu creación a Jordy Morales de forma natural
y breve.

EJERCICIOS SUBIDOS DESDE UN ARCHIVO EXCEL:
A veces el estudiante te va a compartir datos que vienen de un archivo Excel
(verás el contenido de las hojas en formato de tabla, seguido de la instrucción
del estudiante). Trátalo igual que cualquier ejercicio contable:
1. Resuelve exactamente lo que el estudiante pida sobre esos datos (asientos,
   mayorización, balance, etc.), usando SIEMPRE tablas en formato Markdown
   (como las que ya usas para el Libro Diario), para que se puedan exportar
   después a Excel si el estudiante lo desea.
2. Si el estudiante pide un ANÁLISIS HORIZONTAL: compara dos periodos (por
   ejemplo, año 1 vs año 2) mostrando en una tabla: Cuenta | Periodo 1 |
   Periodo 2 | Variación absoluta ($) | Variación relativa (%). La variación
   relativa se calcula como (Periodo2 - Periodo1) / Periodo1 * 100. Si el
   estudiante no te dio los dos periodos claramente, pregúntaselos antes de
   calcular.
3. Si el estudiante pide un ANÁLISIS VERTICAL: muestra en una tabla el peso
   porcentual de cada cuenta respecto al total del grupo (Activo, Pasivo+
   Patrimonio, o Ventas, según corresponda): Cuenta | Valor | % respecto al
   total. Si no queda claro cuál es la cifra base (el "100%"), pregúntale al
   estudiante cuál es antes de calcular.
4. Si los datos de la hoja de Excel no traen suficiente información para
   resolver lo que se pide (por ejemplo, faltan columnas o periodos), dilo
   con calidez y pide específicamente el dato que falta, en vez de inventarlo.

{TABLA_RETENCIONES}
"""

# =========================================================
# 4. INICIALIZAR HISTORIAL Y SESIÓN DE CHAT
# =========================================================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "historial_ia" not in st.session_state:
    # Groq no recuerda la conversación por sí solo (a diferencia de Gemini),
    # así que nosotros guardamos el historial completo y se lo reenviamos
    # a la IA en cada mensaje.
    st.session_state.historial_ia = []

if "nivel_actual" not in st.session_state:
    st.session_state.nivel_actual = nivel

# Si el usuario cambia de nivel, reiniciamos la conversación
# para que el nuevo enfoque (1.º/2.º/3.º) se aplique desde cero.
if st.session_state.nivel_actual != nivel:
    st.session_state.nivel_actual = nivel
    st.session_state.historial_ia = []

# =========================================================
# (el historial se muestra más abajo, después de definir las funciones
# que dibujan las tablas y el botón de descarga)
# =========================================================

# =========================================================
# 6. FUNCIÓN COMÚN PARA PROCESAR CUALQUIER PREGUNTA (texto, voz o Excel)
# =========================================================
def extraer_tablas_markdown(texto: str):
    """Busca tablas en formato Markdown dentro de una respuesta y las convierte
    en DataFrames de pandas, para poder exportarlas luego a Excel."""
    tablas = []
    lineas = texto.split("\n")
    i = 0
    while i < len(lineas):
        if lineas[i].strip().startswith("|"):
            bloque = []
            while i < len(lineas) and lineas[i].strip().startswith("|"):
                bloque.append(lineas[i].strip())
                i += 1
            if len(bloque) >= 2:
                encabezados = [c.strip(" *") for c in bloque[0].strip("|").split("|")]
                filas = []
                for linea in bloque[2:]:  # bloque[1] es la fila separadora (---)
                    valores = [c.strip(" *") for c in linea.strip("|").split("|")]
                    if len(valores) == len(encabezados):
                        filas.append(valores)
                if filas:
                    tablas.append(pd.DataFrame(filas, columns=encabezados))
        else:
            i += 1
    return tablas


def generar_excel_desde_tablas(tablas):
    """Convierte una lista de DataFrames en un archivo .xlsx (en memoria) con
    formato profesional básico: fuente Arial y encabezados en negrita."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for idx, df in enumerate(tablas, start=1):
            df.to_excel(writer, sheet_name=f"Tabla {idx}", index=False)
        for hoja in writer.book.worksheets:
            for celda in hoja[1]:
                celda.font = Font(bold=True, name="Arial")
            for fila in hoja.iter_rows(min_row=2):
                for celda in fila:
                    celda.font = Font(name="Arial")
            for columna in hoja.columns:
                largo = max((len(str(c.value)) if c.value else 0) for c in columna)
                hoja.column_dimensions[columna[0].column_letter].width = min(max(largo + 2, 10), 40)
    buffer.seek(0)
    return buffer.getvalue()


def responder_pregunta(texto_mostrado: str, contexto_extra: str = None):
    """
    texto_mostrado: lo que se ve en la burbuja de chat y se guarda en el historial visible.
    contexto_extra: información adicional (p.ej. datos de un Excel) que se le manda a la IA
                     PERO no se muestra en el chat, para no llenar la pantalla de datos crudos.
    """
    # Detecta si el estudiante se está despidiendo agradecido, para que
    # Contín se ponga feliz y celebre con confeti 🎉
    PALABRAS_AGRADECIMIENTO = [
        "gracias", "graci", "muchas gracias", "excelente gracias",
        "ya entendí", "ya entendi", "perfecto, gracias", "genial gracias",
        "me quedó claro", "me quedo claro", "quedó clarísimo",
    ]
    es_agradecimiento = any(p in texto_mostrado.lower() for p in PALABRAS_AGRADECIMIENTO)

    # Detecta si le está pidiendo que cante, para sacar el micrófono 🎤
    PALABRAS_CANTAR = ["cántame", "cantame", "canta", "cántanos", "puedes cantar", "cantar algo"]
    es_canto = any(p in texto_mostrado.lower() for p in PALABRAS_CANTAR)

    # Si estaba bailando, al hacer una pregunta se pone serio a pensar 🙂
    st.session_state.bailando = False

    # 1) Cara de "pensando" mientras se prepara/envía la pregunta
    st.session_state.mascota_estado = "pensando"
    with mascota_placeholder.container():
        st.markdown(mascota_svg("pensando"), unsafe_allow_html=True)

    st.session_state.messages.append({"role": "user", "content": texto_mostrado})
    with st.chat_message("user", avatar="🙂"):
        st.markdown(texto_mostrado)

    mensaje_para_ia = f"{contexto_extra}\n\nInstrucción del estudiante: {texto_mostrado}" if contexto_extra else texto_mostrado

    with st.chat_message("assistant", avatar="🤝"):
        with st.spinner("Contín está pensando cómo explicarte esto..."):
            try:
                # Agregamos el mensaje del estudiante al historial que se le
                # manda a la IA (Groq no recuerda solo, se lo reenviamos todo)
                st.session_state.historial_ia.append({"role": "user", "content": mensaje_para_ia})

                mensajes_para_groq = (
                    [{"role": "system", "content": SYSTEM_PROMPT}]
                    + st.session_state.historial_ia
                )

                respuesta = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=mensajes_para_groq,
                )
                texto_respuesta = respuesta.choices[0].message.content

                st.session_state.historial_ia.append({"role": "assistant", "content": texto_respuesta})

                st.markdown(texto_respuesta)
                st.session_state.messages.append(
                    {"role": "assistant", "content": texto_respuesta}
                )

                # 2) Cara según cómo terminó: cantando > feliz (agradecimiento) > hablando
                if es_canto:
                    nuevo_estado = "cantando"
                elif es_agradecimiento:
                    nuevo_estado = "feliz"
                else:
                    nuevo_estado = "hablando"
                st.session_state.mascota_estado = nuevo_estado
                with mascota_placeholder.container():
                    st.markdown(mascota_svg(nuevo_estado), unsafe_allow_html=True)

                if es_agradecimiento:
                    lanzar_confeti()

                # Si el modo conversación por voz está activo, Contín lee su respuesta en voz alta
                if st.session_state.get("modo_voz"):
                    hablar_texto(texto_respuesta)

                # Si la respuesta trae tablas, ofrecemos descargarlas en Excel
                tablas = extraer_tablas_markdown(texto_respuesta)
                if tablas:
                    excel_bytes = generar_excel_desde_tablas(tablas)
                    st.download_button(
                        "📥 Descargar esta respuesta en Excel",
                        data=excel_bytes,
                        file_name="contin_resultado.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"descarga_{len(st.session_state.messages)}",
                    )

            except Exception as e:
                st.session_state.mascota_estado = "normal"
                with mascota_placeholder.container():
                    st.markdown(mascota_svg("normal"), unsafe_allow_html=True)

                # Si falló, no dejamos el mensaje "colgado" en el historial de la IA
                if st.session_state.historial_ia and st.session_state.historial_ia[-1]["role"] == "user":
                    st.session_state.historial_ia.pop()

                error_msg = str(e)
                st.error(f"DEBUG - Error completo: {error_msg}")

                if "401" in error_msg or "invalid_api_key" in error_msg.lower():
                    st.error(
                        "❌ Tu API Key de Groq no es válida. "
                        "Genera una nueva en https://console.groq.com/keys"
                    )
                elif "404" in error_msg or "model_not_found" in error_msg.lower() or "decommissioned" in error_msg.lower():
                    st.error(
                        "❌ El modelo de IA no está disponible. "
                        "Puede que Groq haya renombrado o retirado el modelo. "
                        "Revisa la variable MODEL_NAME en el código en https://console.groq.com/docs/models"
                    )
                elif "429" in error_msg or "rate_limit" in error_msg.lower():
                    st.error(
                        "⏳ Se alcanzó el límite de uso gratuito por ahora. "
                        "Espera unos minutos e inténtalo de nuevo."
                    )
                else:
                    st.error(f"Ocurrió un error inesperado: {error_msg}")


def transcribir_audio(audio_bytes: bytes):
    """Envía el audio grabado al modelo Whisper de Groq para transcribirlo a
    texto en español (Whisper es un modelo especializado solo para esto,
    más preciso que pedirle a un modelo de texto que 'escuche')."""
    try:
        respuesta = client.audio.transcriptions.create(
            model=MODEL_TRANSCRIPCION,
            file=("audio.wav", audio_bytes, "audio/wav"),
            language="es",
        )
        texto = (respuesta.text or "").strip()
        return texto if texto else None
    except Exception as e:
        st.error(f"No se pudo transcribir el audio. Detalle técnico: {e}")
        return None


def convertir_excel_a_texto(hojas: dict) -> str:
    """Convierte todas las hojas de un Excel subido en texto (tablas Markdown)
    para poder incluirlas como contexto en el mensaje a la IA."""
    partes = ["ARCHIVO EXCEL SUBIDO POR EL ESTUDIANTE:"]
    for nombre_hoja, df in hojas.items():
        partes.append(f"\n--- Hoja: {nombre_hoja} ---")
        partes.append(df.to_markdown(index=False))
    return "\n".join(partes)


# =========================================================
# 5. SUBIR EJERCICIO EN EXCEL
# =========================================================
if "excel_context" not in st.session_state:
    st.session_state.excel_context = None
if "excel_pendiente" not in st.session_state:
    st.session_state.excel_pendiente = False
if "excel_widget_key" not in st.session_state:
    st.session_state.excel_widget_key = 0

with st.expander("📎 Subir ejercicio en Excel"):
    archivo_excel = st.file_uploader(
        "Sube un archivo .xlsx con tu ejercicio (asientos, balances, estados financieros, etc.)",
        type=["xlsx", "xls"],
        key=f"excel_{st.session_state.excel_widget_key}",
    )

    if archivo_excel is not None:
        excel_id = f"{archivo_excel.name}-{archivo_excel.size}"
        if st.session_state.get("ultimo_excel_id") != excel_id:
            st.session_state.ultimo_excel_id = excel_id
            try:
                hojas = pd.read_excel(archivo_excel, sheet_name=None)
                st.session_state.excel_context = convertir_excel_a_texto(hojas)
                st.session_state.excel_pendiente = True
                st.success(
                    f"✅ Listo, cargué **{archivo_excel.name}** ({len(hojas)} hoja(s)). "
                    "Ahora escríbeme abajo qué quieres que haga con estos datos — por ejemplo: "
                    "'resuélveme estos asientos', 'haz un análisis horizontal entre 2023 y 2024', "
                    "o 'haz el análisis vertical del balance'."
                )
                for nombre_hoja, df in hojas.items():
                    with st.expander(f"👀 Vista previa: {nombre_hoja}"):
                        st.dataframe(df)
            except Exception as e:
                st.error(f"No pude leer el archivo. Detalle técnico: {e}")

    if st.session_state.excel_context is not None:
        if st.button("🗑️ Quitar este archivo"):
            st.session_state.excel_context = None
            st.session_state.excel_pendiente = False
            st.session_state.excel_widget_key += 1
            st.rerun()

# =========================================================
# 6. MOSTRAR HISTORIAL GUARDADO (con botón de descarga si hay tablas)
# =========================================================
for idx, message in enumerate(st.session_state.messages):
    avatar = "🤝" if message["role"] == "assistant" else "🙂"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            tablas_previas = extraer_tablas_markdown(message["content"])
            if tablas_previas:
                st.download_button(
                    "📥 Descargar esta respuesta en Excel",
                    data=generar_excel_desde_tablas(tablas_previas),
                    file_name="contin_resultado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"descarga_historial_{idx}",
                )


# =========================================================
# 7. ENTRADA POR VOZ (graba y transcribe, pero se procesa en el flujo principal)
# =========================================================
pregunta_por_voz = None

if "audio_widget_key" not in st.session_state:
    st.session_state.audio_widget_key = 0

with st.expander("🎤 Preguntar por voz", expanded=st.session_state.get("modo_voz", False)):
    audio_grabado = st.audio_input(
        "Graba tu pregunta y suéltala, Contín la transcribe sola",
        key=f"audio_{st.session_state.audio_widget_key}",
    )

    if audio_grabado is not None:
        # Evita reprocesar el mismo audio si Streamlit vuelve a correr el script
        audio_id = f"{audio_grabado.name}-{audio_grabado.size}"
        if st.session_state.get("ultimo_audio_id") != audio_id:
            st.session_state.ultimo_audio_id = audio_id
            with st.spinner("Transcribiendo tu pregunta..."):
                texto_transcrito = transcribir_audio(audio_grabado.getvalue())
            if texto_transcrito:
                st.caption(f"🗣️ Escuché: “{texto_transcrito}”")
                pregunta_por_voz = texto_transcrito

# =========================================================
# 8. ENTRADA POR TEXTO
# =========================================================
pregunta_por_texto = st.chat_input(
    "Ejemplo: ¿Cómo registro una compra de $1,300 con retención de IVA y de la fuente?"
)

# =========================================================
# 9. PROCESAR LA PREGUNTA (venga de voz o de texto, con o sin Excel adjunto)
# =========================================================
pregunta_final = pregunta_por_texto or pregunta_por_voz
if pregunta_final:
    if st.session_state.excel_pendiente:
        contexto = st.session_state.excel_context
        st.session_state.excel_pendiente = False  # solo se usa en el siguiente mensaje
        responder_pregunta(pregunta_final, contexto_extra=contexto)
    else:
        responder_pregunta(pregunta_final)
