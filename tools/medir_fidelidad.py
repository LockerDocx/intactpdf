#!/usr/bin/env python3
"""
Arnés de fidelidad de IntactPDF.

Mide cuánta diferencia visual introduce una operación sobre un PDF, comparando
el render antes y después. Es el mecanismo que hace creíble la promesa del
proyecto: "cambias una cosa, todo lo demás sigue igual".

Modos (operaciones):
  identidad    -> compara el PDF consigo mismo. Control: debe dar 0 exacto.
  qpdf         -> round-trip lossless con qpdf. Control: debe dar 0 exacto.
  libreoffice  -> PDF -> .odg -> PDF con LibreOffice Draw. Es lo que hace un
                  editor que RECONSTRUYE el documento en vez de editarlo.

Salida: resultados/fidelidad.json + tabla por pantalla.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
RESULTADOS = ROOT / "resultados"
TMP = ROOT / ".tmp"
SCALE = 2.0          # 2x -> ~144 dpi, suficiente para detectar cambios reales
TOL_PX = 12          # diferencia por canal por debajo de esto = mismo píxel


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------
def render_paginas(ruta: Path, max_paginas: int = 12) -> tuple[list[np.ndarray], dict]:
    """Devuelve (arrays HxWx3 uint8, metadatos estructurales)."""
    doc = pdfium.PdfDocument(str(ruta))
    info = {
        "paginas": len(doc),
        "tamanos_pt": [tuple(round(v, 2) for v in doc[i].get_size())
                       for i in range(min(len(doc), max_paginas))],
    }
    frames = []
    for i in range(min(len(doc), max_paginas)):
        page = doc[i]
        pil = page.render(scale=SCALE).to_pil().convert("RGB")
        frames.append(np.asarray(pil, dtype=np.uint8))
    doc.close()
    return frames, info


def diff_frames(a: list[np.ndarray], b: list[np.ndarray]) -> dict:
    """Compara dos listas de renders. Si difieren en número o tamaño, lo reporta."""
    out = {
        "mismo_numero_paginas": len(a) == len(b),
        "paginas_comparadas": min(len(a), len(b)),
        "paginas_con_diferencias": 0,
        "peor_pct_pixeles_distintos": 0.0,
        "peor_diff_max_canal": 0,
        "media_diff_absoluta": 0.0,
        "pct_medio_pixeles_distintos": 0.0,
        "diferencia_de_tamano_en_alguna_pagina": False,
        "por_pagina": [],
    }
    diffs_abs = []
    for i in range(out["paginas_comparadas"]):
        fa, fb = a[i], b[i]
        if fa.shape != fb.shape:
            out["diferencia_de_tamano_en_alguna_pagina"] = True
            h = min(fa.shape[0], fb.shape[0])
            w = min(fa.shape[1], fb.shape[1])
            fa, fb = fa[:h, :w], fb[:h, :w]
            recorte = {"pagina": i + 1, "recortado": True,
                       "shape_a": list(a[i].shape), "shape_b": list(b[i].shape)}
        else:
            recorte = {"pagina": i + 1, "recortado": False}

        d = np.abs(fa.astype(np.int16) - fb.astype(np.int16))
        maxcanal = d.max(axis=2)
        distintos = maxcanal > TOL_PX
        pct = float(distintos.mean() * 100.0)
        recorte.update({
            "pct_pixeles_distintos": round(pct, 3),
            "diff_max_canal": int(d.max()),
            "diff_media_abs": round(float(d.mean()), 3),
        })
        out["por_pagina"].append(recorte)
        diffs_abs.append(float(d.mean()))
        if distintos.any():
            out["paginas_con_diferencias"] += 1
        out["peor_pct_pixeles_distintos"] = max(out["peor_pct_pixeles_distintos"], pct)
        out["peor_diff_max_canal"] = max(out["peor_diff_max_canal"], int(d.max()))

    if diffs_abs:
        out["media_diff_absoluta"] = round(sum(diffs_abs) / len(diffs_abs), 3)
        out["pct_medio_pixeles_distintos"] = round(
            sum(p["pct_pixeles_distintos"] for p in out["por_pagina"]) / len(out["por_pagina"]), 3)
    out["veredicto"] = (
        "IDENTICO" if out["paginas_con_diferencias"] == 0
        and not out["diferencia_de_tamano_en_alguna_pagina"]
        and out["mismo_numero_paginas"]
        else ("CAMBIOS_MENORES" if out["peor_pct_pixeles_distintos"] < 1.0
              else "RECONSTRUIDO"))
    return out


# --------------------------------------------------------------------------
# operaciones
# --------------------------------------------------------------------------
def op_identidad(src: Path) -> Path:
    return src


def op_qpdf(src: Path, dst: Path) -> Path:
    subprocess.run(["qpdf", "--qdf", str(src), str(dst)], check=True,
                   capture_output=True, timeout=300)
    return dst


def op_libreoffice(src: Path, dst: Path) -> Path:
    """PDF -> .odg -> PDF. El camino de un editor que reconstruye el documento."""
    work = TMP / f"lo_{src.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    env = {"HOME": str(TMP), "PATH": "/usr/bin:/bin"}
    subprocess.run(
        ["soffice", "--headless", "--norestore", "-env:UserInstallation="
         f"file://{work}/profile", "--convert-to", "odg", "--outdir", str(work), str(src)],
        check=True, capture_output=True, timeout=900, env=env)
    odg = work / f"{src.stem}.odg"
    if not odg.exists():
        raise RuntimeError(f"LibreOffice no produjo .odg para {src.name}")
    subprocess.run(
        ["soffice", "--headless", "--norestore", "-env:UserInstallation="
         f"file://{work}/profile", "--convert-to", "pdf", "--outdir", str(work), str(odg)],
        check=True, capture_output=True, timeout=900, env=env)
    pdf_out = work / f"{src.stem}.pdf"
    if not pdf_out.exists():
        raise RuntimeError(f"LibreOffice no produjo .pdf para {src.name}")
    shutil.copy(pdf_out, dst)
    return dst


# --------------------------------------------------------------------------
# estructura: cuenta cajas de texto antes/después (la firma de la fragmentación)
# --------------------------------------------------------------------------
def contar_textos(ruta: Path, max_paginas: int = 12) -> dict:
    doc = pdfium.PdfDocument(str(ruta))
    n_chars, n_segs = 0, 0
    for i in range(min(len(doc), max_paginas)):
        tp = doc[i].get_textpage()
        n_chars += tp.count_chars()
        n_segs += tp.count_segments() if hasattr(tp, "count_segments") else 0
    doc.close()
    return {"chars": n_chars, "segmentos": n_segs}


def extraer_texto(ruta: Path, max_paginas: int = 4) -> str:
    doc = pdfium.PdfDocument(str(ruta))
    partes = []
    for i in range(min(len(doc), max_paginas)):
        partes.append(doc[i].get_textpage().get_text_bounded())
    doc.close()
    return "\n".join(partes)


# --------------------------------------------------------------------------
def main() -> None:
    RESULTADOS.mkdir(exist_ok=True)
    TMP.mkdir(exist_ok=True)
    ops = [("identidad", op_identidad), ("qpdf", op_qpdf), ("libreoffice", op_libreoffice)]

    archivos = sorted(CORPUS.glob("*.pdf"))
    resultados = []

    for src in archivos:
        # el documento de 300 páginas solo se prueba con las ops baratas
        baratas = [o for o in ops if not (src.name.startswith("09_") and o[0] == "libreoffice")]
        antes, info_antes = render_paginas(src)
        txt_antes = contar_textos(src)

        for nombre, fn in baratas:
            t0 = time.time()
            try:
                if nombre == "identidad":
                    dst = fn(src)
                else:
                    dst = TMP / f"{src.stem}__{nombre}.pdf"
                    fn(src, dst)
                despues, info_despues = render_paginas(dst)
                d = diff_frames(antes, despues)
                txt_despues = contar_textos(dst)
                res = {
                    "archivo": src.name,
                    "operacion": nombre,
                    "segundos": round(time.time() - t0, 1),
                    "tam_bytes_antes": src.stat().st_size,
                    "tam_bytes_despues": dst.stat().st_size,
                    "estructura_antes": info_antes,
                    "estructura_despues": info_despues,
                    "chars_texto_antes": txt_antes["chars"],
                    "chars_texto_despues": txt_despues["chars"],
                    **d,
                }
            except subprocess.TimeoutExpired:
                res = {"archivo": src.name, "operacion": nombre,
                       "segundos": round(time.time() - t0, 1), "error": "timeout"}
            except Exception as e:
                res = {"archivo": src.name, "operacion": nombre,
                       "segundos": round(time.time() - t0, 1),
                       "error": f"{type(e).__name__}: {e}"}
            resultados.append(res)
            if "error" in res:
                print(f"  {src.name:34} {nombre:12} ERROR {res['error'][:70]}")
            else:
                print(f"  {src.name:34} {nombre:12} {res['veredicto']:16} "
                      f"peor={res['peor_pct_pixeles_distintos']:7.3f}% px | "
                      f"págs dif={res['paginas_con_diferencias']}/{res['paginas_comparadas']} | "
                      f"{res['segundos']}s")

    (RESULTADOS / "fidelidad.json").write_text(
        json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")

    # muestra de texto antes/después para el caso fragmentado
    frag = CORPUS / "01_texto_fragmentado.pdf"
    lo = TMP / "01_texto_fragmentado__libreoffice.pdf"
    if frag.exists() and lo.exists():
        muestra = {
            "original": extraer_texto(frag, 1)[:400],
            "tras_libreoffice": extraer_texto(lo, 1)[:400],
        }
        (RESULTADOS / "muestra_texto.json").write_text(
            json.dumps(muestra, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nresultados/fidelidad.json con {len(resultados)} mediciones")


if __name__ == "__main__":
    main()
