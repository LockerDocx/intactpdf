"""
Alinea los runs de texto extraídos del content stream con las posiciones reales
que da pdfium.

Por qué hace falta: para editar texto hay que saber dónde está cada carácter.
Reconstruir eso desde el stream exige métricas de fuente, CMaps y kerning.
pdfium ya lo sabe, así que se lo pedimos.

Cómo se alinea: por CAJA, no por orden. Un alineador secuencial (run 1 toma los
primeros N caracteres, run 2 los siguientes...) se rompe en cuanto pdfium y el
parser discrepan, y entonces asigna caracteres equivocados en silencio. En su
lugar cada carácter se asigna al run cuya caja aproximada más lo cubre.

Tres verificaciones, porque alinear mal es peor que no alinear:
  1. un carácter que cae en dos runs se descarta (ambigüedad)
  2. un carácter que no cae en ninguno se descarta
  3. el texto resultante debe parecerse al que descodificó el parser

Lo que no supera las verificaciones se marca `alineado = False` y conserva su
caja aproximada, de modo que la UI pueda permitir mover y borrar pero no editar
carácter a carácter. Nunca se inventa una posición.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometria import Caja
from .objetos import ContenidoPagina, TextoRun

# pdfium emite estos caracteres entre bloques de texto aunque el PDF no los
# contenga. No son texto real y hay que quitarlos antes de alinear.
_SINTETICOS = {"\r", "\n"}

_UMBRAL_SIMILITUD = 0.6


@dataclass(slots=True)
class CharReal:
    texto: str
    caja: tuple[float, float, float, float]   # x0, y0, x1, y1 en espacio PDF (y arriba)
    indice: int = -1


def chars_de_pagina(textpage) -> list[CharReal]:
    """Lista ordenada de caracteres con su caja, en espacio de usuario PDF.

    El texto se pide de una sola vez (`get_text_range(0, n)`) en lugar de
    carácter a carácter: son 0,1 ms frente a 17,7 ms en una página de 3000
    caracteres, 177 veces menos.
    """
    n = textpage.count_chars()
    if n == 0:
        return []
    try:
        todo = textpage.get_text_range(0, n)
    except Exception:
        todo = ""

    out: list[CharReal] = []
    for i in range(n):
        try:
            caja = tuple(textpage.get_charbox(i))
        except Exception:
            continue
        ch = todo[i] if i < len(todo) else ""
        out.append(CharReal(texto=ch, caja=caja, indice=i))  # type: ignore[arg-type]
    return out


def filtrar_sinteticos(chars: list[CharReal]) -> tuple[list[CharReal], int]:
    reales = [c for c in chars if c.texto not in _SINTETICOS]
    return reales, len(chars) - len(reales)


def _similitud(a: str, b: str) -> float:
    """Proporción de caracteres coincidentes posición a posición, con castigo
    por diferencia de longitud. No es distancia de edición, y no hace falta:
    solo queremos detectar "esto no es el mismo texto"."""
    if not a and not b:
        return 1.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    iguales = sum(1 for i in range(n) if a[i] == b[i])
    penalizacion = abs(len(a) - len(b))
    return max(0.0, (iguales - penalizacion) / max(len(a), len(b)))


def _tolerancia_conteo(n: int) -> int:
    """pdfium omite espacios al final de línea y algún PDF suelta algún glifo."""
    return max(4, int(n * 0.05))


def alinear(contenido: ContenidoPagina, chars: list[CharReal]) -> dict:
    """Asigna a cada run de texto sus caracteres reales.

    Camino principal: secuencial, en el orden del stream. Es exacto cuando el
    parser y pdfium cuentan lo mismo, que es lo normal. Cada run se verifica
    contra el texto que descodificó el parser; si no coincide, se rechaza en vez
    de asignar caracteres equivocados en silencio.

    Camino de reserva: si el conteo global no cuadra, se intenta por caja.
    """
    runs = [o for o in contenido.objetos if isinstance(o, TextoRun)]
    reales, n_quitados = filtrar_sinteticos(chars)

    informe: dict = {
        "runs": len(runs),
        "chars_pdfium_brutos": len(chars),
        "chars_sinteticos_quitados": n_quitados,
        "chars_reales": len(reales),
        "chars_que_cuenta_el_parser": sum(r.n_codigos for r in runs),
        "runs_alineados": 0,
        "runs_sin_alinear": 0,
        "chars_ambiguos": 0,
        "chars_huerfanos": 0,
        "metodo": "ninguno",
        "cuadre_global": sum(r.n_codigos for r in runs) == len(reales),
    }

    for r in runs:
        r.posiciones_chars = []
        r.alineado = False
        r.motivo_sin_alinear = ""

    if not runs or not reales:
        informe["runs_sin_alinear"] = len(runs)
        informe["chars_huerfanos"] = len(reales)
        return informe

    # El secuencial se prueba SIEMPRE primero: es exacto y no depende de las
    # cajas aproximadas. Solo se recurre al de caja si alinea menos de la mitad.
    _alinear_secuencial(runs, reales, informe)
    informe["metodo"] = "secuencial"
    if informe["runs_alineados"] * 2 < len(runs):
        for r in runs:
            r.posiciones_chars = []
            r.alineado = False
            r.motivo_sin_alinear = ""
        informe["runs_alineados"] = 0
        informe["runs_sin_alinear"] = 0
        _alinear_por_caja(runs, reales, informe)
        informe["metodo"] = "caja (el secuencial alineaba menos de la mitad)"
    return informe


def _es_el_mismo_texto(a: str, b: str) -> bool:
    """¿Son el mismo texto, admitiendo lo que pdfium hace con los espacios?

    pdfium omite sistemáticamente los espacios al final de línea. Eso no es una
    discrepancia real, es una convención suya, y hay que admitirla de forma
    explícita: si lo que falta es espacio en blanco al final, es el mismo texto.
    Lo que NO se admite es cualquier otra diferencia, porque entonces la
    alineación voraz empezaría a repartir caracteres equivocados.
    """
    if a == b:
        return True
    largo = min(len(a), len(b))
    if a[:largo] != b[:largo]:
        return False
    resto = (a[largo:] if len(a) > len(b) else b[largo:])
    return resto.strip() == ""


def _emparejar_lineal(a: str, b: str) -> tuple[list[int | None], int]:
    """Empareja dos textos con un escaneo lineal de dos punteros.

    Las dos únicas diferencias que introduce pdfium son espacios: quita los del
    final de línea y colapsa los consecutivos. Un difflib general es O(n*m) y
    costaba 402 ms en una página de 3000 caracteres, cuando el caso real se
    resuelve avanzando dos punteros. Lo que no casa se marca como hueco.

    Devuelve (mapa de a->indice en b o None, número de aciertos).
    """
    pares: list[int | None] = [None] * len(a)
    i = j = 0
    aciertos = 0
    la, lb = len(a), len(b)

    while i < la and j < lb:
        if a[i] == b[j]:
            pares[i] = j
            aciertos += 1
            i += 1
            j += 1
        elif a[i].isspace():
            # pdfium no emitió este espacio de a
            i += 1
        elif b[j].isspace():
            # pdfium emitió un espacio que a no tiene
            j += 1
        else:
            # diferencia no explicada por espacios: se declara hueco
            i += 1
    return pares, aciertos


def _aceptar_run(r: TextoRun, trozo: list[CharReal], informe: dict) -> bool:
    """Verifica y, si pasa, asigna. Devuelve True si el run quedó alineado."""
    texto_pdfium = "".join(c.texto for c in trozo)
    if not _es_el_mismo_texto(r.texto, texto_pdfium):
        sim = _similitud(r.texto, texto_pdfium)
        r.motivo_sin_alinear = (
            f"el texto del parser y el de pdfium difieren (similitud {sim:.2f})")
        return False
    if abs(len(trozo) - r.n_codigos) > _tolerancia_conteo(r.n_codigos):
        r.motivo_sin_alinear = (
            f"pdfium da {len(trozo)} caracteres donde el parser cuenta "
            f"{r.n_codigos}")
        return False

    r.texto = texto_pdfium or r.texto
    r.posiciones_chars = [c.caja for c in trozo]
    r.caja = Caja(
        min(c.caja[0] for c in trozo),
        min(c.caja[1] for c in trozo),
        max(c.caja[2] for c in trozo),
        max(c.caja[3] for c in trozo),
    )
    r.alineado = True
    informe["runs_alineados"] += 1
    return True


def _alinear_secuencial(runs: list[TextoRun], reales: list[CharReal],
                        informe: dict) -> None:
    """Alinea por secuencia sobre la página entera.

    Se concatena el texto de todos los runs y se alinea con el texto de pdfium
    usando emparejamiento de secuencias. Así se toleran las dos cosas que pdfium
    hace por su cuenta —soltar espacios al final de línea y colapsar espacios
    consecutivos— sin repartir caracteres equivocados: lo que no empareja se
    declara como hueco y ese carácter queda sin posición.

    Un run se acepta si al menos el 80 % de sus caracteres tienen posición.
    """
    texto_parser = "".join(r.texto for r in runs)
    texto_pdfium = "".join(c.texto for c in reales)

    pares, aciertos = _emparejar_lineal(texto_parser, texto_pdfium)

    # Si el emparejamiento lineal no reconoce la mayor parte del texto, se
    # recurre al difflib, que es lento pero robusto ante diferencias reales.
    if aciertos < 0.5 * max(len(texto_parser), 1):
        import difflib
        pares = [None] * len(texto_parser)
        sm = difflib.SequenceMatcher(a=texto_parser, b=texto_pdfium,
                                     autojunk=False)
        for ai, bi, n in sm.get_matching_blocks():
            for k in range(n):
                if ai + k < len(pares) and bi + k < len(reales):
                    pares[ai + k] = bi + k

    cursor = 0
    for r in runs:
        n = max(len(r.texto), r.n_codigos)
        trozo_pares = pares[cursor:cursor + n]
        cursor += n

        con_pos = [(i, j) for i, j in enumerate(trozo_pares) if j is not None]
        if not con_pos:
            r.motivo_sin_alinear = "ningún carácter suyo empareja con pdfium"
            informe["runs_sin_alinear"] += 1
            continue

        cobertura = len(con_pos) / n
        if cobertura < 0.8:
            r.motivo_sin_alinear = (
                f"solo el {cobertura:.0%} de sus caracteres tienen posición")
            informe["runs_sin_alinear"] += 1
            continue

        cajas = [reales[j].caja for _, j in con_pos]
        r.posiciones_chars = cajas
        r.texto = "".join(reales[j].texto for _, j in con_pos)
        r.indices_sin_posicion = [i for i, j in enumerate(trozo_pares) if j is None]
        r.caja = Caja(
            min(b[0] for b in cajas), min(b[1] for b in cajas),
            max(b[2] for b in cajas), max(b[3] for b in cajas),
        )
        r.alineado = True
        informe["runs_alineados"] += 1
        informe["chars_sin_posicion"] = informe.get("chars_sin_posicion", 0) + \
            len(r.indices_sin_posicion)


def _alinear_por_caja(runs: list[TextoRun], reales: list[CharReal],
                      informe: dict) -> None:
    votos: list[list[int]] = [[] for _ in runs]
    for ci, c in enumerate(reales):
        cx = (c.caja[0] + c.caja[2]) / 2
        cy = (c.caja[1] + c.caja[3]) / 2
        for ri, r in enumerate(runs):
            if r.caja is not None and r.caja.contiene(cx, cy, tolerancia=3.0):
                votos[ri].append(ci)

    duenos: dict[int, int] = {}
    for ri, lista in enumerate(votos):
        for ci in lista:
            duenos[ci] = -1 if ci in duenos else ri
    ambiguos = {ci for ci, ri in duenos.items() if ri == -1}
    informe["chars_ambiguos"] = len(ambiguos)
    informe["chars_huerfanos"] = len(reales) - len(duenos)

    for ri, r in enumerate(runs):
        indices = sorted(ci for ci in votos[ri] if ci not in ambiguos)
        if not indices:
            r.motivo_sin_alinear = "ningún carácter de pdfium cae dentro de su caja"
            informe["runs_sin_alinear"] += 1
            continue
        if not _aceptar_run(r, [reales[i] for i in indices], informe):
            informe["runs_sin_alinear"] += 1


def alinear_pagina(pdf_path: str, num_pagina: int, contenido: ContenidoPagina) -> dict:
    """Conveniencia: abre con pdfium, alinea y cierra."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_path)
    try:
        tp = doc[num_pagina].get_textpage()
        chars = chars_de_pagina(tp)
    finally:
        doc.close()
    return alinear(contenido, chars)
