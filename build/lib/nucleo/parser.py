"""
Lexer y parser del content stream de una página PDF.

Un content stream es una secuencia plana de operandos seguidos de un operador:

    q 1 0 0 1 72 780 cm BT /F1 12 Tf (Hola) Tj ET Q

El lexer devuelve tokens con su posición en el stream (imprescindible para poder
reescribir el stream al editar) y el parser los agrupa en instrucciones
(operandos, operador).

Sin dependencias externas. Solo stdlib.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    rb"""
    (?P<ws>   \s+ )
  | (?P<num>  [+-]?(?:\d+\.?\d*|\.\d+) )
  | (?P<name> /[^/\[\]<>()\s{}\x00]* )
  | (?P<hexs> <[0-9A-Fa-f\s]*> )
  | (?P<dicts> << )
  | (?P<dicte> >> )
  | (?P<arrl> \[ )
  | (?P<arrr> \] )
  | (?P<strl> \( )
  | (?P<kw>   [A-Za-z][A-Za-z0-9]*\*?|['\"*]\*?|d[01] )
    """,
    re.VERBOSE,
)

# Operadores que no son letras puras
_KW_ESPECIALES = {b"'", b'"', b"f*", b"B*", b"b*", b"W*", b"T*", b"d0", b"d1"}


@dataclass(slots=True)
class Token:
    tipo: str          # 'num' | 'name' | 'string' | 'hexstring' | 'array' |
                       # 'dict' | 'bool' | 'null' | 'op'
    valor: Any
    inicio: int        # offset en el stream
    fin: int           # offset exclusivo


def _leer_string_literal(datos: bytes, i: int) -> tuple[bytes, int]:
    """Lee (...) desde el paréntesis de apertura. Soporta escapes y anidación."""
    assert datos[i:i + 1] == b"("
    i += 1
    out = bytearray()
    prof = 1
    n = len(datos)
    while i < n:
        c = datos[i:i + 1]
        if c == b"\\":
            i += 1
            if i >= n:
                break
            e = datos[i:i + 1]
            if e in b"nrtbf":
                out.append({b"n": 10, b"r": 13, b"t": 9, b"b": 8, b"f": 12}[e])
                i += 1
            elif e in b"01234567":
                oct_ = e
                for _ in range(2):
                    if i + 1 < n and datos[i + 1:i + 2] in b"01234567":
                        oct_ += datos[i + 1:i + 2]
                        i += 1
                    else:
                        break
                out.append(int(oct_, 8) & 0xFF)
                i += 1
            elif e in b"\r\n":
                i += 1
                if e == b"\r" and datos[i:i + 1] == b"\n":
                    i += 1
            else:
                out += e
                i += 1
        elif c == b"(":
            prof += 1
            out += c
            i += 1
        elif c == b")":
            prof -= 1
            i += 1
            if prof == 0:
                return bytes(out), i
            out += c
        else:
            out += c
            i += 1
    return bytes(out), i


def _hex_a_bytes(s: bytes) -> bytes:
    limpio = re.sub(rb"\s", b"", s)
    if len(limpio) % 2:
        limpio += b"0"
    return bytes.fromhex(limpio.decode("ascii"))


def _decode_nombre(raw: bytes) -> str:
    """Deshace los escapes #XX de un nombre PDF."""
    return re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]),
                  raw).decode("utf-8", "replace")


def tokenizar(datos: bytes) -> list[Token]:
    """Convierte un content stream en tokens. Nunca lanza: lo que no entiende
    lo descarta, porque un stream corrupto no debe tumbar el editor."""
    tokens: list[Token] = []
    i, n = 0, len(datos)
    pila_arrays: list[tuple[list, int]] = []

    while i < n:
        m = _TOKEN_RE.match(datos, i)
        if not m:
            # byte no reconocido: dentro de una cadena ya se consumió, así que
            # esto solo pasa con basura. Se salta.
            i += 1
            continue
        kind = m.lastgroup
        ini, fin = m.span()
        i = fin

        if kind == "ws":
            continue
        if kind == "num":
            raw = m.group("num")
            v = float(raw) if (b"." in raw) else int(raw)
            tok = Token("num", v, ini, fin)
        elif kind == "name":
            tok = Token("name", _decode_nombre(m.group("name")[1:]), ini, fin)
        elif kind == "strl":
            contenido, nuevo_i = _leer_string_literal(datos, m.start())
            i = nuevo_i
            tok = Token("string", contenido, ini, nuevo_i)
        elif kind == "hexs":
            tok = Token("hexstring", _hex_a_bytes(m.group("hexs")[1:-1]), ini, fin)
        elif kind == "kw":
            raw = m.group("kw")
            if raw == b"true":
                tok = Token("bool", True, ini, fin)
            elif raw == b"false":
                tok = Token("bool", False, ini, fin)
            elif raw == b"null":
                tok = Token("null", None, ini, fin)
            else:
                tok = Token("op", raw.decode("latin-1"), ini, fin)
        elif kind == "arrl":
            pila_arrays.append(([], ini))
            continue
        elif kind == "arrr":
            if pila_arrays:
                items, ini_arr = pila_arrays.pop()
                tok = Token("array", items, ini_arr, fin)
            else:
                continue
        elif kind in ("dicts", "dicte"):
            continue
        else:
            continue

        if pila_arrays:
            pila_arrays[-1][0].append(tok.valor)
        else:
            tokens.append(tok)

    return tokens


# ---------------------------------------------------------------------------
# Instrucciones: operandos + operador
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Instruccion:
    op: str
    operandos: list[Any]
    tokens: list[Token] = field(default_factory=list)

    @property
    def inicio(self) -> int:
        return self.tokens[0].inicio if self.tokens else -1

    @property
    def fin(self) -> int:
        return self.tokens[-1].fin if self.tokens else -1

    def operandos_num(self) -> list[float]:
        return [float(o) for o in self.operandos if isinstance(o, (int, float))]


# Operadores de pintado: cierran el objeto vectorial en curso
OPS_PINTADO = {"f", "F", "f*", "B", "B*", "b", "b*", "S", "s", "n", "sh", "Do"}
OPS_CONSTRUCCION = {"m", "l", "c", "v", "y", "re", "h"}
OPS_TEXTO_MOSTRAR = {"Tj", "TJ", "'", '"'}
OPS_TEXTO_POS = {"Td", "TD", "Tm", "T*"}

# Aridad conocida, para detectar streams desalineados
ARIDAD = {
    "q": 0, "Q": 0, "cm": 6, "BT": 0, "ET": 0,
    "Tf": 2, "Td": 2, "TD": 2, "Tm": 6, "T*": 0,
    "Tc": 1, "Tw": 1, "Tz": 1, "TL": 1, "Ts": 1, "Tr": 1,
    "Tj": 1, "TJ": 1, "'": 1, '"': 3,
    "m": 2, "l": 2, "c": 6, "v": 4, "y": 4, "re": 4, "h": 0,
    "f": 0, "F": 0, "f*": 0, "B": 0, "B*": 0, "b": 0, "b*": 0, "S": 0, "s": 0, "n": 0,
    "W": 0, "W*": 0, "Do": 1, "sh": 1,
    "w": 1, "J": 1, "j": 1, "M": 1, "d": 2, "ri": 1, "i": 1,
    "SC": None, "SCN": None, "sc": None, "scn": None,
    "G": 1, "g": 1, "RG": 3, "rg": 3, "K": 4, "k": 4,
    "gs": 1, "CS": 1, "cs": 1,
    "BX": 1, "EX": 1, "MP": 1, "DP": None, "BMC": 1, "BDC": 2, "EMC": 0,
}


def agrupar(tokens: list[Token]) -> list[Instruccion]:
    """Agrupa tokens en instrucciones (operandos hasta el siguiente operador)."""
    out: list[Instruccion] = []
    operandos: list[Any] = []
    toks: list[Token] = []

    for t in tokens:
        toks.append(t)
        if t.tipo != "op":
            operandos.append(t.valor)
            continue
        out.append(Instruccion(op=t.valor, operandos=operandos, tokens=toks))
        operandos, toks = [], []
    return out


def descomprimir_stream(stream) -> bytes:
    """Devuelve el contenido de un stream aplicando sus filtros.

    Acepta un objeto pikepdf o bytes ya descomprimidos.
    """
    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream)
    try:
        return stream.read_bytes()
    except Exception:
        pass
    # Fallback manual si pikepdf no puede (filtro raro): al menos Flate.
    try:
        raw = bytes(stream.read_raw_bytes())
        filtros = stream.get("/Filter")
        if filtros is None:
            return raw
        nombres = [str(f) for f in (filtros if isinstance(filtros, (list, tuple))
                                    else [filtros])]
        data = raw
        for nombre in nombres:
            if nombre.endswith("FlateDecode"):
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    return data
        return data
    except Exception:
        return b""


def contenido_pagina(pagina) -> bytes:
    """Contenido descomprimido de una página, con los trozos concatenados."""
    try:
        c = pagina["/Contents"]
    except Exception:
        return b""
    if c is None:
        return b""
    try:
        if isinstance(c, (list, tuple)) or hasattr(c, "__iter__") and not hasattr(c, "read_bytes"):
            return b"\n".join(descomprimir_stream(s) for s in c)
        return descomprimir_stream(c)
    except Exception:
        return b""


def parsear(datos: bytes) -> list[Instruccion]:
    return agrupar(tokenizar(datos))


def iterar(datos: bytes) -> Iterator[Instruccion]:
    yield from agrupar(tokenizar(datos))
