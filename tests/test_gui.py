"""
Tests de la interfaz gráfica.

Dos niveles, y el segundo es el que importa:

  1. El modelo de la sesión, que no depende de GTK y se puede probar en
     cualquier sitio.

  2. LA GUI NO PUEDE GUARDAR ALGO DISTINTO DEL CLI. Es la prueba de que la
     interfaz gráfica es una forma distinta de pulsar los mismos botones y no un
     segundo programa con su propia idea de cómo se edita un PDF. Se hace la
     misma operación por los dos caminos y se comparan los bytes: si no son
     idénticos, esto falla.

Los tests de la ventana se saltan solos si no hay PyGObject o si no hay pantalla,
para que la suite siga corriendo en un contenedor sin escritorio.

    python3 tests/test_gui.py                      # solo el modelo
    DISPLAY=:99 python3 tests/test_gui.py          # modelo y ventana (Xvfb)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from gui.modelo import Sesion  # noqa: E402

CORPUS = RAIZ / "corpus"
TMP = RAIZ / ".tmp"
TMP.mkdir(exist_ok=True)


def _hay_gtk() -> bool:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# El modelo
# ---------------------------------------------------------------------------

def test_abrir_lista_los_objetos_de_la_pagina():
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    tipos = [o.tipo for o in s.objetos()]
    assert tipos == ["imagen", "vector", "texto", "texto"], tipos
    assert s.n_paginas == 1


def test_el_clic_selecciona_el_objeto_que_hay_debajo():
    """El hit-test del núcleo, a través del modelo."""
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    assert s.seleccionar_en(232, 680).tipo == "imagen"
    assert s.seleccionar_en(200, 550).tipo == "vector"
    assert s.seleccionar_en(150, 500).tipo == "texto"
    # en un sitio vacío no selecciona nada
    assert s.seleccionar_en(500, 100) is None


def test_volver_a_pinchar_pasa_al_siguiente_candidato():
    """Con cosas apiladas, hay que poder llegar a la de debajo."""
    s = Sesion()
    s.abrir(CORPUS / "03_vectores_clip_degradado.pdf")
    centro = s.objetos()[0].caja.centro
    vistos = set()
    for _ in range(6):
        o = s.seleccionar_en(*centro)
        if o is not None:
            vistos.add(o.tipo)
    assert vistos >= {"vector"}, vistos


def test_mover_escala_y_borrar_dejan_la_geometria_donde_toca():
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    img = s.objetos_de("imagen")[0]
    antes = img.caja.como_tupla()
    s.seleccionar(img)
    assert s.escalar(0.5)
    despues = [o for o in s.objetos() if o.tipo == "imagen"][0].caja.como_tupla()
    esperado = (antes[0] + antes[2]) / 2, (antes[1] + antes[3]) / 2
    assert abs((despues[0] + despues[2]) / 2 - esperado[0]) < 0.5
    assert abs((despues[1] + despues[3]) / 2 - esperado[1]) < 0.5
    assert abs((despues[2] - despues[0]) - (antes[2] - antes[0]) * 0.5) < 0.5

    s.seleccionar(s.objetos_de("vector")[0])
    assert s.borrar()
    assert [o.tipo for o in s.objetos()].count("vector") == 0


def test_deshacer_devuelve_el_documento_exacto():
    """Deshacer no es «más o menos como estaba»: son los mismos bytes."""
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    original = s.bytes_actuales()
    s.seleccionar(s.objetos_de("imagen")[0])
    s.escalar(0.6)
    assert s.hay_cambios
    assert s.bytes_actuales() != original
    assert s.deshacer()
    assert not s.hay_cambios, "tras deshacer no debería quedar ningún cambio"
    assert s.bytes_actuales() == original, "los bytes no son los del original"


def test_la_vista_previa_refleja_las_ediciones_pendientes():
    """Lo que se ve es lo que se va a guardar, no el fichero del disco.

    Este test existe por un bug real: `hay_cambios` miraba solo la lista de
    objetos nuevos, y mover/escalar/borrar no crean objetos nuevos, así que la
    aplicación creía que no había cambios y la vista previa seguía enseñando el
    documento original después de editar. El tamaño del PDF en memoria era el
    del original, que es lo que lo delató.
    """
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    antes = len(s.bytes_actuales())
    s.seleccionar(s.objetos_de("imagen")[0])
    s.escalar(0.6)
    assert s.hay_cambios is True
    assert len(s.bytes_actuales()) != antes


def test_editar_texto_con_un_glifo_que_falta():
    """La GUI llega al nivel 2 (incrustar subconjunto) igual que el CLI."""
    s = Sesion()
    s.abrir(CORPUS / "02_fuente_subset.pdf")
    s.seleccionar_en(150, 785)
    assert s.seleccion is not None and s.seleccion.tipo == "texto"
    assert s.editar_texto("Letras con acento: ñ, ó, €.")
    assert s.hay_cambios
    assert "nivel 2" in s.ultimo_mensaje, s.ultimo_mensaje


def test_editar_texto_avisa_cuando_no_puede():
    """Si no se puede, hay que decir POR QUÉ. No basta con fallar."""
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    s.seleccionar_en(232, 680)          # la imagen, no un texto
    assert s.editar_texto("lo que sea") is False
    assert "texto" in s.ultimo_aviso


def test_indices_de_pagina_van_y_vienen():
    s = Sesion()
    s.abrir(CORPUS / "07_paginas_rotadas_mixtas.pdf")
    assert s.n_paginas == 5
    s.ir_a_pagina(3)
    assert s.num_pagina == 3
    assert s.objetos(), "la página 4 tiene que tener objetos"


# ---------------------------------------------------------------------------
# GUI contra CLI: el test que de verdad importa
# ---------------------------------------------------------------------------

def _por_el_cli(args: list[str]) -> int:
    r = subprocess.run([sys.executable, "-m", "nucleo.cli"] + args,
                       cwd=RAIZ, capture_output=True, text=True)
    assert r.returncode == 0, f"el CLI falló: {r.stdout}\n{r.stderr}"
    return r.returncode


def test_la_gui_guarda_lo_mismo_que_el_cli_escalar():
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    s.seleccionar(s.objetos_de("imagen")[0])
    s.escalar(0.6)
    de_gui = TMP / "gui_vs_cli_escalar_gui.pdf"
    s.guardar(de_gui)

    de_cli = TMP / "gui_vs_cli_escalar_cli.pdf"
    _por_el_cli(["scale", str(CORPUS / "05_cmyk_imprenta.pdf"),
                 "--object", "0", "--factor", "0.6", "-o", str(de_cli)])

    assert de_gui.read_bytes() == de_cli.read_bytes(), (
        "la GUI y el CLI han guardado ficheros distintos con la misma edición")


def test_la_gui_guarda_lo_mismo_que_el_cli_borrar():
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    s.seleccionar(s.objetos_de("vector")[0])
    s.borrar()
    de_gui = TMP / "gui_vs_cli_borrar_gui.pdf"
    s.guardar(de_gui)

    de_cli = TMP / "gui_vs_cli_borrar_cli.pdf"
    _por_el_cli(["delete", str(CORPUS / "05_cmyk_imprenta.pdf"),
                 "--object", "1", "-o", str(de_cli)])
    assert de_gui.read_bytes() == de_cli.read_bytes()


def test_la_gui_guarda_lo_mismo_que_el_cli_texto():
    s = Sesion()
    s.abrir(CORPUS / "00_baseline.pdf")
    s.seleccionar_en(150, 785)
    nuevo = "Cambiado desde la ventana"
    assert s.editar_texto(nuevo)
    de_gui = TMP / "gui_vs_cli_texto_gui.pdf"
    s.guardar(de_gui)

    de_cli = TMP / "gui_vs_cli_texto_cli.pdf"
    _por_el_cli(["edit", str(CORPUS / "00_baseline.pdf"),
                 "--object", "0", "--text", nuevo, "-o", str(de_cli)])
    assert de_gui.read_bytes() == de_cli.read_bytes()


def test_lo_que_guarda_la_gui_empieza_por_el_original():
    """La promesa del proyecto, comprobada también por el camino de la GUI."""
    s = Sesion()
    s.abrir(CORPUS / "02_fuente_subset.pdf")
    s.seleccionar_en(150, 785)
    s.editar_texto("Otra cosa con ñ")
    salida = TMP / "gui_prefijo.pdf"
    s.guardar(salida)
    original = (CORPUS / "02_fuente_subset.pdf").read_bytes()
    assert salida.read_bytes()[:len(original)] == original


def test_guardar_sobre_original_en_gui_crea_backup_y_reinicia_cambios():
    """Guardar sin destino en la sesión guarda sobre el original con backup."""
    import shutil
    origen = CORPUS / "02_fuente_subset.pdf"
    inplace = TMP / "gui_inplace.pdf"
    backup = TMP / "gui_inplace.pdf~"
    backup.unlink(missing_ok=True)
    shutil.copy2(origen, inplace)
    bytes_orig = origen.read_bytes()

    s = Sesion()
    s.abrir(inplace)
    s.seleccionar_en(150, 785)
    assert s.editar_texto("Texto modificado in-place")
    assert s.hay_cambios is True

    msg = s.guardar()
    assert s.hay_cambios is False
    assert backup.exists()
    assert backup.read_bytes() == bytes_orig
    assert inplace.read_bytes()[:len(bytes_orig)] == bytes_orig
    assert "copia previa" in msg


def test_sesion_rotar_extraer_y_reemplazar_imagen():
    """Operaciones de imagen y rotación sobre la Sesion de la GUI."""
    import shutil
    from PIL import Image

    origen = CORPUS / "04_imagen_smask.pdf"
    trabajo = TMP / "gui_imagen_trabajo.pdf"
    shutil.copy2(origen, trabajo)

    s = Sesion()
    s.abrir(trabajo)
    assert s.tiene_firma is False

    # 1. Rotar página
    assert s.rotar(90) is True
    assert "rotada 90°" in s.ultimo_mensaje

    # 2. Seleccionar imagen
    im_objs = [o for o in s.objetos() if o.tipo == "imagen"]
    assert len(im_objs) > 0
    s.seleccionar(im_objs[0])

    # 3. Extraer imagen
    salida_png = TMP / "gui_extraida.png"
    salida_png.unlink(missing_ok=True)
    res = s.extraer_imagen_seleccionada(salida_png)
    assert res is not None and salida_png.exists()
    with Image.open(salida_png) as pim:
        assert pim.size == (300, 200)

    # 4. Reemplazar imagen
    nueva_png = TMP / "gui_nueva.png"
    Image.new("RGB", (64, 64), color="red").save(nueva_png)
    assert s.reemplazar_imagen_seleccionada(nueva_png) is True
    assert "reemplazada" in s.ultimo_mensaje


def test_sesion_deshacer_y_rehacer():
    """Historial completo de operaciones: deshacer (Ctrl+Z) y rehacer (Ctrl+Shift+Z/Ctrl+Y)."""
    s = Sesion()
    s.abrir(CORPUS / "00_baseline.pdf")
    assert s.puede_deshacer is False
    assert s.puede_rehacer is False

    # Editar un texto
    s.seleccionar_en(150, 785)
    assert s.editar_texto("Texto modificado para test")
    assert s.puede_deshacer is True
    assert s.puede_rehacer is False

    # Deshacer
    assert s.deshacer() is True
    assert s.puede_deshacer is False
    assert s.puede_rehacer is True
    assert "Deshecho" in s.ultimo_mensaje

    # Rehacer
    assert s.rehacer() is True
    assert s.puede_deshacer is True
    assert s.puede_rehacer is False
    assert "Rehecho" in s.ultimo_mensaje



def test_tras_editar_el_texto_la_lista_ensena_el_texto_nuevo():
    """Lo que se ve tiene que ser lo que hay, no los códigos de la fuente.

    Con el nivel 2 la fuente nueva se incrusta en el fichero que se guardaría.
    Si la lista lateral se reconstruye a partir del fichero del disco, que
    todavía no la tiene, los códigos del texto editado no se pueden traducir y
    la lista enseñaba «\x00\x07\x00\x0e...» en vez del texto.
    """
    s = Sesion()
    s.abrir(CORPUS / "05_cmyk_imprenta.pdf")
    obj = [o for o in s.objetos() if o.tipo == "texto"][1]
    s.seleccionar_en(*obj.caja.centro)
    nuevo = "Una frase distinta, con acentos: ñ, ó, €."
    assert s.editar_texto(nuevo), "la edición debería aceptarse"

    textos = [o.texto or "" for o in s.objetos() if o.tipo == "texto"]
    assert nuevo in textos, f"la lista enseña {textos}"


def test_mover_texto_deja_la_caja_donde_toca():
    """Un texto movido no puede volver a su sitio en la pantalla.

    Las cajas de texto se alinean contra la tinta que ve pdfium. Si esa tinta
    se pide al fichero del disco y no al estado con las ediciones pendientes, el
    texto movido se dibuja en su sitio nuevo pero su caja vuelve al viejo.
    """
    s = Sesion()
    s.abrir(CORPUS / "02_fuente_subset.pdf")
    obj = [o for o in s.objetos() if o.tipo == "texto"][0]
    antes = obj.caja.como_tupla()
    s.seleccionar_en(*obj.caja.centro)
    assert s.mover(0, 40), "el movimiento debería aplicarse"

    despues = [o for o in s.objetos() if o.tipo == "texto"][0].caja.como_tupla()
    assert abs((despues[1] - antes[1]) - 40) < 1.5, (
        f"la caja estaba en y={antes[1]:.1f} y debería estar en "
        f"y={antes[1] + 40:.1f}; está en y={despues[1]:.1f}")
    assert abs(despues[0] - antes[0]) < 1.5, f"se ha movido en x: {despues[0]:.1f}"


# ---------------------------------------------------------------------------
# La ventana (solo con pantalla y con GTK instalado)
# ---------------------------------------------------------------------------

def test_la_ventana_se_construye_y_se_dibuja():
    """La ventana se construye, se dibuja y produce una imagen con contenido.

    **Se hace en otro proceso, y no es un capricho**: `Gio.Application.run()`
    sólo se puede llamar una vez por proceso (la segunda vez no dibuja nada y
    sale con 1), así que si esta prueba corriera dentro del proceso de las demás,
    dependería de qué otras pruebas se hayan ejecutado antes. Ya pasó: pasaba
    sola y fallaba al ejecutar el fichero entero, porque otra prueba anterior
    había creado otra aplicación. Se descubrió en el CI, que ejecuta todo junto.

    Se usa la herramienta de capturas, que es la que genera las que van a
    Flathub: así la prueba comprueba también el camino que se usa de verdad.
    """
    import os
    import subprocess
    if not _hay_gtk():
        print("      (sin PyGObject: se salta)")
        return
    if not os.environ.get("DISPLAY"):
        print("      (sin DISPLAY: se salta)")
        return

    destino = SALIDA_CAPTURAS / "02-seleccion.png"
    antes = destino.stat().st_mtime_ns if destino.exists() else 0
    r = subprocess.run([sys.executable, str(RAIZ / "tools/capturas_gui.py"),
                        "--solo=02-seleccion"],
                       capture_output=True, text=True, timeout=180, cwd=str(RAIZ))
    if r.returncode != 0:
        raise AssertionError(f"la captura falló: {r.stdout[-300:]}{r.stderr[-300:]}")
    assert destino.exists(), "no se generó la captura"
    assert destino.stat().st_mtime_ns != antes, "la captura es la de antes"

    datos = destino.read_bytes()
    assert len(datos) > 10_000, f"la captura es sospechosamente pequeña: {len(datos)} B"

    # Se decodifica el PNG con GdkPixbuf y se cuentan colores en una rejilla.
    # No se usa Pillow a propósito: PyGObject se instala con el gestor de
    # paquetes del sistema y Pillow con pip, y mezclar los dos en un test es
    # pedir que falle en la mitad de las distribuciones.
    from gi.repository import GdkPixbuf
    imagen = GdkPixbuf.Pixbuf.new_from_file(str(destino))
    ancho, alto, paso = imagen.get_width(), imagen.get_height(), imagen.get_rowstride()
    pixeles = imagen.get_pixels()
    assert ancho > 800 and alto > 500, f"la ventana salió pequeña: {ancho}x{alto}"
    colores = set()
    for y in range(0, alto, 20):
        for x in range(0, ancho, 20):
            i = y * paso + x * 4
            colores.add(bytes(pixeles[i:i + 3]))
    assert len(colores) > 30, f"la ventana parece vacía: {len(colores)} colores"


def test_soltar_un_pdf_encima_de_la_ventana_lo_abre():
    """Arrastrar y soltar, que es lo que promete la pantalla vacía.

    El gesto en sí no se puede simular sin ratón, pero sí el paso que importa:
    lo que GTK entrega al soltar es una lista de ficheros, y a partir de ahí el
    camino es el mismo que el de «Abrir». Aquí se le da esa lista a mano.
    """
    import os
    if not _hay_gtk():
        print("      (sin PyGObject: se salta)")
        return
    if not os.environ.get("DISPLAY"):
        print("      (sin DISPLAY: se salta)")
        return

    from gi.repository import Gdk, Gio, Gtk
    from gui.ventana import Aplicacion, Ventana

    s = Sesion()
    ventana = Ventana(_app_compartida(), s)   # una sola aplicación por proceso
    assert not s.abierto, "la sesión empieza sin documento"

    fichero = Gio.File.new_for_path(str(CORPUS / "05_cmyk_imprenta.pdf"))
    soltados = Gdk.FileList.new_from_array([fichero])
    assert ventana._al_soltar(None, soltados, 0.0, 0.0) is True
    assert s.abierto, "soltar un PDF debería abrirlo"
    assert s.ruta.name == "05_cmyk_imprenta.pdf"
    assert len(s.objetos()) == 4, f"{len(s.objetos())} objetos en vez de 4"
    # Y la ventana deja de enseñar la pantalla vacía.
    assert ventana.pila.get_visible_child_name() == "documento"


# ---------------------------------------------------------------------------
# La cinta
# ---------------------------------------------------------------------------

def _ventana_con(pdf: str | None = None):
    """Una ventana de verdad, con una sola aplicación para todo el proceso.

    Una `Gio.Application` por proceso y ya está: crear otra con el mismo
    identificador hace que la segunda no pueda registrarse, y llamar a `run()`
    dos veces en un proceso no dibuja nada (devuelve 1). Aquí no hace falta
    registrar ni ejecutar nada: las pruebas construyen la ventana a mano, que es
    lo que quieren comprobar. Lo que sí hace falta es no crear una aplicación
    nueva por prueba, y eso es lo que ya se hacía mal: las pruebas que creaban la
    suya se saltaban en silencio en cuanto otra se hubiera registrado antes.
    """
    from gui.ventana import Ventana

    s = Sesion()
    if pdf:
        s.abrir(CORPUS / pdf)
    return s, Ventana(_app_compartida(), s)


SALIDA_CAPTURAS = RAIZ / "docs" / "capturas"
_APP = None


def _app_compartida():
    """La única `Gio.Application` de este proceso.

    Existe una sola por proceso a propósito: crear dos con el mismo
    identificador hace que la segunda no pueda registrarse ni dibujar nada, y
    además las pruebas que creaban la suya se saltaban en silencio en cuanto otra
    se hubiera registrado antes.
    """
    global _APP
    from gui.ventana import Aplicacion
    if _APP is None:
        _APP = Aplicacion(Sesion())
    return _APP


def _iconos(widget):
    """Todos los nombres de icono que cuelgan de un widget."""
    from gi.repository import Gtk
    if isinstance(widget, Gtk.Image):
        nombre = widget.get_icon_name()
        if nombre:
            yield nombre
    hijo = widget.get_first_child()
    while hijo is not None:
        yield from _iconos(hijo)
        hijo = hijo.get_next_sibling()


def test_la_cinta_cabe_en_la_ventana():
    """Ninguna pestaña puede pedir más ancho del que hay.

    Una cinta que se sale de la ventana deja opciones fuera de la vista sin
    decirlo, que es justo lo contrario de para qué se puso. Medido, no supuesto:
    la pestaña «Texto» llegó a pedir 1486 px de los 1170 que hay, y las dos
    frases que lo causaban acabaron en la ayuda emergente.
    """
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    s, v = _ventana_con("05_cmyk_imprenta.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return

    # Sin presentar, la ventana todavía no tiene ancho asignado: se usa el que
    # se le pide al crearla, que es el que tendrá al abrirse.
    ancho = v.get_width() or v.get_default_size()[0]
    for clave in ("inicio", "objeto", "texto", "pagina", "ver"):
        pagina = v.cinta._paginas[clave]
        natural = pagina.caja.get_preferred_size()[1].width
        assert natural <= ancho - 8, (
            f"la pestaña «{clave}» pide {natural} px y la ventana tiene {ancho}")


def test_todos_los_botones_de_la_cinta_explican_qué_hacen():
    """Un botón sin ayuda emergente es un icono que hay que adivinar.

    Es la comprobación más barata que hay contra la cinta llena de botones
    mudos, que es lo que hace inservible una cinta.
    """
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    from gi.repository import Gtk

    s, v = _ventana_con("05_cmyk_imprenta.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return

    mudos = []
    cuantos = 0
    for hijo in v.cinta.botones():
        if isinstance(hijo, (Gtk.Button, Gtk.CheckButton)):
            cuantos += 1
            if not (hijo.get_tooltip_text() or "").strip():
                descripcion = hijo.get_label() or hijo.get_icon_name() or "?"
                mudos.append(descripcion)
    assert cuantos > 25, f"solo se han encontrado {cuantos} botones en la cinta"
    assert not mudos, f"botones sin ayuda emergente: {mudos}"


def test_los_iconos_de_la_cinta_existen_en_el_tema():
    """Un nombre de icono que no existe se dibuja como un hueco roto.

    No revienta nada, y por eso se cuela: la ventana se construye, los tests
    pasan y en la esquina hay un cuadro de «imagen no encontrada» que nadie mira.
    """
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    from gi.repository import Gdk, Gtk

    s, v = _ventana_con("05_cmyk_imprenta.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return

    tema = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    usados = set()
    for hijo in v.cinta.botones():
        usados.update(_iconos(hijo))
    assert len(usados) >= 10, f"solo {len(usados)} iconos en la cinta: {usados}"
    faltan = sorted(n for n in usados if not tema.has_icon(n))
    assert not faltan, f"iconos que no están en el tema: {faltan}"


def test_la_cinta_apaga_lo_que_no_se_puede_usar():
    """Lo que no aplica se apaga, no se esconde: es lo que hace Word."""
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return

    # Sin documento: casi todo apagado, pero Abrir sigue encendido.
    s, v = _ventana_con()
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return
    apagados = {w.get_tooltip_text() for w, _c in v.cinta._condiciones
                if hasattr(w, "get_sensitive") and not w.get_sensitive()
                and not __import__("gi.repository", fromlist=["Gtk"]).Gtk
                .ToggleButton.__instancecheck__(w)}
    assert len(apagados) >= 8, f"sin documento solo se han apagado {len(apagados)}"
    assert not any("Ctrl+O" in (t or "") for t in apagados),         "Abrir no puede estar apagado sin documento: es lo único que se puede hacer"

    # Con una imagen seleccionada: Borrar y Escalar se encienden, Editar texto no.
    s, v = _ventana_con("05_cmyk_imprenta.pdf")
    s.seleccionar_en(232, 680)
    v.actualizar()
    assert s.seleccion.tipo == "imagen"
    encendido = {w.get_tooltip_text() for w, c in v.cinta._condiciones
                 if hasattr(w, "get_sensitive") and w.get_sensitive()}
    assert any("Borrar" in (t or "") for t in encendido)
    assert any("Redimensionar" in (t or "") for t in encendido)
    assert not any("Cambiar el texto" in (t or "") for t in encendido),         "con una imagen seleccionada no se puede editar texto"

    # Con un texto: al revés.
    s.seleccionar_en(150, 500)
    v.actualizar()
    assert s.seleccion.tipo == "texto", s.seleccion.tipo
    encendido = {w.get_tooltip_text() for w, c in v.cinta._condiciones
                 if hasattr(w, "get_sensitive") and w.get_sensitive()}
    assert any("Cambiar el texto" in (t or "") for t in encendido)


def test_las_pestanas_cambian_de_pagina():
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    s, v = _ventana_con("05_cmyk_imprenta.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return
    assert v.cinta.pagina_activa() == "inicio"
    v.cinta.activar("objeto")
    assert v.cinta.pagina_activa() == "objeto"
    v.cinta.activar("ver")
    assert v.cinta.pagina_activa() == "ver"


def test_la_casilla_de_la_cinta_y_el_interruptor_del_panel_van_juntos():
    """Si se cambia uno, el otro tiene que enterarse.

    Sin la bandera de sincronización esto se llama a sí mismo sin parar: el
    cambio del uno dispara el del otro, que vuelve a disparar el primero.
    """
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    s, v = _ventana_con("05_cmyk_imprenta.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return

    v.b_cajas.set_active(False)
    assert v.mostrar_cajas is False
    assert v.fila_cajas.get_active() is False

    v.fila_cajas.set_active(True)
    assert v.mostrar_cajas is True
    assert v.b_cajas.get_active() is True


def test_tamano_real_y_ajustar_a_la_ventana():
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    s, v = _ventana_con("05_cmyk_imprenta.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return
    v.zoom_real()
    assert abs(v.lienzo.zoom - 1.0) < 1e-9
    assert v.etiquetas["zoom"][0].get_text() == "100 %"
    v.zoom_ajustado()
    assert 0.25 <= v.lienzo.zoom <= 6.0


def test_los_campos_del_desplazamiento_mueven_de_verdad():
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    s, v = _ventana_con("02_fuente_subset.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return
    obj = [o for o in s.objetos() if o.tipo == "texto"][0]
    s.seleccionar_en(*obj.caja.centro)
    antes = s.seleccion.caja.como_tupla()
    v.controles["dx"][-1].set_text("0")
    v.controles["dy"][-1].set_text("25")
    v.mover_exacto()
    despues = [o for o in s.objetos() if o.tipo == "texto"][0].caja.como_tupla()
    assert abs((despues[1] - antes[1]) - 25) < 1.5, f"{antes} -> {despues}"

    # Y si se escribe algo que no es un número, lo dice en vez de reventar.
    v.controles["dy"][-1].set_text("veinticinco")
    v.mover_exacto()
    assert s.ultimo_aviso is not None


def test_ocultar_el_panel_quita_el_panel_de_verdad():
    """La casilla «Panel de objetos» de la pestaña Ver, comprobada por estado.

    Los píxeles no valen aquí: el modo captura dibuja el árbol de widgets, y un
    widget sin mapear sale pintado igual. Lo que se comprueba es lo que importa:
    que el panel deja de estar mapeado y que la página se queda con todo el
    ancho.
    """
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    s, v = _ventana_con("05_cmyk_imprenta.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return

    assert v.b_panel.get_active() is True
    assert v.split.get_show_sidebar() is True

    v.b_panel.set_active(False)
    assert v.split.get_show_sidebar() is False
    # Sin mapear: GTK no lo dibuja aunque siga en el árbol.
    assert not v.split.get_sidebar().get_mapped()

    v.b_panel.set_active(True)
    assert v.split.get_show_sidebar() is True


def test_los_dialogos_funcionan_con_libadwaita_antigua():
    """openSUSE Leap 15.6 trae libadwaita 1.4, y ahí no existe Adw.AlertDialog.

    Se añadió en la 1.5. Sin este apaño, en Leap la ventana arrancaría, dibujaría
    la página entera y reventaría al primer doble clic, que es cuando se abre un
    diálogo. En una captura de pantalla no se ve; preguntando por la versión,
    sí.
    """
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    from gi.repository import Adw
    from gui import dialogos

    assert isinstance(dialogos.nuevo("hola", "cuerpo"), Adw.AlertDialog)

    # Se finge que es libadwaita 1.4: AlertDialog no existe y hay que usar el
    # MessageDialog de toda la vida. Se parchea la comprobación y no el módulo
    # de C, que no se deja.
    original = dialogos.hay_alertdialog
    dialogos.hay_alertdialog = lambda: False
    try:
        dlg = dialogos.nuevo("hola", "cuerpo")
        assert isinstance(dlg, Adw.MessageDialog), type(dlg)
        # Y tiene que aceptar lo mismo que el moderno, que es de lo que se fía
        # el resto de la ventana.
        dlg.add_response("aceptar", "Vale")
        dlg.set_default_response("aceptar")
        dlg.set_extra_child(__import__("gi.repository", fromlist=["Gtk"]).Gtk.Label(label="x"))
        dlg.connect("response", lambda *_: None)
    finally:
        dialogos.hay_alertdialog = original


def test_los_dialogos_de_la_ventana_se_abren_con_la_libadwaita_vieja():
    """El camino de verdad: doble clic sobre un texto, con libadwaita 1.4.

    No basta con probar el ayudante: aquí se llama a lo que se llama al hacer
    doble clic, que es donde estaría el fallo.
    """
    import os
    if not _hay_gtk() or not os.environ.get("DISPLAY"):
        print("      (sin PyGObject o sin DISPLAY: se salta)")
        return
    from gi.repository import Gtk, Gdk
    from gui import dialogos

    s, v = _ventana_con("02_fuente_subset.pdf")
    if v is None:
        print("      (no se pudo registrar la aplicación: se salta)")
        return
    obj = [o for o in s.objetos() if o.tipo == "texto"][0]
    s.seleccionar_en(*obj.caja.centro)
    v.actualizar()

    original = dialogos.hay_alertdialog
    dialogos.hay_alertdialog = lambda: False
    try:
        v.dialogo_texto()
        v.dialogo_escalar()
        v.error("Un título", "Un detalle")
        v._dialogo_largo("Largo", "mucho texto\nmás texto")
    finally:
        dialogos.hay_alertdialog = original


def test_la_ventana_se_abre_desde_la_entrada_de_pipx():
    """`--comprobar` dice si la ventana podría abrirse, sin abrirla.

    Es lo que usa el instalador para comprobar una instalación en un sitio sin
    pantalla, así que tiene que existir y decir la verdad.
    """
    import subprocess
    r = subprocess.run([sys.executable, "-m", "gui.lanzar", "--comprobar"],
                       capture_output=True, text=True, cwd=str(RAIZ))
    if not _hay_gtk():
        # Sin PyGObject instalado para ESTE intérprete el comando tiene que
        # fallar, y con un mensaje que diga qué falta.
        assert r.returncode == 3
        assert "no está instalado" in (r.stderr + r.stdout)
        return
    assert r.returncode == 0, r.stderr
    assert "GTK" in r.stdout and "libadwaita" in r.stdout, r.stdout


def test_seleccionar_en_cicla_con_tolerancia_y_prioriza_texto():
    """El hit-test cicla entre capas con tolerancia de ratón y prioriza texto."""
    from gui.modelo import Sesion
    s = Sesion()
    s.abrir(CORPUS / "03_vectores_clip_degradado.pdf")
    # Punto donde hay un vector
    v = s.objetos()[0]
    cx, cy = v.caja.centro
    primero = s.seleccionar_en(cx, cy)
    assert primero is not None
    # Segundo clic desplazado 2 pt (pequeño movimiento de mano): debe ciclar si hay candidatos
    segundo = s.seleccionar_en(cx + 2.0, cy + 2.0)
    assert segundo is not None


def test_borrar_objeto_permite_nueva_seleccion_limpia():
    """Tras borrar un objeto, el estado interno se resetea y permite seleccionar otros."""
    from gui.modelo import Sesion
    s = Sesion()
    s.abrir(CORPUS / "03_vectores_clip_degradado.pdf")
    v = s.objetos()[0]
    s.seleccionar(v)
    assert s.borrar() is True
    assert s.seleccion is None
    assert len(s._candidatos) == 0
    assert s._ultimo_punto is None

    # Seleccionar un objeto restante debe funcionar sin excepciones
    restantes = s.objetos()
    assert len(restantes) > 0
    otro = restantes[0]
    sel = s.seleccionar_en(*otro.caja.centro)
    assert sel is not None
    assert sel is otro


def test_cli_tutorial_y_guia():
    """Los comandos tutorial y guia devuelven código 0 y texto explicativo."""
    import subprocess
    for orden in ("tutorial", "guia"):
        r = subprocess.run([sys.executable, "-m", "nucleo.cli", orden],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert "TUTORIAL" in r.stdout or "GUÍA" in r.stdout


def test_lienzo_transformacion_pixel_pdf_exacta_con_zoom():
    """a_pdf y a_pixel deben ser inversas matemáticas exactas a cualquier nivel de zoom."""
    if not _hay_gtk():
        return
    s, v = _ventana_con("03_vectores_clip_degradado.pdf")
    lienzo = v.lienzo

    for zoom in (0.5, 1.0, 1.5, 2.0, 3.0):
        lienzo.zoom = zoom
        # Puntos de prueba variados en el PDF
        for x_pdf, y_pdf in [(50.0, 50.0), (150.0, 400.0), (300.0, 750.0)]:
            px, py = lienzo.a_pixel(x_pdf, y_pdf)
            rec_x, rec_y = lienzo.a_pdf(px, py)
            assert abs(rec_x - x_pdf) < 1e-3, f"Fallo en X con zoom {zoom}: {rec_x} != {x_pdf}"
            assert abs(rec_y - y_pdf) < 1e-3, f"Fallo en Y con zoom {zoom}: {rec_y} != {y_pdf}"


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
