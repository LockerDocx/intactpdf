"""El instalador: que detecte bien el sistema y que no mienta.

No se prueba «instala el paquete y aparece el fichero», eso es lo que hace el
propio instalador con `--simular` y luego a mano en cada distribución (hay
comprobaciones hechas en Debian y en el Flatpak). Lo que se prueba aquí es lo
que más fácil se rompe y peor se nota: **la decisión** y **la tabla de
paquetes**.

Aquí también está el camino **remoto**, que es el que se usa con `curl | sh`: el
instalador se ejecuta desde una carpeta vacía, sin el proyecto al lado. Ese caso
tiene dos formas de salir mal que costaron una tarde cada una —decir «no se pudo
descargar» sin decir de dónde, y descargar de verdad cuando solo se estaba
simulando— y las dos tienen test.

La tabla está escrita dos veces, en `nucleo/dependencias.py` (para que `doctor`
diga qué falta) y en `instalar.sh` (para instalarlo). Dos listas que se separan
acaban mandando al usuario a un comando que ya no funciona, así que hay un test
que compara las dos. Ese test es el que evita el fallo clásico de este tipo de
programas: la ayuda que dice una cosa y el instalador que hace otra.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from nucleo import dependencias  # noqa: E402

INSTALADOR = RAIZ / "instalar.sh"


def _simular(sistema: str, *extra: str) -> str:
    """Ejecuta el instalador fingiendo ese sistema, sin tocar nada."""
    r = subprocess.run([str(INSTALADOR), f"--simular={sistema}", "--si", *extra],
                       capture_output=True, text=True, timeout=120,
                       cwd=str(RAIZ))
    assert r.returncode == 0, f"el instalador falló: {r.stderr}"
    return r.stdout + r.stderr


def test_el_instalador_detecta_las_distribuciones_de_verdad():
    """Cada ID de /etc/os-release cae en la familia que le toca."""
    casos = {
        "opensuse-leap": "opensuse",
        "opensuse-tumbleweed": "opensuse",
        "sles": "opensuse",
        "fedora": "fedora",
        "rhel": "fedora",
        "debian": "debian",
        "ubuntu": "debian",
        "linuxmint": "debian",
        "arch": "arch",
        "manjaro": "arch",
        "alpine": "alpine",
    }
    for ident, esperada in casos.items():
        assert dependencias.familia(ident) == esperada, ident
    # Una distribución sin receta no puede caer en una familia por accidente.
    assert dependencias.familia("void") is None
    assert dependencias.familia("nixos") is None
    # Las derivadas que no están en la tabla se resuelven por ID_LIKE.
    assert dependencias.familia("tuxedo", "ubuntu debian") == "debian"
    assert dependencias.familia("nobara", "fedora") == "fedora"


def _tabla_del_instalador() -> dict:
    """Lee la tabla de recetas del instalador, que es texto plano a propósito."""
    texto = INSTALADOR.read_text()
    bloque = re.findall(r"^RECETAS='([^']+)'", texto, re.M)
    assert bloque, "no encuentro la tabla RECETAS en instalar.sh"
    tabla = {}
    for linea in bloque[0].strip().splitlines():
        fam, gestor, paquetes, pipx = linea.split("|")
        tabla[fam] = (gestor, paquetes, pipx)
    return tabla


def test_las_dos_tablas_de_paquetes_dicen_lo_mismo():
    """`doctor` y el instalador no pueden recetar cosas distintas.

    Es el test que evita que el día que alguien arregle una lista se olvide de
    la otra, y que el usuario acabe con un comando que ya no existe. Se
    comparan las dos tablas de verdad, campo a campo, y no lo que cada una
    imprime: los flags de cada gestor de paquetes pueden cambiar de forma (el
    `-y` de apt no es el de zypper) sin que eso sea una divergencia.
    """
    tabla = _tabla_del_instalador()
    assert set(tabla) == set(dependencias.FAMILIAS), (
        f"el instalador conoce {sorted(tabla)} y doctor "
        f"{sorted(dependencias.FAMILIAS)}")
    for fam, (gestor, paquetes, pipx) in tabla.items():
        g, p, _ = dependencias.FAMILIAS[fam]
        assert gestor == g, f"{fam}: gestor {gestor} contra {g}"
        assert paquetes.split() == p.split(), (
            f"{fam}: el instalador instala «{paquetes}» y doctor recomienda "
            f"«{p}»")
        assert pipx == dependencias.PIPX[fam], f"{fam}: el paquete de pipx"
    assert "PIPX = {" in (RAIZ / "nucleo" / "dependencias.py").read_text()


def test_una_distribucion_con_receta_elige_instalar_lo_que_falta():
    """Sin GTK y sin pipx, lo correcto es instalarlos, no rendirse.

    Es el caso de alguien que acaba de instalar openSUSE: quiere la ventana.
    """
    salida = _simular("opensuse-leap")
    assert "Vía elegida: deps" in salida
    assert "zypper install" in salida
    assert "python3-gobject-Gdk" in salida, "falta uno de los cuatro paquetes"
    assert "typelib-1_0-Adw-1" in salida
    assert "pipx" in salida, "después de las dependencias hay que instalar pipx"
    assert "intactpdf-gui" in salida


def test_una_distribucion_sin_receta_cae_en_el_appimage():
    """De void y nixos no sabemos los paquetes: mejor algo que funcione ya.

    El AppImage no necesita ni root ni instalar nada, así que es la respuesta
    honesta cuando no sabemos el nombre de los paquetes.
    """
    salida = _simular("void", "--base-url=https://ejemplo.invalid/x")
    assert "Vía elegida: appimage" in salida
    assert "no incluye la pila de GTK" in salida, \
        "hay que decir que esa vía no trae la ventana"


def test_el_instalador_avisa_de_que_el_appimage_no_trae_la_ventana():
    """No se puede prometer una ventana que no va a haber."""
    salida = _simular("void", "--metodo=appimage",
                      "--base-url=https://ejemplo.invalid/x")
    assert "CONSOLA, no la ventana" in salida


def test_el_instalador_para_en_opensuse_avisa_de_glibc():
    """En openSUSE el glibc nunca es un problema, y se dice por qué."""
    salida = _simular("opensuse-leap")
    assert "glibc:    2.38" in salida


def test_el_instalador_no_necesita_root_para_el_appimage():
    """La vía AppImage se instala entera en el home, sin sudo."""
    salida = _simular("void", "--metodo=appimage",
                      "--base-url=https://ejemplo.invalid/x")
    assert "sudo" not in salida.lower().replace("sin sudo", ""), \
        "la vía del AppImage no debe pedir privilegios"


# ─────────────────────────── el camino remoto ────────────────────────────────
#
# `curl -sSL …/instalar.sh | sh` es la forma en que la gente va a instalar esto, y
# NO se parece a ejecutarlo en el repositorio: el script llega solo a una carpeta
# donde no hay ni código ni artefactos.
#
# Ojo con cómo se reproduce eso, porque el primer intento estaba mal: el
# instalador localiza el proyecto **a partir de su propio fichero** (`$0`), así
# que ejecutar `sh /ruta/al/repo/instalar.sh` desde una carpeta vacía NO simula
# nada — encuentra el proyecto porque está donde está el script. Hay que copiar
# el script a la carpeta vacía y ejecutarlo desde dentro, que es exactamente lo
# que pasa cuando alguien se lo baja con `curl`.

def _plano(texto: str) -> str:
    """El texto con los saltos de línea de los mensajes vueltos uno.

    Los mensajes del instalador van partidos en varias líneas a propósito (para
    que quepan en una terminal), así que buscar una frase larga en crudo falla
    por un salto de línea y no por un fallo de verdad. Esto ya pasó una vez.
    """
    return " ".join(texto.split())


def _desde_carpeta_vacia(*args, entorno=None, timeout=180):
    """Ejecuta el instalador como lo vería un desconocido: solo el script."""
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as carpeta:
        copia = Path(carpeta) / "instalar.sh"
        shutil.copy2(INSTALADOR, copia)
        entorno_completo = dict(os.environ)
        entorno_completo.pop("INTACTPDF_BASE", None)   # que no lo herede del test
        if entorno:
            entorno_completo.update(entorno)
        return subprocess.run(["/bin/sh", str(copia), *args],
                              capture_output=True, text=True, timeout=timeout,
                              cwd=carpeta, env=entorno_completo)


def test_sin_url_y_sin_proyecto_al_lado_dice_qué_le_falta():
    """El error más probable del camino remoto, con un mensaje que sirva.

    Alguien se baja `instalar.sh` (solo el script) y lo ejecuta sin decirle de
    dónde descargar. Tiene que leer **qué opción le falta** y las alternativas,
    no un «no se pudo descargar» ni un error de otra herramienta.
    """
    r = _desde_carpeta_vacia("--si", "--metodo=pipx")
    assert r.returncode != 0, "sin código al lado no puede fingir que fue bien"
    salida = r.stdout + r.stderr
    assert "--base-url" in salida, "el mensaje debe nombrar la opción que falta"
    assert "--desde" in salida, "y la alternativa, si tiene el código"
    assert "no encuentro el código" in salida


def test_simular_con_una_url_no_descarga_nada():
    """Simular dice qué haría: no puede tocar la red.

    Falló de verdad: se le pasaba una URL que no existía y el modo simulado
    intentaba descargar, así que reventaba con «no se pudo descargar» en vez de
    contar lo que haría. Y como el instalador usa `morir` (que termina el
    proceso entero), no bastaba con proteger la llamada con `|| true`.
    """
    r = _desde_carpeta_vacia("--simular=opensuse-leap", "--si",
                             entorno={"INTACTPDF_BASE": "https://ejemplo.invalid/x"})
    assert r.returncode == 0, f"simular no debe fallar: {r.stdout}{r.stderr}"
    salida = r.stdout + r.stderr
    assert "descargaría" in salida
    assert "ejemplo.invalid" in salida, "y decir de dónde, sin bajarlo"


def test_simular_no_deja_nada_en_la_caché_de_descargas():
    """Ni siquiera el fichero de sumas: simular no escribe en el disco."""
    cache = Path(os.environ.get("HOME", "/tmp")) / ".cache/intactpdf/descargas"
    antes = set(cache.iterdir()) if cache.is_dir() else set()
    r = _desde_carpeta_vacia("--simular=opensuse-leap", "--si",
                             entorno={"INTACTPDF_BASE": "https://ejemplo.invalid/x"})
    assert r.returncode == 0
    despues = set(cache.iterdir()) if cache.is_dir() else set()
    assert despues == antes, f"simular escribió en la caché: {despues - antes}"


# ─────────────────────── la vía Flatpak: tres casos ──────────────────────────
#
# Esta es la parte que estaba mal de raíz y se descubrió ejecutando el
# instalador solo, en una carpeta vacía: la vía Flatpak solo se elegía si la
# aplicación **ya estaba instalada**, y cuando lo estaba y no había manifiesto al
# lado, se iba a Flathub a buscar algo que no está publicado y moría con
# «error: Nothing matches io.github.lockerdocx.IntactPDF in remote flathub». Un usuario con
# el Flatpak puesto no podía ni leer qué había pasado.

def test_con_flatpak_y_el_manifiesto_al_lado_se_construye_en_local():
    """En el repositorio, el manifiesto está al lado: se construye y punto."""
    salida = _simular("opensuse-leap", "--con-flatpak")
    assert "Vía elegida: flatpak" in salida
    assert "construyendo el Flatpak" in salida
    assert "Flathub" not in salida, "no hay que ir a Flathub si se puede construir"


def test_sin_manifiesto_y_sin_publicar_no_manda_a_flathub():
    """El fallo encontrado: Flatpak puesto, manifiesto lejos, app sin publicar.

    Lo que NO puede pasar es irse a Flathub. Lo que tiene que hacer es elegir
    otra vía y decirlo.
    """
    r = _desde_carpeta_vacia("--simular=opensuse-leap", "--con-flatpak", "--si")
    salida = r.stdout + r.stderr
    assert "Nothing matches" not in salida
    assert "instalando desde Flathub" not in salida, \
        "la aplicación todavía no está publicada en Flathub"
    assert "Vía elegida: flatpak" not in salida, \
        "sin manifiesto y sin publicar, la vía Flatpak no puede servir"


def test_pedir_flatpak_a_mano_sin_manifiesto_explica_por_que_no_se_puede():
    """Forzando la vía, el error tiene que ser útil, no el de flatpak."""
    r = _desde_carpeta_vacia("--simular=opensuse-leap", "--con-flatpak",
                             "--si", "--metodo=flatpak")
    assert r.returncode != 0
    salida = _plano(r.stdout + r.stderr)
    assert "todavía no está publicado en Flathub" in salida
    assert "--metodo=pipx" in salida, "y decir por dónde sí se puede ir"


def test_la_constante_de_flathub_está_en_el_instalador():
    """Cuando se publique en Flathub hay que darle la vuelta a UNA línea."""
    texto = INSTALADOR.read_text()
    assert "PUBLICADO_EN_FLATHUB=0" in texto, \
        "si ya está publicado, esta constante tiene que ser 1"


# ─────────────────────── publicar, que ahora tiene herramienta ───────────────
#
# `tools/publicar.sh` hace lo que en un proyecto normal hace el CI: preparar los
# cuatro ficheros, comprobar que las sumas cuadran, escribir dentro del
# instalador la dirección desde la que se servirá, y subirlo. Aquí se comprueba
# el paso que puede pasar desapercibido: que la comprobación pasa de verdad con
# lo que hay en el repositorio.

def test_la_herramienta_de_publicar_dice_que_todo_está_listo():
    """`tools/publicar.sh --comprobar` es la puerta de salida a publicar.

    Si este test falla, publicar dejaría a los usuarios con un error de suma que
    no pueden entender, que es justo lo que la herramienta tiene que evitar.
    """
    herramienta = RAIZ / "tools/publicar.sh"
    if not herramienta.exists():
        import pytest
        pytest.skip("la herramienta de publicación no está en el repositorio")
    if not (RAIZ / "dist/publico").is_dir():
        import pytest
        pytest.skip("no hay dist/publico: hay que construirlo antes")
    r = subprocess.run(["/bin/sh", str(herramienta), "--comprobar"],
                       capture_output=True, text=True, timeout=600, cwd=str(RAIZ))
    salida = _plano(r.stdout + r.stderr)
    assert r.returncode == 0, f"la comprobación no pasa: {salida[-800:]}"
    assert "todo listo para publicar" in salida
    assert "las sumas cuadran" in salida


def test_publicar_no_toca_los_ficheros_cuando_es_un_simulacro():
    """Un simulacro no puede dejar una dirección de mentira dentro del script.

    Pasó: el simulacro escribía dentro de `dist/publico/instalar.sh` la dirección
    fingida, las sumas dejaban de cuadrar y la publicación se paraba sola con un
    «1 computed checksum did NOT match» que parecía un fallo del paquete.
    """
    herramienta = RAIZ / "tools/publicar.sh"
    publicado = RAIZ / "dist/publico/instalar.sh"
    if not herramienta.exists() or not publicado.exists():
        import pytest
        pytest.skip("no hay nada que simular")
    antes = publicado.read_bytes()
    subprocess.run(["/bin/sh", str(herramienta), "--github=USUARIO/repo", "--simular"],
                   capture_output=True, text=True, timeout=600, cwd=str(RAIZ))
    assert publicado.read_bytes() == antes, \
        "el simulacro no debe tocar el fichero que se publica"


def test_el_appimage_construido_funciona_si_está():
    """Si hay AppImage construido, que arranque de verdad.

    Se salta si no está: `dist/` es salida de construcción y no viaja con el
    código. Lo que NO se salta es el caso de tenerlo y que esté roto.
    """
    import pytest
    appimage = next((RAIZ / "dist").glob("IntactPDF-*.AppImage"), None) if (RAIZ / "dist").is_dir() else None
    if appimage is None:
        pytest.skip("no hay AppImage construido en dist/")
    r = subprocess.run([str(appimage), "doctor"], capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, f"el AppImage no arranca: {r.stdout[-400:]}{r.stderr[-400:]}"


# ─────────────────────────── el PATH de los comandos ─────────────────────────
#
# `pipx` (y la vía AppImage) dejan los comandos en `~/.local/bin`, que en muchas
# distribuciones no está en el PATH. El primer mensaje que llegó de una
# instalación de verdad, en un Ubuntu 26.04, acababa justo con ese aviso. El
# instalador ahora lo arregla: le pide a `pipx ensurepath` que lo haga, y si no
# puede, escribe el bloque en `~/.profile` con la carpeta de verdad (no `$HOME/bin`,
# que es lo que escribía la primera versión).
#
# Dos cosas que NO puede hacer, y tienen test porque son las que hacen daño:
# no tocar el fichero de arranque de quien sólo estaba simulando, y no añadir el
# bloque dos veces al ejecutarlo dos veces.

def test_simular_dice_que_arreglaría_el_path_pero_no_lo_toca():
    """Simular no puede escribir en el fichero de arranque del shell.

    Es el mismo error que ya se cometió con la caché de descargas: un modo que
    dice «esto es lo que haría» y luego hace. Aquí además el daño es en el
    fichero que lee cada terminal de quien lo ejecuta.
    """
    perfil = Path(os.environ.get("HOME", "/tmp")) / ".profile"
    antes = perfil.read_bytes() if perfil.exists() else None
    r = _desde_carpeta_vacia("--simular=opensuse-leap", "--si", "--metodo=pipx",
                             entorno={"INTACTPDF_BASE": "https://ejemplo.invalid/x"})
    assert r.returncode == 0
    salida = _plano(r.stdout + r.stderr)
    assert "al PATH" in salida, "tiene que decir que lo arreglaría"
    assert "simulado, no se toca nada" in salida
    despues = perfil.read_bytes() if perfil.exists() else None
    assert despues == antes, "simular escribió en ~/.profile"


def test_el_bloque_del_path_se_escribe_una_sola_vez():
    """Ejecutarlo dos veces no puede llenar el fichero de bloques.

    Se comprueba sobre la función, no haciendo una instalación entera: una
    instalación de verdad tarda y necesita red, y lo que puede fallar aquí es la
    comprobación de si ya estaba, que es texto. El primer intento de esta
    comprobación era `sed -n "/marca/d"`, que no imprime nada nunca, así que no
    detectaba nada y escribía el bloque otra vez en cada ejecución.
    """
    funcion = _funcion_del_instalador("arreglar_path")
    assert funcion, "no encuentro arreglar_path en instalar.sh"
    # Se mira el código, no los comentarios: los comentarios explican el fallo
    # que se arregló, y nombrarlo forma parte de la explicación.
    codigo = "\n".join(l for l in funcion.splitlines() if not l.strip().startswith("#"))
    # La búsqueda tiene que ser por la CARPETA en el perfil, no por la marca: si
    # lo añadió `pipx ensurepath`, la carpeta está y la marca no.
    assert 'grep -qF "$PREFIJO/bin"' in codigo, \
        "hay que buscar la carpeta en el perfil antes de escribir"
    assert 'PATH="%s/bin:$PATH"' in codigo, \
        "el PATH tiene que escribirse con el prefijo de verdad"
    assert '$HOME/bin' not in codigo, \
        "no se puede escribir $HOME/bin: la carpeta es $PREFIJO/bin"
    # Y no puede tocar el fichero de arranque cuando sólo se está simulando.
    assert 'SIMULAR' in codigo, "simular tiene que salir antes de escribir nada"


def _funcion_del_instalador(nombre: str) -> str:
    """El texto de una función del instalador, desde `nombre() {` hasta su `}`."""
    texto = INSTALADOR.read_text()
    marca = f"\n{nombre}() {{"
    if marca not in texto:
        return ""
    trozo = texto.split(marca, 1)[1]
    return trozo.split("\n}\n", 1)[0]
