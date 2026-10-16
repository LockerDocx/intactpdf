"""Tests de la extracción y selección de objetos sobre el corpus real."""
from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nucleo.alinear_texto import alinear, chars_de_pagina  # noqa: E402
from nucleo.fuentes import parsear_tounicode, resolver_fuentes  # noqa: E402
from nucleo.geometria import (Caja, aplicar, invertir, matriz_pagina,  # noqa: E402
                              multiplicar)
from nucleo.objetos import (Imagen, TextoRun, Vector, aplanar_camino,  # noqa: E402
                            en_poligono, extraer_objetos)

CORPUS = Path(__file__).resolve().parent.parent / "corpus"
CASOS = [p.stem for p in sorted(CORPUS.glob("*.pdf"))]


def pagina(ruta: Path, n: int = 0):
    """Devuelve (datos_del_stream, fuentes, doc_pdfium)."""
    pdf = pikepdf.open(str(ruta))
    pg = pdf.pages[n]
    c = pg.get("/Contents")
    datos = (b"\n".join(s.read_bytes() for s in c)
             if isinstance(c, pikepdf.Array) else c.read_bytes())
    return datos, resolver_fuentes(pg), pdf


def contenido_de(ruta: Path, n: int = 0):
    datos, fuentes, pdf = pagina(ruta, n)
    try:
        return extraer_objetos(datos, fuentes)
    finally:
        pdf.close()


# ---------------------------------------------------------------------------
# geometría
# ---------------------------------------------------------------------------

def test_identidad_no_mueve_nada():
    from nucleo.geometria import IDENTIDAD
    assert aplicar(IDENTIDAD, 3, 7) == (3, 7)


def test_traslaciones_se_componen():
    m = multiplicar((1, 0, 0, 1, 10, 0), (1, 0, 0, 1, 0, 5))
    assert aplicar(m, 0, 0) == (10, 5)


def test_invertir_deshace():
    m = (2, 0, 0, 3, 10, -5)
    inv = invertir(m)
    assert inv is not None
    x, y = aplicar(inv, *aplicar(m, 4, 7))
    assert abs(x - 4) < 1e-9 and abs(y - 7) < 1e-9


def test_matriz_pagina_invierte_y():
    m, w, h = matriz_pagina([0, 0, 595.276, 841.89], 0)
    assert aplicar(m, 0, 0)[1] == h
    assert aplicar(m, 0, h)[1] == 0
    assert (round(w, 2), round(h, 2)) == (595.28, 841.89)


def test_caja_contiene_y_solape():
    a = Caja(0, 0, 10, 10)
    assert a.contiene(5, 5) and not a.contiene(11, 5)
    assert a.contiene(11, 5, tolerancia=2)
    b = Caja(5, 5, 15, 15)
    assert a.intersecta(b) and a.solape(b) == 25.0 and a.area() == 100.0


# ---------------------------------------------------------------------------
# fuentes
# ---------------------------------------------------------------------------

def test_tounicode_bfchar():
    cmap = (b"beginbfchar\n<0041> <0041>\n<0042> <00FF>\nendbfchar\n")
    d = parsear_tounicode(cmap)
    assert d[0x41] == "A"
    assert d[0x42] == "\u00ff"


def test_tounicode_bfrange():
    cmap = b"beginbfrange\n<0041> <0043> <0061>\nendbfrange\n"
    d = parsear_tounicode(cmap)
    assert d[0x41] == "a" and d[0x42] == "b" and d[0x43] == "c"


def test_fuente_type0_identity_h_usa_dos_bytes():
    """El caso 10 es Type0/Identity-H: 2 bytes por código. Contar 1 byte por
    código daría el doble de caracteres y rompería toda la alineación."""
    ruta = CORPUS / "10_fuente_completa.pdf"
    _, fuentes, pdf = pagina(ruta)
    try:
        f = fuentes["F1"]
        assert f.bytes_por_codigo == 2, f.bytes_por_codigo
        assert f.subtipo.endswith("Type0")
        assert f.descodificar(b"\x00\x41") is not None
    finally:
        pdf.close()


def test_fuente_simple_usa_un_byte():
    ruta = CORPUS / "00_baseline.pdf"
    _, fuentes, pdf = pagina(ruta)
    try:
        assert any(f.bytes_por_codigo == 1 for f in fuentes.values())
    finally:
        pdf.close()


def test_se_detectan_fuentes_subconjuntadas():
    ruta = CORPUS / "02_fuente_subset.pdf"
    _, fuentes, pdf = pagina(ruta)
    try:
        subs = [f for f in fuentes.values() if f.subconjuntada]
        assert subs, "no se detectó ninguna fuente subconjuntada"
        assert any(f.base_font.startswith("AAAAAA+") for f in subs), \
            [(f.nombre, f.base_font) for f in fuentes.values()]
    finally:
        pdf.close()


# ---------------------------------------------------------------------------
# extracción sobre el corpus
# ---------------------------------------------------------------------------

def test_01_texto_fragmentado_da_18_lineas():
    c = contenido_de(CORPUS / "01_texto_fragmentado.pdf")
    runs = c.por_tipo("texto")
    assert len(runs) == 18, len(runs)
    assert all(r.n_operadores_texto == 97 for r in runs)
    # las 18 líneas deben estar en 18 alturas distintas, a 34 pt de distancia
    ys = sorted({round(r.caja.y0) for r in runs if r.caja}, reverse=True)
    assert len(ys) == 18, ys
    pasos = {a - b for a, b in zip(ys, ys[1:])}
    assert pasos == {34}, pasos


def test_03_vectores_detecta_trazados_y_clip():
    c = contenido_de(CORPUS / "03_vectores_clip_degradado.pdf")
    vectores = c.por_tipo("vector")
    assert len(vectores) >= 2, len(vectores)
    rects = [v for v in vectores if v.n_segmentos == 1]
    assert len(rects) >= 50, len(rects)
    assert all(v.recortado_por for v in rects), "el clip no se propaga"
    estrella = [v for v in vectores if v.n_segmentos >= 14]
    assert estrella, "no se encontró la estrella de 14 segmentos"
    assert not estrella[0].recortado_por


def test_04_imagen_con_smask_se_detecta():
    c = contenido_de(CORPUS / "04_imagen_smask.pdf")
    imgs = c.por_tipo("imagen")
    assert len(imgs) == 1, len(imgs)
    caja = imgs[0].caja
    assert (round(caja.x0), round(caja.y0)) == (72, 560), caja
    assert (round(caja.ancho), round(caja.alto)) == (300, 200), caja


def test_06_modos_de_texto_se_marcan():
    c = contenido_de(CORPUS / "06_modos_de_texto.pdf")
    runs = c.por_tipo("texto")
    modos = sorted({r.modo_texto for r in runs})
    assert {0, 1, 3} <= set(modos), modos
    invisibles = [r for r in runs if r.modo_texto == 3]
    assert invisibles and not invisibles[0].es_visible
    assert any("invisible" in x for x in invisibles[0].razones_no_editable)


def test_seleccion_en_punto_encuentra_la_imagen():
    c = contenido_de(CORPUS / "04_imagen_smask.pdf")
    hits = c.en_punto(72 + 150, 560 + 100)
    assert hits and isinstance(hits[0], Imagen)
    assert c.en_punto(10, 10) == []


# ---------------------------------------------------------------------------
# alineación: el test que decide si F1 es viable
# ---------------------------------------------------------------------------

def test_alineacion_del_caso_dificil():
    """1.746 operadores de texto en una página, alineados carácter a carácter."""
    ruta = CORPUS / "01_texto_fragmentado.pdf"
    c = contenido_de(ruta)
    doc = pdfium.PdfDocument(str(ruta))
    chars = chars_de_pagina(doc[0].get_textpage())
    doc.close()
    inf = alinear(c, chars)
    assert inf["cuadre_global"], inf
    assert inf["runs_alineados"] == 18, inf
    primer = c.por_tipo("texto")[0]
    assert primer.texto.startswith("El rápido zorro"), repr(primer.texto[:40])
    assert len(primer.posiciones_chars) == len(primer.texto)
    # cada carácter tiene su propia caja (la altura varía según el glifo);
    # lo que debe cumplirse es que todos caen dentro de la caja de la línea
    for b in primer.posiciones_chars:
        assert primer.caja.contiene((b[0] + b[2]) / 2, (b[1] + b[3]) / 2,
                                    tolerancia=1.0), (b, primer.caja)


def test_corpus_completo_alinea_todos_los_runs():
    """Los 11 PDFs del corpus. Este es el test de viabilidad de la fase F1."""
    filas = []
    for nombre in CASOS:
        ruta = CORPUS / f"{nombre}.pdf"
        c = contenido_de(ruta)
        doc = pdfium.PdfDocument(str(ruta))
        chars = chars_de_pagina(doc[0].get_textpage())
        doc.close()
        inf = alinear(c, chars)
        filas.append((nombre, inf, c))

    print()
    print(f"  {'archivo':30} {'alineados':>10} {'sinPos':>7} {'ambig':>6}  método")
    for nombre, inf, _ in filas:
        print(f"  {nombre:30} {inf['runs_alineados']:>5}/{inf['runs']:<4} "
              f"{inf.get('chars_sin_posicion', 0):>7} {inf['chars_ambiguos']:>6}  "
              f"{inf['metodo']}")
    total_al = sum(i["runs_alineados"] for _, i, _ in filas)
    total = sum(i["runs"] for _, i, _ in filas)
    print(f"  -> {total_al}/{total} runs alineados")
    assert total_al == total, f"{total - total_al} runs sin alinear"


def test_09_declara_los_huecos_en_vez_de_inventarlos():
    """pdfium colapsa los espacios consecutivos. El alineador debe declararlo,
    no repartir caracteres equivocados. 38 líneas con un espacio doble = 38
    caracteres sin posición, que es exactamente la discrepancia de conteo."""
    ruta = CORPUS / "09_documento_grande.pdf"
    c = contenido_de(ruta)
    doc = pdfium.PdfDocument(str(ruta))
    chars = chars_de_pagina(doc[0].get_textpage())
    doc.close()
    inf = alinear(c, chars)
    sin_pos = inf.get("chars_sin_posicion", 0)
    descuadre = inf["chars_que_cuenta_el_parser"] - inf["chars_reales"]
    assert sin_pos == descuadre, (sin_pos, descuadre)
    assert sin_pos == 38, sin_pos
    run = c.por_tipo("texto")[1]
    assert run.alineado and run.indices_sin_posicion, run


def test_texto_invisible_no_se_alinea_a_ciegas():
    """El texto con Tr 3 no lo extrae pdfium. Debe quedar marcado, no alineado
    contra el texto de otro objeto."""
    ruta = CORPUS / "06_modos_de_texto.pdf"
    c = contenido_de(ruta)
    doc = pdfium.PdfDocument(str(ruta))
    chars = chars_de_pagina(doc[0].get_textpage())
    doc.close()
    alinear(c, chars)
    invisibles = [r for r in c.por_tipo("texto") if r.modo_texto == 3]
    assert invisibles
    # o bien no está alineado, o bien lo está con su propio texto intacto
    for r in invisibles:
        if r.alineado:
            assert "invisible" in r.texto, repr(r.texto)


# ---------------------------------------------------------------------------
# hit test: el clip debe respetarse
# ---------------------------------------------------------------------------

def test_aplanar_camino_convierte_re_en_poligono():
    from nucleo.parser import parsear
    subs = aplanar_camino(parsear(b"10 10 20 30 re"))
    assert len(subs) == 1 and len(subs[0]) == 4, subs


def test_aplanar_camino_muestrea_las_bezier():
    """Una circunferencia con 4 Béziers debe dar muchos puntos, no 4: con solo
    los puntos de control la caja incluye esquinas donde el círculo no está."""
    from nucleo.parser import parsear
    k = 0.5523 * 100
    d = (f"200 300 m "
         f"200 {300 + k} 100 {300 + k} 100 300 c "      # arriba-derecha
         f"100 {300 - k} 200 {300 - k} 200 300 c").encode()
    subs = aplanar_camino(parsear(d))
    assert subs and len(subs[0]) > 20, len(subs[0]) if subs else 0


def test_en_poligono():
    cuadrado = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert en_poligono(cuadrado, 5, 5)
    assert not en_poligono(cuadrado, 15, 5)
    assert not en_poligono(cuadrado, -1, 5)
    # un triángulo: el centro de su caja envolvente cae fuera
    triangulo = [(0, 0), (10, 0), (0, 10)]
    assert not en_poligono(triangulo, 8, 8)
    assert en_poligono(triangulo, 2, 2)


def test_hit_test_respeta_el_clip():
    """Un clic en la esquina de un degradado circular NO debe seleccionar los
    rectángulos recortados: visualmente no están ahí."""
    c = contenido_de(CORPUS / "03_vectores_clip_degradado.pdf")
    rects = [v for v in c.por_tipo("vector") if v.n_segmentos == 1]
    assert rects and all(v.recortado_por for v in rects)
    u = rects[0].caja
    for r in rects[1:]:
        u = u.union(r.caja)

    def cuantos(x, y, **kw):
        return [o for o in c.en_punto(x, y, **kw) if o.n_segmentos == 1]

    esquina = (u.x0 + 2, u.y1 - 2)
    centro = u.centro
    assert len(cuantos(*esquina)) == 0, "el clip no se respeta en la esquina"
    assert len(cuantos(*centro)) > 0, "el centro visible debe seleccionar"
    # y con el clip desactivado sí aparece (comportamiento de bbox puro)
    assert len(cuantos(*esquina, respetar_clip=False)) > 0


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
