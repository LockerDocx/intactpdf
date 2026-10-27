"""
Extracción de objetos seleccionables desde el content stream de una página.

Recorre las instrucciones interpretando el estado gráfico (CTM, pila q/Q,
recortes, fuentes, colores) y agrupa los operadores en objetos con sentido para
un usuario:

  - TextoRun : un bloque BT..ET que pinta texto
  - Imagen   : un `Do` sobre un XObject de tipo imagen
  - Vector   : una secuencia de construcción de trazado + su operador de pintado
  - Sombreado: un `sh`

Este módulo es el corazón de la fase F1: sin él no hay selección, y sin
selección no hay editor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .geometria import (IDENTIDAD, Caja, aplicar, es_degenerada, multiplicar)
from .parser import (OPS_CONSTRUCCION, OPS_PINTADO, OPS_TEXTO_MOSTRAR,
                     Instruccion, parsear)

# ---------------------------------------------------------------------------
# Estado gráfico
# ---------------------------------------------------------------------------


@dataclass
class EstadoGrafico:
    ctm: tuple[float, ...] = IDENTIDAD
    color_relleno: tuple[float, ...] = (0.0,)
    color_trazo: tuple[float, ...] = (0.0,)
    ancho_linea: float = 1.0
    limite_inglete: float = 10.0     # operador M, por omisión 10
    union: int = 0                   # operador j: 0 inglete, 1 redondo, 2 bisel
    fuente_nombre: str | None = None
    fuente_tam: float = 0.0
    espacio_char: float = 0.0
    espacio_palabra: float = 0.0
    escala_h: float = 100.0
    leading: float = 0.0
    subida: float = 0.0
    modo_texto: int = 0
    tm: tuple[float, ...] = IDENTIDAD
    tlm: tuple[float, ...] = IDENTIDAD

    def copia(self) -> "EstadoGrafico":
        return EstadoGrafico(
            self.ctm, self.color_relleno, self.color_trazo, self.ancho_linea,
            self.limite_inglete, self.union, self.fuente_nombre, self.fuente_tam, self.espacio_char,
            self.espacio_palabra, self.escala_h, self.leading, self.subida,
            self.modo_texto, self.tm, self.tlm)


# ---------------------------------------------------------------------------
# Objetos
# ---------------------------------------------------------------------------


@dataclass
class TextoRun:
    tipo: str = "texto"
    instrucciones: list[Instruccion] = field(default_factory=list)
    texto: str = ""
    n_codigos: int = 0
    texto_descodificable: bool = True
    alineado: bool = False
    motivo_sin_alinear: str = ""
    indices_sin_posicion: list[int] = field(default_factory=list)
    caja: Caja | None = None
    ctm: tuple[float, ...] = IDENTIDAD
    tm_inicial: tuple[float, ...] = IDENTIDAD
    trm_primer_texto: tuple[float, ...] | None = None
    fuente_nombre: str | None = None
    fuente_base: str = ""
    fuente_subconjuntada: bool = False
    fuente_tam: float = 0.0
    modo_texto: int = 0
    color: tuple[float, ...] = (0.0,)
    recortado_por: list[Any] = field(default_factory=list)
    # lo rellena el alineador con pdfium, si hay suerte
    posiciones_chars: list[tuple[float, float, float, float]] = field(default_factory=list)

    @property
    def n_operadores_texto(self) -> int:
        return sum(1 for i in self.instrucciones if i.op in OPS_TEXTO_MOSTRAR)

    @property
    def es_visible(self) -> bool:
        return self.modo_texto != 3

    @property
    def razones_no_editable(self) -> list[str]:
        """Motivos por los que cambiar los CARACTERES no es seguro.

        Solo lo que bloquea de verdad. Que la fuente esté subconjuntada ya no
        está aquí: desde la fase F4 eso se resuelve incrustando un subconjunto
        nuevo, y ponerlo como bloqueo sería mentir sobre lo que el editor puede
        hacer. Lo que sí bloquea es no poder traducir carácter a código.
        """
        r = []
        if not self.texto_descodificable or not self.fuente_nombre:
            r.append("sin CMap ToUnicode: no se puede saber qué carácter es "
                     "cada glifo")
        if self.modo_texto == 3:
            r.append("texto invisible (modo de renderizado 3): se editaría a "
                     "ciegas")
        if self.modo_texto in (1, 2):
            r.append(f"texto con contorno (modo {self.modo_texto}): el cambio "
                     "afectaría al trazo, no al relleno")
        return r

    @property
    def avisos(self) -> list[str]:
        """Cosas que conviene saber pero no impiden la operación."""
        r = []
        if self.fuente_subconjuntada:
            r.append(f"fuente subconjuntada ({self.fuente_base}): si escribes "
                     "un carácter que no está, se incrustará un subconjunto "
                     "nuevo desde la fuente del sistema")
        if self.recortado_por:
            r.append("recortado por un clip path")
        if not self.alineado:
            r.append("sin posiciones exactas de carácter: se puede editar y "
                     "mover igualmente, pero la caja es aproximada")
        return r


@dataclass
class Imagen:
    tipo: str = "imagen"
    instrucciones: list[Instruccion] = field(default_factory=list)
    nombre_xobject: str = ""
    caja: Caja | None = None
    ctm: tuple[float, ...] = IDENTIDAD
    recortado_por: list[Any] = field(default_factory=list)
    ancho_px: int = 0
    alto_px: int = 0
    colorspace: str = ""
    tiene_smask: bool = False
    filtro: str = ""

    @property
    def razones_no_editable(self) -> list[str]:
        return []

    @property
    def avisos(self) -> list[str]:
        r = []
        if self.recortado_por:
            r.append("recortada por un clip path: si la mueves más allá, "
                     "dejará de verse la parte recortada")
        return r


@dataclass
class Vector:
    tipo: str = "vector"
    instrucciones: list[Instruccion] = field(default_factory=list)
    caja: Caja | None = None
    ctm: tuple[float, ...] = IDENTIDAD
    operado: str = ""            # f, f*, B, S, n, ...
    color_relleno: tuple[float, ...] | None = None
    color_trazo: tuple[float, ...] | None = None
    ancho_linea: float = 1.0
    limite_inglete: float = 10.0
    union: int = 0
    tiene_trazo: bool = False
    extension_trazo: float = 0.0     # cuánto pinta el trazo más allá de los puntos
    n_segmentos: int = 0
    puntos: list[tuple[float, float]] = field(default_factory=list)
    recortado_por: list[Any] = field(default_factory=list)
    es_recorte: bool = False

    @property
    def razones_no_editable(self) -> list[str]:
        r = []
        if self.es_recorte:
            r.append("es un clip path: define el recorte de otros objetos, "
                     "borrarlo cambiaría también los que recorta")
        return r

    @property
    def avisos(self) -> list[str]:
        r = []
        if self.recortado_por:
            r.append("recortado por un clip path")
        return r


@dataclass
class Sombreado:
    tipo: str = "sombreado"
    instrucciones: list[Instruccion] = field(default_factory=list)
    nombre: str = ""
    caja: Caja | None = None
    ctm: tuple[float, ...] = IDENTIDAD
    recortado_por: list[Any] = field(default_factory=list)

    @property
    def razones_no_editable(self) -> list[str]:
        return []

    @property
    def avisos(self) -> list[str]:
        return ["degradado: redimensionarlo exige transformar también su "
                "dominio, que no está implementado"]


Objeto = TextoRun | Imagen | Vector | Sombreado


def _dist_punto_a_segmento(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    import math
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _cerca_del_trazado(vector: Vector, x: float, y: float, tolerancia: float) -> bool:
    pts = vector.puntos
    if not pts or len(pts) < 2:
        return True
    umbral = tolerancia + max(vector.ancho_linea * 0.6, 2.0)
    for i in range(len(pts) - 1):
        if _dist_punto_a_segmento(x, y, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) <= umbral:
            return True
    if len(pts) > 2 and _dist_punto_a_segmento(x, y, pts[-1][0], pts[-1][1], pts[0][0], pts[0][1]) <= umbral:
        return True
    return False


@dataclass
class ContenidoPagina:
    objetos: list[Objeto]
    instrucciones: list[Instruccion]
    avisos: list[str] = field(default_factory=list)

    def por_tipo(self, tipo: str) -> list[Objeto]:
        return [o for o in self.objetos if o.tipo == tipo]

    def en_punto(self, x: float, y: float, tolerancia: float = 2.0,
                 respetar_clip: bool = True) -> list[Objeto]:
        """Objetos cuya caja contiene el punto. Ordenados del más específico
        (texto/imágenes de menor área) a los contenedores más generales (fondos).

        Para vectores de trazo sin relleno, comprueba que el clic esté cerca del
        trazo real y no en el centro hueco.
        """
        out = []
        for o in self.objetos:
            if o.caja is None or not o.caja.contiene(x, y, tolerancia):
                continue
            if respetar_clip and not _dentro_del_clip(o, x, y):
                continue
            if isinstance(o, Vector) and o.tiene_trazo and not o.color_relleno:
                if not _cerca_del_trazado(o, x, y, tolerancia):
                    continue
            out.append(o)

        def _prioridad(obj: Objeto) -> tuple[int, float]:
            area = obj.caja.area() if obj.caja else 0.0
            if obj.tipo == "texto":
                return (0, area)
            elif obj.tipo == "imagen":
                return (1, area)
            elif isinstance(obj, Vector) and area > 80000:
                return (3, area)
            return (2, area)

        out.sort(key=_prioridad)
        return out

    def resumen(self) -> dict[str, int]:
        r: dict[str, int] = {}
        for o in self.objetos:
            r[o.tipo] = r.get(o.tipo, 0) + 1
        return r


def _muestrear_cubica(p0, p1, p2, p3, n: int = 12) -> list[tuple[float, float]]:
    """Puntos de una curva de Bézier cúbica, sin contar p0."""
    pts = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def aplanar_camino(instrucciones) -> list[list[tuple[float, float]]]:
    """Convierte instrucciones de construcción de trazado en subcaminos
    poligonales.

    Hace falta porque la caja envolvente de un camino NO sirve para saber si un
    punto está dentro: los puntos de control de una Bézier quedan fuera de la
    curva, así que la caja de un círculo trazado con 4 Béziers es un cuadrado
    que incluye esquinas donde el círculo no está.
    """
    subcaminos: list[list[tuple[float, float]]] = []
    actual: list[tuple[float, float]] = []
    pos = (0.0, 0.0)
    inicio = (0.0, 0.0)

    def cerrar():
        nonlocal actual
        if len(actual) >= 3:
            subcaminos.append(actual)
        actual = []

    for ins in instrucciones:
        n = ins.operandos_num()
        op = ins.op
        if op == "m" and len(n) >= 2:
            cerrar()
            pos = inicio = (n[0], n[1])
            actual = [pos]
        elif op == "l" and len(n) >= 2:
            pos = (n[0], n[1])
            actual.append(pos)
        elif op == "c" and len(n) >= 6:
            pts = _muestrear_cubica(pos, (n[0], n[1]), (n[2], n[3]), (n[4], n[5]))
            actual.extend(pts)
            pos = (n[4], n[5])
        elif op == "v" and len(n) >= 4:
            pts = _muestrear_cubica(pos, pos, (n[0], n[1]), (n[2], n[3]))
            actual.extend(pts)
            pos = (n[2], n[3])
        elif op == "y" and len(n) >= 4:
            pts = _muestrear_cubica(pos, (n[0], n[1]), (n[2], n[3]), (n[2], n[3]))
            actual.extend(pts)
            pos = (n[2], n[3])
        elif op == "re" and len(n) >= 4:
            cerrar()
            x, y, w, h = n[0], n[1], n[2], n[3]
            actual = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            pos = inicio = (x, y)
        elif op == "h":
            actual.append(inicio)
            pos = inicio
    cerrar()
    return subcaminos


def en_poligono(puntos: list[tuple[float, float]], x: float, y: float) -> bool:
    """Point-in-polygon por lanzamiento de rayo (even-odd)."""
    dentro = False
    n = len(puntos)
    for i in range(n):
        x0, y0 = puntos[i]
        x1, y1 = puntos[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xcruce = x0 + (y - y0) * (x1 - x0) / (y1 - y0) if y1 != y0 else x0
            if x < xcruce:
                dentro = not dentro
    return dentro


def _dentro_del_clip(o: Objeto, x: float, y: float) -> bool:
    """¿El punto cae dentro de todos los recortes activos del objeto?

    Se prueba la trayectoria aplanada real, no su caja: con la caja, un clic en
    la esquina de un degradado circular seleccionaría un rectángulo que
    visualmente no está ahí.
    """
    for clip in getattr(o, "recortado_por", []) or []:
        if not isinstance(clip, dict):
            continue
        subcaminos = clip.get("poligonos")
        if subcaminos:
            if not any(en_poligono(c, x, y) for c in subcaminos):
                return False
        else:
            caja = clip.get("caja")
            if caja is not None and not caja.contiene(x, y, tolerancia=1.0):
                return False
    return True


# ---------------------------------------------------------------------------
# Extracción
# ---------------------------------------------------------------------------


def _num(o: Any, default: float = 0.0) -> float:
    try:
        return float(o)
    except (TypeError, ValueError):
        return default


def _bytes_de_operador(ins: Instruccion) -> bytes:
    """Bytes que pinta un Tj/TJ/'/" . En TJ los números son kerning, no bytes."""
    if not ins.operandos:
        return b""
    o = ins.operandos[0]
    if ins.op == '"' and len(ins.operandos) >= 3:
        o = ins.operandos[-1]
    if isinstance(o, (bytes, bytearray)):
        return bytes(o)
    if isinstance(o, list):
        return b"".join(bytes(e) for e in o if isinstance(e, (bytes, bytearray)))
    return b""


def _puntos_de_construccion(ins: Instruccion) -> list[tuple[float, float]]:
    n = ins.operandos_num()
    op = ins.op
    if op == "m" and len(n) >= 2:
        return [(n[0], n[1])]
    if op == "l" and len(n) >= 2:
        return [(n[0], n[1])]
    if op == "c" and len(n) >= 6:
        return [(n[0], n[1]), (n[2], n[3]), (n[4], n[5])]
    if op == "v" and len(n) >= 4:
        return [(n[0], n[1]), (n[2], n[3])]
    if op == "y" and len(n) >= 4:
        return [(n[0], n[1]), (n[2], n[3])]
    if op == "re" and len(n) >= 4:
        x, y, w, h = n[0], n[1], n[2], n[3]
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return []


def extraer_objetos(datos: bytes, fuentes: dict | None = None) -> ContenidoPagina:
    """Parsea un content stream y devuelve los objetos que contiene.

    `fuentes` es el mapa nombre -> Fuente (ver nucleo.fuentes.resolver_fuentes).
    Sin él se cuenta 1 byte por código, que es correcto para fuentes simples
    pero no para Type0/Identity-H.
    """
    fuentes = fuentes or {}
    instrucciones = parsear(datos)
    objetos: list[Objeto] = []
    avisos: list[str] = []

    estado = EstadoGrafico()
    pila: list[EstadoGrafico] = []
    clips_activos: list[Any] = []          # (caja_en_espacio_usuario, instrucciones)
    pila_clips: list[int] = []             # cuántos clips había en cada q

    trazado: list[Instruccion] = []
    trazado_pts: list[tuple[float, float]] = []
    run: TextoRun | None = None

    for ins in instrucciones:
        op = ins.op

        # --- estado -----------------------------------------------------
        if op == "q":
            pila.append(estado.copia())
            pila_clips.append(len(clips_activos))
            continue
        if op == "Q":
            if pila:
                estado = pila.pop()
            n_clips = pila_clips.pop() if pila_clips else 0
            del clips_activos[n_clips:]
            continue
        if op == "cm":
            n = ins.operandos_num()
            if len(n) >= 6:
                estado.ctm = multiplicar((n[0], n[1], n[2], n[3], n[4], n[5]),
                                         estado.ctm)
            continue
        if op == "w":
            estado.ancho_linea = _num(ins.operandos[0] if ins.operandos else 1)
            continue
        if op == "M":
            estado.limite_inglete = _num(ins.operandos[0] if ins.operandos else 10)
            continue
        if op == "j":
            estado.union = int(_num(ins.operandos[0] if ins.operandos else 0))
            continue
        if op in ("rg", "g", "k"):
            estado.color_relleno = tuple(ins.operandos_num()) or (0.0,)
            continue
        if op in ("RG", "G", "K"):
            estado.color_trazo = tuple(ins.operandos_num()) or (0.0,)
            continue
        if op in ("sc", "scn", "SC", "SCN"):
            nums = ins.operandos_num()
            if nums:
                if op in ("sc", "scn"):
                    estado.color_relleno = tuple(nums)
                else:
                    estado.color_trazo = tuple(nums)
            continue
        if op == "Tr":
            estado.modo_texto = int(_num(ins.operandos[0] if ins.operandos else 0))
            continue
        if op == "Tc":
            estado.espacio_char = _num(ins.operandos[0] if ins.operandos else 0)
            continue
        if op == "Tw":
            estado.espacio_palabra = _num(ins.operandos[0] if ins.operandos else 0)
            continue
        if op == "Tz":
            estado.escala_h = _num(ins.operandos[0] if ins.operandos else 100) or 100
            continue
        if op == "TL":
            estado.leading = _num(ins.operandos[0] if ins.operandos else 0)
            continue
        if op == "Ts":
            estado.subida = _num(ins.operandos[0] if ins.operandos else 0)
            continue

        # --- recortes ---------------------------------------------------
        if op in ("W", "W*"):
            if trazado_pts:
                caja = Caja.de_puntos([aplicar(estado.ctm, p[0], p[1])
                                       for p in trazado_pts])
                poligonos = []
                for sub in aplanar_camino(trazado):
                    poligonos.append([aplicar(estado.ctm, px, py)
                                      for px, py in sub])
                clips_activos.append({"caja": caja, "poligonos": poligonos,
                                      "ins": list(trazado)})
            trazado, trazado_pts = [], []
            continue

        # --- texto ------------------------------------------------------
        if op == "BT":
            estado.tm = IDENTIDAD
            estado.tlm = IDENTIDAD
            fu = fuentes.get(estado.fuente_nombre or "")
            run = TextoRun(ctm=estado.ctm, tm_inicial=IDENTIDAD,
                           fuente_nombre=estado.fuente_nombre,
                           fuente_base=fu.base_font if fu else "",
                           fuente_subconjuntada=bool(fu and fu.subconjuntada),
                           fuente_tam=estado.fuente_tam,
                           modo_texto=estado.modo_texto,
                           color=estado.color_relleno,
                           recortado_por=list(clips_activos))
            continue
        if op == "ET":
            if run is not None:
                # Un BT..ET sin texto no es seleccionable: reportlab emite
                # `BT /F1 12 Tf ET` solo para fijar la fuente de la página.
                if run.texto or run.n_codigos:
                    objetos.append(run)
                run = None
            continue
        if op == "Tf":
            nueva_fuente = str(ins.operandos[0]) if len(ins.operandos) >= 1 else None
            nuevo_tam = _num(ins.operandos[1]) if len(ins.operandos) >= 2 else estado.fuente_tam
            # Si el run ya contenía texto pintado y cambia de fuente o tamaño, cerramos el run
            # previo para que cada fragmento tipográfico sea un objeto independiente y preciso.
            if run is not None and (run.texto or run.n_codigos) and (
                (nueva_fuente is not None and nueva_fuente != run.fuente_nombre) or
                (nuevo_tam != run.fuente_tam)
            ):
                objetos.append(run)
                run = TextoRun(ctm=estado.ctm, tm_inicial=estado.tm,
                               fuente_nombre=nueva_fuente,
                               fuente_base="",
                               fuente_subconjuntada=False,
                               fuente_tam=nuevo_tam,
                               modo_texto=estado.modo_texto,
                               color=estado.color_relleno,
                               recortado_por=list(clips_activos))

            if len(ins.operandos) >= 2:
                estado.fuente_nombre = str(ins.operandos[0])
                estado.fuente_tam = _num(ins.operandos[1])
            if run is not None:
                run.instrucciones.append(ins)
                fu = fuentes.get(estado.fuente_nombre or "")
                run.fuente_nombre = estado.fuente_nombre
                run.fuente_base = fu.base_font if fu else run.fuente_base
                run.fuente_subconjuntada = bool(fu and fu.subconjuntada) or \
                    run.fuente_subconjuntada
                run.fuente_tam = estado.fuente_tam
            continue
        if op in ("Td", "TD", "Tm", "T*"):
            n = ins.operandos_num()
            if op == "Td" and len(n) >= 2:
                estado.tlm = multiplicar((1, 0, 0, 1, n[0], n[1]), estado.tlm)
                estado.tm = estado.tlm
            elif op == "TD" and len(n) >= 2:
                estado.leading = -n[1]
                estado.tlm = multiplicar((1, 0, 0, 1, n[0], n[1]), estado.tlm)
                estado.tm = estado.tlm
            elif op == "Tm" and len(n) >= 6:
                estado.tlm = (n[0], n[1], n[2], n[3], n[4], n[5])
                estado.tm = estado.tlm
            elif op == "T*":
                estado.tlm = multiplicar((1, 0, 0, 1, 0, -estado.leading), estado.tlm)
                estado.tm = estado.tlm
            if run is not None:
                run.instrucciones.append(ins)
            continue
        if op in OPS_TEXTO_MOSTRAR:
            if run is None:
                # texto fuera de BT..ET: raro pero legal
                fu = fuentes.get(estado.fuente_nombre or "")
                run = TextoRun(ctm=estado.ctm, fuente_nombre=estado.fuente_nombre,
                               fuente_base=fu.base_font if fu else "",
                               fuente_subconjuntada=bool(fu and fu.subconjuntada),
                               fuente_tam=estado.fuente_tam,
                               modo_texto=estado.modo_texto,
                               color=estado.color_relleno,
                               recortado_por=list(clips_activos))
            run.instrucciones.append(ins)
            if run.trm_primer_texto is None:
                run.trm_primer_texto = multiplicar(estado.tm, estado.ctm)
            datos = _bytes_de_operador(ins)
            fuente = fuentes.get(estado.fuente_nombre or "")
            if fuente is not None:
                run.n_codigos += fuente.n_codigos(datos)
                desc = fuente.descodificar(datos)
                if desc is None:
                    run.texto_descodificable = False
                    run.texto += datos.decode("latin-1")
                else:
                    run.texto += desc
            else:
                # fuente no resuelta: se cuenta 1 byte por código (lo habitual)
                run.n_codigos += len(datos)
                run.texto += datos.decode("latin-1")
            continue
        if op in ("Tc", "Tw", "Tz", "TL", "Ts", "Tr") and run is not None:
            run.instrucciones.append(ins)
            continue

        # --- construcción de trazado ------------------------------------
        if op in OPS_CONSTRUCCION:
            trazado.append(ins)
            trazado_pts.extend(_puntos_de_construccion(ins))
            continue
        if op == "h":
            trazado.append(ins)
            continue

        # --- pintado ----------------------------------------------------
        if op in OPS_PINTADO:
            if op == "Do":
                nombre = str(ins.operandos[0]) if ins.operandos else ""
                # la imagen se pinta en un cuadrado unidad: la caja es el CTM
                caja = Caja.de_rect_transformado(estado.ctm, 0, 0, 1, 1)
                objetos.append(Imagen(
                    instrucciones=[ins], nombre_xobject=nombre, caja=caja,
                    ctm=estado.ctm,
                    recortado_por=list(clips_activos)))
                continue
            if op == "sh":
                nombre = str(ins.operandos[0]) if ins.operandos else ""
                caja = Caja.de_puntos([aplicar(estado.ctm, p[0], p[1])
                                       for p in trazado_pts]) if trazado_pts else None
                objetos.append(Sombreado(instrucciones=list(trazado) + [ins],
                                         nombre=nombre, caja=caja,
                                         ctm=estado.ctm,
                                         recortado_por=list(clips_activos)))
                trazado, trazado_pts = [], []
                continue
            if trazado:
                pts = [aplicar(estado.ctm, p[0], p[1]) for p in trazado_pts]
                caja = Caja.de_puntos(pts) if pts else None
                es_relleno = op in ("f", "F", "f*", "B", "B*", "b", "b*")
                es_trazo = op in ("S", "s", "B", "B*", "b", "b*")
                # La caja de un trazado CON TRAZO no es la caja de sus puntos:
                # el trazo tiene grosor y, en uniones en inglete, los picos
                # sobresalen bastante (los de una estrella, hasta 2 puntos).
                # Sin esto, clicar en el contorno visible de una figura no la
                # selecciona, y el test de aceptación ve píxeles fantasma.
                escala = 1.0
                det = abs(estado.ctm[0] * estado.ctm[3]
                          - estado.ctm[1] * estado.ctm[2])
                if det > 0:
                    escala = det ** 0.5
                extension = 0.0
                if es_trazo and pts:
                    extension = _extension_trazo(
                        pts, estado.ancho_linea * escala,
                        estado.limite_inglete, estado.union, op not in ("B", "B*", "b", "b*"))
                    if caja is not None:
                        caja = caja.expandida(extension)

                objetos.append(Vector(
                    instrucciones=list(trazado) + [ins], caja=caja,
                    ctm=estado.ctm, operado=op,
                    color_relleno=estado.color_relleno if es_relleno else None,
                    color_trazo=estado.color_trazo if es_trazo else None,
                    ancho_linea=estado.ancho_linea,
                    limite_inglete=estado.limite_inglete,
                    union=estado.union,
                    tiene_trazo=es_trazo,
                    extension_trazo=extension,
                    n_segmentos=len(trazado),
                    puntos=pts,
                    recortado_por=list(clips_activos)))
            elif op == "n":
                pass  # `n` sin trazado: no pinta nada
            trazado, trazado_pts = [], []
            continue

    if run is not None and (run.texto or run.n_codigos):
        objetos.append(run)

    # cajas de los runs de texto: sin métricas de fuente se aproximan.
    # El alineador con pdfium (ver alinear_texto.py) las refina después.
    for o in objetos:
        if isinstance(o, TextoRun) and o.caja is None:
            o.caja = _caja_aproximada_texto(o)

    return ContenidoPagina(objetos=objetos, instrucciones=instrucciones, avisos=avisos)


def _extension_trazo(puntos: list[tuple[float, float]], ancho: float,
                     limite_inglete: float, union: int,
                     abierto: bool = True) -> float:
    """Cuánto puede pintar el trazo más allá de la trayectoria.

    Dos componentes, y la segunda es la que se olvida siempre:

      - el semigrosor del trazo: ancho/2, en todas direcciones
      - los picos de inglete: en un vértice el trazo sobresale
        (ancho/2)/sin(θ/2), donde θ es el ángulo entre los dos segmentos. En una
        punta afilada esto crece mucho, y el límite de inglete lo corta.

    Con union != 0 (redondo o bisel) no hay pico. Con un trazo abierto, los
    extremos también se redondean o se prolongan según el remate.
    """
    semiancho = ancho / 2.0
    if semiancho <= 0:
        return 0.0
    if union != 0 or len(puntos) < 3:
        return semiancho

    import math
    maximo = semiancho
    tope = limite_inglete * semiancho
    n = len(puntos)
    vertices = range(n) if not abierto else range(1, n - 1)
    for i in vertices:
        p0, p1, p2 = puntos[i - 1], puntos[i], puntos[(i + 1) % n]
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        # OJO con el ángulo: lo que cuenta para el inglete es el ÁNGULO DE
        # GIRO, no el ángulo entre los dos vectores. En una punta afilada los
        # segmentos apuntan casi en direcciones opuestas, así que el ángulo
        # entre v1 y v2 es cercano a 180° y el de giro es su suplementario.
        # Usar el equivocado subestima el pico por un factor de 3.
        coseno = -(v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
        coseno = max(-1.0, min(1.0, coseno))
        theta = math.acos(coseno)              # ángulo de giro
        seno = math.sin(theta / 2.0)
        if seno < 1e-6:
            maximo = max(maximo, tope)
            continue
        maximo = max(maximo, min(semiancho / seno, tope))
    return maximo


def _caja_aproximada_texto(run: TextoRun) -> Caja | None:
    """Aproximación grosera: origen del texto + avance estimado.

    Solo se usa si no hay posiciones reales de pdfium. Asume ~0.55 em de ancho
    medio por carácter, que es lo habitual en fuentes latinas.
    """
    if not run.instrucciones:
        return None
    trm = run.trm_primer_texto or multiplicar(run.tm_inicial, run.ctm)
    if es_degenerada(trm):
        return None
    n = max(len(run.texto), 1)
    tam = run.fuente_tam or 12.0
    ancho_est = n * tam * 0.55
    # En PDF el origen es la línea base (baseline); los glifos tienen trazo descendente
    # (aprox. -0.25 em) y ascendente/mayúsculas (aprox. +0.95 em).
    pts = [aplicar(trm, x, y) for x in (0, ancho_est) for y in (-tam * 0.25, tam * 0.95)]
    return Caja.de_puntos(pts)
