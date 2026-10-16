#!/usr/bin/env python3
"""
Perfilador del corpus: mide objetivamente la dificultad de cada PDF.

No se fía de las etiquetas del generador: lee el PDF y cuenta lo que hay.
Salida: corpus/perfil.json + tabla por pantalla.
"""
from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

import pikepdf
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"

OP_TEXTO = re.compile(rb"\b(Tj|TJ|'|\"|T\*)\b")
OP_PINTADO = re.compile(rb"\b(re|l|c|v|y|f|f\*|B|B\*|b|b\*|S|s|Do|sh)\b")
OP_CLIP = re.compile(rb"\b(W|W\*)\b")


def _streams(pdf: pikepdf.Pdf) -> list[bytes]:
    """Contenido descomprimido de todos los streams del documento."""
    out = []
    for obj in pdf.objects:
        try:
            if isinstance(obj, pikepdf.Stream):
                out.append(obj.read_bytes())
        except Exception:
            continue
    return out


def _contenido_pagina(pagina) -> bytes:
    """Contenido descomprimido de UNA página (solo el content stream)."""
    try:
        contenido = pagina.get("/Contents")
    except Exception:
        return b""
    if contenido is None:
        return b""
    try:
        if isinstance(contenido, pikepdf.Array):
            return b"\n".join(s.read_bytes() for s in contenido)
        return contenido.read_bytes()
    except Exception:
        return b""


def _recorrer_xobjects(node, pdf, visto=None):
    """Devuelve (imagenes, smasks, colorspaces) recorriendo los recursos."""
    if visto is None:
        visto = set()
    imgs, smasks, cspaces = [], [], set()
    if node is None or id(node) in visto:
        return imgs, smasks, cspaces
    visto.add(id(node))
    try:
        res = node.get("/Resources")
    except Exception:
        res = None
    if res is None:
        return imgs, smasks, cspaces

    xo = res.get("/XObject")
    if xo is not None:
        for nombre, ref in xo.items():
            try:
                o = ref
                sub = o.get("/Subtype")
                if sub == "/Image":
                    cs = o.get("/ColorSpace")
                    cs_name = str(cs) if not isinstance(cs, pikepdf.Array) else str(cs[0])
                    imgs.append({
                        "nombre": str(nombre),
                        "w": int(o.get("/Width", 0)),
                        "h": int(o.get("/Height", 0)),
                        "bpc": int(o.get("/BitsPerComponent", 0)),
                        "colorspace": cs_name,
                        "filtro": str(o.get("/Filter")),
                        "tiene_smask": "/SMask" in o.keys(),
                    })
                    cspaces.add(cs_name)
                    if "/SMask" in o.keys():
                        smasks.append(str(nombre))
                elif sub == "/Form":
                    i2, s2, c2 = _recorrer_xobjects(o, pdf, visto)
                    imgs += i2
                    smasks += s2
                    cspaces |= c2
            except Exception:
                continue
    return imgs, smasks, cspaces


def perfilar(ruta: Path) -> dict:
    pdf = pikepdf.open(str(ruta))
    lector = PdfReader(str(ruta))

    # IMPORTANTE: contar solo sobre el content stream de cada página.
    # Contar sobre TODOS los streams da falsos positivos: los datos binarios
    # de las imágenes contienen bytes que coinciden con nombres de operador.
    contenidos = [_contenido_pagina(p) for p in pdf.pages]

    n_ops_texto = sum(len(OP_TEXTO.findall(c)) for c in contenidos)
    n_ops_pintado = sum(len(OP_PINTADO.findall(c)) for c in contenidos)
    n_ops_clip = sum(len(OP_CLIP.findall(c)) for c in contenidos)

    # fuentes
    fuentes = []
    try:
        for i, pagina in enumerate(lector.pages):
            res = pagina.get("/Resources")
            if res is None:
                continue
            fd = res.get("/Font")
            if fd is None:
                continue
            for fname, fref in fd.items():
                f = fref.get_object()
                desc = None
                for clave in ("/FontDescriptor", "/DescendantFonts"):
                    if clave in f:
                        v = f[clave].get_object()
                        if clave == "/DescendantFonts":
                            v = v[0].get_object().get("/FontDescriptor")
                            if v is not None:
                                v = v.get_object()
                        desc = v
                        break
                incrustada = False
                subset = False
                if desc is not None:
                    for k in ("/FontFile", "/FontFile2", "/FontFile3"):
                        if k in desc:
                            incrustada = True
                nombre = str(f.get("/BaseFont", "?"))
                # convención de subconjunto: prefijo de 6 mayúsculas + '+'
                base = nombre.split("/")[-1]
                subset = bool(re.match(r"^[A-Z]{6}\+", base))
                fuentes.append({
                    "pagina": i,
                    "nombre": nombre,
                    "subtipo": str(f.get("/Subtype")),
                    "incrustada": incrustada,
                    "prefijo_subset": subset,
                })
    except Exception as e:
        fuentes = [{"error": str(e)}]

    # imágenes
    imgs, smasks, cspaces = [], [], set()
    for pagina in pdf.pages:
        i2, s2, c2 = _recorrer_xobjects(pagina, pdf)
        imgs += i2
        smasks += s2
        cspaces |= c2

    # fragmentación: trozos de texto por página (sobre el content stream)
    frags_por_pagina = [len(OP_TEXTO.findall(c)) for c in contenidos]

    # formas acroform / anotaciones / enlaces
    n_annots = 0
    for pagina in pdf.pages:
        try:
            a = pagina.get("/Annots")
            if a is not None:
                n_annots += len(a)
        except Exception:
            pass
    tiene_acroform = "/AcroForm" in pdf.Root.keys()
    rotaciones = [int(p.get("/Rotate", 0)) for p in pdf.pages]

    return {
        "archivo": ruta.name,
        "bytes": ruta.stat().st_size,
        "paginas": len(pdf.pages),
        "tam_paginas_pt": sorted({(round(float(p.MediaBox[2] - p.MediaBox[0]), 1),
                                   round(float(p.MediaBox[3] - p.MediaBox[1]), 1))
                                  for p in pdf.pages}),
        "rotaciones": sorted(set(rotaciones)),
        "objetos": len(list(pdf.objects)),
        "ops_texto_total": n_ops_texto,
        "ops_pintado_total": n_ops_pintado,
        "ops_clip_total": n_ops_clip,
        "fragmentos_texto_por_pagina": frags_por_pagina[:12],
        "max_fragmentos_en_una_pagina": max(frags_por_pagina) if frags_por_pagina else 0,
        "fuentes": fuentes,
        "imagenes": imgs,
        "imagenes_con_smask": smasks,
        "colorspaces": sorted(cspaces),
        "tiene_acroform": tiene_acroform,
        "anotaciones": n_annots,
        "cifrado": pdf.is_encrypted,
    }


def main() -> None:
    archivos = sorted(CORPUS.glob("*.pdf"))
    perfiles = []
    for f in archivos:
        p = perfilar(f)
        perfiles.append(p)

        srcs = {x["colorspace"] for x in p["imagenes"]}
        n_sub = sum(1 for x in p["fuentes"] if x.get("prefijo_subset"))
        n_inc = sum(1 for x in p["fuentes"] if x.get("incrustada"))
        print(f"\n{p['archivo']}")
        print(f"  {p['bytes']/1024:7.1f} KiB | {p['paginas']} pág | "
              f"{p['objetos']} objetos | tamaños {p['tam_paginas_pt']} | rotate {p['rotaciones']}")
        print(f"  ops: texto={p['ops_texto_total']} pintado={p['ops_pintado_total']} "
              f"clip={p['ops_clip_total']} | máx frag/pág={p['max_fragmentos_en_una_pagina']}")
        print(f"  fuentes: {len(p['fuentes'])} ({n_inc} incrustadas, {n_sub} con prefijo de subset)")
        for fo in p["fuentes"][:4]:
            print(f"     - {fo.get('nombre')} {fo.get('subtipo')} "
                  f"incrustada={fo.get('incrustada')} subset={fo.get('prefijo_subset')}")
        print(f"  imágenes: {len(p['imagenes'])} | con SMask: {len(p['imagenes_con_smask'])} "
              f"| colorspaces: {sorted(srcs) if srcs else '-'}")
        print(f"  AcroForm={p['tiene_acroform']} anotaciones={p['anotaciones']} cifrado={p['cifrado']}")

    (CORPUS / "perfil.json").write_text(
        json.dumps(perfiles, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nperfil.json escrito con {len(perfiles)} entradas")


if __name__ == "__main__":
    main()
