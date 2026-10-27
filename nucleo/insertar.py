"""
Inserción de nuevos objetos en una página PDF existente:
  - Añadir texto (con incrustación limpia de subconjunto tipográfico)
  - Añadir imágenes (PNG/JPEG/etc. con soporte SMask transparente)

Conserva el principio fundamental de IntactPDF: no reconstruye el documento.
Genera los operadores de dibujo encapsulados en un bloque gráfico seguro `q ... Q`
al final del content stream y registra los recursos necesarios (/Font o /XObject)
para guardado incremental.
"""
from __future__ import annotations

import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
import pikepdf

from .fuentes import Fuente, resolver_fuentes
from .guardar import cuerpo_stream, escribir_incremental, InformeGuardado
from .sustitucion_fuente import (
    buscar_fuente_sistema,
    construir_subconjunto,
    cmap_tounicode,
    objetos_fuente,
)


@dataclass
class PlanInsercion:
    nuevo_stream: bytes
    objetos_extra: dict[tuple[int, int], bytes] = field(default_factory=dict)
    descripcion: str = ""


def _nombre_libre(recursos: dict[str, Any] | None, prefijo: str) -> str:
    usados = {k.lstrip("/") for k in (recursos or {}).keys()}
    for i in range(1, 1000):
        c = f"{prefijo}{i}"
        if c not in usados:
            return c
    return f"{prefijo}_{uuid.uuid4().hex[:6]}"


def plan_anadir_texto(
    datos_stream: bytes,
    ruta_pdf: str | Path,
    num_pagina: int,
    texto: str,
    x: float,
    y: float,
    *,
    tamano: float = 12.0,
    color_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0),
    nombre_fuente: str = "DejaVuSans",
) -> PlanInsercion:
    """Prepara la inserción de una nueva línea de texto en una posición dada.

    Genera una fuente subconjuntada con los glifos requeridos y añade al final
    del content stream el bloque:
        q
        r g b rg
        BT
        /LPF... tamano Tf
        1 0 0 1 x y Tm
        <hex> Tj
        ET
        Q
    """
    if not texto:
        return PlanInsercion(datos_stream, {}, "texto vacío")

    ruta_fuente = buscar_fuente_sistema(nombre_fuente)
    if ruta_fuente is None:
        # Fallback a cualquier fuente TrueType disponible del sistema
        from .sustitucion_fuente import _directorios
        for d in _directorios():
            cand = list(d.glob("*.ttf"))
            if cand:
                ruta_fuente = cand[0]
                break
    if ruta_fuente is None:
        raise ValueError(f"No se encontró una fuente en el sistema para incrustar '{nombre_fuente}'")

    fuente_sub = construir_subconjunto(ruta_fuente, texto)
    bytes_texto = fuente_sub.codificar(texto)

    with pikepdf.open(str(ruta_pdf)) as pdf:
        pagina = pdf.pages[num_pagina]
        fuentes_existentes = resolver_fuentes(pagina)

        siguiente = int(pdf.trailer.get("/Size", 0))
        num_ff = siguiente
        num_tu = siguiente + 1

        nombre_alias = _nombre_libre(fuentes_existentes, "IPF")
        nombre_base = Path(fuente_sub.nombre_origen).stem if fuente_sub.nombre_origen else "IntactFont"
        definicion = objetos_fuente(
            fuente_sub,
            nombre_base,
            f"{num_ff} 0 R",
            f"{num_tu} 0 R",
        )

        res = pagina.get("/Resources")
        if res is None:
            # Crear diccionario Resources si no existía
            pagina["/Resources"] = pikepdf.Dictionary()
            res = pagina["/Resources"]

        fd = res.get("/Font")
        if fd is None:
            # Si no hay diccionario Font, se crea dentro de Resources
            if res.objgen != (0, 0):
                fd_objgen = res.objgen
            else:
                fd_objgen = pagina.obj.objgen
            # Serializamos resources con nuevo /Font
            res_dict = dict(res)
            res_dict["/Font"] = pikepdf.Dictionary({f"/{nombre_alias}": pikepdf.Stream(owner=pdf, data=b"")})
        
        # Obtener referencia directa o indirecta del diccionario /Font
        from .editar_texto import _objgen_diccionario_fuentes, _anadir_fuente_al_diccionario
        dic_ref = _objgen_diccionario_fuentes(pagina)
        dic = res.get("/Font")
        if dic is None:
            res["/Font"] = pikepdf.Dictionary()
            dic = res.get("/Font")
            dic_ref = _objgen_diccionario_fuentes(pagina)

        if dic.objgen == (0, 0):
            dic = res
        nuevo_dic = _anadir_fuente_al_diccionario(dic, nombre_alias, definicion)

    objetos_extra = {
        (num_ff, 0): cuerpo_stream(fuente_sub.ttf),
        (num_tu, 0): cuerpo_stream(cmap_tounicode(fuente_sub)),
        dic_ref: nuevo_dic,
    }

    # Bloque gráfico para insertar el texto de forma encapsulada
    r, g, b = color_rgb
    hex_str = bytes_texto.hex().upper()
    bloque_nuevo = (
        f"\nq\n"
        f"{r:.4f} {g:.4f} {b:.4f} rg\n"
        f"BT\n"
        f"/{nombre_alias} {tamano:g} Tf\n"
        f"1 0 0 1 {x:.4f} {y:.4f} Tm\n"
        f"<{hex_str}> Tj\n"
        f"ET\n"
        f"Q\n"
    ).encode("ascii")

    nuevo_stream = datos_stream.rstrip() + b"\n" + bloque_nuevo
    return PlanInsercion(
        nuevo_stream=nuevo_stream,
        objetos_extra=objetos_extra,
        descripcion=f"Añadido texto '{texto}' en ({x:.1f}, {y:.1f})"
    )


def plan_anadir_imagen(
    datos_stream: bytes,
    ruta_pdf: str | Path,
    num_pagina: int,
    ruta_imagen: str | Path,
    x: float,
    y: float,
    ancho_pt: float,
    alto_pt: float,
) -> PlanInsercion:
    """Prepara la inserción de una nueva imagen XObject colocada en (x, y) con tamaño (ancho_pt, alto_pt)."""
    ruta_imagen = Path(ruta_imagen)
    if not ruta_imagen.exists():
        raise FileNotFoundError(f"No existe el archivo de imagen: {ruta_imagen}")

    with pikepdf.open(str(ruta_pdf)) as pdf:
        pagina = pdf.pages[num_pagina]
        res = pagina.get("/Resources")
        if res is None:
            pagina["/Resources"] = pikepdf.Dictionary()
            res = pagina["/Resources"]

        xobjs = res.get("/XObject")
        xobjs_dict = dict(xobjs) if xobjs is not None else {}
        alias_img = _nombre_libre(xobjs_dict, "Img")

        size_trailer = int(pdf.trailer.get("/Size", 0))
        num_img = size_trailer
        num_smask = size_trailer + 1

    with Image.open(str(ruta_imagen)) as img:
        ancho_px, alto_px = img.size
        extra_smask = None

        if img.mode == "L":
            cs = b"/DeviceGray"
            raw_bytes = img.tobytes()
        elif img.mode == "RGBA":
            cs = b"/DeviceRGB"
            r, g, b, a = img.split()
            raw_bytes = Image.merge("RGB", (r, g, b)).tobytes()
            if a.getextrema()[0] < 255:
                alpha_bytes = a.tobytes()
                alpha_payload = zlib.compress(alpha_bytes, 9)
                extra_smask = (
                    b"<< /Type /XObject /Subtype /Image "
                    b"/Width " + str(ancho_px).encode("ascii") + b" "
                    b"/Height " + str(alto_px).encode("ascii") + b" "
                    b"/BitsPerComponent 8 "
                    b"/ColorSpace /DeviceGray "
                    b"/Filter /FlateDecode "
                    b"/Length " + str(len(alpha_payload)).encode("ascii") + b" >>\nstream\n"
                    + alpha_payload + b"\nendstream"
                )
        elif img.mode == "CMYK":
            cs = b"/DeviceCMYK"
            raw_bytes = img.tobytes()
        else:
            cs = b"/DeviceRGB"
            raw_bytes = img.convert("RGB").tobytes()

    payload = zlib.compress(raw_bytes, 9)
    smask_ref = f"/SMask {num_smask} 0 R ".encode("ascii") if extra_smask else b""
    cabecera = (
        b"<< /Type /XObject /Subtype /Image "
        b"/Width " + str(ancho_px).encode("ascii") + b" "
        b"/Height " + str(alto_px).encode("ascii") + b" "
        b"/BitsPerComponent 8 "
        b"/ColorSpace " + cs + b" "
        + smask_ref +
        b"/Filter /FlateDecode "
        b"/Length " + str(len(payload)).encode("ascii") + b" >>\nstream\n"
    )
    cuerpo_xobj = cabecera + payload + b"\nendstream"

    # Actualizar diccionario /XObject en /Resources respetando si Resources es indirecto o inline
    with pikepdf.open(str(ruta_pdf)) as pdf:
        pagina = pdf.pages[num_pagina]
        res = pagina.get("/Resources")
        from .editar_texto import _anadir_fuente_al_diccionario
        if res is not None and res.objgen != (0, 0):
            # Resources es un objeto indirecto
            xobjs = res.get("/XObject")
            if xobjs is not None and xobjs.objgen != (0, 0):
                dic_ref = xobjs.objgen
                nuevo_dic = _anadir_fuente_al_diccionario(
                    xobjs, alias_img, f"{num_img} 0 R".encode("ascii")
                )
            else:
                dic_ref = res.objgen
                xobjs_bytes = b"<< /" + alias_img.encode("ascii") + f" {num_img} 0 R >>".encode("ascii")
                if xobjs is None:
                    nuevo_dic = _anadir_fuente_al_diccionario(res, "XObject", xobjs_bytes)
                else:
                    nuevo_dic = _anadir_fuente_al_diccionario(xobjs, alias_img, f"{num_img} 0 R".encode("ascii"))
        else:
            # Resources es inline dentro del objeto de página: se reescribe el objeto de página
            dic_ref = pagina.obj.objgen
            pg_dict = pikepdf.Dictionary(pagina.obj)
            res_dict = pikepdf.Dictionary(res) if res is not None else pikepdf.Dictionary()
            xobjs = res_dict.get("/XObject")
            xobjs_dict = pikepdf.Dictionary(xobjs) if xobjs is not None else pikepdf.Dictionary()
            # En pikepdf podemos crear la referencia simbólica
            xobjs_dict[f"/{alias_img}"] = pikepdf.Operator(f"{num_img} 0 R")
            res_dict["/XObject"] = xobjs_dict
            pg_dict["/Resources"] = res_dict
            nuevo_dic = pg_dict.unparse(True)

    objetos_extra = {
        (num_img, 0): cuerpo_xobj,
        dic_ref: nuevo_dic,
    }
    if extra_smask:
        objetos_extra[(num_smask, 0)] = extra_smask

    # Operadores para dibujar la imagen colocada en (x, y) y escalada a (ancho_pt, alto_pt)
    bloque_img = (
        f"\nq\n"
        f"{ancho_pt:.4f} 0 0 {alto_pt:.4f} {x:.4f} {y:.4f} cm\n"
        f"/{alias_img} Do\n"
        f"Q\n"
    ).encode("ascii")

    nuevo_stream = datos_stream.rstrip() + b"\n" + bloque_img
    return PlanInsercion(
        nuevo_stream=nuevo_stream,
        objetos_extra=objetos_extra,
        descripcion=f"Añadida imagen {ruta_imagen.name} en ({x:.1f}, {y:.1f})"
    )
