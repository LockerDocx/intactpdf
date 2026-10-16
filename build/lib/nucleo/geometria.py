"""
Geometría 2D afín para PDF.

Las matrices PDF son [a b c d e f] y transforman así:

    x' = a*x + c*y + e
    y' = b*x + d*y + f

que equivale a la matriz 3x3:

    | a b 0 |
    | c d 0 |
    | e f 1 |

con vectores fila [x y 1]. Solo stdlib.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

Matriz = tuple[float, float, float, float, float, float]

IDENTIDAD: Matriz = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiplicar(m1: Matriz, m2: Matriz) -> Matriz:
    """m1 seguida de m2 (el orden de PDF: `m1 m2 cm` aplica m1 y luego m2)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def aplicar(m: Matriz, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def determinante(m: Matriz) -> float:
    a, b, c, d, _, _ = m
    return a * d - b * c


def es_degenerada(m: Matriz, eps: float = 1e-9) -> bool:
    return abs(determinante(m)) < eps


def invertir(m: Matriz) -> Matriz | None:
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return None
    r = 1.0 / det
    return (
        d * r, -b * r,
        -c * r, a * r,
        (c * f - d * e) * r, (b * e - a * f) * r,
    )


def transformar_puntos(m: Matriz, puntos: Iterable[Sequence[float]]) -> list[tuple[float, float]]:
    return [aplicar(m, p[0], p[1]) for p in puntos]


class Caja:
    """Caja alineada a ejes. Inmutable en la práctica."""

    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(self, x0: float, y0: float, x1: float, y1: float):
        self.x0 = min(x0, x1)
        self.y0 = min(y0, y1)
        self.x1 = max(x0, x1)
        self.y1 = max(y0, y1)

    @classmethod
    def de_puntos(cls, puntos: Iterable[Sequence[float]]) -> "Caja":
        pts = list(puntos)
        if not pts:
            return cls(0, 0, 0, 0)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return cls(min(xs), min(ys), max(xs), max(ys))

    @classmethod
    def de_rect_transformado(cls, m: Matriz, x: float, y: float,
                             w: float, h: float) -> "Caja":
        return cls.de_puntos(transformar_puntos(
            m, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]))

    @property
    def ancho(self) -> float:
        return self.x1 - self.x0

    @property
    def alto(self) -> float:
        return self.y1 - self.y0

    @property
    def centro(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def contiene(self, x: float, y: float, tolerancia: float = 0.0) -> bool:
        return (self.x0 - tolerancia <= x <= self.x1 + tolerancia
                and self.y0 - tolerancia <= y <= self.y1 + tolerancia)

    def intersecta(self, otra: "Caja") -> bool:
        return not (self.x1 < otra.x0 or otra.x1 < self.x0
                    or self.y1 < otra.y0 or otra.y1 < self.y0)

    def union(self, otra: "Caja") -> "Caja":
        return Caja(min(self.x0, otra.x0), min(self.y0, otra.y0),
                    max(self.x1, otra.x1), max(self.y1, otra.y1))

    def expandida(self, d: float) -> "Caja":
        return Caja(self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d)

    def solape(self, otra: "Caja") -> float:
        """Área de la intersección."""
        w = min(self.x1, otra.x1) - max(self.x0, otra.x0)
        h = min(self.y1, otra.y1) - max(self.y0, otra.y0)
        return max(0.0, w) * max(0.0, h)

    def area(self) -> float:
        return max(0.0, self.ancho) * max(0.0, self.alto)

    def __repr__(self) -> str:
        return (f"Caja({self.x0:.1f}, {self.y0:.1f}, "
                f"{self.x1:.1f}, {self.y1:.1f})")

    def como_tupla(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


# ---------------------------------------------------------------------------
# Coordenadas de página
# ---------------------------------------------------------------------------

def matriz_pagina(mediabox: Sequence[float], rotate: int = 0) -> tuple[Matriz, float, float]:
    """Matriz que pasa de espacio de usuario del PDF a espacio de página
    (origen arriba-izquierda, y hacia abajo), como hace pdfium.

    Devuelve (matriz, ancho_visible, alto_visible).
    """
    x0, y0, x1, y1 = (float(v) for v in mediabox)
    w, h = x1 - x0, y1 - y0
    rot = ((rotate % 360) + 360) % 360

    # paso 1: origen del mediabox al (0,0) e invertir y
    base: Matriz = (1, 0, 0, -1, -x0, y1)
    if rot == 0:
        return base, w, h
    if rot == 90:
        # rotar 90° en el sentido de las agujas
        return multiplicar(base, (0, -1, 1, 0, 0, w)), h, w
    if rot == 180:
        return multiplicar(base, (-1, 0, 0, -1, w, h)), w, h
    if rot == 270:
        return multiplicar(base, (0, 1, -1, 0, h, 0)), h, w
    return base, w, h


def escala_caja(caja: Caja, m: Matriz) -> Caja:
    """Caja resultante de transformar las 4 esquinas."""
    return Caja.de_rect_transformado(m, caja.x0, caja.y0, caja.ancho, caja.alto)


def angulo_de(m: Matriz) -> float:
    """Rotación implícita de la matriz, en grados."""
    a, b = m[0], m[1]
    if a == 0 and b == 0:
        return 0.0
    return math.degrees(math.atan2(b, a))
