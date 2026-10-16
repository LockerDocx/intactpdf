"""
Resolución de fuentes: cuántos bytes ocupa un código de texto y cómo se
convierte a Unicode.

Un operador de texto pinta BYTES, no caracteres. Cuántos bytes forman un
carácter depende de la fuente:

  - Type1 / TrueType simple  -> 1 byte por código
  - Type0 (CID) con Identity-H / Identity-V -> 2 bytes por código
  - Type0 con un CMap de 1 byte -> 1 byte

Contar mal esto rompe todo lo demás: el caso 10 del corpus tiene 181
caracteres reales y 362 bytes.

Para pasar a Unicode se usa el CMap /ToUnicode cuando existe. Cuando no existe,
no se inventa nada: se devuelve None y el objeto se marca como no editable con
seguridad.
"""
from __future__ import annotations

import re
from typing import Any

from .parser import _decode_nombre


def _resolver(obj):
    """Dereferencia referencias indirectas.

    Cuidado con pikepdf: `Object.__getattr__` interpreta CUALQUIER atributo como
    una clave del diccionario PDF, así que `hasattr(un_nombre, "get_object")`
    lanza ValueError (y hasattr no lo captura, porque solo traga
    AttributeError). Por eso el método se busca en la CLASE, no en la instancia.
    """
    for _ in range(8):
        get = getattr(type(obj), "get_object", None)
        if get is None:
            break
        try:
            nuevo = get(obj)
        except Exception:
            break
        if nuevo is None or nuevo is obj:
            break
        obj = nuevo
    return obj


def _get(d, key, default=None):
    """Acceso a clave de diccionario PDF.

    Las claves de un diccionario PDF son nombres SIN la barra inicial: el
    diccionario tiene la clave `Subtype`, no `/Subtype`. Se aceptan ambas
    formas para no depender de cómo llegue el objeto.
    """
    for k in (key.lstrip("/"), key):
        try:
            return _resolver(d[k])
        except Exception:
            continue
    return default


class Fuente:
    """Lo que hace falta saber de una fuente para interpretar el texto."""

    # `_a_unicode` sigue existiendo como propiedad de solo lectura por
    # compatibilidad con el código escrito antes de F4.
    _a_unicode = property(lambda self: self.a_unicode)

    def __init__(self, nombre: str, bytes_por_codigo: int = 1,
                 a_unicode=None, subconjuntada: bool = False,
                 subtipo: str = "", base_font: str = ""):
        self.nombre = nombre            # clave en /Resources/Font, p.ej. "F2+0"
        self.base_font = base_font      # /BaseFont, p.ej. "AAAAAA+DejaVuSans"
        self.bytes_por_codigo = bytes_por_codigo
        self.a_unicode: dict[int, str] = a_unicode or {}
        self.subconjuntada = subconjuntada
        self.subtipo = subtipo
        # --- añadido para la edición de texto (fase F4) ---
        self.anchos: dict[int, int] = {}     # código -> ancho en 1/1000 em
        self.first_char: int = 0
        self.incrustada: bool = False
        self.fontfile: bytes | None = None   # el programa de fuente, si lo hay
        self.ref = None                      # (num, gen) del objeto fuente
        self.objeto = None                   # el objeto pikepdf de la fuente
        self.es_type0: bool = False

    def ancho_de(self, codigo: int) -> int:
        """Ancho de un código en 1/1000 em. 600 es el valor por omisión."""
        return self.anchos.get(codigo, 600)

    def codigo_de(self, ch: str) -> int | None:
        """Carácter -> código, invirtiendo el ToUnicode.

        Se ignoran las entradas que mapean un código a varios caracteres
        (ligaduras): no se pueden invertir sin ambigüedad.
        """
        for codigo, texto in self.a_unicode.items():
            if texto == ch:
                return codigo
        return None

    def mapa_inverso(self) -> dict[str, int]:
        """char -> código, saltándose las ligaduras."""
        out: dict[str, int] = {}
        for codigo, texto in sorted(self.a_unicode.items()):
            if len(texto) == 1 and texto not in out:
                out[texto] = codigo
        return out

    def codigos_de(self, datos: bytes) -> list[int]:
        """Bytes de un operador de texto -> lista de códigos."""
        n = self.bytes_por_codigo
        if n == 2:
            if len(datos) % 2:
                datos = datos + b"\x00"
            return [int.from_bytes(datos[i:i + 2], "big")
                    for i in range(0, len(datos), 2)]
        return list(datos)

    def bytes_de(self, codigos: list[int]) -> bytes:
        n = self.bytes_por_codigo
        out = bytearray()
        for c in codigos:
            out += c.to_bytes(n, "big")
        return bytes(out)

    def descodificar(self, datos: bytes) -> str | None:
        """Bytes del stream -> texto Unicode. None si no se puede con certeza."""
        n = self.bytes_por_codigo
        if n == 2:
            if len(datos) % 2:
                datos = datos + b"\x00"
            codigos = [int.from_bytes(datos[i:i + 2], "big")
                       for i in range(0, len(datos), 2)]
        else:
            codigos = list(datos)
        if not self.a_unicode:
            # sin ToUnicode: para fuentes simples de 1 byte la convención
            # habitual (WinAnsi/Standard) coincide con latin-1 en la práctica,
            # así que se acepta. Con 2 bytes sin CMap no hay forma de saberlo.
            if n == 2:
                return None
            return bytes(codigos).decode("latin-1", "replace")
        out = []
        for c in codigos:
            v = self.a_unicode.get(c)
            out.append(v if v is not None else "\ufffd")
        return "".join(out)

    def n_codigos(self, datos: bytes) -> int:
        if self.bytes_por_codigo == 2:
            return len(datos) // 2
        return len(datos)


# ---------------------------------------------------------------------------
# CMap /ToUnicode
# ---------------------------------------------------------------------------

_RANGO_BF = re.compile(
    rb"beginbfrange\s*(.*?)\s*endbfrange", re.S)
_CHAR_BF = re.compile(
    rb"beginbfchar\s*(.*?)\s*endbfchar", re.S)
_HEX = re.compile(rb"<([0-9A-Fa-f\s]+)>")


def _hex_a_int(b: bytes) -> int:
    limpio = re.sub(rb"\s", b"", b)
    if len(limpio) % 2:
        limpio = b"0" + limpio
    return int(limpio, 16) if limpio else 0


def _hex_a_str(b: bytes) -> str:
    limpio = re.sub(rb"\s", b"", b)
    if len(limpio) % 2:
        limpio += b"0"
    try:
        return bytes.fromhex(limpio.decode("ascii")).decode("utf-16-be", "replace")
    except Exception:
        return ""


def parsear_tounicode(datos: bytes) -> dict[int, str]:
    """Interpreta un CMap ToUnicode. Solo bfchar y bfrange, que es lo que
    generan prácticamente todos los productores de PDF."""
    out: dict[int, str] = {}
    for bloque in _CHAR_BF.findall(datos):
        pares = _HEX.findall(bloque)
        for i in range(0, len(pares) - 1, 2):
            out[_hex_a_int(pares[i])] = _hex_a_str(pares[i + 1])
    for bloque in _RANGO_BF.findall(datos):
        # <ini> <fin> <dst>   o   <ini> <fin> [<d1> <d2> ...]
        for linea in bloque.split(b"\n"):
            hexes = _HEX.findall(linea)
            if len(hexes) < 3:
                continue
            ini, fin = _hex_a_int(hexes[0]), _hex_a_int(hexes[1])
            destinos = hexes[2:]
            if len(destinos) == 1 and fin - ini < 65536:
                base = _hex_a_int(destinos[0])
                for k in range(fin - ini + 1):
                    out[ini + k] = chr(base + k) if base + k < 0x110000 else ""
            else:
                for k, d in enumerate(destinos):
                    if ini + k > fin:
                        break
                    out[ini + k] = _hex_a_str(d)
    return out


def _parsear_w(w, por_omision: float) -> dict[int, int]:
    """Interpreta el array /W de una fuente CID.

    Dos formas mezclables:
        c [w1 w2 ...]        anchos consecutivos desde c
        cfirst clast w       el mismo ancho para todo el rango
    """
    out: dict[int, int] = {}
    if w is None:
        return out
    i, n = 0, len(w)
    while i < n:
        try:
            c = int(w[i])
        except Exception:
            break
        siguiente = w[i + 1] if i + 1 < n else None
        es_lista = False
        if siguiente is not None:
            try:
                len(siguiente)
                es_lista = True
            except TypeError:
                es_lista = False
        if es_lista:
            for k, v in enumerate(siguiente):
                try:
                    out[c + k] = int(float(v))
                except Exception:
                    pass
            i += 2
        elif i + 2 < n:
            try:
                cfin = int(w[i + 1])
                val = int(float(w[i + 2]))
            except Exception:
                break
            for k in range(max(0, cfin - c + 1)):
                out[c + k] = val
            i += 3
        else:
            break
    return out


def resolver_fuentes(pagina) -> dict[str, Fuente]:
    """Construye el mapa nombre -> Fuente para los recursos de una página.

    Acepta una página de pikepdf. Si algo falla, devuelve un mapa vacío y el
    resto del sistema degrada a "no se puede editar con seguridad".
    """
    fuentes: dict[str, Fuente] = {}
    res = _get(pagina, "/Resources")
    if res is None:
        return fuentes
    fd = _get(res, "/Font")
    if fd is None:
        return fuentes

    for clave in fd.keys():
        nombre = str(clave).lstrip("/")
        try:
            f = _resolver(fd[clave])
        except Exception:
            continue
        subtipo = str(_get(f, "/Subtype", ""))
        base = str(_get(f, "/BaseFont", ""))
        # BaseFont llega como "/AAAAAA+DejaVuSans": la barra hay que quitarla
        subconjuntada = bool(re.match(r"^[A-Z]{6}\+", base.lstrip("/")))

        bytes_por_codigo = 1
        if subtipo.endswith("/Type0"):
            enc = str(_get(f, "/Encoding", ""))
            if "Identity" in enc:
                bytes_por_codigo = 2
            else:
                bytes_por_codigo = 1

        a_unicode = {}
        tu = _get(f, "/ToUnicode")
        if tu is not None:
            try:
                a_unicode = parsear_tounicode(tu.read_bytes())
            except Exception:
                a_unicode = {}

        fuente = Fuente(
            nombre=nombre, bytes_por_codigo=bytes_por_codigo,
            a_unicode=a_unicode, subconjuntada=subconjuntada, subtipo=subtipo,
            base_font=base.lstrip("/"))
        fuente.es_type0 = "Type0" in subtipo
        try:
            fuente.ref = f.objgen
        except Exception:
            fuente.ref = None
        fuente.objeto = f

        # --- anchos y programa de fuente, para poder editar texto ---
        try:
            if fuente.es_type0:
                df = _get(f, "/DescendantFonts")
                d0 = _resolver(df[0]) if df is not None else None
                if d0 is not None:
                    dw = float(_get(d0, "/DW", 1000) or 1000)
                    fuente.anchos = _parsear_w(_get(d0, "/W"), dw)
                    descr = _get(d0, "/FontDescriptor")
                else:
                    descr = None
            else:
                fuente.first_char = int(_get(f, "/FirstChar", 0) or 0)
                w = _get(f, "/Widths")
                if w is not None:
                    for i, v in enumerate(w):
                        fuente.anchos[fuente.first_char + i] = int(float(v))
                descr = _get(f, "/FontDescriptor")
            if descr is not None:
                for kk in ("/FontFile2", "/FontFile3", "/FontFile"):
                    o = _get(descr, kk)
                    if o is not None:
                        fuente.fontfile = o.read_bytes()
                        fuente.incrustada = True
                        break
        except Exception:
            pass

        fuentes[nombre] = fuente
    return fuentes
