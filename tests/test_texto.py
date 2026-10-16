"""Tests de la edición de texto (fase F4)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pikepdf
import pypdfium2 as pdfium

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

# El arnés se carga por ruta, no con `import test_aceptacion`: al lanzar
# `pytest tests/` desde la raíz, ese nombre apunta al OTRO fichero (el de
# tests/) y el resultado es un error de importación que no tiene nada que ver
# con el código. Cargándolo por ruta no hay colisión posible.
_spec = importlib.util.spec_from_file_location(
    "arnes_aceptacion", RAIZ / "tools" / "test_aceptacion.py")
_arnes = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _arnes      # `cargar` usa @dataclass y lo necesita
_spec.loader.exec_module(_arnes)
cargar = _arnes.cargar

from nucleo.alinear_texto import alinear, chars_de_pagina  # noqa: E402
from nucleo.editar_texto import (_tc_en_efecto, escala_de_run,  # noqa: E402
                                 plan_editar_texto)
from nucleo.fuentes import resolver_fuentes  # noqa: E402
from nucleo.geometria import aplicar, matriz_pagina  # noqa: E402
from nucleo.guardar import guardar_pagina_editada  # noqa: E402
from nucleo.objetos import extraer_objetos  # noqa: E402
from nucleo.parser import parsear  # noqa: E402
from nucleo.sustitucion_fuente import (etiqueta_subconjunto,  # noqa: E402
                                       nombre_base_sin_subset)

CORPUS = RAIZ / "corpus"
TMP = RAIZ / ".tmp"


def _cargar(ruta: Path, n: int = 0):
    return cargar(ruta, n)


def _editar(ruta: Path, idx: int, nuevo: str, salida: Path, **kw):
    pdf, pagina, datos, contenido, refs = _cargar(ruta)
    try:
        run = [o for o in contenido.objetos if o.tipo == "texto"][idx]
        plan = plan_editar_texto(datos, ruta, 0, contenido, run, nuevo, **kw)
    finally:
        pdf.close()
    if plan.informe.ok:
        TMP.mkdir(exist_ok=True)
        guardar_pagina_editada(ruta, salida, 0, [plan.contenido], plan.objetos)
    return plan


def _render(f):
    d = pdfium.PdfDocument(str(f))
    try:
        return np.asarray(d[0].render(scale=2.0).to_pil().convert("RGB"),
                          dtype=np.int16)
    finally:
        d.close()


def _texto(f) -> str:
    d = pdfium.PdfDocument(str(f))
    try:
        tp = d[0].get_textpage()
        return tp.get_text_range(0, tp.count_chars())
    finally:
        d.close()


def _caja_en_px(ruta: Path, caja) -> tuple[float, float, float, float]:
    d = pdfium.PdfDocument(str(ruta))
    try:
        pg = d[0]
        M, _, _ = matriz_pagina(list(pg.get_mediabox()), pg.get_rotation())
        x0, y0 = aplicar(M, caja.x0, caja.y1)
        x1, y1 = aplicar(M, caja.x1, caja.y0)
        return x0 * 2, y0 * 2, x1 * 2, y1 * 2
    finally:
        d.close()


# ---------------------------------------------------------------------------
# estado de texto
# ---------------------------------------------------------------------------

def test_tc_en_efecto_lee_el_ultimo_tc():
    contenido = parsear(b"10 Tc 1 0 0 1 5 5 Tm (a) Tj")
    from nucleo.objetos import ContenidoPagina
    pag = ContenidoPagina(objetos=[], instrucciones=contenido)
    assert _tc_en_efecto(pag, 10_000) == 10.0


def test_tc_en_efecto_respeta_la_pila_q():
    """Un Tc dentro de un q..Q ya cerrado no está vigente al salir."""
    from nucleo.objetos import ContenidoPagina
    pag = ContenidoPagina(objetos=[], instrucciones=parsear(
        b"5 Tc q 20 Tc Q 1 0 0 1 5 5 Tm"))
    assert _tc_en_efecto(pag, 10_000) == 5.0


def test_tc_en_efecto_solo_mira_hacia_atras():
    from nucleo.objetos import ContenidoPagina
    ins = parsear(b"(a) Tj 10 Tc")
    pag = ContenidoPagina(objetos=[], instrucciones=ins)
    assert _tc_en_efecto(pag, ins[0].fin) == 0.0


# ---------------------------------------------------------------------------
# nombres de fuente
# ---------------------------------------------------------------------------

def test_nombre_base_quita_el_prefijo_de_subconjunto():
    assert nombre_base_sin_subset("/AAAAAA+DejaVuSans") == "DejaVuSans"
    assert nombre_base_sin_subset("/DejaVuSans") == "DejaVuSans"


def test_etiqueta_de_subconjunto_tiene_seis_mayusculas():
    et = etiqueta_subconjunto("DejaVuSans")
    assert len(et) == 6 and et.isupper() and et.isalpha(), et


# ---------------------------------------------------------------------------
# nivel 1a
# ---------------------------------------------------------------------------

def test_nivel_1a_no_cambia_la_longitud_del_stream():
    """La edición más fiel posible: sustituir bytes sin tocar la estructura."""
    ruta = CORPUS / "00_baseline.pdf"
    pdf, pagina, datos, contenido, refs = _cargar(ruta)
    pdf.close()
    plan = _editar(ruta, 0, "Documento de contral: texto simple, sin trampas.",
                   TMP / "t_1a.pdf")
    assert plan.informe.ok and plan.informe.nivel == "1a", plan.informe.resumen()
    assert len(plan.contenido) == len(datos), (
        f"el stream cambió de longitud: {len(datos)} -> {len(plan.contenido)}")
    # y el mismo número de operadores
    antes = [i.op for i in parsear(datos)]
    despues = [i.op for i in parsear(plan.contenido)]
    assert antes == despues


def test_nivel_1a_el_texto_nuevo_se_extrae():
    ruta = CORPUS / "00_baseline.pdf"
    salida = TMP / "t_1a.pdf"
    plan = _editar(ruta, 0, "Documento de contral: texto simple, sin trampas.",
                   salida)
    assert plan.informe.ok
    assert "contral" in _texto(salida)


# ---------------------------------------------------------------------------
# nivel 1b
# ---------------------------------------------------------------------------

def test_nivel_1b_acorta_y_las_otras_lineas_no_se_mueven():
    ruta = CORPUS / "00_baseline.pdf"
    salida = TMP / "t_1b.pdf"
    plan = _editar(ruta, 0, "Documento de control.", salida)
    assert plan.informe.ok and plan.informe.nivel == "1b", plan.informe.resumen()
    assert plan.informe.delta_en_puntos < 0, "el texto debería encoger"

    a = _render(ruta)
    b = _render(salida)
    m = np.abs(a - b).max(axis=2) > 8
    # la segunda línea del documento no debe moverse ni un píxel
    ys, xs = np.nonzero(m)
    assert ys.max() < 200, f"cambios hasta y={ys.max()}, la línea 2 está abajo"


# ---------------------------------------------------------------------------
# nivel 2
# ---------------------------------------------------------------------------

def test_nivel_2_incrusta_un_subconjunto_nuevo():
    ruta = CORPUS / "02_fuente_subset.pdf"
    salida = TMP / "t_2.pdf"
    plan = _editar(ruta, 0, "Solo aparecen estas letras: a, e, o, i, u, ó.",
                   salida)
    assert plan.informe.ok and plan.informe.nivel == "2", plan.informe.resumen()
    assert plan.informe.glifos_que_faltan == ["ó"]
    # 3 objetos nuevos: el diccionario de fuentes + FontFile2 + ToUnicode
    assert len(plan.objetos) >= 3, sorted(plan.objetos)

    pdf = pikepdf.open(str(salida))
    try:
        nombres = [str(k) for k in pdf.pages[0].Resources.Font.keys()]
        nuevas = [n for n in nombres if "LPF" in n]
        assert nuevas, nombres
    finally:
        pdf.close()


def test_nivel_2_el_texto_nuevo_se_extrae_con_su_acento():
    """El ToUnicode del subconjunto nuevo tiene que ser correcto, o el texto
    no se podrá copiar ni buscar en el PDF resultante."""
    ruta = CORPUS / "02_fuente_subset.pdf"
    salida = TMP / "t_2.pdf"
    plan = _editar(ruta, 0, "Solo aparecen estas letras: a, e, o, i, u, ó.",
                   salida)
    assert plan.informe.ok
    extraido = _texto(salida)
    assert "ó" in extraido, repr(extraido[:80])
    assert extraido.startswith("Solo aparecen estas letras: a, e, o, i, u, ó")


def test_nivel_2_no_toca_la_fuente_original():
    ruta = CORPUS / "02_fuente_subset.pdf"
    salida = TMP / "t_2.pdf"
    _editar(ruta, 0, "Solo aparecen estas letras: a, e, o, i, u, ó.", salida)

    def fuentes(f):
        pdf = pikepdf.open(str(f))
        try:
            return {str(k): (str(v.get("/BaseFont", "")),
                             len(v.get("/ToUnicode").read_bytes())
                             if v.get("/ToUnicode") is not None else 0)
                    for k, v in
                    [(k, pdf.pages[0].Resources.Font[k])
                     for k in pdf.pages[0].Resources.Font.keys()]}
        finally:
            pdf.close()

    antes = fuentes(ruta)
    despues = fuentes(salida)
    for nombre, datos in antes.items():
        assert despues.get(nombre) == datos, (
            f"la fuente {nombre} cambió: {datos} -> {despues.get(nombre)}")


# ---------------------------------------------------------------------------
# nivel 0: rechazo honesto
# ---------------------------------------------------------------------------

def test_nivel_0_rechaza_y_dice_que_fuente_hace_falta():
    ruta = CORPUS / "02_fuente_subset.pdf"
    plan = _editar(ruta, 0, "Solo aparecen estas letras: aeoiu 漢字",
                   TMP / "t_0.pdf")
    assert not plan.informe.ok
    assert plan.informe.nivel == "0"
    assert "漢" in plan.informe.motivo or "漢" in str(
        plan.informe.glifos_que_faltan)
    assert "no se sustituye" in plan.informe.motivo


def test_nivel_0_si_se_prohibe_la_fuente_nueva():
    ruta = CORPUS / "02_fuente_subset.pdf"
    plan = _editar(ruta, 0, "Solo aparecen estas letras: aeoiu ó",
                   TMP / "t_0b.pdf", permitir_fuente_nueva=False)
    assert not plan.informe.ok
    assert "no se permite fuente nueva" in plan.informe.motivo


# ---------------------------------------------------------------------------
# regresión: el espaciado no puede filtrarse a la línea siguiente
# ---------------------------------------------------------------------------

def test_el_tc_no_se_filtra_a_la_linea_siguiente():
    """El bug más peligroso de F4.

    En estos PDFs el `Tc` se emite DESPUÉS de cada `Tj`, así que fija el
    espaciado del carácter siguiente. Una edición que ponga un `Tc` y no
    restaure el anterior descuadra TODAS las líneas de debajo. Se comprobó que
    pasaba de verdad: 13.232 píxeles cambiados fuera de la región.
    """
    ruta = CORPUS / "02_fuente_subset.pdf"
    salida = TMP / "t_tc.pdf"
    plan = _editar(ruta, 0, "Solo aparecen estas letras: a, e, o, i, u y la ó.",
                   salida, ajustar_espaciado=True)
    assert plan.informe.ok and plan.informe.espaciado_aplicado is not None

    pdf, pagina, datos, contenido, refs = _cargar(ruta)
    try:
        run = [o for o in contenido.objetos if o.tipo == "texto"][0]
        caja = run.caja.como_tupla()
    finally:
        pdf.close()

    a = _render(ruta)
    b = _render(salida)
    m = np.abs(a - b).max(axis=2) > 8

    # La aserción que importa es POR DEBAJO: si el `Tc` se filtra, las líneas
    # siguientes salen comprimidas y se ven píxeles ahí. Arriba y en la propia
    # línea se permite todo, porque el texto comprimido recoloca sus glifos y
    # una `ó` añade acento por encima de la caja original.
    x0, y0, x1, y1 = _caja_en_px(ruta, run.caja)
    debajo = m[int(y1) + 5:, :]
    ys, xs = np.nonzero(debajo)
    assert int(debajo.sum()) == 0, (
        f"{int(debajo.sum())} píxeles cambiados POR DEBAJO de la línea editada "
        f"(primero en y={int(y1) + 5 + ys[0]}, x={xs[0]}): el Tc se filtra. "
        f"caja={tuple(round(v) for v in caja)}")


def test_editar_una_linea_fragmentada_no_toca_las_otras_17():
    ruta = CORPUS / "01_texto_fragmentado.pdf"
    salida = TMP / "t_frag.pdf"
    plan = _editar(ruta, 3, "El rápido zorro cambió esta línea entera.", salida)
    assert plan.informe.ok, plan.informe.resumen()

    a = _render(ruta)
    b = _render(salida)
    m = np.abs(a - b).max(axis=2) > 8
    ys, _ = np.nonzero(m)
    pdf, pagina, datos, contenido, refs = _cargar(ruta)
    try:
        run = [o for o in contenido.objetos if o.tipo == "texto"][3]
        caja = run.caja
    finally:
        pdf.close()
    x0, y0, x1, y1 = _caja_en_px(ruta, caja)
    assert ys.min() >= y0 - 4 and ys.max() <= y1 + 4, (
        f"los cambios salen de la línea: y {ys.min()}-{ys.max()}, "
        f"caja y {y0:.0f}-{y1:.0f}")


# ---------------------------------------------------------------------------
# Texto bajo matrices que NO son la identidad (caso 11)
# ---------------------------------------------------------------------------
#
# Por qué estos tests existen aparte. Todo el resto del corpus escribe el texto
# con la matriz identidad, y eso tapaba dos errores de unidades:
#
#   - el `Tc` del ajuste de espaciado está en espacio de TEXTO, no en puntos de
#     página, así que bajo un `cm` escalado x2 hay que dividirlo por 2;
#   - `ancho_nuevo` se leía antes de asignarse en el camino del nivel 1b, así
#     que «ajustar» compensaba el ancho ENTERO del texto en vez de la
#     diferencia: el texto acababa midiendo más del doble.
#
# El mismo error de unidades que mandaba una imagen a 29.000 pt de su sitio al
# moverla. Se vería en cualquier PDF real con un grupo escalado, que es
# corrientesísimo.

CASO11 = CORPUS / "11_texto_transformado.pdf"


def _ancho_de_avance_en_pagina(informe, escala):
    """Ancho final del texto en puntos de página, según las cuentas del informe.

    No se mide la tinta sino el AVANCE: la suma de los anchos de glifo más el
    `Tc` por carácter, todo escalado por la matriz. Es la magnitud que el ajuste
    promete conservar; la tinta no, porque el último carácter lleva su
    lateral izquierdo y no su avance completo.
    """
    n = informe.chars_reutilizados + len(informe.glifos_que_faltan)
    if informe.nivel == "2":
        n = 0
    return informe.ancho_nuevo


def test_escala_del_run_se_detecta():
    """La escala efectiva de cada run del caso 11 es la que se le puso."""
    pdf, pagina, datos, contenido, refs = _cargar(CASO11)
    try:
        runs = [o for o in contenido.objetos if o.tipo == "texto"]
        escalas = [round(escala_de_run(r), 2) for r in runs]
    finally:
        pdf.close()
    assert escalas == [1.0, 2.0, 0.5, 1.0, 1.8], escalas


def test_delta_en_puntos_esta_en_la_pagina():
    """El desborde que se le anuncia al usuario se mide en la página.

    Para el run escalado x2, el texto nuevo «corto y breve» mide mucho menos:
    el delta tiene que salir del orden de -215 pt, no de -107 (que es lo que
    saldría si se confundiera el espacio de texto con el de página). Se
    comprueba contra el cálculo a mano con los anchos de la fuente.
    """
    pdf, pagina, datos, contenido, refs = _cargar(CASO11)
    try:
        runs = [o for o in contenido.objetos if o.tipo == "texto"]
        run = runs[1]                                   # el del cm x2
        fuentes = resolver_fuentes(pagina)
        fuente = fuentes[run.fuente_nombre]
        codigos = [fuente.codigo_de(c) for c in run.texto]
        ancho_orig = sum(fuente.ancho_de(c) for c in codigos)
        nuevo = "corto y breve"
        ancho_nuevo = sum(fuente.ancho_de(fuente.codigo_de(c)) for c in nuevo)
        tam = run.fuente_tam
        escala = escala_de_run(run)
        esperado = (ancho_nuevo - ancho_orig) * tam / 1000.0 * escala
        plan = plan_editar_texto(datos, CASO11, 0, contenido, run, nuevo)
        inf = plan.informe
    finally:
        pdf.close()
    assert inf.nivel == "1b", inf.nivel
    assert abs(inf.delta_en_puntos - esperado) < 0.01, (
        f"delta {inf.delta_en_puntos:.2f} contra {esperado:.2f} calculado a mano")
    assert inf.delta_en_puntos < -200, (
        f"el delta ({inf.delta_en_puntos:.2f}) parece estar en espacio de texto")


def test_ajustar_conserva_el_ancho_en_la_pagina():
    """Con --ajustar, el avance final tiene que ser el mismo que el de partida.

    Es la promesa de la opción. Antes de arreglar `ancho_nuevo` el texto salía
    midiendo más del doble.
    """
    pdf, pagina, datos, contenido, refs = _cargar(CASO11)
    try:
        runs = [o for o in contenido.objetos if o.tipo == "texto"]
        for idx in (1, 2, 4):          # x2, x0.5 y Tm x1.8 (el rotado se mide aparte)
            run = runs[idx]
            escala = escala_de_run(run)
            fuentes = resolver_fuentes(pagina)
            fuente = fuentes[run.fuente_nombre]
            ancho_orig = sum(fuente.ancho_de(fuente.codigo_de(c))
                             for c in run.texto)
            nuevo = "corto y breve"
            plan = plan_editar_texto(datos, CASO11, 0, contenido, run, nuevo,
                                     ajustar_espaciado=True)
            inf = plan.informe
            # El avance de un carácter es `w/1000*Tfs + Tc`: el Tc se suma en
            # puntos del espacio de texto, no en milésimas de em, así que NO se
            # multiplica por el tamaño de fuente. (La escala del run tampoco
            # entra aquí porque se compara todo en espacio de texto.)
            ancho_final = (inf.ancho_nuevo * run.fuente_tam / 1000.0
                           + len(nuevo) * inf.espaciado_aplicado)
            ancho_orig_texto = ancho_orig * run.fuente_tam / 1000.0
            assert abs(ancho_final - ancho_orig_texto) < 0.01, (
                f"run {idx} (escala {escala}): el ancho final sería "
                f"{ancho_final:.2f} y el original {ancho_orig_texto:.2f}")
            assert inf.espaciado_aplicado > 0, (
                f"run {idx}: el texto se acorta, el Tc debería ser positivo")
            assert abs(inf.espaciado_aplicado) < 1000, (
                f"run {idx}: Tc absurdo ({inf.espaciado_aplicado}), señal de "
                f"haber confundido el espacio de texto con el de página")
    finally:
        pdf.close()


def test_texto_escalado_no_desborda_su_caja():
    """Medido con pdfium: el texto ajustado no se sale de su línea."""
    nuevo = "corto y breve"
    salida = TMP / "test_escalado_ajustado.pdf"
    TMP.mkdir(exist_ok=True)
    pdf, pagina, datos, contenido, refs = _cargar(CASO11)
    try:
        runs = [o for o in contenido.objetos if o.tipo == "texto"]
        run = runs[1]
        caja = run.caja
        plan = plan_editar_texto(datos, CASO11, 0, contenido, run, nuevo,
                                 ajustar_espaciado=True)
        assert plan.informe.ok, plan.informe.motivo
        guardar_pagina_editada(CASO11, salida, 0, [plan.contenido],
                               dict(plan.objetos))
    finally:
        pdf.close()

    doc = pdfium.PdfDocument(str(salida))
    try:
        tp = doc[0].get_textpage()
        xs = []
        for i in range(tp.count_chars()):
            try:
                x0, y0, x1, y1 = tp.get_charbox(i)
            except Exception:
                continue
            if abs((y0 + y1) / 2 - (caja.y0 + caja.y1) / 2) < 8:
                xs += [x0, x1]
    finally:
        doc.close()
    assert xs, "pdfium no ve texto en esa línea"
    assert max(xs) <= caja.x1 + 2.0, (
        f"el texto llega a {max(xs):.1f} y su caja acaba en {caja.x1:.1f}")


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"  FALLA {nombre}: {e}")
            except Exception as e:
                fallos += 1
                print(f"  ERROR {nombre}: {type(e).__name__}: {e}")
    print(f"\n{fallos} fallos")
    sys.exit(1 if fallos else 0)
