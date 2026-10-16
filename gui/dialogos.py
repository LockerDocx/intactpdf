"""Los diálogos de la ventana, con la versión de libadwaita que haya.

Por qué existe este fichero: `Adw.AlertDialog` se añadió en **libadwaita 1.5** y
antes de eso el diálogo se llamaba `Adw.MessageDialog`. No es un detalle de
historia: openSUSE Leap 15.6 trae GNOME 45, o sea libadwaita 1.4, y ahí
`Adw.AlertDialog` no existe. Sin este apaño, la ventana arrancaría, se dibujaría
la página entera... y reventaría al primer doble clic, que es cuando se abre un
diálogo. Un fallo así no se descubre mirando una captura de pantalla.

La regla es la de siempre en este proyecto: se usa lo nuevo si está y lo viejo si
no, y **el comportamiento es el mismo** desde fuera. Lo que NO se hace es
depender de una versión concreta y que la aplicación falle en la mitad de las
distribuciones.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


def hay_alertdialog() -> bool:
    """¿Hay `Adw.AlertDialog` (libadwaita 1.5 o posterior)?"""
    return hasattr(Adw, "AlertDialog")


def libadwaita() -> str:
    version = (getattr(Adw, "MAJOR_VERSION", 0), getattr(Adw, "MINOR_VERSION", 0),
               getattr(Adw, "MICRO_VERSION", 0))
    return ".".join(str(v) for v in version)


def nuevo(titulo: str, detalle: str = ""):
    """Un diálogo con encabezado y cuerpo, del tipo que haya.

    Los dos constructores aceptan `heading` y `body`, así que la diferencia se
    queda aquí dentro y el resto de la ventana no se entera.
    """
    if hay_alertdialog():
        return Adw.AlertDialog(heading=titulo, body=detalle)
    return Adw.MessageDialog(heading=titulo, body=detalle)


def presentar(dlg, padre=None) -> None:
    """Enseña el diálogo, con el padre si el diálogo lo admite.

    El padre hay que dárselo: sin él, libadwaita no sabe a qué ventana pertenece
    el diálogo y puede no llegar a mostrarlo. Se probó a mano.

    Pero no siempre se puede. Hay tres casos y los tres están vivos:

    - `Adw.AlertDialog` (libadwaita 1.5+): `present(padre)`.
    - `Adw.MessageDialog` en libadwaita 1.4 (openSUSE Leap 15.6): `present(padre)`,
      y el padre es obligatorio.
    - `Adw.MessageDialog` en libadwaita 1.6+ : se reimplementó sobre `Adw.Dialog`
      y su `present()` es el de `Gtk.Window`, **sin** argumentos. Llamarlo con
      padre revienta con «Gtk.Window.present() takes exactly 1 argument
      (2 given)», que es justo el error que destapó el test.

    Por eso se intenta con padre y, si el diálogo no lo admite, se llama sin él.
    """
    if padre is None:
        try:
            app = Gtk.Application.get_default()
        except Exception:
            app = None
        padre = app.props.active_window if app is not None else None
    try:
        if padre is not None:
            dlg.present(padre)
        else:
            dlg.present()
    except TypeError:
        # Este diálogo no acepta padre (libadwaita moderno).
        dlg.present()


def aviso(titulo: str, detalle: str = "", padre=None, texto_boton: str = "Entendido"):
    """Un aviso de una sola respuesta. Devuelve el diálogo, ya enseñado."""
    dlg = nuevo(titulo, detalle)
    dlg.add_response("cerrar", texto_boton)
    presentar(dlg, padre)
    return dlg


def confirmacion(titulo: str, detalle: str, texto_aceptar: str,
                 al_aceptar, extra: Gtk.Widget | None = None,
                 texto_cancelar: str = "Cancelar", padre=None):
    """Un diálogo de dos respuestas, con el botón de aceptar destacado."""
    dlg = nuevo(titulo, detalle)
    if extra is not None:
        dlg.set_extra_child(extra)
    dlg.add_response("cancelar", texto_cancelar)
    dlg.add_response("aceptar", texto_aceptar)
    dlg.set_default_response("aceptar")
    try:
        dlg.set_response_appearance("aceptar", Adw.ResponseAppearance.SUGGESTED)
    except Exception:
        # En libadwaita 1.4 `ResponseAppearance` existe, pero si algún día no
        # estuviera, quedarse sin el color del botón es un detalle de estética y
        # no motivo para no abrir el diálogo.
        pass

    def respondido(_d, respuesta):
        if respuesta == "aceptar":
            al_aceptar()

    dlg.connect("response", respondido)
    presentar(dlg, padre)
    return dlg
