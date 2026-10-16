#!/usr/bin/env python3
"""
Mide el coste de la fase F1 por página.

Lo que importa para la UI no es el total del documento, sino cuánto tarda una
página: abrir, extraer objetos, alinear y renderizar. Si una página tarda más de
~100 ms, la selección se siente lenta al hacer clic.

  python3 tools/benchmark_f1.py
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pikepdf  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402

from nucleo.alinear_texto import alinear, chars_de_pagina  # noqa: E402
from nucleo.fuentes import resolver_fuentes  # noqa: E402
from nucleo.objetos import extraer_objetos  # noqa: E402

CORPUS = Path(__file__).resolve().parent.parent / "corpus"


def medir(ruta: Path, paginas: list[int]) -> dict:
    pdf = pikepdf.open(str(ruta))
    doc = pdfium.PdfDocument(str(ruta))

    t_extract, t_align, t_render, n_obj = [], [], [], []
    for n in paginas:
        pg = pdf.pages[n]

        t0 = time.perf_counter()
        c = pg.get("/Contents")
        datos = (b"\n".join(s.read_bytes() for s in c)
                 if isinstance(c, pikepdf.Array) else c.read_bytes())
        fuentes = resolver_fuentes(pg)
        contenido = extraer_objetos(datos, fuentes)
        t_extract.append((time.perf_counter() - t0) * 1000)
        n_obj.append(len(contenido.objetos))

        t0 = time.perf_counter()
        chars = chars_de_pagina(doc[n].get_textpage())
        alinear(contenido, chars)
        t_align.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        doc[n].render(scale=2.0)
        t_render.append((time.perf_counter() - t0) * 1000)

    pdf.close()
    doc.close()
    return {
        "extract_ms": statistics.median(t_extract),
        "align_ms": statistics.median(t_align),
        "render_ms": statistics.median(t_render),
        "objetos": statistics.median(n_obj),
        "paginas_medidas": len(paginas),
    }


def main() -> int:
    print()
    print(f"  {'archivo':30} {'págs':>5} {'extraer':>9} {'alinear':>9} "
          f"{'render':>9} {'total':>8} {'objetos':>8}")
    print("  " + "-" * 82)

    peor = 0.0
    for ruta in sorted(CORPUS.glob("*.pdf")):
        doc = pdfium.PdfDocument(str(ruta))
        n_total = len(doc)
        doc.close()
        paginas = list(range(min(n_total, 12)))
        r = medir(ruta, paginas)
        total = r["extract_ms"] + r["align_ms"] + r["render_ms"]
        peor = max(peor, total)
        print(f"  {ruta.stem:30} {n_total:>5} {r['extract_ms']:>8.1f}ms "
              f"{r['align_ms']:>8.1f}ms {r['render_ms']:>8.1f}ms "
              f"{total:>7.0f}ms {r['objetos']:>8.0f}")

    print("  " + "-" * 82)
    print(f"  peor página: {peor:.0f} ms")
    print(f"  presupuesto para que se sienta instantáneo: 100 ms")
    print(f"  veredicto: {'pasa' if peor < 300 else 'NO PASA'}"
          f"{'' if peor < 300 else ' — hay que cachear'}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
