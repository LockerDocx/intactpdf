#!/usr/bin/env python3
"""
Inspector de objetos: la demostración visible de la fase F1.

  python3 tools/inspeccionar.py corpus/01_texto_fragmentado.pdf
  python3 tools/inspeccionar.py corpus/04_imagen_smask.pdf --clic 220,660
  python3 tools/inspeccionar.py corpus/03_vectores_clip_degradado.pdf --png /tmp/out.png

Lista los objetos de la página, dice cuáles son editables y por qué no los que
no, resuelve un clic a un objeto, y dibuja las cajas de selección sobre la
página renderizada.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pikepdf  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402

from nucleo.alinear_texto import alinear, chars_de_pagina  # noqa: E402
from nucleo.fuentes import resolver_fuentes  # noqa: E402
from nucleo.geometria import matriz_pagina  # noqa: E402
from nucleo.objetos import (Imagen, Sombreado, TextoRun, Vector,  # noqa: E402
                            extraer_objetos)

COLORES = {
    "texto": (30, 120, 220),
    "imagen": (210, 60, 40),
    "vector": (30, 160, 90),
    "sombreado": (160, 80, 200),
}


def cargar(ruta: Path, num_pagina: int):
    pdf = pikepdf.open(str(ruta))
    pg = pdf.pages[num_pagina]
    c = pg.get("/Contents")
    datos = (b"\n".join(s.read_bytes() for s in c)
             if isinstance(c, pikepdf.Array) else c.read_bytes())
    fuentes = resolver_fuentes(pg)
    contenido = extraer_objetos(datos, fuentes)

    doc = pdfium.PdfDocument(str(ruta))
    page = doc[num_pagina]
    chars = chars_de_pagina(page.get_textpage())
    informe = alinear(contenido, chars)
    return pdf, doc, page, contenido, informe


def dibujar(ruta: Path, num_pagina: int, salida: Path, contenido, page,
            seleccionado=None) -> Path:
    from PIL import ImageDraw

    escala = 2.0
    pil = page.render(scale=escala).to_pil().convert("RGB")
    draw = ImageDraw.Draw(pil)

    mb = list(page.get_mediabox()) if hasattr(page, "get_mediabox") else [0, 0, *page.get_size()]
    rot = page.get_rotation() if hasattr(page, "get_rotation") else 0
    m, _, _ = matriz_pagina(mb, rot)

    def a_pixel(x, y):
        from nucleo.geometria import aplicar
        px, py = aplicar(m, x, y)
        return px * escala, py * escala

    for o in contenido.objetos:
        if o.caja is None:
            continue
        color = COLORES.get(o.tipo, (90, 90, 90))
        x0, y0 = a_pixel(o.caja.x0, o.caja.y1)   # y del PDF va hacia arriba
        x1, y1 = a_pixel(o.caja.x1, o.caja.y0)
        if seleccionado is o:
            draw.rectangle([x0, y0, x1, y1], outline=(255, 170, 0), width=4)
        else:
            draw.rectangle([x0, y0, x1, y1], outline=color, width=1)

    salida.parent.mkdir(parents=True, exist_ok=True)
    pil.save(salida)
    return salida


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pagina", type=int, default=0)
    ap.add_argument("--clic", help="x,y en puntos PDF para resolver una selección")
    ap.add_argument("--png", help="dónde guardar la página con las cajas dibujadas")
    ap.add_argument("--max", type=int, default=25, help="cuántos objetos listar")
    args = ap.parse_args()

    ruta = Path(args.pdf)
    pdf, doc, page, contenido, informe = cargar(ruta, args.pagina)

    print(f"\n{ruta.name} — página {args.pagina + 1}")
    print(f"  objetos: {contenido.resumen()}")
    print(f"  alineación: {informe['runs_alineados']}/{informe['runs']} runs "
          f"({informe['metodo']}), "
          f"{informe.get('chars_sin_posicion', 0)} chars sin posición")
    print()

    sel = None
    if args.clic:
        x, y = (float(v) for v in args.clic.split(","))
        hits = contenido.en_punto(x, y, tolerancia=3.0)
        print(f"  clic en ({x}, {y}) -> {len(hits)} objeto(s)")
        for h in hits:
            print(f"    {h.tipo:10} caja={h.caja}")
        if hits:
            sel = hits[0]
            print(f"    -> seleccionado: {sel.tipo}")
        print()

    print(f"  primeros {min(args.max, len(contenido.objetos))} objetos:")
    print(f"  {'#':>3} {'tipo':10} {'caja':34} {'editable':>9}  detalle")
    for i, o in enumerate(contenido.objetos[:args.max]):
        caja = f"({o.caja.x0:.0f}, {o.caja.y0:.0f}, {o.caja.x1:.0f}, {o.caja.y1:.0f})" \
            if o.caja else "-"
        razones = o.razones_no_editable
        if isinstance(o, TextoRun):
            detalle = repr(o.texto[:34])
            if not o.alineado:
                detalle += f" [{o.motivo_sin_alinear[:28]}]"
        elif isinstance(o, Imagen):
            detalle = f"XObject {o.nombre_xobject}"
        elif isinstance(o, Vector):
            detalle = f"{o.n_segmentos} segmentos, pintado con '{o.operado}'"
        else:
            detalle = getattr(o, "nombre", "")
        marca = "no" if razones else "sí"
        print(f"  {i:>3} {o.tipo:10} {caja:34} {marca:>9}  {detalle}")
        if razones:
            print(f"  {'':>3} {'':10} {'':34} {'':>9}  └─ {'; '.join(razones[:2])}")

    if args.png:
        out = dibujar(ruta, args.pagina, Path(args.png), contenido, page, sel)
        print(f"\n  imagen con las cajas: {out}")

    doc.close()
    pdf.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
