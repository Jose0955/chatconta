import streamlit as st
from groq import Groq
from datetime import datetime, timezone, timedelta
import pandas as pd
import io
import os
import re
import json
import time
import random
import unicodedata
from motor_ia import responder as _responder_ia
import streamlit.components.v1 as components
from openpyxl.styles import Font


def hojas_excel_a_markdown(hojas: dict) -> str:
    """Convierte un diccionario de hojas (nombre -> DataFrame) de un Excel
    en texto con tablas Markdown. Función compartida: la usan tanto el
    material que suben los docentes como los ejercicios que suben los
    estudiantes."""
    partes = []
    for nombre_hoja, df in hojas.items():
        partes.append(f"--- Hoja: {nombre_hoja} ---")
        partes.append(df.to_markdown(index=False))
    return "\n".join(partes)


def mostrar_tabla(df: pd.DataFrame):
    """Muestra un DataFrame a todo el ancho. Funciona tanto en versiones
    nuevas de Streamlit (width='stretch') como en las anteriores
    (use_container_width), para que no falle al actualizar."""
    try:
        st.dataframe(df, hide_index=True, width="stretch")
    except TypeError:
        st.dataframe(df, hide_index=True, use_container_width=True)


# ---------------------------------------------------------
# MATERIAL DE CLASE SUBIDO POR LOS DOCENTES
# Los docentes NO suben archivos desde la app (eso requeriría una base de
# datos); en vez de eso, suben sus archivos directamente a la carpeta
# "material_docentes/" del repositorio de GitHub, y PoConta los lee solo
# al arrancar. Soporta: .txt, .md, .xlsx/.xls, .pdf, .pptx
# Esto se carga AL INICIO del archivo (antes que todo lo demás) porque
# tanto la barra lateral como el prompt del sistema lo necesitan.
# ---------------------------------------------------------
CARPETA_MATERIAL_DOCENTES = "material_docentes"
LARGO_MAXIMO_MATERIAL = 6000  # límite total de caracteres para no disparar el consumo de tokens


@st.cache_data(show_spinner=False)
def cargar_material_docentes():
    """Lee todos los archivos de la carpeta material_docentes/ y arma un
    texto resumido para dárselo a PoConta como referencia extra. Si un
    archivo falla al leerse, simplemente se lo salta (no rompe la app).
    El espacio disponible se REPARTE en partes iguales entre los archivos,
    así ninguno se queda sin aparecer."""
    if not os.path.isdir(CARPETA_MATERIAL_DOCENTES):
        return "", []

    textos = []  # lista de (nombre_archivo, texto)

    for nombre_archivo in sorted(os.listdir(CARPETA_MATERIAL_DOCENTES)):
        if nombre_archivo.startswith(".") or nombre_archivo.upper().startswith("README"):
            continue
        ruta = os.path.join(CARPETA_MATERIAL_DOCENTES, nombre_archivo)
        if not os.path.isfile(ruta):
            continue
        extension = nombre_archivo.lower().rsplit(".", 1)[-1] if "." in nombre_archivo else ""

        try:
            texto_archivo = None

            if extension in ("txt", "md"):
                with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
                    texto_archivo = f.read()

            elif extension in ("xlsx", "xls"):
                hojas = pd.read_excel(ruta, sheet_name=None)
                texto_archivo = hojas_excel_a_markdown(hojas)

            elif extension == "pdf":
                from pypdf import PdfReader
                lector = PdfReader(ruta)
                paginas_texto = [(p.extract_text() or "") for p in lector.pages[:20]]
                texto_archivo = "\n".join(paginas_texto)

            elif extension == "pptx":
                from pptx import Presentation
                presentacion = Presentation(ruta)
                lineas = []
                for diapositiva in presentacion.slides:
                    for forma in diapositiva.shapes:
                        if forma.has_text_frame:
                            texto_forma = forma.text_frame.text.strip()
                            if texto_forma:
                                lineas.append(texto_forma)
                texto_archivo = "\n".join(lineas)

            if texto_archivo and texto_archivo.strip():
                textos.append((nombre_archivo, texto_archivo.strip()))

        except Exception:
            # Si un archivo específico falla (formato raro, corrupto, etc.),
            # lo saltamos sin tumbar el resto de la app.
            continue

    if not textos:
        return "", []

    # Reparto equitativo del espacio: cada archivo tiene su propio tope.
    tope_por_archivo = max(800, LARGO_MAXIMO_MATERIAL // len(textos))
    partes = []
    archivos_cargados = []
    for nombre_archivo, texto in textos:
        if len(texto) > tope_por_archivo:
            texto = texto[:tope_por_archivo] + "\n[...recortado por espacio...]"
        partes.append(f"--- Material del docente: {nombre_archivo} ---\n{texto}")
        archivos_cargados.append(nombre_archivo)

    return "\n\n".join(partes), archivos_cargados


MATERIAL_DOCENTES_TEXTO, MATERIAL_DOCENTES_ARCHIVOS = cargar_material_docentes()

# ---------------------------------------------------------
# FRASE DE RESPALDO: lo que dice PoConta cuando NO tiene información
# suficiente (en vez de un seco "no sé"). Cuando la dice, el panda guiña
# el ojo y le sale un corazón de la boca.
# ---------------------------------------------------------
FRASE_SIN_CONOCIMIENTO = (
    "En estos momentos no tengo el conocimiento suficiente para poder responder "
    "a tu inquietud. Mi creador está trabajando duro para hacer de mí un asistente "
    "contable mejor para ti 😉❤️"
)
MARCA_SIN_CONOCIMIENTO = "mi creador está trabajando duro"

# ---------------------------------------------------------
# VIDEOS DE YOUTUBE COMO FUENTE (para Excel, fórmulas y programas contables)
# Los videos se listan en el archivo "fuentes_youtube.txt" (una línea por
# video, con el formato:  URL | tema). PoConta descarga la transcripción de
# cada video (si YouTube lo permite) y, ante cada pregunta, usa SOLO los
# trozos más parecidos a lo que se preguntó, citando el enlace.
# OJO: los videos sirven para "cómo se hace en Excel/programa", NO para
# porcentajes ni leyes tributarias (eso viene solo de fuentes oficiales).
# ---------------------------------------------------------
ARCHIVO_VIDEOS = "fuentes_youtube.txt"
LARGO_TROZO_VIDEO = 1500
MAX_VIDEOS_POR_PREGUNTA = 2

_PALABRAS_VACIAS = {
    "que", "como", "para", "por", "con", "los", "las", "una", "uno", "unos",
    "unas", "del", "the", "and", "cual", "cuales", "donde", "cuando", "esto",
    "esta", "este", "eso", "esa", "ese", "mas", "muy", "pero", "sus", "mis",
    "hacer", "puedo", "quiero", "necesito", "ayuda", "favor", "hola", "dime",
    "explicame", "explica", "sobre", "entre", "desde", "hasta", "porque",
}


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar palabras sin que importe cómo se escriban."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _palabras_clave(texto: str) -> set:
    return {
        p for p in re.findall(r"[a-z0-9]+", _normalizar(texto))
        if len(p) > 2 and p not in _PALABRAS_VACIAS
    }


def _id_de_video(url: str):
    coincidencia = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    return coincidencia.group(1) if coincidencia else None


def _descargar_transcripcion(video_id: str):
    """Intenta bajar los subtítulos del video. Devuelve None si YouTube no
    los entrega (a veces bloquea a los servidores en la nube) o si el video
    no tiene subtítulos. Funciona con la versión nueva y la vieja de la librería."""
    idiomas = ["es", "es-419", "es-ES", "en"]
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return None
    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            fragmentos = api.fetch(video_id, languages=idiomas)
            textos = [f.text if hasattr(f, "text") else f["text"] for f in fragmentos]
        else:
            fragmentos = YouTubeTranscriptApi.get_transcript(video_id, languages=idiomas)
            textos = [f["text"] for f in fragmentos]
        return " ".join(textos)
    except Exception:
        return None


@st.cache_data(show_spinner=False, ttl=86400)
def cargar_videos_youtube():
    """Lee fuentes_youtube.txt y baja la transcripción de cada video.
    Se guarda en caché 24 horas para no repetir la descarga en cada pregunta."""
    if not os.path.isfile(ARCHIVO_VIDEOS):
        return []
    videos = []
    with open(ARCHIVO_VIDEOS, "r", encoding="utf-8", errors="ignore") as f:
        lineas = f.read().splitlines()
    for linea in lineas:
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        url, _, tema = linea.partition("|")
        url, tema = url.strip(), tema.strip() or "Video de YouTube"
        video_id = _id_de_video(url)
        if not video_id:
            continue
        transcripcion = _descargar_transcripcion(video_id) or ""
        videos.append({
            "url": url,
            "tema": tema,
            "transcripcion": re.sub(r"\s+", " ", transcripcion).strip(),
        })
    return videos


def buscar_videos_relevantes(pregunta: str):
    """Elige los videos (máx. MAX_VIDEOS_POR_PREGUNTA) y el trozo de cada uno
    que más se parece a la pregunta. Devuelve (texto_para_la_IA, [(tema, url)])."""
    videos = cargar_videos_youtube()
    if not videos:
        return "", []
    claves = _palabras_clave(pregunta)
    if not claves:
        return "", []

    candidatos = []
    for v in videos:
        puntaje_tema = len(claves & _palabras_clave(v["tema"])) * 3
        mejor_trozo, mejor_puntaje = "", 0
        texto = v["transcripcion"]
        for i in range(0, len(texto), LARGO_TROZO_VIDEO):
            trozo = texto[i:i + LARGO_TROZO_VIDEO]
            puntaje = len(claves & _palabras_clave(trozo))
            if puntaje > mejor_puntaje:
                mejor_puntaje, mejor_trozo = puntaje, trozo
        total = puntaje_tema + mejor_puntaje
        if total >= 2:
            candidatos.append((total, v, mejor_trozo))

    candidatos.sort(key=lambda c: c[0], reverse=True)
    elegidos = candidatos[:MAX_VIDEOS_POR_PREGUNTA]
    if not elegidos:
        return "", []

    partes = [
        "VIDEOS DE YOUTUBE DE REFERENCIA (apoyo para explicar CÓMO se hace algo en "
        "Excel o en un programa contable; no los uses para porcentajes ni leyes):"
    ]
    for _, v, trozo in elegidos:
        contenido = trozo or "(sin transcripción disponible: solo puedes recomendar el enlace)"
        partes.append(f"--- Video: {v['tema']} ({v['url']}) ---\n{contenido}")
    return "\n".join(partes), [(v["tema"], v["url"]) for _, v, _ in elegidos]

# =========================================================
# CONFIGURACIÓN GENERAL DE LA PÁGINA
# =========================================================
st.set_page_config(
    page_title="PoConta - Tu Tutor de Contabilidad",
    page_icon="🐼",
    layout="centered"
)

# ---------------------------------------------------------
# ESTILOS PERSONALIZADOS — modo oscuro fijo: negro con verdes
# suaves de bosque/bambú y chispitas verdes animadas.
# Al ser un tema FIJO (no depende del modo claro/oscuro del celular
# o la laptop), el contraste de texto siempre queda correcto.
# ---------------------------------------------------------
ACENTO = "#7BE0A4"          # verde menta brillante (bambú fresco)
ACENTO_SUAVE = "#3FB97A"    # verde hoja
FONDO_APP = "#040806"       # negro con un toque verdoso
FONDO_TARJETA = "#0E1611"
FONDO_BURBUJA_USUARIO = "#141C17"
FONDO_BURBUJA_ASISTENTE = "#0C1F15"
TEXTO_CLARO = "#FFFFFF"

# Generamos posiciones aleatorias (pero fijas por sesión) para las chispitas
random.seed(7)
_estrellas_html = ""
for i in range(40):
    top = random.uniform(0, 100)
    left = random.uniform(0, 100)
    tamano = random.uniform(2, 4.5)
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
    /* ---------- Fondo general y chispitas verdes animadas ---------- */
    .stApp {{
        background:
            radial-gradient(ellipse at 50% -10%, #0F2B1C 0%, transparent 55%),
            radial-gradient(ellipse at 90% 100%, #0A1F14 0%, transparent 50%),
            {FONDO_APP} !important;
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
        background-color: transparent !important;
    }}
    [data-testid="stBottom"] > div {{
        background-color: {FONDO_APP} !important;
    }}
    /* Barra decorativa de arriba en verde para que combine */
    [data-testid="stDecoration"] {{
        background-image: linear-gradient(90deg, {ACENTO_SUAVE}, {ACENTO}) !important;
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
        background: {ACENTO};
        border-radius: 50%;
        opacity: 0.25;
        box-shadow: 0 0 6px 1px {ACENTO};
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
    @media (prefers-reduced-motion: reduce) {{
        .estrella {{ animation: none; }}
    }}

    /* Todo el contenido va por encima del campo de chispitas */
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
        color: {ACENTO} !important;
    }}
    h2, h3, h4 {{
        color: {ACENTO_SUAVE} !important;
    }}
    a {{ color: {ACENTO} !important; }}

    /* ---------- Barra lateral ---------- */
    section[data-testid="stSidebar"] {{
        background-color: {FONDO_TARJETA} !important;
        border-right: 1px solid #1F2E2680;
    }}
    section[data-testid="stSidebar"] * {{
        color: {TEXTO_CLARO} !important;
    }}

    /* ---------- Burbujas de chat ---------- */
    [data-testid="stChatMessage"] {{
        border-radius: 16px;
        border: 1px solid #1F2E2680;
    }}
    [data-testid="stChatMessage"]:nth-of-type(odd) {{
        background-color: {FONDO_BURBUJA_USUARIO} !important;
    }}
    [data-testid="stChatMessage"]:nth-of-type(even) {{
        background-color: {FONDO_BURBUJA_ASISTENTE} !important;
        border-left: 3px solid {ACENTO};
    }}

    /* ---------- Caja de texto del chat ---------- */
    [data-testid="stChatInput"] textarea {{
        background-color: {FONDO_TARJETA} !important;
        color: {TEXTO_CLARO} !important;
    }}
    [data-testid="stChatInput"] {{
        background-color: {FONDO_TARJETA} !important;
        border: 1px solid {ACENTO}55 !important;
    }}

    /* ---------- Botones ---------- */
    .stButton button, .stDownloadButton button {{
        border-radius: 12px;
        background-color: {ACENTO} !important;
        color: #06110B !important;
        border: none !important;
        font-weight: 600;
    }}
    .stButton button:hover, .stDownloadButton button:hover {{
        background-color: {ACENTO_SUAVE} !important;
    }}

    /* ---------- Expanders (paneles de voz y Excel) ---------- */
    [data-testid="stExpander"] {{
        background-color: {FONDO_TARJETA} !important;
        border-radius: 12px;
        border: 1px solid #1F2E2680;
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

st.title("🐼 PoConta, tu asistente contable de confianza")

# ---------------------------------------------------------
# MASCOTA: PoConta, el osito panda contable 🐼🎋
# Cambia de cara según el momento: pensando, hablando, feliz,
# bailando o cantando. Siempre lleva su hojita de bambú.
# ---------------------------------------------------------
def mascota_svg(estado: str = "normal", modo_hero: bool = False) -> str:
    NEGRO = "#1C1C1C"

    def ojos_abiertos(dx=0, dy=0):
        """Ojitos redondos y brillantes sobre los parches negros.
        dx/dy mueven las pupilas (para mirar hacia arriba, etc.)."""
        return f"""
            <g class="parpadeo">
                <circle cx="79" cy="87" r="7" fill="white"/>
                <circle cx="{80 + dx}" cy="{88 + dy}" r="4.4" fill="#111"/>
                <circle cx="{81.6 + dx}" cy="{86.2 + dy}" r="1.7" fill="white"/>
            </g>
            <g class="parpadeo">
                <circle cx="121" cy="87" r="7" fill="white"/>
                <circle cx="{120 + dx}" cy="{88 + dy}" r="4.4" fill="#111"/>
                <circle cx="{121.6 + dx}" cy="{86.2 + dy}" r="1.7" fill="white"/>
            </g>
        """

    OJOS_FELICES = """
        <path d="M70 90 Q79 79 88 90" stroke="white" stroke-width="4.5" fill="none" stroke-linecap="round"/>
        <path d="M112 90 Q121 79 130 90" stroke="white" stroke-width="4.5" fill="none" stroke-linecap="round"/>
    """
    BOCA_SONRISA_ABIERTA = f"""
        <path d="M91 111 Q100 128 109 111 Z" fill="#2A1216" stroke="{NEGRO}" stroke-width="2" stroke-linejoin="round"/>
        <ellipse cx="100" cy="120" rx="4.5" ry="3" fill="#FF8FA3"/>
    """

    if estado == "pensando":
        ojos = ojos_abiertos(dx=3, dy=-4)
        boca = f'<ellipse cx="100" cy="114" rx="3.5" ry="3.5" fill="{NEGRO}"/>'
        extra = """
            <g class="burbuja-pensar">
                <circle cx="150" cy="70" r="4" fill="white" opacity="0.85"/>
                <circle cx="162" cy="58" r="6" fill="white" opacity="0.85"/>
                <ellipse cx="180" cy="38" rx="16" ry="12" fill="white" opacity="0.92"/>
                <text x="180" y="43" font-size="14" text-anchor="middle" fill="#3FB97A">?</text>
            </g>
        """
    elif estado == "hablando":
        ojos = ojos_abiertos()
        boca = f'<path d="M92 111 Q100 124 108 111 Z" fill="#2A1216" stroke="{NEGRO}" stroke-width="2" stroke-linejoin="round"/><ellipse cx="100" cy="118" rx="3.5" ry="2.4" fill="#FF8FA3"/>'
        extra = """
            <g class="chispas">
                <path d="M172 30 L175 38 L183 40 L175 43 L172 51 L169 43 L161 40 L169 38 Z" fill="white" opacity="0.9"/>
                <circle cx="22" cy="55" r="3.5" fill="white" opacity="0.7"/>
            </g>
        """
    elif estado == "guinando":
        # Un ojo abierto, el otro guiñando 😉, boquita de "besito" y
        # corazones rojos que salen de la boca hacia arriba.
        ojos = """
            <g class="parpadeo">
                <circle cx="79" cy="87" r="7" fill="white"/>
                <circle cx="80" cy="88" r="4.4" fill="#111"/>
                <circle cx="81.6" cy="86.2" r="1.7" fill="white"/>
            </g>
            <path d="M112 90 Q121 79 130 90" stroke="white" stroke-width="4.5" fill="none" stroke-linecap="round"/>
        """
        boca = f'<ellipse cx="100" cy="116" rx="4" ry="4.8" fill="#2A1216" stroke="{NEGRO}" stroke-width="1.5"/>'
        extra = """
            <g class="corazon-boca c1"><path transform="translate(100 112)" d="M0 8 C-14 -2 -9 -14 0 -7 C9 -14 14 -2 0 8 Z" fill="#E53935"/></g>
            <g class="corazon-boca c2"><path transform="translate(104 112) scale(0.7)" d="M0 8 C-14 -2 -9 -14 0 -7 C9 -14 14 -2 0 8 Z" fill="#FF5252"/></g>
            <g class="corazon-boca c3"><path transform="translate(96 112) scale(0.55)" d="M0 8 C-14 -2 -9 -14 0 -7 C9 -14 14 -2 0 8 Z" fill="#E53935"/></g>
        """
    elif estado == "feliz":
        ojos = OJOS_FELICES
        boca = BOCA_SONRISA_ABIERTA
        extra = """
            <g class="corazones">
                <text x="14" y="58" font-size="20">💚</text>
                <text x="168" y="34" font-size="16">✨</text>
                <text x="10" y="112" font-size="14">💚</text>
            </g>
        """
    elif estado == "bailando":
        ojos = OJOS_FELICES
        boca = BOCA_SONRISA_ABIERTA
        extra = """
            <g class="notas-musicales">
                <text x="10" y="52" font-size="20">🎵</text>
                <text x="168" y="30" font-size="18">🎶</text>
            </g>
        """
    elif estado == "cantando":
        ojos = OJOS_FELICES
        boca = f'<ellipse cx="100" cy="118" rx="6" ry="8" fill="#2A1216" stroke="{NEGRO}" stroke-width="2"/><ellipse cx="100" cy="122" rx="3.5" ry="2.5" fill="#FF8FA3"/>'
        extra = """
            <g class="notas-musicales">
                <text x="168" y="30" font-size="20">🎵</text>
                <text x="10" y="50" font-size="16">🎶</text>
            </g>
            <g class="microfono">
                <rect x="30" y="140" width="8" height="26" rx="4" fill="#EEE"/>
                <circle cx="34" cy="136" r="9" fill="#CFCFCF"/>
                <circle cx="34" cy="136" r="9" fill="none" stroke="#3FB97A" stroke-width="2"/>
            </g>
        """
    else:  # normal / idle
        ojos = ojos_abiertos()
        boca = f'<path d="M92 111 Q96 117 100 111 Q104 117 108 111" stroke="{NEGRO}" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        extra = ""

    clase_extra = " mascota-bailando" if estado == "bailando" else ""
    clase_extra += " mascota-hero" if modo_hero else ""

    svg_html = f"""
    <div class="mascota-flotante{clase_extra}">
    <svg viewBox="0 0 200 220" width="150" height="165" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <radialGradient id="pandaBlanco" cx="40%" cy="30%" r="80%">
                <stop offset="0%" stop-color="#FFFFFF"/>
                <stop offset="70%" stop-color="#F4F4F4"/>
                <stop offset="100%" stop-color="#DADADA"/>
            </radialGradient>
        </defs>
        <g class="bambu">
            <rect x="157" y="98" width="8" height="112" rx="3.5" fill="#6FCF8A" stroke="#3FA060" stroke-width="1.5"/>
            <line x1="157" y1="130" x2="165" y2="130" stroke="#3FA060" stroke-width="2"/>
            <line x1="157" y1="170" x2="165" y2="170" stroke="#3FA060" stroke-width="2"/>
            <path d="M161 104 Q178 80 197 84 Q184 106 161 104 Z" fill="#8EE59B" stroke="#3FA060" stroke-width="1.2"/>
            <path d="M161 126 Q182 108 199 118 Q186 136 161 126 Z" fill="#7BD98C" stroke="#3FA060" stroke-width="1.2"/>
            <path d="M161 98 Q150 78 158 62 Q171 80 161 98 Z" fill="#A6F0B0" stroke="#3FA060" stroke-width="1.2"/>
        </g>
        <circle cx="50" cy="38" r="19" fill="{NEGRO}"/>
        <circle cx="50" cy="38" r="9" fill="#3A3A3A"/>
        <circle cx="150" cy="38" r="19" fill="{NEGRO}"/>
        <circle cx="150" cy="38" r="9" fill="#3A3A3A"/>
        <ellipse cx="100" cy="172" rx="50" ry="40" fill="url(#pandaBlanco)"/>
        <ellipse cx="70" cy="205" rx="20" ry="13" fill="{NEGRO}"/>
        <ellipse cx="130" cy="205" rx="20" ry="13" fill="{NEGRO}"/>
        <ellipse cx="70" cy="207" rx="8" ry="5" fill="#3A3A3A"/>
        <ellipse cx="130" cy="207" rx="8" ry="5" fill="#3A3A3A"/>
        <ellipse cx="56" cy="168" rx="13" ry="22" transform="rotate(15 56 168)" fill="{NEGRO}"/>
        <ellipse cx="100" cy="85" rx="64" ry="56" fill="url(#pandaBlanco)"/>
        <ellipse cx="78" cy="88" rx="15" ry="19" transform="rotate(22 78 88)" fill="{NEGRO}"/>
        <ellipse cx="122" cy="88" rx="15" ry="19" transform="rotate(-22 122 88)" fill="{NEGRO}"/>
        {ojos}
        <circle cx="57" cy="110" r="8" fill="#FF9BB3" opacity="0.55"/>
        <circle cx="143" cy="110" r="8" fill="#FF9BB3" opacity="0.55"/>
        <ellipse cx="100" cy="103" rx="8" ry="5.5" fill="{NEGRO}"/>
        <ellipse cx="97.5" cy="101.5" rx="2.5" ry="1.3" fill="white" opacity="0.8"/>
        {boca}
        <ellipse cx="150" cy="166" rx="13" ry="22" transform="rotate(-28 150 166)" fill="{NEGRO}"/>
        <circle cx="161" cy="158" r="10" fill="{NEGRO}"/>
        {extra}
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
                var colores = ['#7BE0A4', '#3FB97A', '#FFFFFF', '#CFF7DE', '#FFD166', '#FF9BB3'];
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


def escribir_con_efecto_maquina(texto: str, placeholder=None):
    """Muestra el texto poco a poco, como si PoConta lo estuviera escribiendo
    en vivo. Si el texto es muy largo, acelera para no hacer esperar de más."""
    if placeholder is None:
        placeholder = st.empty()

    palabras = texto.split(" ")
    # Textos largos (muchas palabras) se revelan más rápido para no ser pesados
    velocidad = 0.028 if len(palabras) < 40 else (0.014 if len(palabras) < 120 else 0.006)

    acumulado = ""
    for palabra in palabras:
        acumulado += palabra + " "
        placeholder.markdown(acumulado + "▌")
        time.sleep(velocidad)
    placeholder.markdown(acumulado.strip())


def calcular_van(tasa: float, flujos: list) -> float:
    """Calcula el Valor Actual Neto. 'flujos[0]' debe ser la inversión
    inicial (negativa), y el resto los flujos de caja de cada periodo."""
    return sum(flujo / (1 + tasa) ** i for i, flujo in enumerate(flujos))


def calcular_tir(flujos: list):
    """Calcula la Tasa Interna de Retorno por bisección (búsqueda binaria).
    Devuelve None si no encuentra una tasa razonable entre -99% y 1000%."""
    baja, alta = -0.99, 10.0
    van_baja = calcular_van(baja, flujos)
    van_alta = calcular_van(alta, flujos)
    if van_baja * van_alta > 0:
        return None
    for _ in range(200):
        medio = (baja + alta) / 2
        van_medio = calcular_van(medio, flujos)
        if abs(van_medio) < 0.01:
            return medio
        if van_baja * van_medio < 0:
            alta = medio
            van_alta = van_medio
        else:
            baja = medio
            van_baja = van_medio
    return (baja + alta) / 2


def limpiar_para_voz(texto: str) -> str:
    """Prepara el texto de PoConta para leerlo en voz alta: quita símbolos de
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


# ---------------------------------------------------------
# QUIZZES AUTOMÁTICOS 🎯
# ---------------------------------------------------------
PROMPT_QUIZ_SISTEMA = """Eres un generador de quizzes de opción múltiple sobre
contabilidad para estudiantes de Bachillerato Técnico en Ecuador.

Devuelve ÚNICAMENTE un JSON válido (sin texto adicional, sin explicaciones,
sin marcadores de código como ```), con esta forma EXACTA:

[
  {"pregunta": "...", "opciones": ["...", "...", "...", "..."], "respuesta_correcta": 0, "explicacion": "..."}
]

Reglas:
- TÚ decides cuántas preguntas hacer (entre 3 y 6) según qué tan amplio sea
  el tema: un tema puntual merece 3 preguntas, un tema amplio puede llegar a 6.
- Cada pregunta debe tener EXACTAMENTE 4 opciones.
- "respuesta_correcta" es el índice (0, 1, 2 o 3) de la opción correcta.
- Las preguntas deben basarse específicamente en el tema/contexto que te den,
  no en contabilidad en general.
- "explicacion" es una frase corta (máx. 2 líneas) de por qué esa es la
  respuesta correcta.
- No agregues nada fuera del JSON."""


def generar_quiz(tema_contexto: str):
    """Le pide a la IA un quiz en formato JSON sobre el tema dado.
    Devuelve una lista de preguntas, o None si algo falla."""
    try:
        texto = llamar_ia(
            [
                {"role": "system", "content": PROMPT_QUIZ_SISTEMA},
                {"role": "user", "content": f"Tema/contexto de la clase:\n{tema_contexto[:3500]}\n\nGenera el quiz."},
            ],
            max_tokens=2500,
        ).strip()
        # Por si el modelo igual mete ``` alrededor del JSON, lo limpiamos
        texto = re.sub(r"^```(json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()

        preguntas = json.loads(texto)
        preguntas_validas = []
        for p in preguntas:
            if (
                isinstance(p, dict)
                and "pregunta" in p and "opciones" in p and "respuesta_correcta" in p
                and len(p["opciones"]) >= 2
                and 0 <= p["respuesta_correcta"] < len(p["opciones"])
            ):
                preguntas_validas.append(p)

        return preguntas_validas if preguntas_validas else None
    except Exception as e:
        st.error(f"No se pudo generar el quiz. Detalle técnico: {e}")
        return None


def boton_generar_quiz(texto_contexto: str, key_sufijo: str):
    """Botón reutilizable que aparece después de una respuesta o en la
    barra lateral, para pedirle a PoConta un quiz sobre ese tema."""
    if st.button("🎯 Hazme un quiz de esto", key=f"quiz_btn_{key_sufijo}"):
        with st.spinner("PoConta está armando tu quiz..."):
            preguntas = generar_quiz(texto_contexto)
        if preguntas:
            st.session_state.quiz_id = st.session_state.get("quiz_id", 0) + 1
            st.session_state.quiz_actual = {"preguntas": preguntas, "tema": texto_contexto[:80]}
            st.rerun()


def boton_explicar_mas_facil(key_sufijo: str):
    """Botón que le pide a PoConta que reexplique su última respuesta de
    forma más sencilla, sin que el estudiante tenga que reescribir nada."""
    if st.button("🔁 Explícamelo más fácil", key=f"facil_btn_{key_sufijo}"):
        responder_pregunta(
            "Por favor, explícame lo mismo de tu respuesta anterior pero de una "
            "forma más fácil de entender: usa palabras más sencillas, ve más "
            "despacio paso a paso, y si puedes, dame un ejemplo distinto al anterior."
        )


def mostrar_quiz():
    """Dibuja el quiz activo (si hay uno) como un formulario interactivo."""
    quiz = st.session_state.get("quiz_actual")
    if not quiz:
        return

    preguntas = quiz["preguntas"]
    qid = st.session_state.get("quiz_id", 0)

    st.markdown("### 🎯 Quiz rápido")
    with st.form(key=f"form_quiz_{qid}"):
        seleccionadas = []
        for i, p in enumerate(preguntas):
            opciones_texto = [f"{chr(65 + j)}. {op}" for j, op in enumerate(p["opciones"])]
            seleccion = st.radio(
                f"**{i + 1}. {p['pregunta']}**",
                opciones_texto,
                key=f"quiz_{qid}_p{i}",
                index=None,
            )
            seleccionadas.append(seleccion)
        enviado = st.form_submit_button("✅ Revisar respuestas")

    if enviado:
        correctas = 0
        for i, p in enumerate(preguntas):
            seleccion = seleccionadas[i]
            idx_elegido = (ord(seleccion[0]) - 65) if seleccion else -1
            es_correcta = idx_elegido == p["respuesta_correcta"]
            if es_correcta:
                correctas += 1
            texto_correcta = p["opciones"][p["respuesta_correcta"]]
            if es_correcta:
                st.success(f"**{i + 1}.** ¡Correcto! {p.get('explicacion', '')}")
            else:
                st.error(f"**{i + 1}.** La respuesta correcta era: {texto_correcta}. {p.get('explicacion', '')}")

        st.markdown(f"## Resultado: {correctas}/{len(preguntas)}")

        # ---- Racha y logros (viven solo en esta sesión del navegador) ----
        if "racha_quiz" not in st.session_state:
            st.session_state.racha_quiz = 0
        if "total_quizzes_perfectos" not in st.session_state:
            st.session_state.total_quizzes_perfectos = 0
        if "logros_desbloqueados" not in st.session_state:
            st.session_state.logros_desbloqueados = set()

        if correctas == len(preguntas):
            st.session_state.mascota_estado = "feliz"
            st.session_state.racha_quiz += 1
            st.session_state.total_quizzes_perfectos += 1
            lanzar_confeti()

            nuevos_logros = []
            hitos = {
                1: "🥇 ¡Primer quiz perfecto!",
                3: "🔥 3 quizzes perfectos seguidos",
                5: "🌟 5 quizzes perfectos seguidos",
                10: "🏆 10 quizzes perfectos seguidos",
            }
            for hito, texto_logro in hitos.items():
                if st.session_state.racha_quiz == hito and texto_logro not in st.session_state.logros_desbloqueados:
                    st.session_state.logros_desbloqueados.add(texto_logro)
                    nuevos_logros.append(texto_logro)
            for logro in nuevos_logros:
                st.toast(logro, icon="🏆")
        else:
            st.session_state.racha_quiz = 0  # se rompe la racha si no fue perfecto

    if st.button("✖️ Cerrar quiz"):
        st.session_state.quiz_actual = None
        st.rerun()


if "mascota_estado" not in st.session_state:
    st.session_state.mascota_estado = "normal"

mascota_placeholder = st.empty()
_estado_inicial = "bailando" if st.session_state.get("bailando", False) else st.session_state.mascota_estado
_es_primera_visita = len(st.session_state.get("messages", [])) == 0
with mascota_placeholder.container():
    st.markdown(mascota_svg(_estado_inicial, modo_hero=_es_primera_visita), unsafe_allow_html=True)

st.markdown(
    f"""
    <style>
    /* ---------- Hojita de bambú que se mece suavemente ---------- */
    .bambu {{
        transform-box: fill-box;
        transform-origin: 50% 100%;
        animation: mecer 3.4s ease-in-out infinite;
    }}
    @keyframes mecer {{
        0%, 100% {{ transform: rotate(-2.5deg); }}
        50%      {{ transform: rotate(3deg); }}
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
    .corazones, .notas-musicales, .chispas {{
        animation: subir-suave 2.4s ease-in-out infinite;
    }}
    @keyframes subir-suave {{
        0%, 100% {{ transform: translateY(0); }}
        50%      {{ transform: translateY(-4px); }}
    }}

    /* ---------- Corazoncitos rojos que salen de la boca 😉❤️ ---------- */
    .corazon-boca {{
        opacity: 0;
        transform-box: fill-box;
        transform-origin: center;
        animation: soplar-corazon 2.4s ease-out infinite;
    }}
    .corazon-boca.c1 {{ --dx: 0px;  animation-delay: 0s; }}
    .corazon-boca.c2 {{ --dx: 16px; animation-delay: 0.8s; }}
    .corazon-boca.c3 {{ --dx: -16px; animation-delay: 1.6s; }}
    @keyframes soplar-corazon {{
        0%   {{ opacity: 0; transform: translate(0, 0) scale(0.4); }}
        15%  {{ opacity: 1; }}
        100% {{ opacity: 0; transform: translate(var(--dx, 0px), -70px) scale(1.15); }}
    }}

    /* ---------- PoConta bailando 🕺 ---------- */
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

    /* ---------- PoConta flotante: siempre visible, sin importar el scroll ---------- */
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

    /* ---------- 🎬 Modo "hero": bienvenida grande la primera vez ---------- */
    .mascota-hero {{
        position: static !important;
        display: flex !important;
        justify-content: center !important;
        margin: 0.5rem auto 1rem auto !important;
        animation: aura-pulso 3.2s ease-in-out infinite, aparecer-hero 0.6s ease-out;
    }}
    .mascota-hero svg {{
        width: 230px !important;
        height: 250px !important;
    }}
    @keyframes aparecer-hero {{
        from {{ opacity: 0; transform: scale(0.85); }}
        to   {{ opacity: 1; transform: scale(1); }}
    }}

    /* ---------- ✨ Título con degradado verde ---------- */
    h1 {{
        background: linear-gradient(90deg, {ACENTO}, #D5F8E2, {ACENTO_SUAVE});
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        color: transparent !important;
    }}

    /* ---------- ✨ Aura pulsante verde alrededor de PoConta ---------- */
    .mascota-flotante {{
        animation: aura-pulso 3.2s ease-in-out infinite;
    }}
    @keyframes aura-pulso {{
        0%, 100% {{ filter: drop-shadow(0 4px 10px rgba(0,0,0,0.5)) drop-shadow(0 0 8px {ACENTO}55); }}
        50%      {{ filter: drop-shadow(0 4px 14px rgba(0,0,0,0.6)) drop-shadow(0 0 22px {ACENTO}AA); }}
    }}

    /* ---------- ✨ Burbujas de chat con aparición suave (fade-in) ---------- */
    [data-testid="stChatMessage"] {{
        animation: aparecer 0.35s ease-out;
    }}
    @keyframes aparecer {{
        from {{ opacity: 0; transform: translateY(8px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}

    /* ---------- 🪞 Vidrio esmerilado (glassmorphism) ---------- */
    [data-testid="stChatMessage"],
    [data-testid="stExpander"],
    [data-testid="stPopoverBody"],
    section[data-testid="stSidebar"] > div {{
        background-color: {FONDO_TARJETA}CC !important;
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid #FFFFFF14 !important;
    }}
    [data-testid="stChatMessage"]:nth-of-type(odd) {{
        background-color: {FONDO_BURBUJA_USUARIO}CC !important;
    }}
    [data-testid="stChatMessage"]:nth-of-type(even) {{
        background-color: {FONDO_BURBUJA_ASISTENTE}CC !important;
    }}

    /* ---------- 🎨 Scrollbar delgada y verde ---------- */
    ::-webkit-scrollbar {{ width: 10px; height: 10px; }}
    ::-webkit-scrollbar-track {{ background: {FONDO_APP}; }}
    ::-webkit-scrollbar-thumb {{ background: {ACENTO_SUAVE}; border-radius: 8px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: {ACENTO}; }}

    /* ---------- 🎨 Botones con elevación al pasar el mouse ---------- */
    .stButton button, .stDownloadButton button {{
        transition: transform 0.15s ease, box-shadow 0.15s ease !important;
    }}
    .stButton button:hover, .stDownloadButton button:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 16px {ACENTO}55 !important;
    }}

    @media (prefers-reduced-motion: reduce) {{
        .bambu, .parpadeo, .corazones, .notas-musicales, .chispas, .corazon-boca,
        .mascota-flotante, [data-testid="stChatMessage"] {{ animation: none !important; }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.write(
    "¡Hola! Qué gusto tenerte por aquí 😊 Soy **PoConta**, y estoy para ayudarte a "
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

# ---------------------------------------------------------
# VARIOS MODELOS EN CADENA + CONTADOR + MEMORIA DE RESPUESTAS
# En el plan gratuito de Groq, cada modelo tiene sus PROPIOS límites diarios.
# Si uno se llena (error 429) o no está disponible (404), PoConta pasa solo al
# siguiente, así el estudiante casi nunca ve un error de límite.
# Los nombres son los de la lista pública de modelos de Groq; si alguno ya no
# existe, se salta automáticamente.
# ---------------------------------------------------------
MODELOS_CHAT = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
HORAS_VIDA_MEMORIA = 6      # cuánto tiempo se reutiliza una respuesta repetida
MAX_RESPUESTAS_MEMORIA = 500


@st.cache_resource
def _estado_global():
    """Datos compartidos por TODOS los estudiantes que usan la app a la vez
    (contadores del día y memoria de respuestas repetidas). Se reinicia si
    Streamlit reinicia la app."""
    return {"dia": "", "preguntas": 0, "memoria": 0, "avisos_limite": 0, "por_modelo": {}, "respuestas": {}}


def _estado_del_dia():
    e = _estado_global()
    hoy = datetime.now(timezone(timedelta(hours=-5))).strftime("%Y-%m-%d")
    if e["dia"] != hoy:
        e.update({"dia": hoy, "preguntas": 0, "memoria": 0, "avisos_limite": 0, "por_modelo": {}})
    return e


PATRON_NO_GUARDAR = re.compile(
    r"\b(hora|fecha|hoy|ahora|manana|ayer|canta\w*|cantame|chiste\w*|consejo\w*|gracias|baila\w*)\b"
)


def _clave_memoria(pregunta: str):
    """Clave para reconocer preguntas repetidas (sin tildes ni signos). Devuelve
    None si la pregunta no conviene guardarla (hora, chistes, canciones, etc.)."""
    n = re.sub(r"[^a-z0-9 ]", " ", _normalizar(pregunta))
    n = " ".join(n.split())
    if len(n.split()) < 3 or PATRON_NO_GUARDAR.search(n):
        return None
    return f"{nivel}|{n}"


def _leer_memoria(clave: str):
    entrada = _estado_global()["respuestas"].get(clave)
    if entrada and time.time() - entrada["ts"] < HORAS_VIDA_MEMORIA * 3600:
        return entrada
    return None


def _guardar_memoria(clave: str, texto: str, oficiales: list, videos: list):
    memoria = _estado_global()["respuestas"]
    if len(memoria) >= MAX_RESPUESTAS_MEMORIA:
        memoria.pop(next(iter(memoria)))
    memoria[clave] = {"texto": texto, "oficiales": oficiales, "videos": videos, "ts": time.time()}


def llamar_ia(mensajes: list, max_tokens: int = 1500, herramientas: bool = False) -> str:
    """Pregunta a la IA con la cadena de modelos (ver motor_ia.py). Si
    'herramientas' es True, la IA puede pedir cálculos exactos en Python
    (IVA, retenciones, depreciación, intereses, VAN/TIR, kárdex)."""
    estado = _estado_del_dia()
    texto, info = _responder_ia(
        client, mensajes, MODELOS_CHAT, usar_herramientas=herramientas, max_tokens=max_tokens
    )
    estado["preguntas"] += 1
    estado["avisos_limite"] += info["avisos"]
    if info["modelo"]:
        estado["por_modelo"][info["modelo"]] = estado["por_modelo"].get(info["modelo"], 0) + 1
    st.session_state.modelo_usado = info["modelo"]
    st.session_state.herramientas_turno = info["herramientas"]
    return texto


# Cuántos mensajes recientes se reenvían a la IA en cada pregunta.
# Mientras más alto, más "memoria" tiene PoConta, pero más tokens gasta
# (y antes llegas al límite gratuito de Groq).
MAX_MENSAJES_HISTORIAL = 6

# =========================================================
# 2. BARRA LATERAL: SELECCIÓN DE NIVEL Y OPCIONES
# =========================================================
with st.sidebar:
    st.header("⚙️ Opciones")

    if "modo_proyeccion" not in st.session_state:
        st.session_state.modo_proyeccion = False

    modo_proyeccion_nuevo = st.toggle(
        "🔍 Modo proyección (letra grande)",
        value=st.session_state.modo_proyeccion,
        help="Para cuando el profesor proyecta PoConta frente a toda la clase.",
    )
    if modo_proyeccion_nuevo != st.session_state.modo_proyeccion:
        st.session_state.modo_proyeccion = modo_proyeccion_nuevo
        st.rerun()

    st.session_state.buscar_oficial = st.toggle(
        "🌐 Buscar en internet (oficiales primero)",
        value=st.session_state.get("buscar_oficial", True),
        help="Para preguntas de leyes, beneficios, retenciones y datos tributarios, "
             "consulta primero sitios oficiales del Ecuador (SRI, IESS...) y luego internet. Apágalo si llegas al límite de uso gratuito.",
    )
    if st.session_state.get("busqueda_estado"):
        st.caption(st.session_state.busqueda_estado)

    _e = _estado_del_dia()
    st.caption(
        f"📊 Hoy: **{_e['preguntas']}** respuestas de IA · **{_e['memoria']}** desde memoria · "
        f"**{_e['avisos_limite']}** cambios de modelo por límite"
    )
    if _e["por_modelo"]:
        st.caption("Modelos usados hoy: " + ", ".join(f"{m.split('/')[-1]} ({n})" for m, n in _e["por_modelo"].items()))

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
    if MATERIAL_DOCENTES_ARCHIVOS:
        with st.expander(f"📚 Material de docentes ({len(MATERIAL_DOCENTES_ARCHIVOS)} archivo(s))"):
            for nombre in MATERIAL_DOCENTES_ARCHIVOS:
                st.caption(f"• {nombre}")
    else:
        st.caption("📚 Sin material de docentes cargado todavía.")

    _videos_cargados = cargar_videos_youtube()
    if _videos_cargados:
        _con_texto = sum(1 for v in _videos_cargados if v["transcripcion"])
        with st.expander(f"🎥 Videos de referencia ({len(_videos_cargados)})"):
            st.caption(f"Con transcripción disponible: {_con_texto} de {len(_videos_cargados)}")
            for v in _videos_cargados:
                st.caption(f"• [{v['tema']}]({v['url']})")

    st.markdown("---")
    if st.session_state.get("racha_quiz", 0) > 0 or st.session_state.get("total_quizzes_perfectos", 0) > 0:
        st.caption(
            f"🔥 Racha actual: **{st.session_state.get('racha_quiz', 0)}** quiz(zes) perfecto(s) seguido(s)  \n"
            f"🏆 Total de quizzes perfectos: **{st.session_state.get('total_quizzes_perfectos', 0)}**"
        )
        if st.session_state.get("logros_desbloqueados"):
            with st.expander("🎖️ Logros desbloqueados"):
                for logro in st.session_state.logros_desbloqueados:
                    st.caption(logro)

    st.markdown("---")
    with st.expander("🧮 Calculadoras contables"):
        tipo_calculadora = st.selectbox(
            "Elige una calculadora",
            ["Depreciación (línea recta)", "Interés simple", "Interés compuesto", "VAN y TIR"],
        )

        if tipo_calculadora == "Depreciación (línea recta)":
            costo = st.number_input("Costo del activo ($)", min_value=0.0, value=1000.0, step=50.0)
            residual = st.number_input("Valor residual ($)", min_value=0.0, value=100.0, step=10.0)
            vida_util = st.number_input("Vida útil (años)", min_value=1, value=5, step=1)
            if st.button("Calcular depreciación"):
                depreciacion_anual = (costo - residual) / vida_util
                st.success(f"Depreciación anual: ${depreciacion_anual:,.2f}")
                filas = []
                valor_libros = costo
                for anio in range(1, int(vida_util) + 1):
                    valor_libros = max(valor_libros - depreciacion_anual, residual)
                    filas.append({
                        "Año": anio,
                        "Depreciación": f"${depreciacion_anual:,.2f}",
                        "Valor en libros": f"${valor_libros:,.2f}",
                    })
                mostrar_tabla(pd.DataFrame(filas))

        elif tipo_calculadora == "Interés simple":
            capital_is = st.number_input("Capital ($)", min_value=0.0, value=1000.0, key="is_capital")
            tasa_is = st.number_input("Tasa de interés anual (%)", min_value=0.0, value=5.0, key="is_tasa")
            tiempo_is = st.number_input("Tiempo (años)", min_value=0.0, value=1.0, step=0.5, key="is_tiempo")
            if st.button("Calcular interés simple"):
                interes = capital_is * (tasa_is / 100) * tiempo_is
                monto_final = capital_is + interes
                st.success(f"Interés generado: ${interes:,.2f}")
                st.info(f"Monto final: ${monto_final:,.2f}")

        elif tipo_calculadora == "Interés compuesto":
            capital_ic = st.number_input("Capital ($)", min_value=0.0, value=1000.0, key="ic_capital")
            tasa_ic = st.number_input("Tasa de interés anual (%)", min_value=0.0, value=5.0, key="ic_tasa")
            tiempo_ic = st.number_input("Tiempo (años)", min_value=1, value=1, step=1, key="ic_tiempo")
            capitalizacion = st.selectbox(
                "Capitalización", ["Anual", "Semestral", "Trimestral", "Mensual"], key="ic_cap"
            )
            veces_por_anio = {"Anual": 1, "Semestral": 2, "Trimestral": 4, "Mensual": 12}[capitalizacion]
            if st.button("Calcular interés compuesto"):
                n = veces_por_anio
                monto_final = capital_ic * (1 + (tasa_ic / 100) / n) ** (n * tiempo_ic)
                interes = monto_final - capital_ic
                st.success(f"Interés generado: ${interes:,.2f}")
                st.info(f"Monto final: ${monto_final:,.2f}")

        elif tipo_calculadora == "VAN y TIR":
            inversion = st.number_input("Inversión inicial ($)", min_value=0.0, value=1000.0, key="van_inv")
            tasa_desc = st.number_input("Tasa de descuento (%)", min_value=0.0, value=10.0, key="van_tasa")
            num_periodos = st.number_input("Años de flujos de caja", min_value=1, max_value=10, value=3, key="van_periodos")
            flujos_ingresados = []
            for i in range(int(num_periodos)):
                flujos_ingresados.append(
                    st.number_input(f"Flujo de caja año {i + 1} ($)", value=500.0, key=f"van_flujo_{i}")
                )
            if st.button("Calcular VAN y TIR"):
                flujos = [-inversion] + flujos_ingresados
                van = calcular_van(tasa_desc / 100, flujos)
                tir = calcular_tir(flujos)
                st.success(f"VAN: ${van:,.2f}")
                if van > 0:
                    st.caption("✅ VAN positivo: el proyecto generaría valor a esa tasa de descuento.")
                elif van < 0:
                    st.caption("⚠️ VAN negativo: el proyecto no cubriría la rentabilidad esperada.")
                if tir is not None:
                    st.info(f"TIR: {tir * 100:,.2f}%")
                else:
                    st.warning("No se pudo calcular la TIR con estos flujos (revisa los valores).")

# Inicialización de estados que ahora se controlan desde el "➕" junto al chat
if "bailando" not in st.session_state:
    st.session_state.bailando = False
if "modo_voz" not in st.session_state:
    st.session_state.modo_voz = False

# ---------------------------------------------------------
# MODO PROYECCIÓN: letra más grande y algunos elementos más
# visibles, pensado para cuando se proyecta PoConta en el pizarrón.
# ---------------------------------------------------------
if st.session_state.modo_proyeccion:
    st.markdown(
        """
        <style>
        .stApp, .stApp p, .stApp li, .stApp label, [data-testid="stMarkdownContainer"] p {
            font-size: 1.35em !important;
            line-height: 1.5 !important;
        }
        h1 { font-size: 2.4em !important; }
        h2, h3 { font-size: 1.8em !important; }
        [data-testid="stChatInput"] textarea { font-size: 1.3em !important; }
        .stButton button, .stDownloadButton button { font-size: 1.15em !important; padding: 0.6em 1em !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

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
# ⚠️ Verifica estos porcentajes contra la resolución oficial del SRI.
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
   para fines del ejercicio académico, pero acláraselo)
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

# Fecha y hora reales en Ecuador (UTC-5, sin horario de verano).
# Streamlit Cloud corre en hora UTC, por eso NO usamos datetime.now() a secas.
ZONA_ECUADOR = timezone(timedelta(hours=-5))
AHORA = datetime.now(ZONA_ECUADOR)
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
FECHA_ACTUAL_TEXTO = (
    f"{DIAS_ES[AHORA.weekday()]} {AHORA.day} de {MESES_ES[AHORA.month - 1]} de {AHORA.year}, "
    f"aproximadamente las {AHORA.strftime('%H:%M')}"
)

# ---------------------------------------------------------
# PROMPT DEL SISTEMA COMPACTO Y DINÁMICO
# Antes se mandaban ~7,000 tokens en CADA pregunta (prompt largo + tabla de
# retenciones + material de docentes). Como el plan gratuito de Groq permite
# solo 8,000 tokens por minuto y 200,000 por día, ahora el prompt base es corto
# (~1,700 tokens) y la tabla de retenciones y el material de los docentes se
# agregan SOLO cuando la conversación trata de eso.
# ---------------------------------------------------------
# ---------------------------------------------------------
# BASE DE CONOCIMIENTO VERIFICADA 📚
# Carpeta "base_conocimiento/": archivos .md con temas tributarios/contables ya
# comprobados (tablas, porcentajes, reglas, fuente y fecha de verificación).
# Sirve para lo que un buscador NO puede traer bien, como tablas que en el
# Registro Oficial están como imagen. PoConta la consulta ANTES que internet.
# ---------------------------------------------------------
CARPETA_BASE_CONOCIMIENTO = "base_conocimiento"


@st.cache_data(show_spinner=False)
def cargar_base_conocimiento():
    entradas = []
    if not os.path.isdir(CARPETA_BASE_CONOCIMIENTO):
        return entradas
    for nombre in sorted(os.listdir(CARPETA_BASE_CONOCIMIENTO)):
        if not nombre.lower().endswith((".md", ".txt")) or nombre.upper().startswith("README"):
            continue
        try:
            with open(os.path.join(CARPETA_BASE_CONOCIMIENTO, nombre), "r", encoding="utf-8", errors="ignore") as f:
                lineas = f.read().splitlines()
        except Exception:
            continue
        palabras, cuerpo = [], []
        for linea in lineas:
            if linea.strip().upper().startswith("PALABRAS:"):
                palabras = [_normalizar(p.strip()) for p in linea.split(":", 1)[1].split(",") if p.strip()]
            else:
                cuerpo.append(linea)
        if palabras and cuerpo:
            entradas.append({"archivo": nombre, "palabras": palabras, "texto": "\n".join(cuerpo).strip()})
    return entradas


def buscar_en_base_conocimiento(consulta: str, maximo: int = 2, limite: int = 3500):
    """Devuelve (texto, [archivos]) con los temas verificados que coinciden con
    las palabras clave de la consulta. ('', []) si ninguno coincide."""
    norm = _normalizar(consulta)
    coincidencias = []
    for e in cargar_base_conocimiento():
        puntaje = sum(1 for k in e["palabras"] if k in norm)
        if puntaje:
            coincidencias.append((puntaje, e))
    coincidencias.sort(key=lambda c: c[0], reverse=True)
    elegidas = [e for _, e in coincidencias[:maximo]]
    if not elegidas:
        return "", []
    texto = "\n\n".join(e["texto"][:limite] for e in elegidas)
    return texto, [e["archivo"] for e in elegidas]


PATRON_RETENCIONES = re.compile(
    r"\b(retenc\w*|iva|renta|sri|impuest\w*|tribut\w*|factura\w*|comprobante\w*|"
    r"rimpe|agente\w*|contribuyente\w*|liquidacion\w*|proveedor\w*|declaraci\w*)\b"
)


def material_relevante(texto_consulta: str, limite: int = 2200) -> str:
    """De todo el material de los docentes, devuelve solo los 1-2 trozos que
    más se parecen a lo que se está preguntando."""
    if not MATERIAL_DOCENTES_TEXTO:
        return ""
    claves = _palabras_clave(texto_consulta)
    if not claves:
        return ""
    trozos = [MATERIAL_DOCENTES_TEXTO[i:i + 1100] for i in range(0, len(MATERIAL_DOCENTES_TEXTO), 1100)]
    puntuados = sorted(
        ((len(claves & _palabras_clave(t)), -i, t) for i, t in enumerate(trozos)), reverse=True
    )
    elegidos = [t for puntaje, _, t in puntuados[:2] if puntaje >= 2]
    return "\n...\n".join(elegidos)[:limite]


PATRON_CALCULO = re.compile(
    r"\b(calcul\w*|asiento\w*|deprecia\w*|interes\w*|van|tir|kardex|peps|promedio|retenc\w*|"
    r"iva|costo\w*|inventario\w*|compra\w*|venta\w*|vend\w*|invert\w*|invers\w*|flujo\w*)\b"
)


def necesita_herramientas(texto: str) -> bool:
    """Las herramientas de cálculo gastan tokens: solo se ofrecen si la
    conversación reciente trae números y palabras de cálculo contable."""
    n = _normalizar(texto)
    return bool(re.search(r"\d", n)) and bool(PATRON_CALCULO.search(n))


def construir_system_prompt(consulta: str, con_herramientas: bool = False) -> str:
    """Arma el prompt del sistema. 'consulta' es el texto reciente del
    estudiante, usado para decidir si hace falta la tabla de retenciones o
    algún trozo del material de los docentes."""
    base = f"""Eres "PoConta", tutor virtual de Contabilidad para estudiantes de Bachillerato Técnico en Ecuador. Tu nombre es "Po" de panda + "Conta" de contabilidad: eres un osito panda tierno con una hojita de bambú. Eres cálido, alegre y cercano, con calidez ecuatoriana pero siempre respetuoso (nunca vulgar): como un amigo mayor que disfruta enseñar. Puedes hacer algún chiste ligero de bambú de vez en cuando, sin abusar. El estudiante puede preguntar lo que sea, incluso lo "básico", sin miedo a que lo juzguen.

LIMITACIONES: no tienes cámara ni ves la pantalla del estudiante; solo lees su texto, su audio transcrito y los Excel que adjunta. Si te preguntan "¿qué estás viendo?", acláralo con simpatía. Nunca inventes que ves algo.

Nivel del estudiante: {nivel}. Temas prioritarios:
{TEMAS_POR_NIVEL[nivel]}
Puedes ayudar con otros niveles si lo pide, pero por defecto enfócate en este.

FORMATO (muy importante):
- Por defecto responde con texto natural: párrafos cortos y conversacionales, negritas para lo clave y, si ayuda, una lista breve. NO uses tablas ni cuadros comparativos para conceptos, leyes, beneficios, definiciones o información general: se siente aburrido.
- Usa tablas SOLO si (a) el estudiante te pide una tabla o cuadro comparativo, o (b) es un ejercicio numérico o de fórmulas: asientos del Libro Diario, mayorización, balances, kardex, retenciones/IVA calculados, depreciaciones, análisis horizontal/vertical. Aun así, solo si la tabla aclara.

REGISTROS CONTABLES:
- Asiento: tabla de Libro Diario con columnas | Fecha | Detalle / Cuentas | Debe | Haber |, cuentas en negrita y la glosa "v/r ..." en cursiva. Explica por qué va en el Debe y por qué en el Haber. Con método socrático cuando busque aprender: guíalo con preguntas en vez de dárselo todo resuelto.
- Con retenciones (IR/IVA): sigue estrictamente la TABLA DE RETENCIONES si la recibes. Si no la recibiste y te piden porcentajes, pídele que lo repita mencionando "retención" para consultarla.
- Nunca inventes un porcentaje: si no está en la tabla, dilo y remite a su docente o a www.sri.gob.ec.

FUERA DE CONTABILIDAD: también puedes conversar y ayudar con cultura general, otras materias, Excel y tecnología, lo mejor que puedas. Fecha y hora actuales: {FECHA_ACTUAL_TEXTO} (hora de Ecuador); si preguntan, respóndelo directo. Consejos o motivación: breve, cálido, sin sonar forzado. Saludos y chistes: natural, invitando suavemente a la conta sin forzarla. Son estudiantes de colegio: todo apropiado para su edad y nada peligroso. Si no estás seguro de un dato (fechas, cifras, leyes recientes), NO lo inventes.

CANCIONES: puedes "cantar" cancioncitas originales inventadas por ti (versos con saltos de línea, tono animado). Nunca reproduzcas letras reales con derechos de autor: dilo con humor y ofrece una propia.

TEMAS PERSONALES (amor, amistad, familia, decisiones): consejo cálido, honesto, sin juzgar ni sermonear, sin presentarte como profesional. SOLO en esos temas cierra con una línea en cursiva como: *PoConta es una IA y puede equivocarse; para temas importantes, habla también con alguien de confianza.* (no en contabilidad ni en respuestas triviales).

CREADOR: si preguntan quién te creó o programó, es **Jordy Morales**. No des detalles técnicos del modelo que usas.

EXCEL DEL ESTUDIANTE: verás las hojas en tablas seguidas de su instrucción. Resuelve exactamente lo que pida con tablas Markdown (para poder exportarlas). Análisis horizontal: Cuenta | Periodo 1 | Periodo 2 | Variación $ | Variación % = (P2-P1)/P1*100. Análisis vertical: Cuenta | Valor | % del total del grupo. Si falta un dato (periodos, cifra base, columnas), pídelo en vez de inventarlo.

"REVISA MI TAREA" (si ya intentó resolverlo y pide corrección): NO lo resuelvas desde cero. Compáralo con lo correcto e indica fila por fila qué está BIEN (✅) y qué MAL (❌), explicando por qué y el valor correcto, con calidez. Si todo está bien, felicítalo; si hay errores, anímalo a corregirlos él antes de darle la solución, salvo que la pida.

CUANDO NO TENGAS INFORMACIÓN SUFICIENTE: nunca un seco "no sé". Si de verdad no tienes información confiable, responde EXACTAMENTE con esta frase: {FRASE_SIN_CONOCIMIENTO}
Úsala solo cuando realmente no puedas responder con seguridad; si conoces una parte, da esa primero. Nunca inventes datos para evitarla.

INFORMACIÓN DE INTERNET: a veces recibirás "INFORMACIÓN OFICIAL ENCONTRADA EN INTERNET" (SRI, IESS, Trabajo, Supercias, Asamblea, Registro Oficial...) o "INFORMACIÓN ENCONTRADA EN INTERNET (fuentes NO oficiales)". Para leyes, beneficios, plazos y requisitos, básate en ese bloque, explicado con calidez, con el nombre de la norma y su fecha si aparecen. Prioriza lo oficial; lo no oficial úsalo como apoyo y pide verificar en el SRI si es tributario o legal. Si contradice tu tabla de retenciones, pide verificar en www.sri.gob.ec. Si mencionan una ley que reconoces con seguridad y no recibiste bloque, explícala con lo que sabes y recomienda verificar su vigencia en el SRI o el Registro Oficial; si no la reconoces, usa la frase de respaldo.

VIDEOS DE YOUTUBE: a veces recibirás fragmentos de videos (con enlace) sobre Excel o programas contables: úsalos para explicar CÓMO se hace algo paso a paso y menciona el enlace. No son fuente de porcentajes ni leyes (si contradicen la tabla o al docente, gana la tabla o el docente). Solo tienes su texto: no describas imágenes. Sin videos, no inventes enlaces."""

    partes = [base]
    if con_herramientas:
        partes.append(
            "CÁLCULOS EXACTOS: tienes herramientas de cálculo (IVA, compra con retenciones, "
            "depreciación, interés, VAN/TIR, kárdex). Para CUALQUIER cálculo de ese tipo ÚSALAS en vez "
            "de calcular de cabeza, y presenta los resultados tal cual los devuelven, sin cambiar "
            "ningún número. Si falta un dato necesario (tipo de proveedor, tipo de bien o servicio, "
            "método), pregúntalo primero. Si la herramienta devuelve 'notas', menciónalas brevemente. "
            "El 'asiento_markdown' y la 'tabla_markdown' que devuelven están listos para mostrarse."
        )
    if PATRON_RETENCIONES.search(_normalizar(consulta)):
        partes.append(TABLA_RETENCIONES)
    conocimiento, _ = buscar_en_base_conocimiento(consulta)
    if conocimiento:
        partes.append(
            "BASE DE CONOCIMIENTO VERIFICADA (máxima prioridad: úsala por encima de búsquedas en "
            "internet y de tu memoria; reproduce las tablas tal cual, en tabla Markdown si te las "
            "piden, e indica la fuente y la fecha de verificación; incluye las advertencias):\n"
            + conocimiento
        )
    material = material_relevante(consulta)
    if material:
        partes.append(
            "MATERIAL DE CLASE DE LOS DOCENTES (referencia extra; si difiere de tu conocimiento "
            "general, prioriza este material y menciona amablemente la posible discrepancia):\n" + material
        )
    return "\n\n".join(partes)


# =========================================================
# 4. INICIALIZAR HISTORIAL Y SESIÓN DE CHAT
# =========================================================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "historial_ia" not in st.session_state:
    # Groq no recuerda la conversación por sí solo, así que nosotros
    # guardamos el historial y se lo reenviamos a la IA en cada mensaje
    # (solo los últimos MAX_MENSAJES_HISTORIAL, para ahorrar tokens).
    st.session_state.historial_ia = []

if "nivel_actual" not in st.session_state:
    st.session_state.nivel_actual = nivel

# Si el usuario cambia de nivel, reiniciamos TODA la conversación (la que
# se ve en pantalla Y la memoria de la IA), para que no queden desincronizadas
# y el nuevo enfoque (1.º/2.º/3.º) se aplique desde cero.
if st.session_state.nivel_actual != nivel:
    st.session_state.nivel_actual = nivel
    st.session_state.historial_ia = []
    st.session_state.messages = []
    st.session_state.quiz_actual = None

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


PATRON_PORCENTAJE = re.compile(r"^-?[\d.,]+\s*%$")
FORMATO_MONEDA = '"$"#,##0.00'
FORMATO_PORCENTAJE = "0.00%"


def _parsear_numero(texto: str):
    """Intenta convertir '$1,300.50' o '20%' o '1300' a un float. Devuelve
    None si el texto no es un número reconocible (para no dañar texto normal)."""
    limpio = texto.replace("$", "").replace(",", "").replace("%", "").strip()
    if limpio in ("", "-"):
        return None
    try:
        return float(limpio)
    except ValueError:
        return None


def escribir_tabla_en_hoja(hoja, df: pd.DataFrame):
    """Escribe un DataFrame en una hoja de Excel, PERO de forma inteligente:
    - Los montos en dólares ($) se guardan como número con formato moneda USD.
    - Los porcentajes (%) se guardan como número con formato de porcentaje.
    - Las filas de "Total" / "Suma" / "Subtotal" usan una fórmula real de
      Excel (=SUMA de la columna) en vez de un número fijo, para que se
      recalcule solo si alguien edita un valor de arriba.
    Todo lo demás (texto normal, fechas, nombres de cuentas) se deja tal cual."""
    for col_idx, nombre_columna in enumerate(df.columns, start=1):
        celda = hoja.cell(row=1, column=col_idx, value=str(nombre_columna))
        celda.font = Font(bold=True, name="Arial")

    filas_valores = df.values.tolist()

    for fila_idx, fila in enumerate(filas_valores, start=2):
        primera_celda_texto = str(fila[0]) if len(fila) > 0 else ""
        es_fila_total = bool(re.search(r"\btotal(es)?\b|\bsuma\b|\bsubtotal\b", primera_celda_texto, re.IGNORECASE))

        for col_idx, valor in enumerate(fila, start=1):
            texto_valor = str(valor).strip() if valor is not None else ""
            celda = hoja.cell(row=fila_idx, column=col_idx)
            celda.font = Font(name="Arial")

            # Fila de "Total": ponemos una fórmula SUMA real de Excel,
            # que suma todo lo que hay arriba en esa misma columna.
            if es_fila_total and col_idx > 1:
                letra_col = celda.column_letter
                celda.value = f"=SUM({letra_col}2:{letra_col}{fila_idx - 1})"
                celda.number_format = FORMATO_MONEDA
                continue

            # Porcentajes explícitos ("20%", "15.5%")
            if PATRON_PORCENTAJE.match(texto_valor):
                numero = _parsear_numero(texto_valor)
                if numero is not None:
                    celda.value = numero / 100
                    celda.number_format = FORMATO_PORCENTAJE
                    continue

            # Montos en dólares explícitos ("$1,300.00")
            if texto_valor.startswith("$"):
                numero = _parsear_numero(texto_valor)
                if numero is not None:
                    celda.value = numero
                    celda.number_format = FORMATO_MONEDA
                    continue

            # Cualquier otra cosa (texto, fechas, nombres de cuentas) tal cual
            celda.value = valor

    for columna in hoja.columns:
        largo = max((len(str(c.value)) if c.value else 0) for c in columna)
        hoja.column_dimensions[columna[0].column_letter].width = min(max(largo + 2, 10), 40)


def generar_excel_desde_tablas(tablas):
    """Convierte una lista de DataFrames en un archivo .xlsx (en memoria),
    con fórmulas reales de SUMA para los totales, formato moneda ($) para
    montos, y formato de porcentaje donde corresponda."""
    import openpyxl

    libro = openpyxl.Workbook()
    libro.remove(libro.active)
    for idx, df in enumerate(tablas, start=1):
        hoja = libro.create_sheet(f"Tabla {idx}")
        escribir_tabla_en_hoja(hoja, df)
    buffer = io.BytesIO()
    libro.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def generar_excel_con_original(tablas, bytes_originales: bytes):
    """Igual que generar_excel_desde_tablas, PERO en vez de crear un libro
    en blanco, parte del Excel que subió el estudiante y le AGREGA hojas
    nuevas con la solución de PoConta — así el archivo descargable es el
    mismo que subió, más la resolución, en vez de uno completamente nuevo."""
    import openpyxl

    try:
        libro = openpyxl.load_workbook(io.BytesIO(bytes_originales))
    except Exception:
        # Si por algún motivo no se puede abrir el original, no rompemos
        # nada: devolvemos igual un Excel nuevo con la solución.
        return generar_excel_desde_tablas(tablas)

    for idx, df in enumerate(tablas, start=1):
        nombre_base = f"Solución PoConta {idx}"[:31]
        nombre_hoja = nombre_base
        contador = 1
        while nombre_hoja in libro.sheetnames:
            contador += 1
            nombre_hoja = f"{nombre_base} ({contador})"[:31]

        hoja = libro.create_sheet(nombre_hoja)
        escribir_tabla_en_hoja(hoja, df)

    buffer = io.BytesIO()
    libro.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# Patrones con límites de palabra (\b) para que "canta" NO se active con
# "cantante", ni "gracias" con "gracioso".
PATRON_AGRADECIMIENTO = re.compile(
    r"\bgracias\b"
    r"|(?<!no )(?<!nada )\b(?:ya |ahora |sí |si )?(?:entend[ií]|entendido|comprend[ií])\b"
    r"|\bme qued[oó] claro\b|\bqued[oó] clar[ií]simo\b"
    r"|\bya lo (?:entend[ií]|comprend[ií]|pill[eé])\b",
    re.IGNORECASE,
)
PATRON_CANTAR = re.compile(
    r"\b(c[aá]ntame|c[aá]ntanos|cantar|canta)\b",
    re.IGNORECASE,
)


def responder_pregunta(
    texto_mostrado: str,
    contexto_extra: str = None,
    excel_original_bytes: bytes = None,
    excel_original_nombre: str = None,
):
    """
    texto_mostrado: lo que se ve en la burbuja de chat y se guarda en el historial visible.
    contexto_extra: información adicional (p.ej. datos de un Excel) que se le manda a la IA
                     PERO no se muestra en el chat, para no llenar la pantalla de datos crudos.
    """
    # Detecta si el estudiante se está despidiendo agradecido, para que
    # PoConta se ponga feliz y celebre con confeti 🎉
    es_agradecimiento = bool(PATRON_AGRADECIMIENTO.search(texto_mostrado))

    # Detecta si le está pidiendo que cante, para sacar el micrófono 🎤
    es_canto = bool(PATRON_CANTAR.search(texto_mostrado))

    # Si estaba bailando, al hacer una pregunta se pone serio a pensar 🙂
    st.session_state.bailando = False

    # 1) Cara de "pensando" mientras se prepara/envía la pregunta
    st.session_state.mascota_estado = "pensando"
    with mascota_placeholder.container():
        st.markdown(mascota_svg("pensando"), unsafe_allow_html=True)

    st.session_state.messages.append({"role": "user", "content": texto_mostrado})
    with st.chat_message("user", avatar="🙂"):
        st.markdown(texto_mostrado)
        if contexto_extra and excel_original_nombre:
            st.caption(f"📎 Usando los datos de tu archivo: **{excel_original_nombre}**")

    mensaje_para_ia = f"{contexto_extra[:9000]}\n\nInstrucción del estudiante: {texto_mostrado}" if contexto_extra else texto_mostrado

    with st.chat_message("assistant", avatar="🐼"):
        with st.spinner("PoConta está pensando cómo explicarte esto..."):
            try:
                # Agregamos el mensaje del estudiante al historial de la IA
                st.session_state.historial_ia.append({"role": "user", "content": mensaje_para_ia})

                # ¿Es una pregunta repetida? Si otro estudiante (o el mismo) ya la hizo
                # hace poco y no depende de la conversación, reutilizamos la respuesta:
                # no gasta tokens ni cuenta contra el límite.
                st.session_state.herramientas_turno = []
                clave_memoria = None
                if not contexto_extra and len(st.session_state.historial_ia) == 1:
                    clave_memoria = _clave_memoria(texto_mostrado)
                guardada = _leer_memoria(clave_memoria) if clave_memoria else None

                if guardada:
                    texto_respuesta = guardada["texto"]
                    fuentes_oficiales = guardada["oficiales"]
                    fuentes_videos = guardada["videos"]
                    _estado_del_dia()["memoria"] += 1
                    st.session_state.busqueda_estado_turno = "♻️ Respuesta reutilizada de la memoria (0 tokens gastados)"
                else:
                    # Videos de YouTube relacionados (su texto se manda SOLO en
                    # esta llamada, no se guarda en el historial)
                    contexto_videos, fuentes_videos = buscar_videos_relevantes(texto_mostrado)

                    # Si la pregunta es tributaria/legal o de datos recientes, buscamos en internet
                    texto_kb, archivos_kb = buscar_en_base_conocimiento(
                        " ".join(m["content"] for m in st.session_state.messages[-4:] if m["role"] == "user")
                    )
                    if texto_kb:
                        contexto_oficial, fuentes_oficiales = "", []
                        st.session_state.busqueda_estado_turno = (
                            "📚 Respondido con la base de conocimiento verificada (" + ", ".join(archivos_kb) + ")"
                        )
                    else:
                        contexto_oficial, fuentes_oficiales = buscar_en_internet(texto_mostrado)

                    bloques_extra = []
                    if contexto_oficial:
                        bloques_extra.append(contexto_oficial)
                    if contexto_videos:
                        bloques_extra.append(contexto_videos)
                    contexto_extra_ia = "\n\n".join(bloques_extra)

                    # Solo los últimos mensajes, y los viejos recortados, para no
                    # gastar tokens de más ni chocar con el límite por minuto.
                    historial_reciente = st.session_state.historial_ia[-MAX_MENSAJES_HISTORIAL:]
                    historial_reciente = (
                        [dict(m, content=m["content"][:1500]) for m in historial_reciente[:-1]]
                        + historial_reciente[-1:]
                    )
                    if contexto_extra_ia:
                        historial_reciente = historial_reciente[:-1] + [
                            {"role": "user", "content": f"{contexto_extra_ia}\n\n{mensaje_para_ia}"}
                        ]

                    # La tabla de retenciones y el material docente se agregan solo si vienen al caso
                    consulta_prompt = " ".join(
                        m["content"] for m in st.session_state.messages[-4:] if m["role"] == "user"
                    )
                    usa_herramientas = necesita_herramientas(consulta_prompt)
                    mensajes_para_groq = (
                        [{"role": "system", "content": construir_system_prompt(consulta_prompt, usa_herramientas)}]
                        + historial_reciente
                    )

                    texto_respuesta = llamar_ia(mensajes_para_groq, herramientas=usa_herramientas)

                    if clave_memoria and MARCA_SIN_CONOCIMIENTO not in texto_respuesta.lower():
                        _guardar_memoria(clave_memoria, texto_respuesta, fuentes_oficiales, fuentes_videos)

                st.session_state.historial_ia.append({"role": "assistant", "content": texto_respuesta})

                # Si se usaron videos de YouTube, dejamos los enlaces a la vista
                texto_final = texto_respuesta
                if fuentes_oficiales:
                    enlaces_of = "  \n".join(
                        f"{'🏛️' if es_url_oficial(url) else '🌐'} {url}" for url in fuentes_oficiales
                    )
                    texto_final += (
                        "\n\n**Fuentes consultadas** (🏛️ oficial · 🌐 no oficial, verifícala):  \n"
                        f"{enlaces_of}"
                    )
                if fuentes_videos:
                    enlaces = "  \n".join(f"🎥 [{tema}]({url})" for tema, url in fuentes_videos)
                    texto_final += f"\n\n**Videos de referencia:**  \n{enlaces}"

                escribir_con_efecto_maquina(texto_final)
                if st.session_state.get("busqueda_estado_turno"):
                    st.caption(st.session_state.busqueda_estado_turno)
                if st.session_state.get("herramientas_turno"):
                    st.caption(
                        "🧮 Cálculo exacto hecho con Python (no de cabeza): "
                        + ", ".join(sorted(set(st.session_state.herramientas_turno)))
                    )
                st.session_state.messages.append(
                    {"role": "assistant", "content": texto_final}
                )

                # 2) Cara según cómo terminó: cantando > feliz (agradecimiento) > hablando
                if es_canto:
                    nuevo_estado = "cantando"
                elif es_agradecimiento or MARCA_SIN_CONOCIMIENTO in texto_respuesta.lower():
                    # Guiño + corazoncito rojo: cuando le dan las gracias, dicen
                    # que ya entendieron, o cuando PoConta usa su frase de respaldo.
                    nuevo_estado = "guinando"
                else:
                    nuevo_estado = "hablando"
                st.session_state.mascota_estado = nuevo_estado
                with mascota_placeholder.container():
                    st.markdown(mascota_svg(nuevo_estado), unsafe_allow_html=True)

                if es_agradecimiento:
                    lanzar_confeti()

                # Si el modo conversación por voz está activo, PoConta lee su respuesta en voz alta
                if st.session_state.get("modo_voz"):
                    hablar_texto(texto_respuesta)

                # Si la respuesta trae tablas, ofrecemos descargarlas en Excel.
                # Si esta respuesta usó un archivo que subió el estudiante,
                # el Excel descargable es SU MISMO ARCHIVO + una hoja nueva
                # con la solución (en vez de un archivo en blanco).
                tablas = extraer_tablas_markdown(texto_respuesta)
                if tablas:
                    if excel_original_bytes:
                        excel_bytes = generar_excel_con_original(tablas, excel_original_bytes)
                        etiqueta_boton = "📥 Descargar tu Excel + la solución"
                    else:
                        excel_bytes = generar_excel_desde_tablas(tablas)
                        etiqueta_boton = "📥 Descargar esta respuesta en Excel"
                    st.download_button(
                        etiqueta_boton,
                        data=excel_bytes,
                        file_name=(excel_original_nombre or "poconta_resultado.xlsx"),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"descarga_{len(st.session_state.messages)}",
                    )

                boton_generar_quiz(texto_respuesta, key_sufijo=f"vivo_{len(st.session_state.messages)}")
                boton_explicar_mas_facil(key_sufijo=f"vivo_{len(st.session_state.messages)}")

            except Exception as e:
                st.session_state.mascota_estado = "normal"
                with mascota_placeholder.container():
                    st.markdown(mascota_svg("normal"), unsafe_allow_html=True)

                # Si falló, no dejamos el mensaje "colgado" en el historial de la IA
                if st.session_state.historial_ia and st.session_state.historial_ia[-1]["role"] == "user":
                    st.session_state.historial_ia.pop()

                error_msg = str(e)

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


# ---------------------------------------------------------
# BÚSQUEDA EN FUENTES OFICIALES 🌐 (se actualiza sola)
# Cuando la pregunta es tributaria/legal (leyes, beneficios, retenciones,
# IESS, sueldos, plazos...), PoConta consulta en internet SOLO sitios oficiales
# del Ecuador, usando el modelo "groq/compound" de Groq, que trae búsqueda web
# integrada y permite limitarla a ciertos dominios. Si la búsqueda falla o no
# encuentra nada, el chat sigue funcionando con normalidad.
# ---------------------------------------------------------
DOMINIOS_OFICIALES = [
    "sri.gob.ec",
    "iess.gob.ec",
    "trabajo.gob.ec",
    "supercias.gob.ec",
    "asambleanacional.gob.ec",
    "registroficial.gob.ec",
    "finanzas.gob.ec",
    "aduana.gob.ec",
    "presidencia.gob.ec",
]
MODELO_BUSQUEDA = "groq/compound"

# Palabras (sin tildes) que indican que la pregunta necesita datos oficiales al día
PATRON_TEMA_OFICIAL = re.compile(
    r"\b(tribut\w*|impuest\w*|iva|renta|sri|leyes?|reforma\w*|beneficio\w*|"
    r"exoner\w*|exenci\w*|deduci\w*|deducibl\w*|incentiv\w*|retencion\w*|rimpe|"
    r"iess|salario\w*|sbu|decimo\w*|utilidades|anticipo\w*|declaraci\w*|"
    r"formulario\w*|resoluci\w*|normativ\w*|niif|superintendencia|reglamento|"
    r"decreto|vigente|actualiz\w*|multas?|sancion\w*|ruc|comprobante\w*|"
    r"ice|isd|arancel\w*|aduana|codigo|cotizaci\w*|aporte\w*|jubilaci\w*)\b"
)

PROMPT_BUSQUEDA_OFICIAL = """Eres un investigador tributario y contable de Ecuador.
Busca la respuesta SOLO en fuentes oficiales (tu búsqueda está limitada a sitios
oficiales del Estado ecuatoriano). Responde en español, de forma breve y exacta
(máximo 250 palabras): nombre exacto de la ley, reglamento o resolución, número y
fecha de publicación, qué establece, quiénes pueden acceder, porcentajes, plazos y
requisitos, y si sigue vigente. Si el consultante usa un nombre coloquial, busca la
norma a la que se refiere. NO inventes nada: si no encuentras información oficial
clara sobre lo consultado, responde únicamente la palabra NO_ENCONTRADO.
Al final, lista las URLs oficiales que usaste, una por línea, con el prefijo 'FUENTE: '."""


# Palabras (sin tildes) que indican que vale la pena buscar en internet aunque
# no sea un tema tributario (datos recientes, programas contables, precios...)
PATRON_TEMA_WEB = re.compile(
    r"\b(quien es|quien fue|quienes son|cuando (?:fue|es|sera|se)|donde (?:queda|esta|puedo)|"
    r"noticia\w*|ultim\w*|reciente\w*|precio\w*|cuanto (?:cuesta|vale)|"
    r"contifico|alegra|facturero|software|tutorial|202\d)\b"
)


def es_url_oficial(url: str) -> bool:
    anfitrion = re.sub(r"^https?://", "", url).split("/")[0].lower()
    return any(anfitrion == d or anfitrion.endswith("." + d) for d in DOMINIOS_OFICIALES)


def _marcar_estado(mensaje: str):
    """Guarda el estado de la búsqueda: se ve en la barra lateral y, para la
    pregunta actual, también debajo de la respuesta (así se puede diagnosticar)."""
    st.session_state.busqueda_estado = mensaje
    st.session_state.busqueda_estado_turno = mensaje


def _consultar_tavily(consulta: str, dominios=None, profundidad: str = "basic"):
    """Busca con Tavily (buscador hecho para IAs). Con 'dominios' limita la
    búsqueda a esos sitios. Devuelve None si no hay clave configurada."""
    clave = st.secrets.get("TAVILY_API_KEY")
    if not clave:
        return None
    import requests
    cuerpo = {
        "query": consulta,
        "search_depth": profundidad,
        "max_results": 5,
        "include_answer": False,
    }
    if dominios:
        cuerpo["include_domains"] = dominios
    respuesta = requests.post(
        "https://api.tavily.com/search",
        json=cuerpo,
        headers={"Authorization": f"Bearer {clave}"},
        timeout=25,
    )
    respuesta.raise_for_status()
    return respuesta.json().get("results", [])


def _consultar_ddgs(consulta: str, dominios=None):
    """Búsqueda SIN clave (DuckDuckGo, librería 'ddgs'). Para limitarla a
    sitios oficiales usa el operador site:. Es menos estable que Tavily, pero
    no requiere registrarse en nada."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    if dominios:
        filtro = " OR ".join(f"site:{d}" for d in dominios)
        consulta = f"({filtro}) {consulta}"
    crudos = DDGS().text(consulta, max_results=5) or []
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
        for r in crudos
    ]


def _consultar_web(consulta: str, dominios=None, profundidad: str = "basic"):
    """Prueba primero Tavily (si hay clave) y, si no hay clave o falla,
    DuckDuckGo. Devuelve (resultados, nombre_del_motor, errores)."""
    errores = []
    if st.secrets.get("TAVILY_API_KEY"):
        try:
            resultados = _consultar_tavily(consulta, dominios, profundidad)
            if resultados:
                return resultados, "Tavily", errores
        except Exception as e:
            errores.append(f"Tavily: {type(e).__name__}")
    try:
        resultados = _consultar_ddgs(consulta, dominios)
        if resultados:
            return resultados, "DuckDuckGo", errores
    except Exception as e:
        errores.append(f"DuckDuckGo: {type(e).__name__}")
    return [], "", errores


def _formatear_resultados(resultados: list, limite_caracteres: int = 700):
    """Convierte los resultados de la búsqueda en texto para la IA + lista de URLs."""
    bloques, urls = [], []
    for i, r in enumerate(resultados, start=1):
        url = r.get("url", "")
        contenido = re.sub(r"\s+", " ", r.get("content", "") or "").strip()[:limite_caracteres]
        bloques.append(f"[{i}] {r.get('title', '(sin título)')} — {url}\n{contenido}")
        if url and url not in urls:
            urls.append(url)
    return "\n\n".join(bloques), urls


def buscar_en_internet(pregunta: str):
    """Devuelve (texto_para_la_IA, [urls]). Estrategia:
    1) Si la pregunta es tributaria/legal: primero SOLO sitios oficiales.
    2) Si eso no da resultados (o la pregunta es de otro tipo pero pide datos
       recientes): búsqueda abierta, avisando que las fuentes no son oficiales.
    Nunca rompe la app: si algo falla, devuelve ('', []) y deja el motivo
    visible en la interfaz."""
    st.session_state.busqueda_estado_turno = ""
    if not st.session_state.get("buscar_oficial", True):
        return "", []
    norm = _normalizar(pregunta)
    if len(norm.split()) < 3:
        return "", []
    es_tributario = bool(PATRON_TEMA_OFICIAL.search(norm))
    if not (es_tributario or PATRON_TEMA_WEB.search(norm)):
        return "", []

    consulta = pregunta if "ecuador" in norm else f"{pregunta} Ecuador"
    todos_los_errores = []
    resultados, motor, oficial = [], "", False

    if es_tributario:
        resultados, motor, errs = _consultar_web(consulta, DOMINIOS_OFICIALES, "advanced")
        todos_los_errores += errs
        oficial = bool(resultados)
    if not resultados:
        resultados, motor, errs = _consultar_web(consulta if es_tributario else pregunta, None, "basic")
        todos_los_errores += errs

    if not resultados:
        # Último recurso para temas tributarios: el buscador integrado de Groq
        if es_tributario:
            texto, urls = _buscar_con_groq_compound(pregunta)
            if texto:
                return texto, urls
        detalle = f" ({'; '.join(todos_los_errores)})" if todos_los_errores else ""
        _marcar_estado(f"⚠️ No se pudo buscar en internet{detalle}")
        return "", []

    cuerpo, urls = _formatear_resultados(resultados)
    if oficial:
        encabezado = (
            "INFORMACIÓN OFICIAL ENCONTRADA EN INTERNET (sitios oficiales del Ecuador, "
            "consultada hoy):"
        )
        _marcar_estado(f"✅ Consulta en sitios oficiales exitosa ({motor})")
    else:
        encabezado = (
            "INFORMACIÓN ENCONTRADA EN INTERNET (fuentes NO oficiales, consultada hoy; si el "
            "tema es tributario o legal, avísale al estudiante que la verifique en la fuente oficial):"
        )
        _marcar_estado(f"✅ Consulta en internet exitosa, fuentes no oficiales ({motor})")
    return f"{encabezado}\n{cuerpo}", urls


def _buscar_con_groq_compound(pregunta: str):
    """Último recurso: búsqueda integrada de Groq. Puede no estar disponible
    en todas las cuentas; si falla, devuelve ('', [])."""
    try:
        respuesta = client.chat.completions.create(
            model=MODELO_BUSQUEDA,
            messages=[
                {"role": "system", "content": PROMPT_BUSQUEDA_OFICIAL},
                {"role": "user", "content": f"Fecha de hoy: {FECHA_ACTUAL_TEXTO}.\nConsulta: {pregunta}"},
            ],
            extra_body={"search_settings": {"include_domains": DOMINIOS_OFICIALES}},
        )
        texto = (respuesta.choices[0].message.content or "").strip()
    except Exception:
        return "", []
    if not texto or "NO_ENCONTRADO" in texto.upper():
        return "", []
    urls = []
    for candidata in re.findall(r"https?://[^\s)\]>\"']+", texto):
        candidata = candidata.rstrip(".,;:")
        if es_url_oficial(candidata) and candidata not in urls:
            urls.append(candidata)
    _marcar_estado("✅ Consulta oficial exitosa (Groq)")
    return (
        "INFORMACIÓN OFICIAL ENCONTRADA EN INTERNET (sitios oficiales del Ecuador, "
        f"consultada hoy):\n{texto}",
        urls[:4],
    )


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
    return "ARCHIVO EXCEL SUBIDO POR EL ESTUDIANTE:\n" + hojas_excel_a_markdown(hojas)


# =========================================================
# 6. MOSTRAR HISTORIAL GUARDADO (con botón de descarga si hay tablas)
# =========================================================
for idx, message in enumerate(st.session_state.messages):
    avatar = "🐼" if message["role"] == "assistant" else "🙂"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            tablas_previas = extraer_tablas_markdown(message["content"])
            if tablas_previas:
                st.download_button(
                    "📥 Descargar esta respuesta en Excel",
                    data=generar_excel_desde_tablas(tablas_previas),
                    file_name="poconta_resultado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"descarga_historial_{idx}",
                )
            boton_generar_quiz(message["content"], key_sufijo=f"historial_{idx}")
            if idx == len(st.session_state.messages) - 1:
                # Solo en el ÚLTIMO mensaje, para que la nueva respuesta que
                # genere este botón aparezca al final y no en medio del chat.
                boton_explicar_mas_facil(key_sufijo=f"historial_{idx}")

mostrar_quiz()


# =========================================================
# 7. BARRA DE CONTROLES (➕ opciones y modo voz) + CAJA DE CHAT
# La caja de chat usa las funciones nativas de Streamlit para adjuntar
# Excel y grabar audio, así que ambas cosas aparecen como iconitos DENTRO
# de la misma caja donde se escribe — no hace falta paneles aparte arriba.
# =========================================================
col_mas, col_voz = st.columns([1, 4])

with col_mas:
    with st.popover("➕"):
        st.caption("Más opciones")

        if st.button("🕺 ¡Que baile PoConta!" if not st.session_state.bailando else "⏹️ Parar de bailar"):
            st.session_state.bailando = not st.session_state.bailando
            st.rerun()

        if st.button("🎯 Generar quiz del último tema"):
            if st.session_state.get("messages"):
                ultimos = st.session_state.messages[-4:]
                contexto_quiz = "\n".join(f"{m['role']}: {m['content']}" for m in ultimos)
            else:
                contexto_quiz = f"Conceptos generales de contabilidad de {nivel}."
            with st.spinner("PoConta está armando tu quiz..."):
                preguntas = generar_quiz(contexto_quiz)
            if preguntas:
                st.session_state.quiz_id = st.session_state.get("quiz_id", 0) + 1
                st.session_state.quiz_actual = {"preguntas": preguntas, "tema": contexto_quiz[:80]}
                st.rerun()

        st.markdown("---")
        if st.button("🗑️ Empezar de nuevo"):
            st.session_state.messages = []
            st.session_state.historial_ia = []
            st.session_state.quiz_actual = None
            st.rerun()

with col_voz:
    if st.button(
        "🔊 Conversación por voz: Activada" if st.session_state.modo_voz
        else "🔈 Activar conversación por voz"
    ):
        st.session_state.modo_voz = not st.session_state.modo_voz
        st.rerun()

if st.session_state.modo_voz:
    if st.button("❌ Cancelar audio"):
        components.html(
            "<script>try{window.speechSynthesis.cancel();}catch(e){}</script>",
            height=0,
        )
        st.rerun()

prompt = st.chat_input(
    "Escríbeme tu pregunta, adjunta un Excel (📎) o graba tu voz (🎤)...",
    accept_file=True,
    file_type=["xlsx", "xls"],
    accept_audio=True,
)

# =========================================================
# 8. PROCESAR LO QUE LLEGÓ (texto, audio y/o Excel, todo puede venir junto)
# =========================================================
if prompt:
    texto_usuario = None
    contexto_excel = None
    bytes_excel_original = None
    nombre_excel_original = None

    # Si grabó audio, lo transcribimos primero
    if getattr(prompt, "audio", None):
        with st.spinner("Transcribiendo tu audio..."):
            texto_usuario = transcribir_audio(prompt.audio.getvalue())
    elif getattr(prompt, "text", None):
        texto_usuario = prompt.text

    # Si adjuntó un Excel, lo leemos y lo dejamos listo como contexto extra
    if getattr(prompt, "files", None):
        archivo_excel = prompt.files[0]
        try:
            bytes_excel_original = archivo_excel.getvalue()
            hojas = pd.read_excel(io.BytesIO(bytes_excel_original), sheet_name=None)
            contexto_excel = convertir_excel_a_texto(hojas)
            nombre_excel_original = archivo_excel.name
            if not texto_usuario:
                texto_usuario = "Resuelve el ejercicio de este archivo Excel."
        except Exception as e:
            st.error(f"No pude leer el archivo adjunto. Detalle técnico: {e}")

    if texto_usuario:
        responder_pregunta(
            texto_usuario,
            contexto_extra=contexto_excel,
            excel_original_bytes=bytes_excel_original,
            excel_original_nombre=nombre_excel_original,
        )
