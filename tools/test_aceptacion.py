#!/usr/bin/env python3
"""
Test de aceptación del proyecto.

El criterio literal que fijó el usuario:

    "el usuario abre un PDF real con texto e imágenes, selecciona una imagen, la
     redimensiona, borra un vector, cambia un texto, guarda, reabre — sus cambios
     están y NADA MÁS ha cambiado."

Traducido a algo medible, tiene dos partes:

  1. El cambio está: los píxeles donde debería verse el cambio, cambian.
  2. Nada más ha cambiado: fuera de la región del objeto editado, el diff de
     píxeles es CERO.

Y una tercera que este proyecto puede permitirse y LibreOffice no:

  3. El fichero guardado EMPIEZA POR los bytes del original. Si eso se cumple,
     no es que "no haya cambiado nada más": es que es imposible, porque el
     original sigue ahí íntegro y sólo se ha añadido un apéndice.

Y una cuarta, que se añadió al descubrir que las tres anteriores no bastaban:

  4. La geometría de la página, medida con pdfium —un motor que no comparte ni
     una línea con este proyecto— es la esperada: cada objeto sigue donde
     estaba y el objeto editado está donde dijimos que iba.

Por qué hizo falta la cuarta. Los píxeles se comparan contra una región
PERMITIDA, que se construye con las cajas de NUESTRO parser. Si el parser o el
escritor se equivocan, la región de permiso se equivoca con ellos y el error
queda tapado. Pasó de verdad: al escalar una imagen, la matriz se insertaba sin
convertirla al espacio local del objeto, así que se multiplicaba por la escala de
emplazamiento (320x200) y la imagen acababa en x=29768, fuera de la página para
siempre. El arnés lo dio por bueno: los píxeles de su sitio viejo estaban
"permitidos" porque el objeto se había ido, y en el sitio nuevo no había nada que
comparar. Aprobar la desaparición del objeto no es aprobar la edición.

  python3 tools/test_aceptacion.py
  python3 tools/test_aceptacion.py --caso 04_imagen_smask --guardar-png
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pikepdf  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402

from nucleo.alinear_texto import alinear, chars_de_pagina  # noqa: E402
from nucleo.editar import (borrar_objeto, caja_tras_escalar,  # noqa: E402
                           caja_tras_mover, escalar_objeto, mover_objeto)
from nucleo.editar_texto import (escala_de_run,  # noqa: E402
                                 plan_editar_texto)
from nucleo.fuentes import resolver_fuentes  # noqa: E402
from nucleo.geometria import Caja, aplicar, matriz_pagina  # noqa: E402
from nucleo.guardar import guardar_pagina_editada  # noqa: E402
from nucleo.objetos import (ContenidoPagina, Imagen, TextoRun, Vector,  # noqa: E402
                            extraer_objetos)

CORPUS = Path(__file__).resolve().parent.parent / "corpus"
TMP = Path(__file__).resolve().parent.parent / ".tmp"
ESCALA = 2.0          # ~144 dpi
TOL_PX = 8            # 8/255: por debajo de esto es ruido de antialiasing
MARGEN_PX = 3         # holgura por el suavizado del borde del objeto editado


# ---------------------------------------------------------------------------

# Tolerancia del oráculo por tipo, en puntos. Las imágenes no tienen excusa: su
# caja la fija el CTM tal cual, así que 0,5 pt es generosidad.
TOL_ORACULO = {"texto": 6.0, "vector": 6.0, "imagen": 0.5, "sombreado": 8.0}


def _cajas_oraculo(ruta: Path, pagina: int = 0):
    """(tipo, caja) de cada objeto de la página, según pdfium."""
    doc = pdfium.PdfDocument(str(ruta))
    try:
        salida = []
        for o in doc[pagina].get_objects():
            try:
                b = tuple(float(v) for v in o.get_bounds())
            except Exception:
                continue
            tipo = {1: "texto", 2: "vector", 3: "imagen",
                    4: "sombreado", 5: "form"}.get(o.type, str(o.type))
            salida.append((tipo, b))
        return salida
    finally:
        doc.close()


def _union(cajas):
    cajas = [c for c in cajas if c]
    if not cajas:
        return None
    return (min(c[0] for c in cajas), min(c[1] for c in cajas),
            max(c[2] for c in cajas), max(c[3] for c in cajas))


def _solapan(a, b, tol: float = 0.0) -> bool:
    """¿Se solapan dos cajas? Con margen, para el suavizado de bordes."""
    return not (a[2] < b[0] - tol or b[2] < a[0] - tol
                or a[3] < b[1] - tol or b[3] < a[1] - tol)


def _fuera_de(caja, region, tol) -> float:
    """Cuánto se sale `caja` de `region`, en puntos. 0 si está dentro."""
    if region is None or caja is None:
        return 0.0
    return max(0.0, region[0] - caja[0] - tol, caja[2] - region[2] - tol,
               region[1] - caja[1] - tol, caja[3] - region[3] - tol)


def comprobar_geometria(ruta_original: Path, ruta_salida: Path,
                        nuevas: dict, eliminados: dict,
                        pagina: int = 0) -> list[str]:
    """Comprueba con pdfium que la página quedó como tiene que quedar.

    Dos reglas, las dos independientes de nuestro código:

      A. Ningún objeto puede aparecer fuera de la región formada por donde ya
         había objetos y donde hemos dicho que iba el objeto editado. Al escalar
         mal, la imagen se iba a x=29768 y esta regla salta sola.
      B. Cada objeto que hemos movido o escalado tiene que estar de verdad en la
         posición predicha.
    """
    problemas: list[str] = []
    antes = _cajas_oraculo(ruta_original, pagina)
    despues = _cajas_oraculo(ruta_salida, pagina)

    for tipo in ("imagen", "vector", "texto", "sombreado"):
        ca = [c for t, c in antes if t == tipo]
        cd = [c for t, c in despues if t == tipo]
        if not ca and not cd:
            continue
        tol = TOL_ORACULO.get(tipo, 6.0)
        region = _union(ca)
        for c in nuevas.get(tipo, []):
            region = _union([region, tuple(c)])
        u = _union(cd)
        exceso = _fuera_de(u, region, tol)
        if exceso > 0:
            problemas.append(
                f"geometría: los objetos de tipo {tipo} se salen "
                f"{exceso:.1f} pt de donde estaban o de donde se dijo. "
                f"caja de la unión ahora={tuple(round(v,1) for v in u)} "
                f"permitido={tuple(round(v,1) for v in region)}")

        # Regla B: el objeto editado está donde dijimos.
        #
        # Para el texto se exige SOLAPE y no igualdad de caja: pdfium crea un
        # objeto por glifo cuando el generador emite un `Tj` por carácter, así
        # que un run nuestro son muchos objetos suyos y ninguno coincide con la
        # caja del run. Lo que sí tiene que cumplirse, y se cumple, es que haya
        # texto donde hemos dicho. Que el texto no se vaya a otro sitio ya lo
        # garantiza la regla A, que es la que cazaría un desplazamiento mal
        # aplicado.
        for c in nuevas.get(tipo, []):
            if tipo == "texto":
                bien = any(_solapan(c, o, tol) for o in cd)
            else:
                bien = any(max(abs(a - b) for a, b in zip(c, o)) <= tol
                           for o in cd)
            if not bien:
                problemas.append(
                    f"geometría: se dijo que {tipo} quedaría en "
                    f"{tuple(round(v,1) for v in c)} y pdfium no ve ningún "
                    f"{tipo} ahí (los ve en "
                    f"{[tuple(round(v,1) for v in o) for o in cd[:4]]}...)")

        # Regla de recuento: borrar quita exactamente uno, mover no cambia nada.
        # No se aplica al texto, donde pdfium hace un objeto por glifo cuando el
        # generador emite un `Tj` por carácter (caso 01).
        n_el = eliminados.get(tipo, 0)
        if tipo != "texto" and len(cd) != len(ca) - n_el:
            problemas.append(
                f"geometría: {tipo} era {len(ca)} objetos y ahora son "
                f"{len(cd)} (se borraron {n_el})")
    return problemas


@dataclass
class Caso:
    nombre: str
    pdf: str
    descripcion: str
    acciones: list = field(default_factory=list)
    # ("borrar"|"mover"|"escalar", tipo, índice, params...)
    # ("texto", índice, texto_nuevo, opciones)
    region: list[Caja] = field(default_factory=list)   # dónde se permite cambio


@dataclass
class Resultado:
    caso: str
    ok: bool
    px_cambiados: int
    px_fuera: int
    px_totales: int
    px_permitidos: int
    bytes_original: int
    bytes_anadidos: int
    prefijo_intacto: bool
    geometria_ok: bool = True
    detalle: list[str] = field(default_factory=list)
    png_antes: Path | None = None
    png_despues: Path | None = None


# ---------------------------------------------------------------------------

def cargar(ruta: Path, num_pagina: int = 0):
    """Extrae los objetos Y los alinea.

    El paso de alineación no es opcional: sin él los runs de texto conservan su
    caja APROXIMADA, que se desvía unos 3 pt de la tinta real porque estima el
    ancho medio de un carácter. Un editor de verdad trabaja con las cajas
    alineadas, y una región de tolerancia construida sobre la caja aproximada
    está desplazada, no es que los píxeles se escapen.
    """
    pdf = pikepdf.open(str(ruta))
    pg = pdf.pages[num_pagina]
    c = pg.get("/Contents")
    if isinstance(c, pikepdf.Array):
        datos = b"\n".join(s.read_bytes() for s in c)
        refs = [s.objgen for s in c]
    else:
        datos = c.read_bytes()
        refs = [c.objgen]
    contenido = extraer_objetos(datos, resolver_fuentes(pg))

    doc = pdfium.PdfDocument(str(ruta))
    try:
        chars = chars_de_pagina(doc[num_pagina].get_textpage())
    finally:
        doc.close()
    alinear(contenido, chars)
    return pdf, pg, datos, contenido, refs


def render(ruta: Path, num_pagina: int = 0):
    doc = pdfium.PdfDocument(str(ruta))
    try:
        return doc[num_pagina].render(scale=ESCALA).to_pil().convert("RGB")
    finally:
        doc.close()


def a_pixel(pagina, caja: Caja) -> tuple[float, float, float, float]:
    """Caja en puntos PDF -> caja en píxeles de la imagen renderizada."""
    mb = list(pagina.get_mediabox())
    rot = pagina.get_rotation()
    m, _, _ = matriz_pagina(mb, rot)
    x0, y0 = aplicar(m, caja.x0, caja.y1)
    x1, y1 = aplicar(m, caja.x1, caja.y0)
    return (x0 * ESCALA, y0 * ESCALA, x1 * ESCALA, y1 * ESCALA)


def _selector(tipo: str, contenido: ContenidoPagina, idx: int):
    objetos = [o for o in contenido.objetos if o.tipo == tipo]
    if not objetos:
        raise LookupError(f"no hay objetos de tipo {tipo}")
    if idx < 0:
        idx += len(objetos)
    return objetos[idx]


def ejecutar(caso: Caso, guardar_png: bool = False) -> Resultado:
    ruta = CORPUS / caso.pdf
    detalle: list[str] = []

    pdf, pagina, datos, contenido, refs = cargar(ruta)
    objetos_nuevos: dict = {}
    # Lo que el oráculo espera encontrar después, en cajas de PÁGINA.
    cajas_nuevas: dict[str, list] = {}
    eliminados: dict[str, int] = {}
    try:
        nuevos = bytearray(datos)
        permitidos: list[Caja] = list(caso.region)

        for accion in caso.acciones:
            op = accion[0]
            if op == "borrar":
                tipo, idx = accion[1], accion[2]
                obj = _selector(tipo, contenido, idx)
                if obj.caja is None:
                    raise ValueError("el objeto no tiene caja")
                permitidos.append(obj.caja)
                detalle.append(
                    f"borrar {tipo}[{idx}] en {obj.caja.como_tupla()}")
                eliminados[tipo] = eliminados.get(tipo, 0) + 1
                nuevos = borrar_objeto(bytes(nuevos), contenido, obj)
            elif op == "mover":
                tipo, idx, dx, dy = accion[1], accion[2], accion[3], accion[4]
                obj = _selector(tipo, contenido, idx)
                antes = obj.caja
                permitidos.append(antes)
                permitidos.append(caja_tras_mover(obj, dx, dy))
                detalle.append(
                    f"mover {tipo}[{idx}] +({dx},{dy}) "
                    f"{antes.como_tupla()} -> "
                    f"{caja_tras_mover(obj, dx, dy).como_tupla()}")
                cajas_nuevas.setdefault(tipo, []).append(
                    caja_tras_mover(obj, dx, dy).como_tupla())
                nuevos = mover_objeto(bytes(nuevos), contenido, obj, dx, dy)
            elif op == "escalar":
                tipo, idx, ex, ey = accion[1], accion[2], accion[3], accion[4]
                obj = _selector(tipo, contenido, idx)
                centro = obj.caja.centro
                permitidos.append(obj.caja)
                permitidos.append(caja_tras_escalar(obj, ex, ey, centro))
                detalle.append(
                    f"escalar {tipo}[{idx}] x({ex},{ey}) alrededor de "
                    f"({centro[0]:.0f},{centro[1]:.0f})")
                cajas_nuevas.setdefault(tipo, []).append(
                    caja_tras_escalar(obj, ex, ey, centro).como_tupla())
                nuevos = escalar_objeto(bytes(nuevos), contenido, obj,
                                        ex, ey, centro)
            elif op == "texto":
                idx, texto_nuevo = accion[1], accion[2]
                opciones = accion[3] if len(accion) > 3 else {}
                obj = _selector("texto", contenido, idx)
                if obj.caja is None:
                    raise ValueError("el run no tiene caja")
                tam = obj.fuente_tam or 12.0
                escala = escala_de_run(obj)
                plan = plan_editar_texto(bytes(nuevos), ruta, 0, contenido,
                                         obj, texto_nuevo, **opciones)
                if not plan.informe.ok:
                    raise ValueError(f"edición de texto rechazada: "
                                     f"{plan.informe.motivo}")
                inf = plan.informe
                # la región permitida es la caja vieja más lo que crezca el texto
                # La región permitida es la caja vieja, lo que crezca el texto
                # hacia la derecha, y la extensión tipográfica VERTICAL.
                #
                # Por qué lo vertical: la caja que da el parser es la de la tinta
                # del texto VIEJO. Si el texto nuevo lleva una letra con cola
                # (g, j, p, q, y) y el viejo no tenía ninguna, el descendente
                # baja un par de puntos por debajo de la caja. Pasó al escribir
                # «aqui» en un run que sólo tenía letras sin cola: 14 píxeles
                # fuera. Es la misma lección del acento de la «ó» en F4: la
                # región tiene que ser la extensión TIPOGRÁFICA, no la tinta
                # concreta de la frase anterior. El 0,35 em cubre ascendente y
                # descendente de DejaVu (0,24 em de cola) con holgura.
                crece = max(0.0, inf.delta_en_puntos)
                ext = 0.35 * tam * escala
                caja_nueva = Caja(obj.caja.x0, obj.caja.y0 - ext,
                                  obj.caja.x1 + crece, obj.caja.y1 + ext)
                permitidos.append(caja_nueva)
                # Se declara al oráculo dónde decimos que quedará el texto. Sin
                # esto, un texto que crece sale de la unión de las cajas viejas
                # y el oráculo avisa — con razón: no le hemos dicho que íbamos a
                # crecer.
                cajas_nuevas.setdefault("texto", []).append(
                    caja_nueva.como_tupla())
                detalle.append(
                    f"editar texto[{idx}] {obj.texto[:28]!r} -> "
                    f"{texto_nuevo[:28]!r}")
                detalle.append(f"   {inf.resumen()}")
                nuevos = bytearray(plan.contenido)
                objetos_nuevos = dict(plan.objetos)
            else:
                raise ValueError(f"acción desconocida: {op}")

        salida = TMP / f"acept_{caso.nombre}.pdf"
        TMP.mkdir(exist_ok=True)
        info = guardar_pagina_editada(ruta, salida, 0, [bytes(nuevos)],
                                      objetos_nuevos)
        detalle.append(
            f"guardado incremental: {info.bytes_anadidos} bytes añadidos "
            f"de {info.bytes_original}")
        detalle.append(
            f"objetos redefinidos: {info.objetos_redefinidos}")
    finally:
        pdf.close()

    if not info.prefijo_intacto:
        detalle.append("AVISO: el fichero de salida NO empieza por el original")

    # --- comparación de píxeles ------------------------------------------
    antes = render(ruta)
    despues = render(salida)
    if antes.size != despues.size:
        raise AssertionError(
            f"el tamaño de página cambió: {antes.size} -> {despues.size}")

    import numpy as np
    a = np.asarray(antes, dtype=np.int16)
    b = np.asarray(despues, dtype=np.int16)
    diff = np.abs(a - b).max(axis=2)
    mascara = diff > TOL_PX
    px_cambiados = int(mascara.sum())

    # máscara de lo permitido
    permitido = np.zeros(mascara.shape, dtype=bool)
    h, w = mascara.shape
    pagina_pdf = pdfium.PdfDocument(str(ruta))
    try:
        pg = pagina_pdf[0]
        for caja in permitidos:
            if caja is None:
                continue
            x0, y0, x1, y1 = a_pixel(pg, caja)
            x0 = max(0, int(x0) - MARGEN_PX)
            y0 = max(0, int(y0) - MARGEN_PX)
            x1 = min(w, int(x1) + MARGEN_PX + 1)
            y1 = min(h, int(y1) + MARGEN_PX + 1)
            permitido[y0:y1, x0:x1] = True
    finally:
        pagina_pdf.close()

    fuera = mascara & ~permitido
    px_fuera = int(fuera.sum())

    if px_fuera:
        ys, xs = np.nonzero(fuera)
        detalle.append(
            f"FUERA DE LA REGIÓN PERMITIDA: {px_fuera} píxeles, "
            f"p. ej. en ({int(xs[0])},{int(ys[0])})")

    # --- comprobación independiente de la geometría ----------------------
    problemas_geo = comprobar_geometria(ruta, salida, cajas_nuevas, eliminados)
    for x in problemas_geo:
        detalle.append("ORÁCULO: " + x)

    res = Resultado(
        caso=caso.nombre, ok=(px_fuera == 0 and not problemas_geo),
        px_cambiados=px_cambiados,
        px_fuera=px_fuera, px_totales=int(mascara.size),
        px_permitidos=int(permitido.sum()),
        bytes_original=info.bytes_original, bytes_anadidos=info.bytes_anadidos,
        prefijo_intacto=info.prefijo_intacto, geometria_ok=not problemas_geo,
        detalle=detalle,
    )

    if guardar_png:
        d = Path(__file__).resolve().parent.parent / "resultados" / "f2"
        d.mkdir(parents=True, exist_ok=True)
        p1 = d / f"{caso.nombre}_antes.png"
        p2 = d / f"{caso.nombre}_despues.png"
        antes.save(p1)
        despues.save(p2)
        res.png_antes, res.png_despues = p1, p2

    return res


# ---------------------------------------------------------------------------

CASOS = [
    Caso(
        nombre="borrar_estrella",
        pdf="03_vectores_clip_degradado.pdf",
        descripcion="Borrar la estrella de 14 segmentos; el degradado "
                    "recortado debe quedar idéntico",
        acciones=[("borrar", "vector", -1)],
    ),
    Caso(
        nombre="borrar_un_rect_del_degradado",
        pdf="03_vectores_clip_degradado.pdf",
        descripcion="Borrar una sola banda del degradado: es un objeto entre 62",
        acciones=[("borrar", "vector", 30)],
    ),
    Caso(
        nombre="mover_imagen_smask",
        pdf="04_imagen_smask.pdf",
        descripcion="Mover la imagen con SMask 100 pt a la derecha",
        acciones=[("mover", "imagen", 0, 100.0, 0.0)],
    ),
    Caso(
        nombre="escalar_imagen_smask",
        pdf="04_imagen_smask.pdf",
        descripcion="Redimensionar la imagen al 50 % alrededor de su centro",
        acciones=[("escalar", "imagen", 0, 0.5, 0.5)],
    ),
    Caso(
        nombre="mover_imagen_cmyk",
        pdf="05_cmyk_imprenta.pdf",
        descripcion="Mover la imagen CMYK. LibreOffice convierte este caso a "
                    "RGB y cambia el 11,8 % de los píxeles",
        acciones=[("mover", "imagen", 0, 0.0, -80.0)],
    ),
    Caso(
        nombre="borrar_vector_cmyk",
        pdf="05_cmyk_imprenta.pdf",
        descripcion="Borrar el rectángulo CMYK de fondo",
        acciones=[("borrar", "vector", 0)],
    ),
    Caso(
        nombre="mover_texto_fuente_completa",
        pdf="10_fuente_completa.pdf",
        descripcion="Mover un run de texto en el caso Type0 + Identity-H + "
                    "ToUnicode. Ojo: mover NO es editar el texto (eso es F4)",
        acciones=[("mover", "texto", 0, 0.0, -60.0)],
    ),
    Caso(
        nombre="mover_linea_fragmentada",
        pdf="01_texto_fragmentado.pdf",
        descripcion="Mover una de las 18 líneas del caso de 1.746 operadores "
                    "de texto: las otras 17 deben quedar intactas",
        acciones=[("mover", "texto", 5, 40.0, 0.0)],
    ),
    Caso(
        nombre="borrar_una_linea_fragmentada",
        pdf="01_texto_fragmentado.pdf",
        descripcion="Borrar una sola línea entre 18, en la página con "
                    "1.746 operadores de texto",
        acciones=[("borrar", "texto", 9)],
    ),
    Caso(
        nombre="texto_misma_longitud",
        pdf="00_baseline.pdf",
        descripcion="Cambiar 'control' por 'contral'. Nivel 1a: sustitución de "
                    "bytes, la estructura del stream queda intacta",
        acciones=[("texto", 0, "Documento de contral: texto simple, sin trampas.")],
    ),
    Caso(
        nombre="texto_mas_corto",
        pdf="00_baseline.pdf",
        descripcion="Acortar la primera línea. Nivel 1b: el texto encoge y el "
                    "resto de la página no se mueve",
        acciones=[("texto", 0, "Documento de control.")],
    ),
    Caso(
        nombre="texto_glifo_ausente",
        pdf="02_fuente_subset.pdf",
        descripcion="Escribir una 'ó' en un run cuyo subconjunto no la tiene. "
                    "Nivel 2: se incrusta un subconjunto nuevo del sistema",
        acciones=[("texto", 0, "Solo aparecen estas letras: a, e, o, i, u, ó.")],
    ),
    Caso(
        nombre="texto_glifo_ausente_ajustado",
        pdf="02_fuente_subset.pdf",
        descripcion="Igual que el anterior pero con ajuste de espaciado (Tc) "
                    "para que no desborde",
        acciones=[("texto", 0,
                   "Solo aparecen estas letras: a, e, o, i, u y la ó.",
                   {"ajustar_espaciado": True})],
    ),
    Caso(
        nombre="texto_linea_fragmentada",
        pdf="01_texto_fragmentado.pdf",
        descripcion="Editar una línea del caso de 1.746 operadores de texto. "
                    "El stream es un Tj por carácter, así que es nivel 1b",
        acciones=[("texto", 3, "El rápido zorro cambió esta línea entera.")],
    ),
    # --- caso 11: texto bajo matrices que no son la identidad ------------
    # Estos cuatro existen porque todo el corpus anterior escribía el texto con
    # la matriz identidad, y eso escondía dos errores de unidades en el ajuste
    # de espaciado. Ver el comentario largo en 11_texto_transformado.pdf.
    Caso(
        nombre="editar_texto_escalado_x2",
        pdf="11_texto_transformado.pdf",
        descripcion="Cambiar el texto de un run dentro de un cm con escala 2",
        acciones=[("texto", 1, "Otro texto distinto aqui dentro")],
    ),
    Caso(
        nombre="editar_texto_escalado_ajustado",
        pdf="11_texto_transformado.pdf",
        descripcion="El mismo run con --ajustar: el ancho tiene que aguantar",
        acciones=[("texto", 1, "Otro texto distinto aqui dentro",
                   {"ajustar_espaciado": True})],
    ),
    Caso(
        nombre="mover_texto_rotado",
        pdf="11_texto_transformado.pdf",
        descripcion="Mover un run rotado 30 grados: la matriz va conjugada "
                    "por el CTM, no aplicada en la página",
        acciones=[("mover", "texto", 3, 25.0, 30.0)],
    ),
    Caso(
        nombre="escalar_texto_escalado",
        pdf="11_texto_transformado.pdf",
        descripcion="Redimensionar al 140 % un run que ya estaba bajo un cm "
                    "con escala 1.8",
        acciones=[("escalar", "texto", 4, 1.4, 1.4)],
    ),
    Caso(
        nombre="escalar_imagen_doble",
        pdf="04_imagen_smask.pdf",
        descripcion="Redimensionar al 150 %: el caso que pide el brief",
        acciones=[("escalar", "imagen", 0, 1.5, 1.5)],
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caso", help="ejecutar sólo un caso")
    ap.add_argument("--guardar-png", action="store_true")
    args = ap.parse_args()

    casos = [c for c in CASOS if not args.caso or args.caso in c.nombre]
    if not casos:
        print(f"no hay ningún caso que coincida con {args.caso!r}")
        print("disponibles:", ", ".join(c.nombre for c in CASOS))
        return 2

    print()
    print("  TEST DE ACEPTACIÓN — IntactPDF")
    print("  criterio: el cambio está, y nada más ha cambiado")
    print()
    resultados = []
    for caso in casos:
        print(f"  ── {caso.nombre} ─────────────────────────────────────")
        print(f"     {caso.descripcion}")
        try:
            r = ejecutar(caso, guardar_png=args.guardar_png)
        except Exception as e:
            print(f"     ERROR: {type(e).__name__}: {e}")
            resultados.append(None)
            print()
            continue
        for d in r.detalle:
            print(f"     · {d}")
        pct = 100.0 * r.px_cambiados / r.px_totales
        print(f"     · píxeles cambiados: {r.px_cambiados} ({pct:.3f} %)")
        print(f"     · de ellos fuera de la región permitida: {r.px_fuera}")
        print(f"     · 1 = la salida empieza por el original: "
              f"{'sí' if r.prefijo_intacto else 'NO'}")
        print(f"     => {'PASA' if r.ok else 'FALLA'}")
        print()
        resultados.append(r)

    validos = [r for r in resultados if r]
    print("  " + "═" * 66)
    if validos:
        pasan = sum(1 for r in validos if r.ok)
        prefijos = sum(1 for r in validos if r.prefijo_intacto)
        total_fuera = sum(r.px_fuera for r in validos)
        print(f"  casos: {pasan}/{len(validos)} pasan")
        print(f"  la salida empieza por el original: {prefijos}/{len(validos)}")
        print(f"  píxeles cambiados fuera de la región permitida: {total_fuera}")
    fallos = sum(1 for r in resultados if r is None) + \
        sum(1 for r in resultados if r and not r.ok)
    print(f"  fallos: {fallos}")
    print("  " + "═" * 66)
    print()
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
