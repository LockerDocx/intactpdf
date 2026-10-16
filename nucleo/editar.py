"""
Edición del content stream: borrar y mover objetos.

Modelo de edición: no se reescribe el stream. Se calculan sustituciones sobre
rangos de bytes concretos y se aplican de atrás hacia delante, para que los
desplazamientos de una edición no invaliden las posiciones de las siguientes.

Por qué importa: cada byte que no se toca es un byte que no puede cambiar de
significado. Un editor que reconstruye el stream entero es exactamente el
problema que este proyecto existe para resolver.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .geometria import Matriz, invertir, multiplicar
from .objetos import ContenidoPagina, Imagen, Objeto, TextoRun, Vector

# Operadores que fijan estado gráfico. Si preceden a un objeto y no pertenecen a
# otro, son la preparación de ESE objeto y se van con él al borrarlo.
OPS_ESTADO = {
    "rg", "g", "k", "RG", "G", "K", "sc", "scn", "SC", "SCN",
    "w", "J", "j", "M", "d", "ri", "i", "gs", "CS", "cs",
}


@dataclass(slots=True)
class Edicion:
    inicio: int
    fin: int
    reemplazo: bytes


def _cm(m: Matriz) -> bytes:
    """La instrucción `q ... cm` que envuelve un objeto."""
    n = " ".join(_formatear_numero(v) for v in m)
    return f"q {n} cm\n".encode("latin-1")


def _formatear_numero(v: float) -> str:
    """Números PDF compactos: 3.0 -> 3, 3.5 -> 3.5. Menos bytes, menos ruido."""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.6f}".rstrip("0").rstrip(".")


Matriz_IDENTIDAD = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def matriz_en_espacio_local(objeto: Objeto, t: Matriz) -> Matriz:
    """Reexpresa una transformación de PÁGINA en el espacio local del objeto.

    El `cm` que se inserta delante del objeto se aplica en el espacio en el que
    está escrito el objeto, no en el de la página. Y ese espacio casi nunca es
    el de la página: una imagen se pinta siempre en un cuadrado unidad y su
    tamaño y posición los pone el CTM que la precede (en el corpus:
    `320 0 0 200 72 580 cm`). Insertar la matriz de página tal cual multiplica
    los desplazamientos por esa escala.

    Está medido y era un bug de verdad: escalar al 0,6 esa imagen la mandaba a
    x=29768, fuera de la página para siempre. Lo destapó el CLI al reabrir el
    fichero; los tests no lo veían porque aceptaban «el objeto se ha ido» como
    resultado válido.

    Lo que hay que insertar es la conjugada por el CTM:  L = C · T · C⁻¹
    (con la convención de `multiplicar`, que aplica el primer argumento antes).
    Comprobación con el caso real: C manda el cuadrado unidad a la página, así
    que el centro (232, 680) está en el punto local (0,5, 0,5); la conjugada
    resulta (0,6, 0, 0, 0,6, 0,2, 0,2), que es exactamente «escala 0,6 alrededor
    de (0,5, 0,5)», y devuelve la esquina a (136, 620), donde tiene que estar.
    """
    c = getattr(objeto, "ctm", None) or Matriz_IDENTIDAD
    inv = invertir(c)
    if inv is None:
        # CTM degenerada (objeto de área cero): no hay espacio local válido.
        # Se devuelve la matriz de página sin conjugar, que es lo mejor que se
        # puede hacer, y el objeto no se verá.
        return t
    return multiplicar(multiplicar(c, t), inv)


def _preludio(contenido: ContenidoPagina, objeto: Objeto) -> int | None:
    """Offset donde empieza la preparación del objeto.

    Al borrar un vector hay que llevarse también los operadores que lo preparan
    (color, grosor...). Dejarlos atrás cambiaría el aspecto del objeto
    siguiente, que heredaría un estado que no era suyo.

    Se camina hacia atrás desde el primer operador del objeto recogiendo
    operadores de estado consecutivos, y se para en cuanto aparece cualquier
    otra cosa: un `q`, un `Q`, o un operador que pertenece a otro objeto.
    """
    if not objeto.instrucciones:
        return None
    primero = objeto.instrucciones[0].inicio
    if primero < 0:
        return None

    # offset de fin del objeto anterior del mismo stream
    limite = 0
    for otro in contenido.objetos:
        if otro is objeto or not otro.instrucciones:
            continue
        ultimo = otro.instrucciones[-1].fin
        if 0 <= ultimo <= primero and ultimo > limite:
            limite = ultimo

    candidatos = [i for i in contenido.instrucciones
                  if i.inicio >= limite and i.fin <= primero]
    inicio = primero
    for ins in reversed(candidatos):
        if ins.op in OPS_ESTADO:
            inicio = ins.inicio
        else:
            break
    return inicio if inicio < primero else None


def edicion_borrar(contenido: ContenidoPagina, objeto: Objeto,
                   incluir_preludio: bool = True) -> Edicion:
    """Sustituye el objeto por espacios en blanco: misma longitud, sin objeto.

    Se rellena con espacios en vez de borrar los bytes para que las longitudes
    del stream no bailen y el diff sea mínimo.
    """
    if not objeto.instrucciones:
        raise ValueError("el objeto no tiene instrucciones que borrar")
    inicio = objeto.instrucciones[0].inicio
    fin = objeto.instrucciones[-1].fin
    if incluir_preludio:
        pre = _preludio(contenido, objeto)
        if pre is not None:
            inicio = pre
    if inicio < 0 or fin <= inicio:
        raise ValueError("rango inválido para borrar")
    return Edicion(inicio, fin, b" " * (fin - inicio))


def edicion_mover(contenido: ContenidoPagina, objeto: Objeto,
                  dx: float, dy: float) -> list[Edicion]:
    """Envuelve el objeto en `q <matriz> cm ... Q`.

    Se envuelve en vez de transformar los puntos del trazado por dos razones:
    funciona igual para vectores, imágenes y texto, y no toca ni un byte del
    interior del objeto. La traducción se compone DELANTE del CTM existente.
    """
    if not objeto.instrucciones:
        raise ValueError("el objeto no tiene instrucciones que mover")
    inicio = objeto.instrucciones[0].inicio
    fin = objeto.instrucciones[-1].fin
    if inicio < 0 or fin <= inicio:
        raise ValueError("rango inválido para mover")

    t = (1.0, 0.0, 0.0, 1.0, float(dx), float(dy))
    m = matriz_en_espacio_local(objeto, t)
    return [
        Edicion(inicio, inicio, _cm(m)),
        Edicion(fin, fin, b"\nQ\n"),
    ]


def edicion_escalar(contenido: ContenidoPagina, objeto: Objeto,
                    escala_x: float, escala_y: float,
                    centro: tuple[float, float]) -> list[Edicion]:
    """Escala el objeto alrededor de un punto, envolviéndolo en q..cm..Q."""
    if not objeto.instrucciones:
        raise ValueError("el objeto no tiene instrucciones que escalar")
    inicio = objeto.instrucciones[0].inicio
    fin = objeto.instrucciones[-1].fin
    cx, cy = centro
    # trasladar al centro, escalar, deshacer la traslación, todo en la página
    t = multiplicar(
        multiplicar((1.0, 0.0, 0.0, 1.0, -cx, -cy),
                    (float(escala_x), 0.0, 0.0, float(escala_y), 0.0, 0.0)),
        (1.0, 0.0, 0.0, 1.0, cx, cy))
    m = matriz_en_espacio_local(objeto, t)
    return [
        Edicion(inicio, inicio, _cm(m)),
        Edicion(fin, fin, b"\nQ\n"),
    ]


def aplicar_ediciones(datos: bytes, ediciones: list[Edicion]) -> bytes:
    """Aplica las sustituciones de atrás hacia delante.

    El orden importa: si se aplicara de delante hacia atrás, cada edición
    desplazaría los offsets de todas las siguientes y se escribiría en el sitio
    equivocado. Ordenar por offset descendente evita el problema sin necesidad
    de recalcular nada.
    """
    out = datos
    for ed in sorted(ediciones, key=lambda e: e.inicio, reverse=True):
        if ed.inicio < 0 or ed.fin > len(out) or ed.inicio > ed.fin:
            raise ValueError(
                f"edición fuera de rango: [{ed.inicio}, {ed.fin}) "
                f"sobre {len(out)} bytes")
        out = out[:ed.inicio] + ed.reemplazo + out[ed.fin:]
    return out


def borrar_objeto(datos: bytes, contenido: ContenidoPagina, objeto: Objeto,
                  incluir_preludio: bool = True) -> bytes:
    return aplicar_ediciones(datos, [edicion_borrar(contenido, objeto,
                                                    incluir_preludio)])


def mover_objeto(datos: bytes, contenido: ContenidoPagina, objeto: Objeto,
                 dx: float, dy: float) -> bytes:
    return aplicar_ediciones(datos, edicion_mover(contenido, objeto, dx, dy))


def escalar_objeto(datos: bytes, contenido: ContenidoPagina, objeto: Objeto,
                   escala_x: float, escala_y: float,
                   centro: tuple[float, float]) -> bytes:
    return aplicar_ediciones(
        datos, edicion_escalar(contenido, objeto, escala_x, escala_y, centro))


def caja_tras_mover(objeto: Objeto, dx: float, dy: float):
    from .geometria import Caja
    if objeto.caja is None:
        return None
    return Caja(objeto.caja.x0 + dx, objeto.caja.y0 + dy,
                objeto.caja.x1 + dx, objeto.caja.y1 + dy)


def caja_tras_escalar(objeto: Objeto, escala_x: float, escala_y: float,
                      centro: tuple[float, float]):
    from .geometria import Caja
    if objeto.caja is None:
        return None
    cx, cy = centro
    return Caja(
        cx + (objeto.caja.x0 - cx) * escala_x,
        cy + (objeto.caja.y0 - cy) * escala_y,
        cx + (objeto.caja.x1 - cx) * escala_x,
        cy + (objeto.caja.y1 - cy) * escala_y,
    )
