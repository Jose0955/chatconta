import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="ChatConta - Tutor Contable BGU", page_icon="📊")
st.title("📊 ChatConta: Tutor Virtual de Contabilidad")
st.write("¡Hola! Soy tu asistente de contabilidad para 1.º, 2.º y 3.º de Bachillerato Técnico. ¿En qué ejercicio o tema tienes dudas hoy?")

# 1. Validación de API Key
api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.error("Configura tu API Key de Gemini en los secretos de Streamlit.")
    st.stop()

client = genai.Client(api_key=api_key)

SYSTEM_PROMPT = """
Eres "ChatConta", un tutor virtual de Inteligencia Artificial especializado en la especialidad de Contabilidad para Bachillerato Técnico (1.º, 2.º y 3.º de BGU).

NIVEL Y TEMAS DE COBERTURA:
1. PRIMERO DE BACHILLERATO:
   - Conceptos básicos: ¿Qué es contabilidad?, Ecuación contable (Activo = Pasivo + Patrimonio).
   - Clasificación y naturaleza de cuentas (Debe / Haber, Saldo Deudor / Acreedor).
   - Asientos contables básicos de comercio (compras, ventas al contado y crédito).

2. SEGUNDO DE BACHILLERATO:
   - Ajustes contables, depreciaciones de activos fijos y amortizaciones.
   - Retenciones en la fuente e IVA en compras y ventas.
   - Balance de comprobación y Estado de Resultados.

3. TERCERO DE BACHILLERATO:
   - Contabilidad de Costos (Materia prima, Mano de obra, CIF).
   - Conciliaciones bancarias y control de inventarios (Kardex: PEPS, Promedio Ponderado).
   - Rol de pagos, beneficios sociales y liquidaciones.

CÓMO DEBES RESPONDER A DUDAS Y REGISTROS EN LIBROS CONTABLES:
1. Si el estudiante te pide ayuda para registrar una transacción:
   - Muéstrale la estructura del asiento contable en formato de tabla (Libro Diario).
   - Explicarle paso a paso por qué va en el DEBE y por qué va en el HABER.
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

# 2. Inicializar historial de chat en la sesión
if "messages" not in st.session_state:
    st.session_state.messages = []

# 3. Mostrar historial guardado en la interfaz
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. Procesar la entrada del usuario
if user_input := st.chat_input("Ejemplo: ¿Cómo registro una compra de mercadería al contado por $100?"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        try:
            # Cambio a gemini-1.5-flash
            chat = client.chats.create(
                model="gemini-1.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                )
            )
            
            response = chat.send_message(user_input)
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
            
        except Exception as e:
            st.error(f"Error en la consulta: {e}")
