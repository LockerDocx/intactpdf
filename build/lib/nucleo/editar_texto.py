"""
Edición de texto: cambiar los caracteres de un run sin rehacer la línea.

La escalera de niveles, de la edición más fiel a la más invasiva:

  Nivel 1a — misma longitud y todos los códigos ya existen.
             Sustitución de bytes en cada operador de texto. La estructura del
             stream NO se toca: ni un operador, ni un espacio de más. Es la
             edición más barata y la más segura. Cubre corregir una errata,
             cambiar un dígito, cambiar una fecha.

  Nivel 1b — longitud distinta, pero todos los códigos existen.
             Se colapsan los operadores de texto del run en uno solo. El run se
             vuelve a componer con espaciado normal, así que su ancho cambia y
             eso se avisa. Nada fuera del run se mueve.

  Nivel 2  — falta algún glifo y la fuente está en el sistema.
             Se construye un subconjunto nuevo con fontTools y se incrusta como
             fuente NUEVA. La fuente original no se toca, así que el resto del
             documento es inmune. Se cambia el `Tf` de ese run.

  Nivel 0  — falta el glifo y la fuente no está.
             Se rechaza diciendo qué fuente hace falta. No se sustituye por otra
             parecida: eso cambiaría el aspecto del documento en silencio.

En los cuatro casos el resultado es el mismo tipo de edición que en F2: un
cambio en el content stream que se guarda de forma incremental. Nada más del
documento se reescribe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

from .editar import Edicion, aplicar_ediciones
from .geometria import multiplicar
from .fuentes import Fuente, resolver_fuentes
from .objetos import ContenidoPagina, Instruccion, TextoRun
from .sustitucion_fuente import (buscar_fuente_sistema, construir_subconjunto,
                                 cmap_tounicode, nombre_base_sin_subset,
                                 objetos_fuente)

# operadores que no pintan texto pero forman parte de su estado
OPS_ESTADO_TEXTO = {"Tc", "Tw", "Tz", "TL", "Ts", "Tr"}


@dataclass
class InformeTexto:
    ok: bool = False
    nivel: str = "0"
    motivo: str = ""
    glifos_que_faltan: list[str] = field(default_factory=list)
    chars_reutilizados: int = 0
    ancho_original: float = 0.0      # en 1/1000 em
    ancho_nuevo: float = 0.0
    delta_ancho: float = 0.0
    delta_en_puntos: float = 0.0
    desborde: bool = False
    fuente_nueva: str | None = None
    espaciado_aplicado: float | None = None

    def resumen(self) -> str:
        if not self.ok:
            return f"NO EDITABLE: {self.motivo}"
        partes = [f"nivel {self.nivel}"]
        partes.append(f"ancho {self.ancho_original:.0f} -> {self.ancho_nuevo:.0f}"
                      f" ({self.delta_ancho:+.0f} milésimas)")
        if self.delta_en_puntos:
            partes.append(f"{self.delta_en_puntos:+.2f} pt")
        if self.desborde:
            partes.append("DESBORDA")
        if self.fuente_nueva:
            partes.append(f"fuente nueva {self.fuente_nueva}")
        if self.espaciado_aplicado is not None:
            partes.append(f"Tc {self.espaciado_aplicado:+.3f}")
        return "; ".join(partes)


@dataclass
class PlanTexto:
    contenido: bytes
    objetos: dict[tuple[int, int], bytes] = field(default_factory=dict)
    informe: InformeTexto = field(default_factory=InformeTexto)


# ---------------------------------------------------------------------------
# Codificación de cadenas PDF
# ---------------------------------------------------------------------------

def _escapar_literal(datos: bytes) -> bytes:
    out = bytearray(b"(")
    for b in datos:
        if b in (0x28, 0x29, 0x5C):          # ( ) backslash
            out += b"\\" + bytes([b])
        elif b == 0x0A:
            out += b"\\n"
        elif b == 0x0D:
            out += b"\\r"
        elif b < 0x20 or b > 0x7E:
            out += f"\\{b:03o}".encode("ascii")
        else:
            out.append(b)
    out += b")"
    return bytes(out)


def _hexstring(datos: bytes) -> bytes:
    return b"<" + datos.hex().upper().encode("ascii") + b">"


def _forma_del_operando(ins: Instruccion) -> str:
    for t in ins.tokens:
        if t.tipo == "hexstring":
            return "hex"
        if t.tipo == "string":
            return "literal"
        if t.tipo == "array":
            return "array"
    return "literal"


def _string_token(ins: Instruccion):
    """El token de cadena de un Tj / TJ. En TJ es el array."""
    for t in ins.tokens:
        if t.tipo in ("string", "hexstring", "array"):
            return t
    return None


def _trozo_texto(ins: Instruccion, fuente: Fuente) -> list[int]:
    """Códigos que pinta una instrucción de texto (ignora el kerning de TJ)."""
    if not ins.operandos:
        return []
    o = ins.operandos[0]
    if ins.op == '"' and len(ins.operandos) >= 3:
        o = ins.operandos[-1]
    if isinstance(o, (bytes, bytearray)):
        return fuente.codigos_de(bytes(o))
    if isinstance(o, list):
        datos = b"".join(bytes(e) for e in o
                         if isinstance(e, (bytes, bytearray)))
        return fuente.codigos_de(datos)
    return []


def _instrucciones_de_texto(run: TextoRun) -> list[Instruccion]:
    return [i for i in run.instrucciones if i.op in ("Tj", "TJ", "'", '"')]


def _numero(o, por_omision: float = 0.0) -> float:
    try:
        return float(o)
    except (TypeError, ValueError):
        return por_omision


def _tc_en_efecto(contenido: ContenidoPagina, offset: int) -> float:
    """Valor de `Tc` (espaciado entre caracteres) en efecto en un offset.

    Hace falta porque `Tc` es estado gráfico y sobrevive al `ET`: si una edición
    pone un `Tc` y no lo restaura, TODAS las líneas siguientes de la página salen
    con el espaciado equivocado. Es exactamente el tipo de «ha cambiado algo
    más» que este editor no puede permitirse.

    Se respeta la pila `q`/`Q`, porque un `Tc` dentro de un bloque cerrado ya no
    está vigente al salir.
    """
    tc = 0.0
    pila: list[float] = []
    for ins in contenido.instrucciones:
        if ins.fin > offset:
            break
        if ins.op == "q":
            pila.append(tc)
        elif ins.op == "Q":
            tc = pila.pop() if pila else 0.0
        elif ins.op == "Tc":
            tc = _numero(ins.operandos[0] if ins.operandos else 0.0)
    return tc


def _rango_del_run(datos: bytes, contenido: ContenidoPagina,
                   run: TextoRun) -> tuple[int, int]:
    """Rango de bytes que ocupa el TEXTO del run.

    Del primer operador de texto al último. El `Tm` y el `Tf` de delante se
    conservan: son los que colocan el texto. Lo que va detrás tampoco se toca,
    porque puede pertenecer a la línea siguiente.

    Quien reemplace este rango DEBE restaurar el `Tc` que dejaba el original,
    con `_tc_en_efecto`: es estado gráfico y sobrevive al `ET`.
    """
    muestra = _instrucciones_de_texto(run)
    if not muestra:
        raise ValueError("el run no tiene operadores de texto")

    # Del primer operador de texto al último, y nada más. NO se extiende hacia
    # delante para tragarse los operadores de estado que van detrás: en muchos
    # PDFs el `Tc` se emite DESPUÉS de cada `Tj` para fijar el espaciado del
    # carácter siguiente, así que ese `Tc` pertenece a la línea siguiente y
    # comérselo la descuadra.
    return muestra[0].inicio, muestra[-1].fin


# ---------------------------------------------------------------------------
# Planificación
# ---------------------------------------------------------------------------

def _nombre_libre(fuentes: dict[str, Fuente]) -> str:
    usados = {n.lstrip("/") for n in fuentes}
    for i in range(1, 100):
        cand = f"LPF{i}"
        if cand not in usados:
            return cand
    raise ValueError("no hay nombre de fuente libre")


def _objgen_diccionario_fuentes(pagina):
    """(num, gen) del diccionario /Font, subiendo por la jerarquía si hace falta.

    En los 11 PDFs del corpus /Font es siempre indirecto, pero un PDF cualquiera
    puede tenerlo todo directo, y entonces hay que redefinir la página entera.
    """
    res = pagina.get("/Resources")
    if res is None:
        return None
    fd = res.get("/Font")
    if fd is None:
        return None
    if fd.objgen != (0, 0):
        return fd.objgen
    if res.objgen != (0, 0):
        return res.objgen
    return pagina.obj.objgen


def _anadir_fuente_al_diccionario(dic, nombre: str, definicion: bytes) -> bytes:
    """Devuelve el diccionario /Font serializado con la fuente nueva dentro."""
    texto = dic.unparse(True)
    if not texto.rstrip().endswith(b">>"):
        raise ValueError("el diccionario de fuentes no se pudo serializar")
    cuerpo = texto.rstrip()[:-2].rstrip()
    return cuerpo + b" /" + nombre.encode("ascii") + b" " + definicion + b" >>"


def plan_editar_texto(
    datos: bytes,
    ruta_pdf: str | Path,
    num_pagina: int,
    contenido: ContenidoPagina,
    run: TextoRun,
    nuevo_texto: str,
    *,
    ajustar_espaciado: bool = False,
    permitir_fuente_nueva: bool = True,
) -> PlanTexto:
    """Calcula cómo cambiar el texto de un run. No escribe nada en disco.

    `datos` es el content stream tal cual está en el PDF: las ediciones se
    calculan sobre offsets de ESE stream.
    """
    informe = InformeTexto()
    pdf = pikepdf.open(str(ruta_pdf))
    try:
        pagina = pdf.pages[num_pagina]
        fuentes = resolver_fuentes(pagina)

        if not run.fuente_nombre or run.fuente_nombre not in fuentes:
            informe.motivo = f"no se encuentra la fuente {run.fuente_nombre!r}"
            return PlanTexto(bytes(), {}, informe)
        fuente = fuentes[run.fuente_nombre]

        if not fuente.a_unicode:
            informe.motivo = ("la fuente no tiene /ToUnicode: no se sabe qué "
                              "carácter es cada código")
            return PlanTexto(bytes(), {}, informe)
        if not fuente.incrustada and fuente.es_type0:
            informe.motivo = "fuente CID sin programa incrustado"
            return PlanTexto(bytes(), {}, informe)

        # --- qué caracteres faltan ---------------------------------------
        inverso = fuente.mapa_inverso()
        faltan = sorted({ch for ch in nuevo_texto if ch not in inverso})
        informe.glifos_que_faltan = faltan
        informe.chars_reutilizados = len(nuevo_texto) - sum(
            1 for ch in nuevo_texto if ch in faltan)

        # --- anchos de referencia ----------------------------------------
        codigos_originales: list[int] = []
        for ins in _instrucciones_de_texto(run):
            codigos_originales.extend(_trozo_texto(ins, fuente))
        informe.ancho_original = float(sum(fuente.ancho_de(c)
                                           for c in codigos_originales))

        tam = run.fuente_tam or 12.0

        # ---------------------------------------------------------------- #
        # Nivel 1: todos los códigos existen
        # ---------------------------------------------------------------- #
        if not faltan:
            texto_por_operador = [_trozo_texto(i, fuente)
                                  for i in _instrucciones_de_texto(run)]
            # La referencia es el número REAL de códigos del stream, no
            # run.texto: al alinear, el texto puede haber perdido los espacios
            # finales que pdfium no devuelve.
            #
            # No se exige un código por operador: lo normal es un único `Tj` con
            # la línea entera, y ese es justo el caso que el nivel 1a debe
            # cubrir. Se exige que ningún código sea una ligadura (un código que
            # mapea a varios caracteres), porque entonces el reparto por
            # caracteres no es reversible.
            total_codigos = sum(len(t) for t in texto_por_operador)
            sin_ligaduras = all(
                len(fuente.a_unicode.get(c, "")) == 1
                for t in texto_por_operador for c in t)
            misma_longitud = (total_codigos == len(nuevo_texto) > 0
                              and sin_ligaduras)

            # El ancho nuevo se calcula ANTES de entrar en el nivel, no después.
            # `_nivel_1b` lo necesita para calcular el `Tc` de --ajustar, y
            # estaba asignado detrás del `return`: el nivel 1b lo leía siempre a
            # cero, así que «ajustar» calculaba un `Tc` que compensaba el ancho
            # ENTERO del texto en vez de la diferencia. Se multiplicaba el ancho
            # por más de dos en lugar de conservarlo. Lo destapó el caso 11 (texto
            # escalado), que es el primero con `Tc` medible en la página.
            informe.ancho_nuevo = float(sum(
                fuente.ancho_de(fuente.codigo_de(ch) or 0) for ch in nuevo_texto))

            if misma_longitud:
                plan = _nivel_1a(datos, contenido, run, fuente,
                                 texto_por_operador, nuevo_texto, informe)
            else:
                plan = _nivel_1b(datos, contenido, run, fuente, nuevo_texto,
                                 informe, tam, ajustar_espaciado)
            if plan is None:
                # el 1a no se pudo aplicar: se cae al colapso, que siempre va
                plan = _nivel_1b(datos, contenido, run, fuente, nuevo_texto,
                                 informe, tam, ajustar_espaciado)
            informe.ok = True
            return plan

        # ---------------------------------------------------------------- #
        # Nivel 2: falta algún glifo -> fuente nueva
        # ---------------------------------------------------------------- #
        base = nombre_base_sin_subset(fuente.base_font)
        if not permitir_fuente_nueva:
            informe.motivo = f"faltan glifos y no se permite fuente nueva: {faltan}"
            return PlanTexto(bytes(), {}, informe)

        ruta_fuente = buscar_fuente_sistema(base)
        if ruta_fuente is None:
            informe.nivel = "0"
            from .sustitucion_fuente import _directorios
            informe.motivo = (
                f"faltan los glifos {faltan} y la fuente {base!r} no está "
                f"disponible. Se buscó en: "
                f"{', '.join(str(d) for d in _directorios())}. Instálala y "
                f"vuelve a intentarlo: sustituirla por otra cambiaría el "
                f"aspecto del documento")
            return PlanTexto(bytes(), {}, informe)

        fuente_nueva = construir_subconjunto(ruta_fuente, nuevo_texto)

        # La fuente del sistema puede no tener el glifo (p. ej. DejaVuSans no
        # tiene caracteres CJK). Se comprueba antes de seguir: es un rechazo,
        # no una excepción.
        sin_glifo = sorted({ch for ch in nuevo_texto
                            if ch not in fuente_nueva.char_a_gid})
        if sin_glifo:
            informe.nivel = "0"
            informe.glifos_que_faltan = sin_glifo
            informe.motivo = (
                f"la fuente del sistema {ruta_fuente.name!r} tampoco tiene "
                f"estos caracteres: {sin_glifo}. Hace falta una fuente que los "
                f"tenga, y no se sustituye por otra sin avisar")
            return PlanTexto(bytes(), {}, informe)

        informe.fuente_nueva = f"{base} ({ruta_fuente.name}, "
        informe.fuente_nueva += f"{len(fuente_nueva.ttf)} B)"
        informe.ancho_nuevo = fuente_nueva.ancho_de(nuevo_texto)

        plan = _nivel_2(datos, contenido, run, fuente_nueva, base, nuevo_texto,
                        informe, tam, pagina, pdf, fuentes, ajustar_espaciado)
        informe.ok = True
        return plan
    finally:
        pdf.close()


def escala_de_run(run: TextoRun) -> float:
    """Cuántos puntos de PÁGINA mide una unidad del espacio de texto del run.

    El operador `Tc` no se mide en puntos de página, se mide en el espacio de
    texto: la matriz del texto y el CTM lo escalan igual que escalan los glifos.
    Un run dentro de `q 2 0 0 2 0 0 cm` necesita la MITAD del `Tc` para separar
    lo mismo en la página. Sin esto, el ajuste de espaciado se queda corto (o se
    pasa) por el factor de escala.

    Es el mismo error que teníamos en `mover`/`escalar`, donde la matriz se
    insertaba sin convertirla al espacio local del objeto. Allí se destapó
    mandando una imagen a 29.000 pt de su sitio; aquí estaba latente porque
    ningún PDF del corpus tenía texto escalado.

    Se usa la matriz del principio del run. Si un run cambia de Tm a mitad (con
    `Td`, `T*`), la escala puede variar entre líneas; se documenta como límite.
    """
    m = multiplicar(run.tm_inicial, run.ctm)
    det = abs(m[0] * m[3] - m[1] * m[2])
    return det ** 0.5 if det > 1e-12 else 1.0


def _formatear_tc(valor: float) -> bytes:
    """`Tc` en formato compacto. 0 se escribe '0', no '0.0000'."""
    if valor == 0:
        return b"0"
    texto = f"{valor:.4f}".rstrip("0").rstrip(".")
    return texto.encode("ascii")


def _ajuste_ancho(informe: InformeTexto, tam: float,
                  ajustar_espaciado: bool, n_chars: int,
                  escala: float = 1.0) -> str | None:
    """Calcula el Tc para conservar el ancho, y anota el desborde.

    `delta_ancho` está en milésimas de em por el tamaño, o sea en unidades del
    espacio de TEXTO. `delta_en_puntos` es lo mismo llevado a la PÁGINA, que es
    lo que le importa al usuario (y lo que mide el test de aceptación). El `Tc`
    vuelve a ser espacio de texto: se calcula sobre la medida de texto, no sobre
    la de página.
    """
    informe.delta_ancho = informe.ancho_nuevo - informe.ancho_original
    delta_texto = informe.delta_ancho * tam / 1000.0
    informe.delta_en_puntos = delta_texto * escala
    informe.desborde = informe.delta_en_puntos > 0.5
    if ajustar_espaciado and n_chars > 0:
        tc = -delta_texto / n_chars
        informe.espaciado_aplicado = tc
        return f"{tc:.4f}".rstrip("0").rstrip(".") + " Tc "
    return None


def _nivel_1a(datos: bytes, contenido: ContenidoPagina, run: TextoRun,
              fuente: Fuente, texto_por_operador: list[list[int]],
              nuevo_texto: str, informe: InformeTexto) -> PlanTexto | None:
    """Sustitución de bytes, un carácter por operador. Estructura intacta."""
    ediciones: list[Edicion] = []
    cursor = 0
    for ins, codigos in zip(_instrucciones_de_texto(run), texto_por_operador):
        n = len(codigos)
        trozo = nuevo_texto[cursor:cursor + n]
        cursor += n
        if len(trozo) != n:
            return None
        try:
            nuevos = [fuente.codigo_de(ch) for ch in trozo]
        except Exception:
            return None
        if any(c is None for c in nuevos):
            return None
        datos_codificados = fuente.bytes_de([c for c in nuevos if c is not None])

        tok = _string_token(ins)
        if tok is None:
            return None
        forma = _forma_del_operando(ins)
        if forma == "array":
            # un TJ con kerning: se reemplaza la cadena dentro del array
            # manteniendo los números. Solo si hay exactamente una cadena.
            return None
        reemplazo = (_hexstring(datos_codificados) if forma == "hex"
                     else _escapar_literal(datos_codificados))
        ediciones.append(Edicion(tok.inicio, tok.fin, reemplazo))

    if cursor != len(nuevo_texto):
        return None
    informe.nivel = "1a"
    informe.motivo = "sustitución de bytes, estructura del stream intacta"
    return PlanTexto(aplicar_ediciones(datos, ediciones), {}, informe)


def _nivel_1b(datos: bytes, contenido: ContenidoPagina, run: TextoRun,
              fuente: Fuente, nuevo_texto: str, informe: InformeTexto,
              tam: float, ajustar_espaciado: bool) -> PlanTexto:
    """Colapsa los operadores de texto del run en uno solo."""
    inicio, fin = _rango_del_run(datos, contenido, run)
    codigos = [fuente.codigo_de(ch) for ch in nuevo_texto]
    if any(c is None for c in codigos):
        raise ValueError("nivel 1b con caracteres que no están en la fuente")
    # OJO: esto NO puede llamarse `datos`, que es el content stream.
    bytes_texto = fuente.bytes_de([c for c in codigos if c is not None])

    tc = _ajuste_ancho(informe, tam, ajustar_espaciado, len(nuevo_texto),
                       escala_de_run(run))
    tc_previo = _tc_en_efecto(contenido, fin)
    prefijo = (tc.encode("ascii") + b" ") if tc else b"0 Tc "
    cierre = b" " + _formatear_tc(tc_previo) + b" Tc"
    reemplazo = prefijo + _hexstring(bytes_texto) + b" Tj" + cierre
    informe.nivel = "1b"
    informe.motivo = "operadores de texto colapsados en uno, misma fuente"
    return PlanTexto(aplicar_ediciones(datos, [Edicion(inicio, fin, reemplazo)]),
                     {}, informe)


def _nivel_2(datos: bytes, contenido: ContenidoPagina, run: TextoRun,
             fuente_nueva, base: str, nuevo_texto: str, informe: InformeTexto,
             tam: float, pagina, pdf, fuentes: dict[str, Fuente],
             ajustar_espaciado: bool) -> PlanTexto:
    """Incrusta un subconjunto nuevo y cambia el Tf de este run."""
    dic_ref = _objgen_diccionario_fuentes(pagina)
    if dic_ref is None:
        raise ValueError("no se encontró el diccionario de fuentes")

    siguiente = int(pdf.trailer.get("/Size", 0))
    num_ff = siguiente
    num_tu = siguiente + 1

    nombre = _nombre_libre(fuentes)
    definicion = objetos_fuente(fuente_nueva, base, f"{num_ff} 0 R",
                                f"{num_tu} 0 R")

    dic = pagina.get("/Resources").get("/Font")
    if dic.objgen == (0, 0):
        dic = pagina.get("/Resources")
    nuevo_dic = _anadir_fuente_al_diccionario(dic, nombre, definicion)

    from .guardar import cuerpo_stream
    objetos = {
        (num_ff, 0): cuerpo_stream(fuente_nueva.ttf),
        (num_tu, 0): cuerpo_stream(cmap_tounicode(fuente_nueva)),
        dic_ref: nuevo_dic,
    }

    inicio, fin = _rango_del_run(datos, contenido, run)
    bytes_texto = fuente_nueva.codificar(nuevo_texto)
    tc = _ajuste_ancho(informe, tam, ajustar_espaciado, len(nuevo_texto),
                       escala_de_run(run))
    tam_txt = f"{tam:g}"
    tc_previo = _tc_en_efecto(contenido, fin)
    prefijo = f"/{nombre} {tam_txt} Tf ".encode("ascii")
    prefijo += (tc.encode("ascii") + b" ") if tc else b"0 Tc "
    cierre = b" " + _formatear_tc(tc_previo) + b" Tc"
    reemplazo = prefijo + _hexstring(bytes_texto) + b" Tj" + cierre

    informe.nivel = "2"
    informe.motivo = (f"subconjunto nuevo incrustado como /{nombre} desde "
                      f"{Path(fuente_nueva.nombre_origen).name}")
    return PlanTexto(aplicar_ediciones(datos, [Edicion(inicio, fin, reemplazo)]),
                     objetos, informe)


