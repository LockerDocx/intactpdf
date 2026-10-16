"""
Escritura incremental de PDF.

Por qué está escrito a mano: ni qpdf ni pikepdf saben escribir incrementalmente
(qpdf 12.2.0 no tiene la opción, y `Pdf.save()` de pikepdf no la expone). Ambos
reescriben el fichero entero. Para un proyecto que se define por NO reconstruir
el documento, eso es inaceptable: reescribir es exactamente lo que hace
LibreOffice Draw y lo que la validación empírica demostró que rompe CMYK,
formularios, dimensiones de página y fuentes.

Qué es una actualización incremental (especificación PDF, 7.5.6): en vez de
reescribir, se AÑADE al final del fichero la nueva versión de los objetos que
cambian, más una sección de referencias cruzadas nueva que apunta a la anterior
con /Prev. El fichero original queda intacto byte a byte.

Consecuencia verificable, y es la base del test de aceptación: el fichero de
salida EMPIEZA POR los bytes del original. Si eso se cumple, es imposible que se
haya modificado cualquier otra cosa.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf


class ErrorGuardado(Exception):
    pass


@dataclass
class Cambio:
    """Nueva definición completa de un objeto existente."""
    num: int
    gen: int
    cuerpo: bytes              # "N G obj ... endobj" ya montado
    offset: int = 0


@dataclass
class InformeGuardado:
    incremental: bool
    bytes_original: int
    bytes_salida: int
    bytes_anadidos: int
    objetos_redefinidos: list[tuple[int, int]] = field(default_factory=list)
    prefijo_intacto: bool = False

    @property
    def empieza_por_el_original(self) -> bool:
        return self.prefijo_intacto


def offset_ultimo_xref(datos: bytes) -> int:
    """Offset de la sección de referencias cruzadas más reciente.

    Es lo que apunta `startxref` al final del fichero, y es por tanto el /Prev
    de la actualización incremental.
    """
    pos = datos.rfind(b"startxref")
    if pos < 0:
        raise ErrorGuardado("el PDF no tiene startxref")
    m = re.search(rb"startxref\s+(\d+)", datos[pos:])
    if not m:
        raise ErrorGuardado("no se pudo leer el offset de startxref")
    return int(m.group(1))


def cuerpo_stream(datos: bytes, comprimir: bool = True) -> bytes:
    """Cuerpo completo de un objeto stream: el diccionario, `stream` y los
    datos. Es lo que se le pasa a `escribir_incremental` como valor."""
    return _montar_stream(datos, comprimir)


def cuerpo_dict(texto: bytes) -> bytes:
    """Cuerpo de un objeto que es un diccionario normal."""
    return texto


def _montar_stream(datos: bytes, comprimir: bool) -> bytes:
    """Cuerpo de un objeto stream, sin el envoltorio obj/endobj."""
    if comprimir:
        payload = zlib.compress(datos, 9)
        extra = b" /Filter /FlateDecode"
    else:
        payload = datos
        extra = b""
    cab = (b"<< /Length " + str(len(payload)).encode()
           + extra + b" >>\nstream\n")
    return cab + payload + b"\nendstream"


def _formatear_xref(entradas: list[tuple[int, int, int]]) -> bytes:
    """Sección xref clásica.

    Cada entrada ocupa exactamente 20 bytes: 10 dígitos de offset, espacio,
    5 de generación, espacio, tipo, espacio, salto de línea.
    """
    if not entradas:
        return b"xref\n0 0\n"
    entradas = sorted(entradas, key=lambda e: e[0])

    # agrupar en subsecciones contiguas
    partes: list[bytes] = [b"xref\n"]
    grupos: list[list[tuple[int, int, int]]] = []
    actual = [entradas[0]]
    for e in entradas[1:]:
        if e[0] == actual[-1][0] + 1:
            actual.append(e)
        else:
            grupos.append(actual)
            actual = [e]
    grupos.append(actual)

    for g in grupos:
        partes.append(f"{g[0][0]} {len(g)}\n".encode("ascii"))
        for num, gen, off in g:
            if off < 0:
                partes.append(f"{num:010d} {gen:05d} f \n".encode("ascii"))
            else:
                partes.append(f"{off:010d} {gen:05d} n \n".encode("ascii"))
    return b"".join(partes)


def _formatear_id(valor) -> bytes:
    if valor is None:
        return b"[]"
    try:
        partes = []
        for x in valor:
            b = bytes(x)
            partes.append(b"<" + b.hex().encode("ascii") + b">")
        return b"[ " + b" ".join(partes) + b" ]"
    except Exception:
        return b"[]"


def escribir_incremental(
    ruta_original: str | Path,
    ruta_salida: str | Path,
    objetos: dict[tuple[int, int], bytes],
) -> InformeGuardado:
    """Añade objetos al final del PDF como actualización incremental.

    `objetos` mapea (num, gen) -> CUERPO COMPLETO del objeto, es decir lo que va
    entre «N G obj» y «endobj». Para un stream se construye con
    `cuerpo_stream(datos)`; para un diccionario, con `cuerpo_dict(texto)`.

    Un número que ya existía es una redefinición; uno mayor o igual que /Size es
    un objeto nuevo. Mecánicamente es lo mismo: se escribe al final y la xref
    nueva apunta ahí.

    El fichero original NO se modifica; se escribe uno nuevo compuesto por el
    original íntegro más el apéndice.
    """
    ruta_original = Path(ruta_original)
    original = ruta_original.read_bytes()

    with pikepdf.open(str(ruta_original)) as pdf:
        num_prev = offset_ultimo_xref(original)
        raiz = pdf.trailer.get("/Root")
        if raiz is None:
            raise ErrorGuardado("el PDF no tiene /Root")
        num_raiz, gen_raiz = raiz.objgen
        size_original = int(pdf.trailer.get("/Size", 0))
        id_original = pdf.trailer.get("/ID")

        salida = bytearray(original)
        lista = list(objetos.items())
        if not lista:
            Path(ruta_salida).write_bytes(original)
            return InformeGuardado(
                incremental=True, bytes_original=len(original),
                bytes_salida=len(original), bytes_anadidos=0,
                objetos_redefinidos=[], prefijo_intacto=True)

        entradas: list[tuple[int, int, int]] = []
        redefinidos: list[tuple[int, int]] = []
        for (num, gen), cuerpo_objeto in lista:
            offset = len(salida)
            cuerpo = (f"{num} {gen} obj\n".encode("ascii")
                      + cuerpo_objeto + b"\nendobj\n")
            salida += cuerpo
            entradas.append((num, gen, offset))
            redefinidos.append((num, gen))

        offset_xref = len(salida)
        salida += _formatear_xref(entradas)

        num_max = max([n for n, _ in redefinidos] + [size_original - 1])
        trailer = (
            b"trailer\n<< /Size " + str(num_max + 1).encode()
            + b" /Root " + f"{num_raiz} {gen_raiz} R".encode()
            + b" /Prev " + str(num_prev).encode()
            + b" /ID " + _formatear_id(id_original)
            + b" >>\nstartxref\n" + str(offset_xref).encode()
            + b"\n%%EOF\n")
        salida += trailer

    Path(ruta_salida).write_bytes(bytes(salida))
    prefijo = bytes(salida[:len(original)]) == original
    return InformeGuardado(
        incremental=True,
        bytes_original=len(original),
        bytes_salida=len(salida),
        bytes_anadidos=len(salida) - len(original),
        objetos_redefinidos=redefinidos,
        prefijo_intacto=prefijo,
    )


# ---------------------------------------------------------------------------
# Puente desde el editor
# ---------------------------------------------------------------------------

def num_objeto_stream_de_pagina(pagina) -> list[tuple[int, int]]:
    """(num, gen) de cada stream de contenido de la página, en orden."""
    c = pagina.get("/Contents")
    if c is None:
        return []
    if isinstance(c, pikepdf.Array):
        return [s.objgen for s in c]
    return [c.objgen]


def guardar_pagina_editada(
    ruta_original: str | Path,
    ruta_salida: str | Path,
    num_pagina: int,
    contenidos: list[bytes],
    objetos_extra: dict[tuple[int, int], bytes] | None = None,
) -> InformeGuardado:
    """Guarda una página con sus streams de contenido reemplazados.

    Se redefinen los MISMOS objetos que ya existían, así que el objeto de página,
    los recursos, las fuentes y todo lo demás no se tocan en absoluto.
    """
    with pikepdf.open(str(ruta_original)) as pdf:
        refs = num_objeto_stream_de_pagina(pdf.pages[num_pagina])
    if len(refs) != len(contenidos):
        raise ErrorGuardado(
            f"la página tiene {len(refs)} streams de contenido y se han pasado "
            f"{len(contenidos)} contenidos")
    objetos = {ref: cuerpo_stream(datos) for ref, datos in zip(refs, contenidos)}
    if objetos_extra:
        objetos.update(objetos_extra)
    return escribir_incremental(ruta_original, ruta_salida, objetos)
