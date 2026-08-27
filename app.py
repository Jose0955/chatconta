import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="ChatConta - Tutor Contable BGU", page_icon="📊")
st.title("📊 ChatConta: Tutor Virtual de Contabilidad")
st.write("¡Hola! Soy tu asistente de contabilidad para 1.º, 2.º y 3.º de Bachillerato Técnico. ¿En qué ejercicio o tema tienes dudas hoy?")

api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.error("Configura tu API Key de Gemini en los secretos de Streamlit.")
    st.stop()

genai.configure(api_key=api_key)

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

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=SYSTEM_PROMPT
)

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input("Ejemplo: ¿Cómo registro una compra de mercadería a crédito de $200?"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    history_for_gemini = [
        {"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]}
        for m in st.session_state.messages[:-1]
    ]
    
    chat = model.start_chat(history=history_for_gemini)
    
    with st.chat_message("assistant"):
        response = chat.send_message(user_input)
        st.markdown(response.text)
        
    st.session_state.messages.append({"role": "assistant", "content": response.text})
