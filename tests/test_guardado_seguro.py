"""
Las garantías del guardado: que lo escrito se vea, que no se escriba a medias
y que un documento cifrado se rechace en vez de romperse.

Todo esto nació de probar con PDFs reales de servidores públicos
(`tools/prueba_real.py`). El guardado incremental promete que lo que no se toca
queda byte a byte igual, y esa promesa se cumplía... mientras el fichero no se
pudiera ver. Son dos promesas distintas y hay que probar las dos.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nucleo.editar import escalar_objeto  # noqa: E402
from nucleo.fuentes import resolver_fuentes  # noqa: E402
from nucleo.guardar import (ErrorGuardado, esta_cifrado,  # noqa: E402
                            guardar_pagina_editada, verificar_que_se_ve)
from nucleo.objetos import extraer_objetos  # noqa: E402

CORPUS = Path(__file__).resolve().parent.parent / "corpus"
TMP = Path(__file__).resolve().parent.parent / ".tmp"
TMP.mkdir(exist_ok=True)
BLANCO = TMP / "pagina_en_blanco.pdf"


def _pagina_en_blanco() -> Path:
    """Un PDF válido, de una página, sin nada dibujado."""
    if not BLANCO.exists():
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(595, 842))
        pdf.save(BLANCO)
        pdf.close()
    return BLANCO


_pagina_en_blanco()


def _pagina_con_fuente_puesta_una_sola_vez() -> Path:
    """El documento real, en miniatura: la fuente se pone UNA vez.

    Es el patrón de un PDF generado por una herramienta seria (el que lo
    destapó tenía 2.882 páginas y la fuente puesta en el primer objeto): el
    primer bloque de texto pone la fuente y los siguientes escriben sin
    volver a ponerla, apoyándose en que el estado de texto sigue ahí.
    """
    ruta = TMP / "fuente_una_vez.pdf"
    pdf = pikepdf.new()
    pagina = pdf.add_blank_page(page_size=(595, 842))
    pagina.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(
        F1=pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica))))
    pagina.Contents = pdf.make_stream(
        b"BT /F1 24 Tf 1 0 0 1 72 700 Tm (CABECERA) Tj 0 Tc .5 Tw ET\n"
        b"BT 1 0 0 1 72 400 Tm (CUERPO SIN FUENTE) Tj ET")
    pdf.save(ruta)
    pdf.close()
    return ruta


def test_la_comprobacion_de_que_se_ve_detecta_una_pagina_en_blanco():
    """Una salida en blanco donde el original tenía contenido: hay que verlo."""
    problema = verificar_que_se_ve(CORPUS / "00_baseline.pdf", BLANCO, 0)
    assert problema is not None, "una página en blanco tiene que dar la alarma"
    assert "blanco" in problema


def test_la_comprobacion_de_que_se_ve_no_se_queja_cuando_todo_está_bien():
    """Y no puede dar falsos positivos con un documento normal."""
    assert verificar_que_se_ve(CORPUS / "00_baseline.pdf",
                               CORPUS / "00_baseline.pdf", 0) is None


def test_guardar_no_deja_fichero_si_la_comprobacion_falla(monkeypatch_temporal=None):
    """El guardado tiene que negarse Y no dejar el fichero a medias.

    Se fuerza el fallo de la comprobación en vez de buscar un PDF real que lo
    provoque: lo que se prueba aquí es la reacción (borrar y avisar), y con un
    documento de verdad lo que se prueba es la detección, que tiene su test
    arriba. Un fichero a medias es peor que no escribir: parece que el trabajo
    está hecho.
    """
    import nucleo.guardar as g
    original = CORPUS / "00_baseline.pdf"
    salida = CORPUS.parent / ".tmp" / "no_debe_quedar.pdf"
    salida.parent.mkdir(exist_ok=True)
    salida.unlink(missing_ok=True)
    de_verdad = g.verificar_que_se_ve
    g.verificar_que_se_ve = lambda *a, **k: "forzado para el test"
    try:
        pdf = pikepdf.open(original)
        try:
            contenido = pdf.pages[0]["/Contents"].read_bytes()
        finally:
            pdf.close()
        try:
            g.guardar_pagina_editada(original, salida, 0, [contenido])
            raise AssertionError("tenía que negarse a guardar")
        except g.ErrorGuardado as e:
            assert "forzado para el test" in str(e)
    finally:
        g.verificar_que_se_ve = de_verdad
    assert not salida.exists(), "no puede quedar el fichero a medias"


def _tinta(ruta: Path, escala: float = 1.0) -> float:
    """Proporción de la página con algo dibujado, con pdfium (lo que ve la GUI)."""
    import numpy as np
    doc = pdfium.PdfDocument(str(ruta))
    a = np.asarray(doc[0].render(scale=escala).to_pil().convert("RGB"))
    doc.close()
    return float((a.min(axis=2) < 250).mean())


def test_editar_un_texto_no_deja_sin_fuente_al_resto_de_la_pagina():
    """El fallo de la portada del PDF del Gobierno de EE. UU., en miniatura.

    Al escalar un objeto de texto se envuelve en `q … cm … Q`. El `Q` devuelve
    el estado gráfico —y el estado de texto forma parte de él— así que la fuente
    se pierde; y si el documento la puso una sola vez y no la vuelve a poner,
    TODO el texto siguiente se queda sin dibujar. La página se veía casi en
    blanco: se perdía el título, no el fichero.
    """
    ruta = _pagina_con_fuente_puesta_una_sola_vez()
    antes = _tinta(ruta)
    assert antes > 0.002, "la página de partida tiene que tener texto"

    # La edición de verdad: escalar el objeto de texto que pone la fuente.
    # (Con sólo reescribir el contenido sin tocarlo no se reproduce: el fallo
    # lo introduce el `q … cm … Q` que envuelve al objeto editado.)
    salida = TMP / "fuente_una_vez_editado.pdf"
    salida.unlink(missing_ok=True)
    with pikepdf.open(ruta) as pdf:
        pagina = pdf.pages[0]
        datos = pagina["/Contents"].read_bytes()
        fuentes = resolver_fuentes(pagina)
    contenido = extraer_objetos(datos, fuentes)
    objeto = [o for o in contenido.objetos if o.tipo == "texto"][0]
    centro = objeto.caja.centro
    nuevos = escalar_objeto(datos, contenido, objeto, 0.9, 0.9, centro)
    assert b"q 0.9" in nuevos, "la edición tiene que envolver el objeto"
    guardar_pagina_editada(ruta, salida, 0, [nuevos])

    # «CUERPO SIN FUENTE» está en la mitad de abajo: si el `Q` se lleva la
    # fuente por delante, ahí no queda nada.
    import numpy as np
    doc = pdfium.PdfDocument(str(salida))
    a = np.asarray(doc[0].render(scale=1.0).to_pil().convert("RGB"))
    doc.close()
    abajo = a[int(a.shape[0] * 0.4):]
    assert (abajo.min(axis=2) < 250).mean() > 0.001, (
        "el texto de abajo depende de la fuente puesta arriba: no puede "
        "desaparecer sin más")


def test_un_documento_cifrado_se_rechaza_en_vez_de_romperse():
    """Escribir en claro dentro de un fichero cifrado deja una página en blanco."""
    cifrado = TMP / "cifrado.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    pdf.pages[0].Contents = pdf.make_stream(b"BT /F1 24 Tf 1 0 0 1 72 700 Tm (HOLA) Tj ET")
    pdf.save(cifrado, encryption=pikepdf.Encryption(owner="duenyo", user="", R=6))
    pdf.close()

    assert esta_cifrado(cifrado) is True
    assert esta_cifrado(CORPUS / "00_baseline.pdf") is False

    salida = TMP / "cifrado_editado.pdf"
    salida.unlink(missing_ok=True)
    with pikepdf.open(cifrado) as pdf:
        datos = pdf.pages[0]["/Contents"].read_bytes()
    try:
        guardar_pagina_editada(cifrado, salida, 0, [datos])
        raise AssertionError("tenía que negarse a guardar")
    except ErrorGuardado as e:
        assert "cifrado" in str(e)
    assert not salida.exists(), "no puede quedar un fichero a medias"


def test_la_ventana_no_abre_un_documento_cifrado():
    """El rechazo tiene que ser al abrir, no al pintar.

    Un error dentro del bucle de dibujo de GTK no se ve y deja la ventana
    colgada hasta el tiempo límite: por eso se comprueba al abrir el documento.
    """
    from gui.modelo import Sesion
    sesion = Sesion()
    try:
        sesion.abrir(TMP / "cifrado.pdf")
        raise AssertionError("tenía que negarse a abrir")
    except ErrorGuardado as e:
        assert "cifrado" in str(e)
