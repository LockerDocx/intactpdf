"""Qué hay que instalar para la ventana, según la distribución.

Esto existe por un motivo concreto: **PyGObject no se instala con pip a gusto de
nadie**. Va atado a las bibliotecas de GTK que tenga el sistema, así que la vía
normal es el gestor de paquetes de la distribución; y los paquetes se llaman
distinto en cada una. Decirle a alguien «instala PyGObject y GTK 4» es decirle
que se busque la vida; decirle `zypper install python3-gobject
python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1` es resolverle el
problema.

Lo usan dos sitios: `intactpdf doctor`, para decir qué falta, y el instalador
`instalar.sh`, para instalarlo. Un test comprueba que las dos listas coinciden,
porque dos listas que se separan acaban mandando al usuario a un comando que ya
no funciona.
"""
from __future__ import annotations

import shutil
from pathlib import Path

# familia -> (gestor, paquetes, con qué distribuciones se corresponde)
FAMILIAS = {
    "debian": ("apt", "python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1",
               "Debian, Ubuntu, Mint, Pop!_OS, Raspberry Pi OS"),
    "fedora": ("dnf", "python3-gobject gtk4 libadwaita",
               "Fedora, RHEL, CentOS Stream, Rocky, AlmaLinux"),
    "opensuse": ("zypper", "python3-gobject python3-gobject-Gdk "
                           "typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1",
                 "openSUSE Leap, openSUSE Tumbleweed, SLE"),
    "arch": ("pacman", "python-gobject gtk4 libadwaita",
             "Arch, Manjaro, EndeavourOS, CachyOS"),
    "alpine": ("apk", "py3-gobject3 gtk4.0 libadwaita",
               "Alpine Linux (sin comprobar; la vía segura ahí es Flatpak)"),
}

# Identificadores de /etc/os-release -> familia. `ID` primero; si no está, se
# mira `ID_LIKE`, que es lo que ponen las derivadas.
POR_ID = {
    "debian": "debian", "ubuntu": "debian", "linuxmint": "debian", "pop": "debian",
    "raspbian": "debian", "elementary": "debian", "zorin": "debian", "kali": "debian",
    "mx": "debian", "devuan": "debian", "deepin": "debian", "neon": "debian",
    "fedora": "fedora", "rhel": "fedora", "centos": "fedora", "rocky": "fedora",
    "almalinux": "fedora", "ol": "fedora", "amzn": "fedora", "scientific": "fedora",
    "opensuse-leap": "opensuse", "opensuse-tumbleweed": "opensuse",
    "opensuse": "opensuse", "sles": "opensuse", "sled": "opensuse",
    "suse": "opensuse", "opensuse-microos": "opensuse",
    "arch": "arch", "archarm": "arch", "manjaro": "arch", "manjaro-arm": "arch",
    "endeavouros": "arch", "cachyos": "arch", "garuda": "arch",
    "alpine": "alpine", "postmarketos": "alpine",
}

# pipx, que es la forma sensata de instalar una aplicación de Python: hace su
# propio entorno virtual y no toca el Python del sistema. En Debian 12, Ubuntu
# 23.04 y posteriores, `pip install --user` se niega a funcionar
# («externally-managed-environment») salvo con --break-system-packages, así que
# pipx no es un capricho: es la vía que funciona.
PIPX = {
    "debian": "pipx",
    "fedora": "pipx",
    "opensuse": "python3-pipx",
    "arch": "python-pipx",
    "alpine": "py3-pipx",
}

# Cómo se instala, con el prefijo de privilegios que toque.
ORDEN = {
    "apt": "sudo apt install -y",
    "dnf": "sudo dnf install -y",
    "zypper": "sudo zypper install -y",
    "pacman": "sudo pacman -S --needed",
    "apk": "sudo apk add",
}


def leer_os_release(ruta: str | Path = "/etc/os-release") -> dict:
    """Lee /etc/os-release. Devuelve {} si no existe (no es un Linux normal)."""
    datos = {}
    try:
        for linea in Path(ruta).read_text(errors="replace").splitlines():
            if "=" not in linea or linea.startswith("#"):
                continue
            clave, _, valor = linea.partition("=")
            datos[clave.strip()] = valor.strip().strip('"').strip("'")
    except OSError:
        pass
    return datos


def familia(ident: str, like: str = "") -> str | None:
    """A qué familia pertenece una distribución, por su ID o su ID_LIKE."""
    if ident in POR_ID:
        return POR_ID[ident]
    for trozo in (like or "").split():
        if trozo in POR_ID:
            return POR_ID[trozo]
    # «suse», «rhel» y demás aparecen a veces solo como prefijo.
    for nombre, fam in POR_ID.items():
        if ident.startswith(nombre) or nombre.startswith(ident or "\0"):
            return fam
    return None


def detectar(ruta_os_release: str | Path = "/etc/os-release") -> dict:
    """Lo que se sabe del sistema donde se está ejecutando esto."""
    datos = leer_os_release(ruta_os_release)
    ident = datos.get("ID", "")
    like = datos.get("ID_LIKE", "")
    fam = familia(ident, like)
    gestor, paquetes, cubre = FAMILIAS.get(fam, (None, None, None))
    return {
        "id": ident,
        "like": like,
        "nombre": datos.get("PRETTY_NAME") or datos.get("NAME") or "desconocido",
        "version": datos.get("VERSION_ID", ""),
        "familia": fam,
        "gestor": gestor,
        "paquetes": paquetes,
        "cubre": cubre,
    }


def comando(fam: str | None, con_sudo: bool = True) -> str | None:
    """La línea exacta para instalar lo que la ventana necesita."""
    if fam not in FAMILIAS:
        return None
    gestor, paquetes, _ = FAMILIAS[fam]
    orden = ORDEN[gestor]
    if not con_sudo:
        orden = " ".join(t for t in orden.split() if t != "sudo")
    return f"{orden} {paquetes}"


def comando_pipx(fam: str | None, con_sudo: bool = True) -> str | None:
    """La línea para instalar pipx, que es quien instala la aplicación."""
    if fam not in FAMILIAS or fam not in PIPX:
        return None
    gestor = FAMILIAS[fam][0]
    orden = ORDEN[gestor]
    if not con_sudo:
        orden = " ".join(t for t in orden.split() if t != "sudo")
    return f"{orden} {PIPX[fam]}"


def gestor_paquetes_disponible(fam: str | None) -> bool:
    if fam not in FAMILIAS:
        return False
    return shutil.which(FAMILIAS[fam][0]) is not None
