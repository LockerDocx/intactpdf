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


def test_guardado_sobre_el_mismo_archivo_con_backup():
    """Guardar sobre el original genera backup y mantiene el prefijo intacto."""
    import shutil
    origen = CORPUS / "00_baseline.pdf"
    inplace = TMP / "test_inplace.pdf"
    inplace_backup = TMP / "test_inplace.pdf~"
    inplace_backup.unlink(missing_ok=True)
    shutil.copy2(origen, inplace)
    bytes_orig = origen.read_bytes()

    with pikepdf.open(inplace) as pdf:
        pagina = pdf.pages[0]
        datos = pagina["/Contents"].read_bytes()
        fuentes = resolver_fuentes(pagina)
    contenido = extraer_objetos(datos, fuentes)
    objeto = [o for o in contenido.objetos if o.tipo == "texto"][0]
    nuevos = escalar_objeto(datos, contenido, objeto, 0.9, 0.9, objeto.caja.centro)

    informe = guardar_pagina_editada(inplace, inplace, 0, [nuevos], crear_backup=True)
    assert informe.prefijo_intacto is True
    assert inplace_backup.exists()
    assert inplace_backup.read_bytes() == bytes_orig
    assert inplace.read_bytes()[:len(bytes_orig)] == bytes_orig
    assert inplace.stat().st_size > len(bytes_orig)


def test_compactar_pdf_purga_historial():
    """Compactar un PDF elimina revisiones incrementales previas."""
    from nucleo.guardar import compactar_pdf
    original = CORPUS / "00_baseline.pdf"
    incremental = TMP / "para_compactar.pdf"
    compactado = TMP / "compactado.pdf"

    with pikepdf.open(original) as pdf:
        pagina = pdf.pages[0]
        datos = pagina["/Contents"].read_bytes()
        fuentes = resolver_fuentes(pagina)
    contenido = extraer_objetos(datos, fuentes)
    objeto = [o for o in contenido.objetos if o.tipo == "texto"][0]
    nuevos = escalar_objeto(datos, contenido, objeto, 0.8, 0.8, objeto.caja.centro)
    guardar_pagina_editada(original, incremental, 0, [nuevos])

    res = compactar_pdf(incremental, compactado)
    assert compactado.exists()
    assert res.bytes_salida < res.bytes_original
    assert res.bytes_ahorrados > 0
    assert res.paginas == 1


def test_compactar_demuestra_eliminacion_irreversible_de_datos():
    """Demostración empírica de redacción: el contenido sobrescrito/borrado
    continúa en el binario incremental previo, pero desaparece al 100%
    del binario tras compactar (sin rastros en xref, streams ni objetos)."""
    from nucleo.guardar import compactar_pdf, escribir_incremental, cuerpo_stream

    secreto = b"SECRETO_BANCARIO_IBAN_ES9121000418450200051332"
    # PDF sintético donde el secreto está en texto claro en el objeto 4
    pdf_raw = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(len(secreto) + 40).encode() + b" >>\nstream\n"
        b"BT /F1 12 Tf 72 700 Td (" + secreto + b") Tj ET\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000204 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n320\n%%EOF\n"
    )
    orig = TMP / "pdf_con_secreto.pdf"
    orig.write_bytes(pdf_raw)
    assert secreto in orig.read_bytes()

    # Paso 1: Edición incremental donde se redacta/borra el secreto sustituyendo por texto censurado
    inc = TMP / "pdf_secreto_incremental.pdf"
    escribir_incremental(orig, inc, {(4, 0): cuerpo_stream(b"BT /F1 12 Tf 72 700 Td (CENSURADO) Tj ET")})
    # En el archivo incremental, el secreto SIGUE EXISTIENDO en los bytes iniciales del archivo
    assert secreto in inc.read_bytes(), "el guardado incremental preserva revisiones anteriores"

    # Paso 2: Compactar el PDF (purga de objetos huérfanos y revisiones obsoletas)
    comp = TMP / "pdf_secreto_compactado.pdf"
    res = compactar_pdf(inc, comp)
    assert comp.exists()
    assert res.bytes_salida < res.bytes_original
    # Comprobación de redacción segura irreversible: el secreto NO existe en ningún byte del fichero
    assert secreto not in comp.read_bytes(), "la compactación debe purgar irrevocablemente el contenido antiguo"


def test_descifrar_pdf_permite_edicion_posterior():
    """Descifrar un PDF permite trabajarlo luego con el motor incremental."""
    from nucleo.guardar import descifrar_pdf
    cifrado = TMP / "cifrado_para_descifrar.pdf"
    descifrado = TMP / "descifrado.pdf"
    cifrado.unlink(missing_ok=True)
    descifrado.unlink(missing_ok=True)

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    pdf.pages[0].Contents = pdf.make_stream(b"BT /F1 24 Tf 1 0 0 1 72 700 Tm (TEST) Tj ET")
    pdf.save(cifrado, encryption=pikepdf.Encryption(owner="pass", user=""))
    pdf.close()

    assert esta_cifrado(cifrado) is True
    assert descifrar_pdf(cifrado, descifrado) is True
    assert esta_cifrado(descifrado) is False

    # Ahora debe permitir guardar ediciones incrementales sin rechazar por cifrado
    salida = TMP / "descifrado_editado.pdf"
    salida.unlink(missing_ok=True)
    with pikepdf.open(descifrado) as pdf:
        datos = pdf.pages[0]["/Contents"].read_bytes()
    info = guardar_pagina_editada(descifrado, salida, 0, [datos], verificar=False)
    assert info.prefijo_intacto is True
    assert salida.exists()


def test_deteccion_firma_digital():
    """Detecta documentos con firmas digitales y avisa antes de editar."""
    from nucleo.guardar import tiene_firma_digital
    no_firmado = TMP / "sin_firma.pdf"
    firmado = TMP / "con_firma.pdf"
    no_firmado.unlink(missing_ok=True)
    firmado.unlink(missing_ok=True)

    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(no_firmado)
    pdf.close()
    assert tiene_firma_digital(no_firmado) is False

    pdf2 = pikepdf.new()
    pdf2.add_blank_page()
    sig_field = pdf2.make_indirect(pikepdf.Dictionary({
        "/FT": pikepdf.Name("/Sig"),
        "/T": pikepdf.String("Firma1"),
        "/V": pikepdf.Dictionary({
            "/Type": pikepdf.Name("/Sig"),
            "/Filter": pikepdf.Name("/Adobe.PPKLite"),
            "/SubFilter": pikepdf.Name("/adbe.pkcs7.detached"),
            "/ByteRange": pikepdf.Array([0, 100, 200, 300])
        })
    }))
    pdf2.Root.AcroForm = pikepdf.Dictionary({
        "/Fields": pikepdf.Array([sig_field])
    })
    pdf2.save(firmado)
    pdf2.close()
    assert tiene_firma_digital(firmado) is True


def test_rotar_pagina_incremental():
    """Rotar una página preserva el prefijo original intacto y actualiza /Rotate."""
    from nucleo.guardar import rotar_pagina
    orig = CORPUS / "00_baseline.pdf"
    salida = TMP / "rotado_90.pdf"
    salida.unlink(missing_ok=True)

    info = rotar_pagina(orig, salida, 0, 90)
    assert info.prefijo_intacto is True
    assert salida.exists()
    assert salida.read_bytes().startswith(orig.read_bytes())

    with pikepdf.open(salida) as pdf:
        assert int(pdf.pages[0].get("/Rotate", 0)) == 90


def test_extraer_y_reemplazar_imagen():
    """Extraer una imagen a disco y reemplazarla manteniendo el prefijo intacto."""
    from PIL import Image
    from nucleo.guardar import extraer_imagen, reemplazar_imagen

    orig = CORPUS / "04_imagen_smask.pdf"
    with pikepdf.open(orig) as pdf:
        nombre_xobj = list(pdf.pages[0].Resources.XObject.keys())[0]

    # 1. Extraer imagen
    img_extraida = TMP / "extraida.png"
    img_extraida.unlink(missing_ok=True)
    res_path = extraer_imagen(orig, 0, nombre_xobj, img_extraida)
    assert res_path.exists()
    with Image.open(res_path) as im:
        assert im.size == (300, 200)

    # 2. Crear una nueva imagen de sustitución (50x50 verde)
    nueva_img = TMP / "sustituta.png"
    Image.new("RGB", (50, 50), color="green").save(nueva_img)

    # 3. Reemplazar imagen de forma incremental
    pdf_reemplazado = TMP / "img_reemplazada.pdf"
    pdf_reemplazado.unlink(missing_ok=True)
    info = reemplazar_imagen(orig, pdf_reemplazado, 0, nombre_xobj, nueva_img)
    assert info.prefijo_intacto is True
    assert pdf_reemplazado.read_bytes().startswith(orig.read_bytes())

    # 4. Verificar que el XObject en el PDF final tiene las nuevas dimensiones
    with pikepdf.open(pdf_reemplazado) as pdf2:
        xobj = pdf2.pages[0].Resources.XObject[nombre_xobj]
        assert int(xobj.Width) == 50
        assert int(xobj.Height) == 50


def test_reemplazar_imagen_con_transparencia_smask():
    """Reemplazar por una imagen RGBA con transparencia genera máscara /SMask estándar."""
    from PIL import Image
    from nucleo.guardar import reemplazar_imagen

    orig = CORPUS / "04_imagen_smask.pdf"
    with pikepdf.open(orig) as pdf:
        nombre_xobj = list(pdf.pages[0].Resources.XObject.keys())[0]

    # Crear imagen con canal alfa real (mitad transparente)
    nueva_img_rgba = TMP / "transparente.png"
    im = Image.new("RGBA", (60, 40), (255, 0, 0, 120))
    im.save(nueva_img_rgba)

    pdf_salida = TMP / "img_con_smask.pdf"
    pdf_salida.unlink(missing_ok=True)
    info = reemplazar_imagen(orig, pdf_salida, 0, nombre_xobj, nueva_img_rgba)
    assert info.prefijo_intacto is True

    with pikepdf.open(pdf_salida) as pdf_res:
        xobj = pdf_res.pages[0].Resources.XObject[nombre_xobj]
        assert "/SMask" in xobj, "El XObject debe incluir /SMask para preservar la transparencia"
        smask = xobj.SMask
        assert str(smask.ColorSpace) == "/DeviceGray"
        assert int(smask.Width) == 60
        assert int(smask.Height) == 40


def test_rotar_pagina_con_rotacion_heredada():
    """Rotar respeta y acumula /Rotate cuando está definido en un nodo ancestro /Pages."""
    from nucleo.guardar import rotar_pagina
    # Crear un PDF temporal con rotación heredada de 90° en el nodo /Pages
    pdf_base = pikepdf.Pdf.new()
    pdf_base.add_blank_page(page_size=(200, 200))
    # Colocar /Rotate 90 en el padre /Pages
    padre = pdf_base.pages[0].obj.Parent
    padre.Rotate = 90
    ruta_heredada = TMP / "rotacion_heredada_90.pdf"
    pdf_base.save(ruta_heredada)
    pdf_base.close()

    # Ahora rotamos 90° adicionales con rotar_pagina
    salida_rotada = TMP / "rotacion_heredada_180.pdf"
    salida_rotada.unlink(missing_ok=True)
    rotar_pagina(ruta_heredada, salida_rotada, 0, 90)

    with pikepdf.open(salida_rotada) as pdf_res:
        assert int(pdf_res.pages[0].Rotate) == 180


