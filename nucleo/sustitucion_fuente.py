"""
Sustitución de fuentes: construir un subconjunto nuevo cuando al texto editado
le falta algún glifo.

El problema, en una frase: los PDFs llevan **subconjuntos**. Un PDF que sólo dice
«El rápido zorro» no lleva la letra «k» dentro. Si el usuario escribe una «k»,
esa letra no está y no hay forma de sacarla del fichero.

De dónde sale entonces:

  1. Si el glifo YA está en el subconjunto incrustado -> no hay que hacer nada,
     se reutiliza su código. Es el caso más común (corregir una errata dentro del
     vocabulario del documento) y no toca la fuente.
  2. Si falta y la fuente está instalada en el sistema -> se construye un
     subconjunto nuevo con fontTools a partir de la fuente del sistema y se
     incrusta como fuente NUEVA. La fuente original no se toca, así que nada del
     resto del documento cambia.
  3. Si falta y la fuente no está -> se rechaza la edición diciendo qué fuente
     hace falta. Nunca se sustituye por otra en silencio: eso cambiaría el
     aspecto del documento sin avisar, que es justo lo que este editor no hace.

La fuente nueva se emite como Type0 / Identity-H porque es la construcción más
simple y sin ambigüedades: el código ES el identificador de glifo, no hay tabla
de codificación que reconstruir y los anchos se declaran explícitamente.

Dependencia: fontTools (MIT). Nada de AGPL.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

# Directorios donde buscar fuentes, en orden.
#
# Los dos primeros son del anfitrión. Los dos siguientes existen porque el
# empaquetado cambia el mapa: dentro de un sandbox de Flatpak la aplicación NO
# ve `/usr/share/fonts` del sistema anfitrión, solo el runtime. Si no se
# empaquetan fuentes con la aplicación, el nivel 2 de la edición de texto deja
# de funcionar sin que nada avise — el usuario escribiría una letra que falta y
# recibiría un rechazo hablando de una fuente que SÍ tiene instalada.
#
# `fuentes/` junto al paquete cubre ese caso: son fuentes que viajan con la app.
DIRECTORIOS_FUENTES = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    # Las que viajan con la aplicación. Hay tres sitios posibles y los tres
    # valen, porque el mismo código se ejecuta desde el repositorio, desde un
    # pip install y desde dentro de un Flatpak:
    #   - nucleo/fuentes/     datos de paquete (pip install .)
    #   - ../fuentes/         junto al paquete (repositorio, o instalación donde
    #                         el empaquetador las ponga ahí)
    #   - /app/share/fonts    el Flatpak las instala en el directorio estándar y
    #                         llega por XDG_DATA_DIRS, más abajo
    str(Path(__file__).resolve().parent / "fuentes"),
    str(Path(__file__).resolve().parent.parent / "fuentes"),
    # y las que XDG declare, que es lo correcto en sistemas modernos
]

# Alias habituales: un PDF puede decir "Arial" y en el sistema estar DejaVu,
# pero NO son la misma tipografía. Se avisa, no se sustituye a ciegas.
ALIAS_ADMISIBLES = {
    "helvetica": ["Helvetica", "LiberationSans", "Arial", "DejaVuSans"],
    "times": ["Times", "LiberationSerif", "DejaVuSerif"],
    "courier": ["Courier", "LiberationMono", "DejaVuSansMono"],
}


@dataclass
class FuenteNueva:
    """Un subconjunto listo para incrustar."""
    ttf: bytes
    upem: int
    char_a_gid: dict[str, int] = field(default_factory=dict)
    gid_a_char: dict[int, str] = field(default_factory=dict)
    anchos: dict[int, int] = field(default_factory=dict)   # gid -> 1/1000 em
    bbox: tuple[int, int, int, int] = (0, 0, 1000, 1000)
    ascent: int = 800
    descent: int = -200
    cap_height: int = 700
    italic_angle: float = 0.0
    es_nonsymbolic: bool = True
    nombre_origen: str = ""

    def codificar(self, texto: str) -> bytes:
        """Texto -> bytes Identity-H (2 bytes por glifo)."""
        out = bytearray()
        for ch in texto:
            gid = self.char_a_gid.get(ch)
            if gid is None:
                raise KeyError(f"el subconjunto no tiene glifo para {ch!r}")
            out += gid.to_bytes(2, "big")
        return bytes(out)

    def ancho_de(self, texto: str) -> float:
        """Ancho del texto en unidades de texto (1/1000 em), como el PDF."""
        total = 0
        for ch in texto:
            gid = self.char_a_gid.get(ch)
            if gid is None:
                raise KeyError(f"el subconjunto no tiene glifo para {ch!r}")
            total += self.anchos.get(gid, 600)
        return float(total)


# ---------------------------------------------------------------------------
# Nombres y búsqueda
# ---------------------------------------------------------------------------

def nombre_base_sin_subset(base_font: str) -> str:
    """'AAAAAA+DejaVuSans' -> 'DejaVuSans'."""
    return re.sub(r"^[A-Z]{6}\+", "", base_font.lstrip("/"))


def _normalizar(nombre: str) -> str:
    return re.sub(r"[^a-z0-9]", "", nombre.lower())


def _candidatos_ordenados(nombre: str) -> list[str]:
    """Nombres de fichero a buscar, del más fiel al menos."""
    n = _normalizar(nombre)
    out = [nombre]
    # variantes habituales de nombre -> fichero
    for variante in (nombre.replace(" ", ""), nombre.replace("-", ""),
                     nombre.split("-")[0]):
        if variante and variante not in out:
            out.append(variante)
    if n.endswith("bold"):
        base = nombre[:-4]
        out.append(base + "-Bold")
    return out


def _directorios() -> list[Path]:
    """Directorios a explorar, incluidos los que declare XDG_DATA_HOME."""
    import os
    out = [Path(d).expanduser() for d in DIRECTORIOS_FUENTES]
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        out.append(Path(xdg) / "fonts")
    xdg_dirs = os.environ.get("XDG_DATA_DIRS", "")
    for d in [x for x in xdg_dirs.split(":") if x]:
        out.append(Path(d) / "fonts")
    # dentro de un Flatpak, el runtime pone sus fuentes en /usr/share/fonts
    # del propio sandbox, ya cubierto arriba
    return [d for d in out if d.is_dir()]


def fuentes_disponibles() -> list[Path]:
    """Todas las fuentes que se pueden usar. Útil para diagnosticar."""
    vistos = set()
    out = []
    for raiz in _directorios():
        for ruta in raiz.rglob("*"):
            if ruta.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            if ruta in vistos:
                continue
            vistos.add(ruta)
            out.append(ruta)
    return sorted(out)


def buscar_fuente_sistema(nombre: str) -> Path | None:
    """Busca un fichero de fuente cuyo nombre case con `nombre`.

    Devuelve None si no lo encuentra. No devuelve "una parecida": un editor que
    cambia la tipografía sin avisar es exactamente el problema que este proyecto
    existe para resolver.
    """
    quiere_bold = "bold" in _normalizar(nombre)
    candidatos = _candidatos_ordenados(nombre)
    encontrados: list[Path] = []

    for raiz in _directorios():
        for ruta in raiz.rglob("*"):
            if ruta.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            tronco = _normalizar(ruta.stem)
            for cand in candidatos:
                if tronco == _normalizar(cand):
                    encontrados.append(ruta)
                    break

    if not encontrados:
        return None

    # preferir el que coincida en "bold" con lo pedido
    for r in encontrados:
        if quiere_bold == ("bold" in _normalizar(r.stem)):
            return r
    return encontrados[0]


# ---------------------------------------------------------------------------
# Subconjunto
# ---------------------------------------------------------------------------

def construir_subconjunto(ruta: Path, texto: str) -> FuenteNueva:
    """Construye un subconjunto de `ruta` con los glifos de `texto`."""
    from fontTools import subset
    from fontTools.ttLib import TTFont

    opciones = subset.Options()
    opciones.layout_features = []          # sin GPOS/GSUB: no hacen falta
    opciones.notdef_outline = True
    opciones.recalc_bounds = True
    opciones.drop_tables += ["FFTM"]
    opciones.name_IDs = ["*"]
    opciones.recommended_glyphs = True

    fuente = subset.load_font(str(ruta), opciones)
    try:
        subsetter = subset.Subsetter(options=opciones)
        subsetter.populate(text=texto)
        subsetter.subset(fuente)
        buffer = io.BytesIO()
        fuente.save(buffer)
        datos = buffer.getvalue()
    finally:
        fuente.close()

    return _leer_subconjunto(datos, nombre_origen=ruta.name)


def _leer_subconjunto(datos: bytes, nombre_origen: str = "") -> FuenteNueva:
    from fontTools.ttLib import TTFont

    ft = TTFont(io.BytesIO(datos))
    try:
        upem = int(ft["head"].unitsPerEm)
        gid_cmap = ft.getBestCmap() or {}
        orden = ft.getGlyphOrder()
        hmtx = ft["hmtx"]

        char_a_gid: dict[str, int] = {}
        gid_a_char: dict[int, str] = {}
        anchos: dict[int, int] = {}
        for codigo, nombre_glifo in gid_cmap.items():
            try:
                gid = orden.index(nombre_glifo)
            except ValueError:
                continue
            char_a_gid[chr(codigo)] = gid
            gid_a_char[gid] = chr(codigo)
            try:
                avance = hmtx[nombre_glifo][0]
            except Exception:
                avance = int(upem * 0.6)
            anchos[gid] = round(avance * 1000.0 / upem)

        head = ft["head"]
        bbox = (int(head.xMin), int(head.yMin), int(head.xMax), int(head.yMax))
        hhea = ft["hhea"]
        ascent = round(int(hhea.ascent) * 1000.0 / upem)
        descent = round(int(hhea.descent) * 1000.0 / upem)
        cap = ascent
        os2 = ft.get("OS/2")
        if os2 is not None and getattr(os2, "sCapHeight", None):
            cap = round(int(os2.sCapHeight) * 1000.0 / upem)
        ital = 0.0
        post = ft.get("post")
        if post is not None:
            ital = float(getattr(post, "italicAngle", 0.0) or 0.0)

        return FuenteNueva(
            ttf=datos, upem=upem, char_a_gid=char_a_gid, gid_a_char=gid_a_char,
            anchos=anchos, bbox=bbox, ascent=ascent, descent=descent,
            cap_height=cap, italic_angle=ital,
            nombre_origen=nombre_origen)
    finally:
        ft.close()


def etiqueta_subconjunto(nombre: str) -> str:
    """Las 6 letras mayúsculas obligatorias del prefijo de subconjunto."""
    h = hashlib.md5(nombre.encode("utf-8")).digest()
    return "".join(chr(65 + (b % 26)) for b in h[:6])


# ---------------------------------------------------------------------------
# Emisión de los objetos PDF
# ---------------------------------------------------------------------------

def cmap_tounicode(fuente: FuenteNueva) -> bytes:
    """CMap /ToUnicode para una fuente Identity-H.

    Sin esto el texto no se puede copiar ni buscar: el lector vería códigos de
    glifo y no caracteres.
    """
    pares = sorted(fuente.gid_a_char.items())
    lineas = [
        b"/CIDInit /ProcSet findresource begin",
        b"12 dict begin",
        b"begincmap",
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) "
        b"/Supplement 0 >> def",
        b"/CMapName /Adobe-Identity-UCS def",
        b"/CMapType 2 def",
        b"1 begincodespacerange",
        b"<0000> <FFFF>",
        b"endcodespacerange",
    ]
    # el formato admite como máximo 100 entradas por bloque
    for i in range(0, len(pares), 100):
        trozo = pares[i:i + 100]
        lineas.append(f"{len(trozo)} beginbfchar".encode("ascii"))
        for gid, ch in trozo:
            destino = ch.encode("utf-16-be").hex().upper()
            lineas.append(f"<{gid:04X}> <{destino}>".encode("ascii"))
        lineas.append(b"endbfchar")
    lineas += [
        b"endcmap",
        b"CMapName currentdict /CMap defineresource pop",
        b"end",
        b"end",
    ]
    return b"\n".join(lineas) + b"\n"


def _formatear_w(anchos: dict[int, int]) -> bytes:
    """Array /W en formato disperso: [c [w1 w2 ...] ...]."""
    if not anchos:
        return b"[]"
    gids = sorted(anchos)
    partes: list[bytes] = []
    inicio = previo = gids[0]
    grupo = [anchos[gids[0]]]
    for g in gids[1:]:
        if g == previo + 1:
            grupo.append(anchos[g])
        else:
            partes.append(f"{inicio} [".encode() +
                          b" ".join(str(w).encode() for w in grupo) + b"]")
            inicio = g
            grupo = [anchos[g]]
        previo = g
    partes.append(f"{inicio} [".encode() +
                  b" ".join(str(w).encode() for w in grupo) + b"]")
    return b"[ " + b" ".join(partes) + b" ]"


def objetos_fuente(fuente: FuenteNueva, base_font: str,
                   ref_fontfile: str, ref_tounicode: str) -> bytes:
    """El diccionario Type0 con el CIDFont y el descriptor incrustados.

    Todo va directo dentro del diccionario de fuentes menos los dos streams
    (FontFile2 y ToUnicode), que por definición tienen que ser objetos
    indirectos. Así sólo hacen falta 2 objetos nuevos por fuente.
    """
    etiqueta = etiqueta_subconjunto(base_font + str(sorted(fuente.char_a_gid)))
    nombre = f"{etiqueta}+{base_font}"
    flags = 32 if fuente.es_nonsymbolic else 4
    bbox = fuente.bbox

    return (
        b"<< /Type /Font /Subtype /Type0 /BaseFont /" + nombre.encode() +
        b" /Encoding /Identity-H /DescendantFonts [ "
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /" + nombre.encode() +
        b" /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
        b"/Supplement 0 >>"
        b" /FontDescriptor << /Type /FontDescriptor /FontName /" +
        nombre.encode() +
        b" /Flags " + str(flags).encode() +
        b" /FontBBox [ " + b" ".join(str(v).encode() for v in bbox) + b" ]" +
        b" /Ascent " + str(fuente.ascent).encode() +
        b" /Descent " + str(fuente.descent).encode() +
        b" /CapHeight " + str(fuente.cap_height).encode() +
        b" /ItalicAngle " + f"{fuente.italic_angle:g}".encode() +
        b" /StemV 80 /FontFile2 " + ref_fontfile.encode() + b" >>" +
        b" /DW 1000 /W " + _formatear_w(fuente.anchos) +
        b" >> ]"
        b" /ToUnicode " + ref_tounicode.encode() + b" >>"
    )
