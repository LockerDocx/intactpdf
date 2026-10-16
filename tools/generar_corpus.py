#!/usr/bin/env python3
"""
Genera el corpus dorado de PDFs difíciles para IntactPDF.

Cada PDF del corpus ataca un punto débil distinto del formato. El objetivo NO es
tener PDFs bonitos: es tener PDFs donde un editor que "reconstruye" el documento
se rompa, y uno que edite in-place no.

Salida: corpus/*.pdf + corpus/manifest.json
"""
from __future__ import annotations

import io
import json
import os
import random
import zlib
from pathlib import Path

from PIL import Image
from reportlab.lib.colors import CMYKColor, Color
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
CORPUS.mkdir(exist_ok=True)

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
pdfmetrics.registerFont(TTFont("DV", DEJAVU))
pdfmetrics.registerFont(TTFont("DVB", DEJAVU_B))

SAMPLE = ("El rápido zorro ñandú saltó sobre el perro perezoso mientras "
          "ÄÖÜ äöü ß € £ ¥ © § ± ¼ ½ ¾ «» — – …")


# --------------------------------------------------------------------------
# helpers de imagen
# --------------------------------------------------------------------------
def _rgb_noise(seed: int, w: int = 320, h: int = 220) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (
                (x * 3 + y) % 256,
                (rnd.randrange(256) + x) % 256,
                (255 - (x + y) % 256),
            )
    return img


def _rgba_with_alpha(seed: int, w: int = 300, h: int = 200) -> Image.Image:
    """Imagen con canal alfa real -> obliga a usar SMask en el PDF."""
    rnd = random.Random(seed)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        for x in range(w):
            a = 255 if (x // 8 + y // 8) % 2 == 0 else 90
            px[x, y] = (rnd.randrange(256), 120, (x * 5) % 256, a)
    return img


def _cmyk_image(seed: int, w: int = 320, h: int = 200) -> Image.Image:
    """JPEG CMYK: el caso típico de PDF de imprenta."""
    rnd = random.Random(seed)
    img = Image.new("CMYK", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (rnd.randrange(256), (x * 2) % 256, (y * 3) % 256, 40)
    return img


def _save(img: Image.Image, name: str, **kw) -> str:
    p = CORPUS / name
    img.save(p, **kw)
    return str(p)


# --------------------------------------------------------------------------
# generadores de casos
# --------------------------------------------------------------------------
def case_baseline() -> str:
    """00 — Control. Un PDF trivial que TODO editor debe pasar sin tocar un píxel."""
    out = CORPUS / "00_baseline.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("DV", 16)
    c.drawString(72, 780, "Documento de control: texto simple, sin trampas.")
    c.setFont("DV", 11)
    c.drawString(72, 740, SAMPLE)
    c.showPage()
    c.save()
    return str(out)


def case_fragmented_text() -> str:
    """01 — Texto fragmentado: una línea visible dividida en decenas de objetos.

    Así llegan los PDFs de Word/Acrobat con kerning manual. Es el caso que hace
    que LibreOffice Draw convierta cada pedazo en una caja de texto separada.
    """
    out = CORPUS / "01_texto_fragmentado.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("DV", 13)
    y = 780
    rnd = random.Random(7)
    for n_linea in range(18):
        t = c.beginText(72, y)
        frase = SAMPLE
        # emitimos la frase letra a letra / palabra a palabra, con avances
        # manuales: el resultado visual es una línea, el PDF son N objetos
        for i, ch in enumerate(frase):
            t.textOut(ch)
            t.setCharSpace(rnd.choice([0.0, 0.0, 0.35, -0.15]))
        c.drawText(t)
        y -= 34
    c.showPage()
    c.save()
    return str(out)


def case_subset_font() -> str:
    """02 — Fuentes incrustadas subconjuntadas.

    Si el PDF solo incrusta los glifos usados, cualquier letra nueva que el
    usuario escriba NO se puede pintar. Este es el límite duro de editar texto.
    """
    out = CORPUS / "02_fuente_subset.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setPageCompression(0)
    c.setFont("DV", 18)
    c.drawString(72, 780, "Solo aparecen estas letras: aeoiu")
    c.setFont("DVB", 24)
    c.drawString(72, 730, "aeiou")
    c.setFont("DV", 11)
    c.drawString(72, 690, "Prueba: escribe aquí una 'ñ', una 'W' o una '€'.")
    c.drawString(72, 670, "Si la fuente está subconjuntada, ese glifo no existe en el PDF.")
    c.showPage()
    c.save()
    return str(out)


def case_clip_and_shading() -> str:
    """03 — Vectores con clip path y degradado.

    Redimensionar un vector cuyo recorte vive en otro objeto es el caso difícil
    de RF4 (redimensionar).
    """
    out = CORPUS / "03_vectores_clip_degradado.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)

    # degradado por bandas dentro de un clip circular
    p = c.beginPath()
    p.circle(200, 620, 95)
    c.saveState()
    c.clipPath(p, stroke=0, fill=0)
    for i in range(60):
        c.setFillColor(Color(i / 60.0, 0.25, 1 - i / 60.0))
        c.rect(105, 525 + i * 3.2, 190, 3.4, stroke=0, fill=1)
    c.restoreState()
    c.setStrokeColor(Color(0, 0, 0))
    c.setLineWidth(1.2)
    c.circle(200, 620, 95, stroke=1, fill=0)

    # trazados complejos: estrella de muchos segmentos
    c.setFillColor(Color(0.9, 0.6, 0.05))
    p2 = c.beginPath()
    import math
    for k in range(14):
        ang = math.pi * 2 * k / 14
        r = 70 if k % 2 == 0 else 28
        x, y = 430 + math.cos(ang) * r, 620 + math.sin(ang) * r
        if k == 0:
            p2.moveTo(x, y)
        else:
            p2.lineTo(x, y)
    p2.close()
    c.drawPath(p2, stroke=1, fill=1)

    c.setFillColor(Color(0, 0, 0))
    c.setFont("DV", 10)
    c.drawString(72, 500, "Izquierda: degradado dentro de un clip circular.")
    c.drawString(72, 484, "Derecha: trazado de 14 segmentos.")
    c.drawString(72, 460, "Redimensionar cualquiera de los dos exige transformar también su recorte.")
    c.showPage()
    c.save()
    return str(out)


def case_smask_image() -> str:
    """04 — Imagen con máscara de transparencia (SMask)."""
    out = CORPUS / "04_imagen_smask.pdf"
    png = _save(_rgba_with_alpha(11), "_tmp_smask.png")
    c = canvas.Canvas(str(out), pagesize=A4)
    c.drawImage(png, 72, 560, width=300, height=200, mask='auto')
    c.setFillColor(Color(0, 0, 0))
    c.setFont("DV", 11)
    c.drawString(72, 530, "Imagen RGBA: el canal alfa viaja como SMask en el PDF.")
    c.drawString(72, 514, "Un editor que pierda el SMask convierte el fondo en negro o blanco.")
    c.showPage()
    c.save()
    return str(out)


def case_cmyk() -> str:
    """05 — CMYK (PDF de imprenta)."""
    out = CORPUS / "05_cmyk_imprenta.pdf"
    jpg = _save(_cmyk_image(23), "_tmp_cmyk.jpg", quality=90)
    c = canvas.Canvas(str(out), pagesize=A4)
    c.drawImage(jpg, 72, 580, width=320, height=200)
    c.setFillColor(CMYKColor(0.1, 0.85, 0.9, 0.0))
    c.rect(72, 540, 320, 26, stroke=0, fill=1)
    c.setFillColor(CMYKColor(0, 0, 0, 1))
    c.setFont("DV", 10)
    c.drawString(72, 512, "Imagen JPEG CMYK + relleno CMYK.")
    c.drawString(72, 496, "Muchos editores convierten a RGB al guardar y cambian los colores.")
    c.showPage()
    c.save()
    return str(out)


def case_text_modes() -> str:
    """06 — Modos de renderizado de texto raros: invisible, recortado, trazado.

    reportlab no expone el operador Tr, así que se inyecta directamente en el
    stream. Verificado: el PDF resultante contiene `1 Tr` y `3 Tr`.
    """
    out = CORPUS / "06_modos_de_texto.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("DV", 14)

    c.drawString(72, 780, "Modo 0 — relleno normal (este se ve).")

    # Modo 3: texto invisible. No se ve, pero está ahí y se puede seleccionar.
    c.saveState()
    c._code.append("3 Tr")
    c.drawString(72, 750, "Modo 3 — texto invisible pero seleccionable y copiable.")
    c._code.append("0 Tr")
    c.restoreState()

    # Modo 1: solo contorno.
    c.setLineWidth(0.7)
    c.setStrokeColor(Color(0.8, 0.1, 0.1))
    c.saveState()
    c._code.append("1 Tr")
    c.drawString(72, 720, "Modo 1 — solo contorno, sin relleno.")
    c._code.append("0 Tr")
    c.restoreState()

    # Modo 2: relleno + contorno.
    c.saveState()
    c._code.append("2 Tr")
    c.setFillColor(Color(1.0, 0.85, 0.2))
    c.setFont("DVB", 20)
    c.drawString(72, 680, "Modo 2 — relleno y contorno.")
    c._code.append("0 Tr")
    c.restoreState()

    # Texto recortado por un clip path.
    c.saveState()
    p = c.beginPath()
    p.rect(72, 628, 220, 22)
    c.clipPath(p, stroke=0, fill=0)
    c.setFont("DVB", 40)
    c.drawString(72, 628, "RECORTADO")
    c.restoreState()

    c.setFillColor(Color(0, 0, 0))
    c.setFont("DV", 10)
    c.drawString(72, 580, "Un editor que normalice los modos de texto destruye esta página.")
    c.showPage()
    c.save()
    return str(out)


def pdf_w_array(pdf, usados, ancho):
    """Construye el array /W de un CIDFont: [gid [ancho1 ancho2 ...] ...]."""
    import pikepdf
    gids = sorted(usados)
    out = pikepdf.Array()
    i = 0
    while i < len(gids):
        j = i
        while j + 1 < len(gids) and gids[j + 1] == gids[j] + 1:
            j += 1
        out.append(gids[i])
        out.append(pikepdf.Array([ancho(g) for g in gids[i:j + 1]]))
        i = j + 1
    return out


def case_full_font() -> str:
    """10 — Fuente incrustada COMPLETA, sin subconjuntar.

    El otro extremo del caso 02. Aquí sí hay glifos de sobra.

    reportlab 5 no permite incrustar una TTF sin subconjuntar (TTFont siempre es
    "dynamic font"), así que este PDF se construye a mano: CIDFontType2 con
    Identity-H y el FontFile2 completo. Los IDs de glifo salen del cmap de la
    fuente vía fontTools, que es exactamente lo que tendría que hacer un editor
    para escribir texto nuevo en un PDF.
    """
    import pikepdf
    from fontTools.ttLib import TTFont as FTFont

    out = CORPUS / "10_fuente_completa.pdf"
    lineas = [
        (72, 760, 18.0, "Fuente incrustada completa, sin subconjuntar: aeoiu"),
        (72, 720, 12.0, "Aqui si se podria escribir una W, una Q o un signo de euro:"),
        (72, 700, 12.0, "todos los glifos estan dentro del PDF, no hace falta re-subsetting."),
    ]

    ft = FTFont(DEJAVU)
    cmap = ft.getBestCmap()                      # unicode -> nombre de glifo
    orden = ft.getGlyphOrder()                   # posición == GID
    gid_de_nombre = {n: i for i, n in enumerate(orden)}
    hhea = ft["hhea"]
    hmtx = ft["hmtx"]
    os2 = ft["OS/2"]
    units = ft["head"].unitsPerEm
    nombre_ps = ft["name"].getDebugName(6) or "DejaVuSans"

    def ancho(gid: int) -> int:
        """Ancho del glifo en unidades de 1/1000 de em (lo que espera /W)."""
        nombre = orden[gid] if 0 <= gid < len(orden) else orden[0]
        return int(round(hmtx[nombre][0] * 1000 / units))

    ops = []
    usados = {}          # gid -> chr, para construir el ToUnicode
    for x, y, size, texto in lineas:
        gids = [gid_de_nombre.get(cmap.get(ord(ch), ""), 0) for ch in texto]
        for ch, g in zip(texto, gids):
            usados[g] = ch
        hexstr = "".join(f"{g:04X}" for g in gids)
        ops.append(f"BT /F1 {size} Tf 1 0 0 1 {x} {y} Tm <{hexstr}> Tj ET".encode())
    contenido = b"\n".join(ops)

    # Sin ToUnicode ningún extractor de texto puede mapear glifos -> caracteres.
    # Es un caso muy común en PDFs reales, pero aquí lo queremos limpio.
    bfchar = "\n".join(f"<{g:04X}> <{ord(ch):04X}>" for g, ch in sorted(usados.items()))
    tounicode = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"{len(usados)} beginbfchar\n{bfchar}\nendbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode()

    pdf = pikepdf.new()
    datos_ttf = open(DEJAVU, "rb").read()
    ff2 = pdf.make_stream(zlib.compress(datos_ttf, 9))
    ff2.Filter = pikepdf.Name("/FlateDecode")
    ff2.Length1 = len(datos_ttf)      # longitud del TTF SIN comprimir

    fd = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/FontDescriptor"),
        FontName=pikepdf.Name(f"/{nombre_ps}"),
        Flags=4 | 32,
        FontBBox=[int(ft["head"].xMin), int(ft["head"].yMin),
                  int(ft["head"].xMax), int(ft["head"].yMax)],
        ItalicAngle=0,
        Ascent=int(hhea.ascent),
        Descent=int(hhea.descent),
        CapHeight=int(getattr(os2, "sCapHeight", 729)),
        StemV=80,
        FontFile2=ff2,
    ))
    desc = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/Font"),
        Subtype=pikepdf.Name("/CIDFontType2"),
        BaseFont=pikepdf.Name(f"/{nombre_ps}"),
        CIDSystemInfo=pdf.make_indirect(pikepdf.Dictionary(
            Registry=pikepdf.String("Adobe"),
            Ordering=pikepdf.String("Identity"),
            Supplement=0,
        )),
        FontDescriptor=fd,
        DW=ancho(0),
        W=pdf_w_array(pdf, usados, ancho),
    ))
    tu = pdf.make_stream(tounicode)
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/Font"),
        Subtype=pikepdf.Name("/Type0"),
        BaseFont=pikepdf.Name(f"/{nombre_ps}"),
        Encoding=pikepdf.Name("/Identity-H"),
        DescendantFonts=pikepdf.Array([desc]),
        ToUnicode=tu,
    ))
    cs = pdf.make_stream(contenido)
    page = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=[0, 0, 595.276, 841.89],
        Resources=pdf.make_indirect(pikepdf.Dictionary(
            Font=pdf.make_indirect(pikepdf.Dictionary(F1=font)))),
        Contents=cs,
    ))
    pdf.pages.append(pikepdf.Page(page))
    pdf.save(str(out))
    pdf.close()
    ft.close()
    return str(out)


def case_mixed_pages() -> str:
    """07 — Páginas rotadas y tamaños mezclados."""
    out = CORPUS / "07_paginas_rotadas_mixtas.pdf"
    sizes = [A4, landscape(A4), A5, landscape(A5), A4]
    c = canvas.Canvas(str(out))
    for i, sz in enumerate(sizes):
        c.setPageSize(sz)
        c.setFont("DV", 12)
        c.drawString(40, sz[1] - 40, f"Página {i + 1} — {int(sz[0])}x{int(sz[1])} pt")
        if i % 2:
            c.saveState()
            c.translate(sz[0] / 2, sz[1] / 2)
            c.rotate(12)
            c.setFont("DV", 18)
            c.drawCentredString(0, 0, "contenido girado en el stream")
            c.restoreState()
        c.showPage()
    c.save()

    # añade /Rotate 90 real a una página (distinto de girar en el stream)
    import pikepdf
    pdf = pikepdf.open(str(out), allow_overwriting_input=True)
    pdf.pages[2].Rotate = 90
    pdf.save(str(out))
    pdf.close()
    return str(out)


def case_forms_annots() -> str:
    """08 — Formularios AcroForm + anotaciones + enlaces."""
    out = CORPUS / "08_formularios_anotaciones.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("DV", 11)
    c.drawString(72, 780, "Este PDF tiene campos de formulario y anotaciones.")
    c.drawString(72, 760, "Editar el contenido NO debe romperlos.")

    form = c.acroForm
    form.textfield(name="nombre", x=72, y=700, width=220, height=20,
                   borderWidth=1, fillColor=Color(0.95, 0.95, 1.0))
    form.textfield(name="importe", x=72, y=665, width=120, height=20, borderWidth=1)
    form.checkbox(name="acepto", x=72, y=630, size=16, borderWidth=1)
    c.drawString(96, 632, "Acepto las condiciones")

    c.linkURL("https://example.com", (72, 580, 220, 600), thickness=1)
    c.drawString(72, 584, "enlace a example.com")

    c.showPage()
    c.save()
    return str(out)


def case_grande(n: int = 300) -> str:
    """09 — Documento grande, para medir rendimiento."""
    out = CORPUS / "09_documento_grande.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("DV", 10)
    for i in range(n):
        y = 800
        c.setFont("DVB", 14)
        c.drawString(72, y, f"Página {i + 1} de {n}")
        c.setFont("DV", 9)
        y -= 26
        for j in range(38):
            c.drawString(72, y, f"{i + 1}.{j + 1}  " + SAMPLE[:70])
            y -= 18
        c.showPage()
    c.save()
    return str(out)


def case_texto_transformado() -> str:
    """11 — Texto dentro de matrices escaladas y rotadas.

    Por qué existe. Todo el resto del corpus escribe el texto con la matriz
    identidad, y eso escondía un error de fondo: el operador `Tc` no se mide en
    puntos de página sino en el espacio de TEXTO, así que bajo un `cm` con
    escala el ajuste de espaciado se queda corto o se pasa por ese factor. El
    mismo error que mandaba una imagen a 29.000 pt de su sitio al moverla.

    Lo que tiene que poder hacerse aquí, y se comprueba en los tests:
      - editar el texto de un run escalado x2 (nivel 1b o 2),
      - conservar el ancho EN LA PÁGINA con --ajustar,
      - y hacerlo también con el run rotado 30 grados.
    """
    out = CORPUS / "11_texto_transformado.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)

    c.setFont("Helvetica", 8)
    c.drawString(72, 800, "Control: texto sin transformar, matriz identidad.")

    # --- run bajo un cm con escala 2: 8 pt de fuente son 16 pt en la página
    c.saveState()
    c.scale(2, 2)
    c.setFont("DV", 8)
    c.drawString(36, 360, "Escalado x2: texto dentro de una matriz")
    c.restoreState()

    # --- run bajo un cm con escala 0.5
    c.saveState()
    c.scale(0.5, 0.5)
    c.setFont("DV", 20)
    c.drawString(144, 900, "Escalado x0.5 con fuente grande")
    c.restoreState()

    # --- run rotado 30 grados (la escala se conserva, la base no)
    c.saveState()
    c.translate(110, 300)
    c.rotate(30)
    c.setFont("DV", 11)
    c.drawString(0, 0, "Rotado treinta grados con acentos: camion, nino")
    c.restoreState()

    # --- run con la matriz del texto (Tm) escalada, no el CTM
    c.saveState()
    c.setFont("DV", 10)
    c.transform(1.8, 0, 0, 1.8, 72, 520)
    c.drawString(0, 0, "Matriz del texto escalada x1.8")
    c.restoreState()

    c.showPage()
    c.save()
    return str(out)


CASES = [
    ("00_baseline", case_baseline,
     "Control. PDF trivial: cualquier edición debe dejarlo byte a byte igual salvo lo tocado."),
    ("01_texto_fragmentado", case_fragmented_text,
     "Una línea visible dividida en decenas de operadores de texto con charSpace manual."),
    ("02_fuente_subset", case_subset_font,
     "Fuentes TTF incrustadas; solo contiene los glifos usados. Bloquea escribir caracteres nuevos."),
    ("03_vectores_clip_degradado", case_clip_and_shading,
     "Degradado dentro de un clip circular + trazado de 14 segmentos."),
    ("04_imagen_smask", case_smask_image,
     "Imagen RGBA: el alfa viaja como SMask. Perderlo cambia el fondo."),
    ("05_cmyk_imprenta", case_cmyk,
     "JPEG CMYK y rellenos CMYK. Convertir a RGB al guardar cambia los colores."),
    ("06_modos_de_texto", case_text_modes,
     "Texto invisible (Tr 3), solo contorno (Tr 1) y texto recortado por clip."),
    ("07_paginas_rotadas_mixtas", case_mixed_pages,
     "Tamaños mezclados, rotación dentro del stream y /Rotate 90 a nivel de página."),
    ("08_formularios_anotaciones", case_forms_annots,
     "AcroForm con campos, checkbox y enlace. Editar contenido no debe romperlos."),
    ("09_documento_grande", case_grande,
     "300 páginas para medir tiempo de apertura y memoria."),
    ("10_fuente_completa", case_full_font,
     "Fuente TTF incrustada completa (subset=0). El opuesto del caso 02."),
    ("11_texto_transformado", case_texto_transformado,
     "Texto bajo cm escalado x2 y x0.5, rotado 30 grados y con Tm escalada."),
]


def main() -> None:
    manifest = []
    for nombre, fn, desc in CASES:
        ruta = fn()
        size = os.path.getsize(ruta)
        manifest.append({
            "id": nombre,
            "archivo": os.path.basename(ruta),
            "descripcion": desc,
            "bytes": size,
        })
        print(f"  {os.path.basename(ruta):34} {size/1024:8.1f} KiB   {desc[:58]}")

    (CORPUS / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(manifest)} PDFs generados en {CORPUS}")


if __name__ == "__main__":
    main()
