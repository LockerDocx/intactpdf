"""El lanzador de la ventana: dice QUÉ falta, en vez de reventar.

Este fichero es el punto de entrada de `intactpdf-gui`, y existe únicamente por
el mensaje de error. Sin él, ejecutar la ventana en un sistema sin PyGObject da
esto:

    ModuleNotFoundError: No module named 'gi'

que no le dice nada útil a nadie: ni qué falta, ni cómo se instala, ni que el
editor de consola sigue funcionando perfectamente sin ello. Aquí se comprueba el
entorno antes de cargar nada de la interfaz y, si falta algo, se explica en dos
líneas con el comando exacto de **esta** distribución.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

MINIMO_GTK = (4, 10)          # Gtk.FileDialog, que es como se abren ficheros
MINIMO_ADW = (1, 2)           # Adw.ToolbarView, Adw.AboutDialog


def _revisar() -> str | None:
    """Devuelve el problema encontrado, o None si se puede arrancar la ventana."""
    try:
        import gi
    except ImportError:
        return "no está instalado PyGObject"

    try:
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
    except (ValueError, ImportError) as e:
        return f"no está instalado GTK 4 ({e})"

    version = (Gtk.MAJOR_VERSION, Gtk.MINOR_VERSION)
    if version < MINIMO_GTK:
        return (f"GTK {Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION} es demasiado "
                f"antiguo: hace falta {MINIMO_GTK[0]}.{MINIMO_GTK[1]} o posterior "
                f"(el diálogo de abrir y guardar ficheros)")

    try:
        gi.require_version("Adw", "1")
        from gi.repository import Adw
    except (ValueError, ImportError) as e:
        return f"no está instalada libadwaita ({e})"

    version = (Adw.MAJOR_VERSION, Adw.MINOR_VERSION)
    if version < MINIMO_ADW:
        return (f"libadwaita {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION} es "
                f"demasiado antigua: hace falta {MINIMO_ADW[0]}.{MINIMO_ADW[1]} "
                f"o posterior")
    return None


def _gi_en_el_sistema() -> str | None:
    """¿Hay algún intérprete del sistema que SÍ pueda importar GTK?

    Sirve para distinguir dos situaciones que se parecen y no tienen nada que
    ver: «no tienes PyGObject instalado» y «lo tienes, pero este entorno no lo
    ve». La segunda pasa siempre al instalar con pipx sin
    `--system-site-packages`: el entorno virtual nace aislado y no ve el
    PyGObject del sistema, que va atado a las bibliotecas de GTK de la
    distribución. El aviso de «no tienes PyGObject» en ese caso es una mentira
    útil para nadie y una tarde perdida para todo el mundo.
    """
    candidatos = [sys.executable, "/usr/bin/python3",
                  shutil.which("python3"), shutil.which("python3.13"),
                  shutil.which("python3.12")]
    visto = set()
    for cand in candidatos:
        if not cand or cand in visto:
            continue
        visto.add(cand)
        try:
            r = subprocess.run(
                [cand, "-c", "import gi; gi.require_version('Gtk','4.0'); "
                             "from gi.repository import Gtk, Adw"],
                capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and cand != sys.executable:
            return cand
    return None


def _ayuda() -> str:
    """El texto que se enseña cuando no se puede abrir la ventana."""
    from nucleo import dependencias

    d = dependencias.detectar()
    lineas = ["", "  No se puede abrir la ventana de IntactPDF.", ""]
    cmd = dependencias.comando(d["familia"])
    if cmd:
        lineas += [f"  Este sistema es {d['nombre']}.",
                   "  Lo que falta se instala con:", "",
                   f"      {cmd}", ""]
    else:
        lineas += ["  Instala PyGObject, GTK 4 y libadwaita con el gestor de",
                   "  paquetes de tu distribución, o usa el Flatpak, que ya los",
                   "  trae dentro:", "",
                   "      flatpak install flathub io.github.lockerdocx.IntactPDF", ""]
    otro = _gi_en_el_sistema()
    if otro:
        lineas += [f"  Ojo: PyGObject SÍ está instalado (lo tiene {otro}), pero",
                   "  este entorno no lo ve. Es lo que pasa al instalar con pipx",
                   "  sin darle acceso a los paquetes del sistema. Se arregla con:",
                   "",
                   "      pipx install --force --system-site-packages intactpdf",
                   ""]
    lineas += ["  El editor de consola no necesita nada de esto y sigue",
               "  funcionando: `intactpdf doctor` dice cómo está el entorno.",
               ""]
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--comprobar" in argv:
        # Modo para scripts y para el instalador: dice si la ventana podría
        # abrirse y se va, sin abrir ninguna ventana. Es lo que permite
        # comprobar una instalación en un contenedor sin pantalla.
        problema = _revisar()
        if problema is None:
            import gi
            from gi.repository import Adw, Gtk
            print(f"la ventana puede abrirse: GTK "
                  f"{Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}."
                  f"{Gtk.MICRO_VERSION}, libadwaita "
                  f"{Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}."
                  f"{Adw.MICRO_VERSION}, PyGObject "
                  f"{getattr(gi, '__version__', '?')}")
            return 0
        print(f"la ventana NO puede abrirse: {problema}", file=sys.stderr)
        return 3

    problema = _revisar()
    if problema is not None:
        print(_ayuda(), file=sys.stderr)
        print(f"  detalle: {problema}", file=sys.stderr)
        return 3
    from gui.ventana import main as abrir_ventana
    return abrir_ventana(argv)


if __name__ == "__main__":
    raise SystemExit(main())
