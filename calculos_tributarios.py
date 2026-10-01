"""
Cálculos contables y tributarios EXACTOS de PoConta.

Este módulo no usa IA ni Streamlit: son funciones de Python puras. La IA no hace
las cuentas "de cabeza" (los modelos de lenguaje fallan en aritmética): llama a
estas funciones mediante "function calling" y solo explica los resultados.

Dinero: se usa Decimal y redondeo "half up" a 2 decimales (el habitual en contabilidad).

PARÁMETROS QUE DEPENDEN DE LA NORMA (tarifa de IVA y porcentajes de retención):
están en las tablas de abajo, cada uno con su fuente. Cuando cambie la norma, se
edita AQUÍ y todo el sistema se actualiza. Ver la sección "PARÁMETROS".
"""
from collections import deque
from decimal import Decimal, ROUND_HALF_UP

# =====================================================================
# PARÁMETROS (editar aquí cuando cambie la norma)
# =====================================================================
# Tarifa general de IVA. ⚠️ Confirma la tarifa vigente en www.sri.gob.ec.
TARIFA_IVA_GENERAL = 15

# Retención en la fuente de Impuesto a la Renta (%), por tipo de compra/pago.
# Fuente: tabla de retenciones del SRI (Res. NAC-DGERCGC26-00000009, vigente desde
# 1-mar-2026). ⚠️ Contrastada solo en parte (bienes 2 %, mano de obra 3 %,
# sociedades 5 %, residual 3 %): revisa cada porcentaje contra la resolución oficial.
RETENCION_IR = {
    "bienes_muebles": (2, "Bienes muebles de naturaleza corporal (compra de mercadería)"),
    "servicios_mano_obra": (3, "Servicios donde prevalece la mano de obra (persona natural)"),
    "servicios_generales_residual": (3, "Pagos sin porcentaje específico (regla residual)"),
    "publicidad": (3, "Publicidad y comunicación"),
    "liquidacion_compra": (3, "Liquidación de compra (proveedor sin RUC)"),
    "rendimientos_financieros": (3, "Rendimientos financieros"),
    "servicios_profesionales_sociedad": (5, "Servicios profesionales de sociedades"),
    "comisiones_sociedades": (5, "Comisiones a sociedades residentes"),
    "honorarios_persona_natural": (10, "Honorarios y comisiones a personas naturales (profesión liberal)"),
    "arriendo_inmuebles": (10, "Arrendamiento de bienes inmuebles"),
    "docencia_persona_natural": (10, "Docencia a personas naturales"),
    "regalias_propiedad_intelectual": (10, "Cánones, regalías, propiedad intelectual"),
    "imagen_renombre": (10, "Pagos por imagen o renombre"),
    "transporte": (1, "Transporte de carga o pasajeros"),
    "agricola_productor": (1, "Bienes agrícolas/pecuarios comprados directo al productor"),
    "rimpe_emprendedor": (1, "Compras a RIMPE Emprendedores"),
    "agricola_comercializador": (Decimal("1.75"), "Bienes agrícolas/pecuarios a comercializadores"),
    "seguros": (2, "Seguros y reaseguros (sobre primas)"),
    "energia_electrica": (2, "Energía eléctrica"),
    "arrendamiento_mercantil": (2, "Arrendamiento mercantil (leasing)"),
    "tarjeta_credito": (2, "Pagos con tarjeta de crédito/débito a afiliados"),
    "construccion": (2, "Construcción de obra material inmueble"),
    "rimpe_negocio_popular": (0, "Compras a RIMPE Negocios Populares"),
    "intereses_bancos": (0, "Intereses a bancos/financieras supervisadas"),
}

# Retención de IVA (%) cuando el proveedor NO es Contribuyente Especial.
RETENCION_IVA_PROVEEDOR_COMUN = {
    "bienes": 30,
    "servicios": 70,
    "servicios_profesionales_persona_natural": 100,
    "arriendo_inmuebles_persona_natural": 100,
    "liquidacion_compra": 100,
    "construccion": 30,
}
# Si el proveedor SÍ es Contribuyente Especial: bienes 10 %, servicios 20 %,
# construcción 30 % y liquidación de compra 100 %.
TIPOS_IVA = list(RETENCION_IVA_PROVEEDOR_COMUN.keys())


# =====================================================================
# Utilidades
# =====================================================================
def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _r(x) -> Decimal:
    """Redondea a 2 decimales (half up)."""
    return _d(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _num(x) -> float:
    return float(_r(x))


def _m(x) -> str:
    return f"${_r(x):,.2f}"


def _pct(x) -> Decimal:
    return _d(x) / Decimal(100)


def _tabla_md(encabezados, filas) -> str:
    lineas = [
        "| " + " | ".join(encabezados) + " |",
        "| " + " | ".join("---" for _ in encabezados) + " |",
    ]
    for fila in filas:
        lineas.append("| " + " | ".join(str(c) for c in fila) + " |")
    return "\n".join(lineas)


def _validar_positivo(nombre, valor, permitir_cero=False):
    v = _d(valor)
    if v < 0 or (v == 0 and not permitir_cero):
        raise ValueError(f"'{nombre}' debe ser {'mayor o igual a' if permitir_cero else 'mayor que'} cero.")
    return v


# =====================================================================
# 1) IVA
# =====================================================================
def calcular_iva(valor, tarifa_iva=None, valor_incluye_iva=False) -> dict:
    tarifa = _d(TARIFA_IVA_GENERAL if tarifa_iva is None else tarifa_iva)
    valor = _validar_positivo("valor", valor)
    factor = tarifa / Decimal(100)
    if valor_incluye_iva:
        base = _r(valor / (1 + factor))
        iva = _r(valor - base)
        total = _r(valor)
    else:
        base = _r(valor)
        iva = _r(base * factor)
        total = _r(base + iva)
    return {
        "tarifa_iva_porcentaje": float(tarifa),
        "base_imponible": float(base),
        "iva": float(iva),
        "total_con_iva": float(total),
        "nota": f"Tarifa de IVA usada: {tarifa}%. Confirma la tarifa vigente en www.sri.gob.ec.",
    }


# =====================================================================
# 2) Compra con retenciones (IR e IVA) + asiento contable
# =====================================================================
def _porcentaje_retencion_iva(tipo_iva: str, proveedor_especial: bool):
    if tipo_iva not in RETENCION_IVA_PROVEEDOR_COMUN:
        raise ValueError(f"tipo_iva '{tipo_iva}' no válido. Opciones: {', '.join(TIPOS_IVA)}")
    if not proveedor_especial:
        return Decimal(RETENCION_IVA_PROVEEDOR_COMUN[tipo_iva])
    if tipo_iva == "bienes":
        return Decimal(10)
    if tipo_iva == "construccion":
        return Decimal(30)
    if tipo_iva == "liquidacion_compra":
        return Decimal(100)
    return Decimal(20)  # servicios y afines


def compra_con_retenciones(
    base_imponible,
    tipo_ir,
    tipo_iva,
    proveedor_contribuyente_especial=False,
    comprador_es_agente_retencion=True,
    tarifa_iva=None,
    cuenta_debito="Inventario de mercaderías",
    cuenta_pago="Proveedores",
) -> dict:
    """Calcula IVA, retención de IR, retención de IVA, neto a pagar y arma el asiento."""
    base = _r(_validar_positivo("base_imponible", base_imponible))
    if tipo_ir not in RETENCION_IR:
        raise ValueError(f"tipo_ir '{tipo_ir}' no válido. Opciones: {', '.join(RETENCION_IR)}")
    tarifa = _d(TARIFA_IVA_GENERAL if tarifa_iva is None else tarifa_iva)

    iva = _r(base * tarifa / Decimal(100))
    total_factura = _r(base + iva)

    pct_ir = Decimal(0)
    pct_iva = Decimal(0)
    ret_ir = Decimal(0)
    ret_iva = Decimal(0)
    notas = [f"Tarifa de IVA usada: {tarifa}%."]
    if comprador_es_agente_retencion:
        pct_ir = _d(RETENCION_IR[tipo_ir][0])
        pct_iva = _porcentaje_retencion_iva(tipo_iva, bool(proveedor_contribuyente_especial))
        ret_ir = _r(base * pct_ir / Decimal(100))        # IR: sobre la base, SIN IVA
        ret_iva = _r(iva * pct_iva / Decimal(100))        # IVA: sobre el IVA generado
        notas.append(f"Retención de IR: {RETENCION_IR[tipo_ir][1]} ({pct_ir}%), sobre la base sin IVA.")
        notas.append(f"Retención de IVA: {pct_iva}% del IVA "
                     f"({'proveedor Contribuyente Especial' if proveedor_contribuyente_especial else 'proveedor que no es Contribuyente Especial'}).")
    else:
        notas.append("El comprador NO es agente de retención: no se registran retenciones.")
    notas.append("Porcentajes según tabla del SRI (Res. NAC-DGERCGC26-00000009); verifica en www.sri.gob.ec.")

    neto = _r(total_factura - ret_ir - ret_iva)

    filas_debe = [(cuenta_debito, base), ("IVA en compras (crédito tributario)", iva)]
    filas_haber = []
    if ret_ir > 0:
        filas_haber.append(("Retención en la fuente de IR por pagar", ret_ir))
    if ret_iva > 0:
        filas_haber.append(("Retención de IVA por pagar", ret_iva))
    filas_haber.append((cuenta_pago, neto))

    total_debe = sum((v for _, v in filas_debe), Decimal(0))
    total_haber = sum((v for _, v in filas_haber), Decimal(0))

    filas_md = [(c, _m(v), "") for c, v in filas_debe] + [(f"   {c}", "", _m(v)) for c, v in filas_haber]
    filas_md.append(("**Sumas iguales**", f"**{_m(total_debe)}**", f"**{_m(total_haber)}**"))

    return {
        "base_imponible": float(base),
        "tarifa_iva_porcentaje": float(tarifa),
        "iva": float(iva),
        "total_factura": float(total_factura),
        "retencion_ir_porcentaje": float(pct_ir),
        "retencion_ir": float(ret_ir),
        "retencion_iva_porcentaje": float(pct_iva),
        "retencion_iva": float(ret_iva),
        "neto_a_pagar": float(neto),
        "total_debe": float(total_debe),
        "total_haber": float(total_haber),
        "asiento_balanceado": total_debe == total_haber,
        "asiento_markdown": _tabla_md(["Cuenta", "Debe", "Haber"], filas_md),
        "notas": notas,
    }


# =====================================================================
# 3) Depreciación en línea recta
# =====================================================================
def depreciacion_linea_recta(costo, valor_residual, vida_util_anios) -> dict:
    costo = _validar_positivo("costo", costo)
    residual = _validar_positivo("valor_residual", valor_residual, permitir_cero=True)
    vida = int(vida_util_anios)
    if vida < 1:
        raise ValueError("'vida_util_anios' debe ser al menos 1.")
    if residual >= costo:
        raise ValueError("El valor residual debe ser menor que el costo.")
    base_dep = costo - residual
    anual = _r(base_dep / vida)
    mensual = _r(base_dep / vida / 12)
    filas, acumulada = [], Decimal(0)
    for anio in range(1, vida + 1):
        dep = anual if anio < vida else _r(base_dep - acumulada)  # el último año ajusta el centavo
        acumulada += dep
        filas.append({
            "anio": anio,
            "depreciacion": float(dep),
            "depreciacion_acumulada": float(acumulada),
            "valor_en_libros": float(_r(costo - acumulada)),
        })
    tabla = _tabla_md(
        ["Año", "Depreciación", "Dep. acumulada", "Valor en libros"],
        [(f["anio"], _m(f["depreciacion"]), _m(f["depreciacion_acumulada"]), _m(f["valor_en_libros"])) for f in filas],
    )
    return {
        "base_depreciable": float(_r(base_dep)),
        "depreciacion_anual": float(anual),
        "depreciacion_mensual": float(mensual),
        "tabla": filas,
        "tabla_markdown": tabla,
        "formula": "(Costo − Valor residual) ÷ Vida útil",
    }


# =====================================================================
# 4) Interés simple y compuesto
# =====================================================================
def interes(tipo, capital, tasa_anual_pct, tiempo_anios, capitalizaciones_por_anio=1) -> dict:
    tipo = str(tipo).lower()
    if tipo not in ("simple", "compuesto"):
        raise ValueError("'tipo' debe ser 'simple' o 'compuesto'.")
    capital = _validar_positivo("capital", capital)
    tasa = _pct(_validar_positivo("tasa_anual_pct", tasa_anual_pct, permitir_cero=True))
    t = _validar_positivo("tiempo_anios", tiempo_anios)
    if tipo == "simple":
        interes_ganado = _r(capital * tasa * t)
        monto = _r(capital + interes_ganado)
        formula = "I = C × i × t ;  M = C + I"
    else:
        n = int(capitalizaciones_por_anio)
        if n < 1:
            raise ValueError("'capitalizaciones_por_anio' debe ser al menos 1.")
        exponente = _d(n) * t
        factor = Decimal(1) + tasa / n
        if exponente == exponente.to_integral_value():
            acumulado = factor ** int(exponente)            # exacto con Decimal
        else:
            acumulado = _d(float(factor) ** float(exponente))
        monto = _r(capital * acumulado)
        interes_ganado = _r(monto - capital)
        formula = "M = C × (1 + i/n)^(n×t) ;  I = M − C"
    return {
        "tipo": tipo,
        "capital": float(_r(capital)),
        "interes": float(interes_ganado),
        "monto_final": float(monto),
        "formula": formula,
    }


# =====================================================================
# 5) VAN y TIR
# =====================================================================
def _van(tasa: float, flujos: list) -> float:
    return sum(f / (1 + tasa) ** i for i, f in enumerate(flujos))


def _tir(flujos: list):
    baja, alta = -0.99, 10.0
    v_baja, v_alta = _van(baja, flujos), _van(alta, flujos)
    if v_baja * v_alta > 0:
        return None
    for _ in range(300):
        medio = (baja + alta) / 2
        v_medio = _van(medio, flujos)
        if abs(v_medio) < 1e-9:
            return medio
        if v_baja * v_medio < 0:
            alta, v_alta = medio, v_medio
        else:
            baja, v_baja = medio, v_medio
    return (baja + alta) / 2


def van_tir(tasa_descuento_pct, inversion_inicial, flujos) -> dict:
    inv = float(_validar_positivo("inversion_inicial", inversion_inicial))
    if not flujos:
        raise ValueError("Falta la lista de flujos de caja.")
    lista = [-inv] + [float(f) for f in flujos]
    tasa = float(tasa_descuento_pct) / 100
    van = _van(tasa, lista)
    tir = _tir(lista)
    return {
        "van": float(_r(van)),
        "tir_porcentaje": None if tir is None else float(_r(Decimal(str(tir * 100)))),
        "interpretacion": (
            "VAN positivo: el proyecto genera valor a esa tasa de descuento." if van > 0
            else "VAN negativo: el proyecto no cubre la rentabilidad esperada." if van < 0
            else "VAN cero: el proyecto rinde justo la tasa de descuento."
        ),
    }


# =====================================================================
# 6) Kárdex (PEPS y promedio ponderado)
# =====================================================================
def kardex(metodo, movimientos) -> dict:
    """movimientos: lista de {"tipo": "saldo_inicial"|"compra"|"venta",
    "cantidad": n, "costo_unitario": c (no hace falta en ventas)}."""
    metodo = str(metodo).lower().replace(" ", "_")
    if metodo in ("promedio_ponderado", "promedio"):
        metodo = "promedio"
    if metodo != "peps" and metodo != "promedio":
        raise ValueError("'metodo' debe ser 'PEPS' o 'promedio'.")
    if not movimientos:
        raise ValueError("Falta la lista de movimientos.")

    capas = deque()
    cantidad_total, valor_total = Decimal(0), Decimal(0)
    costo_ventas_total = Decimal(0)
    filas = []

    for mov in movimientos:
        tipo = str(mov.get("tipo", "")).lower()
        q = _validar_positivo("cantidad", mov.get("cantidad"))
        if tipo in ("saldo_inicial", "compra"):
            c = _validar_positivo("costo_unitario", mov.get("costo_unitario"), permitir_cero=True)
            capas.append([q, c])
            cantidad_total += q
            valor_total += _r(q * c)
            ent = (q, c, _r(q * c))
            sal = None
        elif tipo == "venta":
            if q > cantidad_total:
                raise ValueError(f"No hay inventario suficiente: se vende {q} y solo hay {cantidad_total}.")
            if metodo == "peps":
                restante, costo = q, Decimal(0)
                while restante > 0:
                    capa = capas[0]
                    usar = min(capa[0], restante)
                    costo += usar * capa[1]
                    capa[0] -= usar
                    restante -= usar
                    if capa[0] == 0:
                        capas.popleft()
            else:
                costo = q * (valor_total / cantidad_total)
            costo = _r(costo)
            cantidad_total -= q
            valor_total -= costo
            costo_ventas_total += costo
            ent = None
            sal = (q, _r(costo / q) if q else Decimal(0), costo)
        else:
            raise ValueError(f"Tipo de movimiento '{tipo}' no válido (saldo_inicial, compra o venta).")

        unit_saldo = (valor_total / cantidad_total) if cantidad_total > 0 else Decimal(0)
        filas.append({
            "movimiento": {"saldo_inicial": "Saldo inicial", "compra": "Compra", "venta": "Venta"}[tipo],
            "entrada": None if ent is None else {"cantidad": float(ent[0]), "costo_unitario": float(ent[1]), "total": float(ent[2])},
            "salida": None if sal is None else {"cantidad": float(sal[0]), "costo_unitario": float(sal[1]), "total": float(sal[2])},
            "saldo": {"cantidad": float(cantidad_total), "costo_unitario": float(unit_saldo.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
                      "total": float(_r(valor_total))},
        })

    def _c(x, dinero=False):
        return "" if x is None else (_m(x) if dinero else f"{x:g}")

    filas_md = []
    for f in filas:
        e, s, sd = f["entrada"], f["salida"], f["saldo"]
        filas_md.append((
            f["movimiento"],
            _c(e and e["cantidad"]), _c(e and e["costo_unitario"], True), _c(e and e["total"], True),
            _c(s and s["cantidad"]), _c(s and s["costo_unitario"], True), _c(s and s["total"], True),
            _c(sd["cantidad"]), _c(sd["costo_unitario"], True), _c(sd["total"], True),
        ))
    tabla = _tabla_md(
        ["Movimiento", "Ent. cant.", "Ent. C/U", "Ent. total", "Sal. cant.", "Sal. C/U", "Sal. total",
         "Saldo cant.", "Saldo C/U", "Saldo total"],
        filas_md,
    )
    return {
        "metodo": "PEPS" if metodo == "peps" else "Promedio ponderado",
        "filas": filas,
        "costo_de_ventas_total": float(_r(costo_ventas_total)),
        "inventario_final_cantidad": float(cantidad_total),
        "inventario_final_valor": float(_r(valor_total)),
        "tabla_markdown": tabla,
    }


# =====================================================================
# Conexión con la IA (function calling)
# =====================================================================
def _esquema(nombre, descripcion, propiedades, requeridos):
    return {
        "type": "function",
        "function": {
            "name": nombre,
            "description": descripcion,
            "parameters": {"type": "object", "properties": propiedades, "required": requeridos},
        },
    }


HERRAMIENTAS_SCHEMA = [
    _esquema(
        "calcular_iva",
        "Calcula base, IVA y total de un valor. Úsala para cualquier cálculo de IVA.",
        {
            "valor": {"type": "number", "description": "Valor dado"},
            "tarifa_iva": {"type": "number", "description": "Tarifa en %. Omítela para usar la general vigente"},
            "valor_incluye_iva": {"type": "boolean", "description": "true si el valor ya incluye el IVA"},
        },
        ["valor"],
    ),
    _esquema(
        "compra_con_retenciones",
        "Calcula IVA, retención de IR, retención de IVA, neto a pagar y el asiento contable de una compra "
        "o pago con retenciones. Si faltan datos (tipo de proveedor, tipo de bien o servicio), pregúntalos antes.",
        {
            "base_imponible": {"type": "number", "description": "Valor de la compra SIN IVA"},
            "tipo_ir": {"type": "string", "enum": list(RETENCION_IR.keys()), "description": "Tipo de bien/servicio para la retención de IR"},
            "tipo_iva": {"type": "string", "enum": TIPOS_IVA, "description": "Tipo para la retención de IVA"},
            "proveedor_contribuyente_especial": {"type": "boolean", "description": "true si el proveedor es Contribuyente Especial"},
            "comprador_es_agente_retencion": {"type": "boolean", "description": "false si el comprador no es agente de retención"},
            "tarifa_iva": {"type": "number", "description": "Tarifa de IVA en %; omítela para la general"},
            "cuenta_debito": {"type": "string", "description": "Cuenta del Debe, p. ej. Inventario de mercaderías, Gastos de servicios"},
        },
        ["base_imponible", "tipo_ir", "tipo_iva"],
    ),
    _esquema(
        "depreciacion_linea_recta",
        "Depreciación en línea recta: cuota anual, mensual y tabla año por año.",
        {
            "costo": {"type": "number"},
            "valor_residual": {"type": "number"},
            "vida_util_anios": {"type": "integer"},
        },
        ["costo", "valor_residual", "vida_util_anios"],
    ),
    _esquema(
        "interes",
        "Interés simple o compuesto: interés ganado y monto final.",
        {
            "tipo": {"type": "string", "enum": ["simple", "compuesto"]},
            "capital": {"type": "number"},
            "tasa_anual_pct": {"type": "number", "description": "Tasa anual en %"},
            "tiempo_anios": {"type": "number", "description": "Tiempo en años (6 meses = 0.5)"},
            "capitalizaciones_por_anio": {"type": "integer", "description": "Solo compuesto: 1 anual, 2 semestral, 4 trimestral, 12 mensual"},
        },
        ["tipo", "capital", "tasa_anual_pct", "tiempo_anios"],
    ),
    _esquema(
        "van_tir",
        "Calcula el VAN y la TIR de un proyecto.",
        {
            "tasa_descuento_pct": {"type": "number", "description": "Tasa de descuento en %"},
            "inversion_inicial": {"type": "number", "description": "Inversión inicial (positiva)"},
            "flujos": {"type": "array", "items": {"type": "number"}, "description": "Flujos de caja de cada año"},
        },
        ["tasa_descuento_pct", "inversion_inicial", "flujos"],
    ),
    _esquema(
        "kardex",
        "Kárdex con método PEPS o promedio ponderado: costo de ventas e inventario final.",
        {
            "metodo": {"type": "string", "enum": ["PEPS", "promedio"]},
            "movimientos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tipo": {"type": "string", "enum": ["saldo_inicial", "compra", "venta"]},
                        "cantidad": {"type": "number"},
                        "costo_unitario": {"type": "number", "description": "No hace falta en ventas"},
                    },
                    "required": ["tipo", "cantidad"],
                },
            },
        },
        ["metodo", "movimientos"],
    ),
]

_FUNCIONES = {
    "calcular_iva": calcular_iva,
    "compra_con_retenciones": compra_con_retenciones,
    "depreciacion_linea_recta": depreciacion_linea_recta,
    "interes": interes,
    "van_tir": van_tir,
    "kardex": kardex,
}


def ejecutar_herramienta(nombre: str, argumentos: dict) -> dict:
    """Ejecuta una herramienta. Si algo sale mal devuelve {"error": ...} en vez de fallar."""
    funcion = _FUNCIONES.get(nombre)
    if funcion is None:
        return {"error": f"Herramienta desconocida: {nombre}"}
    try:
        return funcion(**(argumentos or {}))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, ArithmeticError) as e:
        return {"error": f"No se pudo calcular: {e}"}


def texto_tablas_referencia() -> str:
    """Las tablas de retención en texto plano (para prompts de prueba)."""
    lineas = ["Retención en la fuente de IR (%):"]
    lineas += [f"- {desc}: {pct}%" for _, (pct, desc) in RETENCION_IR.items()]
    lineas.append("Retención de IVA si el proveedor NO es Contribuyente Especial: bienes 30%, servicios 70%, "
                  "servicios profesionales de persona natural 100%, arriendo de inmuebles de persona natural 100%, "
                  "liquidación de compra 100%, construcción 30%.")
    lineas.append("Si el proveedor SÍ es Contribuyente Especial: bienes 10%, servicios 20%.")
    lineas.append("La retención de IR se aplica sobre la base sin IVA; la de IVA, sobre el IVA generado.")
    return "\n".join(lineas)
