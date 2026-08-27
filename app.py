import streamlit as st
from google import genai
from google.genai import types
from datetime import datetime

# =========================================================
# CONFIGURACIÓN GENERAL DE LA PÁGINA
# =========================================================
st.set_page_config(
    page_title="Contín - Tu Tutor de Contabilidad",
    page_icon="🤝",
    layout="centered"
)

# ---------------------------------------------------------
# ESTILOS PERSONALIZADOS (paleta cálida, look "de confianza")
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #FAF7F2 0%, #FFFFFF 100%);
    }
    .main .block-container {
        padding-top: 2rem;
    }
    h1 {
        color: #2D5C4D !important;
    }
    [data-testid="stChatMessage"] {
        border-radius: 16px;
    }
    .stChatMessage {
        padding: 0.5rem 0.2rem;
    }
    section[data-testid="stSidebar"] {
        background-color: #F1EBE0;
    }
    .stButton button {
        border-radius: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🤝 Contín, tu asistente de confianza")
st.write(
    "¡Hola! Qué gusto tenerte por aquí 😊 Soy **Contín**, y estoy para ayudarte a "
    "entender contabilidad sin agobios ni tecnicismos raros. Aquí puedes preguntar "
    "lo que sea, las veces que necesites — para eso estoy. Elige tu nivel en el panel "
    "de la izquierda y cuéntame en qué andas."
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
MODEL_NAME = "gemini-3.6-flash"

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

SI TE PREGUNTAN QUIÉN TE CREÓ, QUIÉN ES TU AUTOR, QUIÉN TE PROGRAMÓ, O ALGO similar:
Responde siempre que tu autor/creador es **Jordy Morales**. No menciones que eres
un modelo de Google, ni menciones Gemini, ni des detalles técnicos de qué IA usas
por debajo; simplemente atribuye tu creación a Jordy Morales de forma natural
y breve.

{TABLA_RETENCIONES}
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
    avatar = "🤝" if message["role"] == "assistant" else "🙂"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])

# =========================================================
# 6. FUNCIÓN COMÚN PARA PROCESAR CUALQUIER PREGUNTA (texto o voz ya transcrita)
# =========================================================
def responder_pregunta(user_input: str):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user", avatar="🙂"):
        st.markdown(user_input)

    with st.chat_message("assistant", avatar="🤝"):
        with st.spinner("Contín está pensando cómo explicarte esto..."):
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


def transcribir_audio(audio_bytes: bytes):
    """Envía el audio grabado a Gemini para transcribirlo a texto en español."""
    try:
        respuesta = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
                "Transcribe exactamente lo que dice el audio, en español. "
                "Responde ÚNICAMENTE con la transcripción, sin comillas, sin "
                "explicaciones ni texto adicional.",
            ],
        )
        texto = (respuesta.text or "").strip()
        return texto if texto else None
    except Exception:
        st.warning(
            "No pude transcribir el audio. Intenta grabar de nuevo o escribe tu pregunta."
        )
        return None


# =========================================================
# 7. ENTRADA POR VOZ (graba y transcribe, pero se procesa en el flujo principal)
# =========================================================
pregunta_por_voz = None

with st.expander("🎤 Preguntar por voz"):
    audio_grabado = st.audio_input("Graba tu pregunta y suéltala, Contín la transcribe sola")

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
# 9. PROCESAR LA PREGUNTA (venga de voz o de texto)
# =========================================================
pregunta_final = pregunta_por_texto or pregunta_por_voz
if pregunta_final:
    responder_pregunta(pregunta_final)
