#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
#  IntactPDF — instalador
#
#  Mira en qué distribución de Linux está corriendo, elige la vía que mejor le
#  viene y lo deja instalado. No hay que saber nada de antemano:
#
#      ./instalar.sh
#
#  Lo que hace, en orden:
#
#    1. lee /etc/os-release y mira la versión de glibc;
#    2. mira qué hay disponible (Flatpak, pipx, python3 con PyGObject, un
#       AppImage al lado);
#    3. elige la vía: Flatpak si ya está puesto, pipx si el sistema tiene la
#       pila de GTK, AppImage si no hay nada de eso (esa vía no necesita ni
#       root ni instalar nada más);
#    4. lo instala, y lo deja en el menú de aplicaciones;
#    5. comprueba que funciona de verdad, no que se ha copiado.
#
#  Se puede pedir la vía a mano (--metodo=flatpak|pipx|appimage), ver qué haría
#  sin hacer nada (--simular), y desinstalarlo (--desinstalar).
#
#  Sin root: la vía AppImage y la de pipx no necesitan privilegios. Solo se usa
#  sudo si hay que instalar la pila de GTK del sistema o flatpak-builder, y
#  siempre avisando antes.
# ─────────────────────────────────────────────────────────────────────────────
set -eu
# `set -u` con listas vacías en sh da guerra; se evita con ${X:-}
LC_ALL=C
export LC_ALL

VERSION_APP="0.1.0"
NOMBRE="IntactPDF"

# De dónde se descargan las cosas cuando este script se ejecuta sin tener el
# proyecto al lado (el caso de `curl … | sh`). Se puede cambiar con la variable
# de entorno INTACTPDF_BASE o con --base-url=, que es lo que hace falta mientras
# el proyecto no tenga su URL definitiva. Al publicar de verdad se rellena aquí
# y el `curl | sh` deja de necesitar nada.
BASE_URL_DEFECTO=""     # lo rellena tools/publicar.sh al publicar
# ¿Está la aplicación publicada en Flathub? Todavía NO, y el instalador tiene que
# saberlo: si no, en una máquina con el runtime de Flatpak puesto intentaba
# bajarla de Flathub y moría con «Nothing matches io.github.lockerdocx.IntactPDF in remote
# flathub», que no le dice nada a nadie. Cuando se publique, esta línea pasa a 1
# y la vía Flatpak se ofrece sola (es el único sitio donde hay que cambiarlo).
PUBLICADO_EN_FLATHUB=0
BASE_URL="${INTACTPDF_BASE:-$BASE_URL_DEFECTO}"
SIN_VERIFICAR=0
DIR_DESCARGAS="${XDG_CACHE_HOME:-$HOME/.cache}/intactpdf/descargas"
TMP_SUMAS=""
RUEDA=""
DESCARGADO=""
ID_APP="io.github.lockerdocx.IntactPDF"
AUTOINSTALAR=0        # --si
SIMULAR=""            # --simular=sistema
METODO="auto"
DESINSTALAR=0
SOLO_DEPS=0
DESDE=""
APPIMAGE_DADO=""
PREFIJO="${HOME}/.local"
PYTHON_FORZADO=""      # --python=RUTA
USAR_MENU=1

AQUI="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "$PWD")"

# ─────────────────────────────── salida ──────────────────────────────────────

titulo() { printf '\n\033[1m%s\033[0m\n' "$*"; }
paso()   { printf '  → %s\n' "$*"; }
hecho()  { printf '    \033[32m✓\033[0m %s\n' "$*"; }
ojo()    { printf '    \033[33m!\033[0m %s\n' "$*"; }
malo()   { printf '    \033[31m✗\033[0m %s\n' "$*" >&2; }
morir()  { malo "$*"; exit 1; }

ayuda() {
    cat <<'FIN'
IntactPDF — instalador para cualquier distribución de Linux

Uso:  ./instalar.sh [opciones]

Opciones:
  --metodo=auto|flatpak|pipx|appimage   vía a usar (por omisión: auto)
  --python=RUTA                         intérprete concreto a usar
  --con-gtk                             con --simular: finge que el sistema ya
                                        tiene la pila de GTK
  --con-pipx, --con-flatpak             con --simular: finge que ya están

--simular supone un sistema LIMPIO (nada instalado salvo lo que se finge), que
es el caso interesante: el de alguien que acaba de instalarse el sistema.
  --si                                  no preguntar nada, instalar y ya
  --simular=SISTEMA                     finge estar en otro sistema, para
                                        probar el instalador sin tenerlo
                                        delante. Ej: --simular=opensuse-leap
                                        (solo con --simular a secas: lista)
  --solo-deps                           solo instalar lo que falta para la
                                        ventana (GTK, libadwaita) y salir
  --desde=RUTA                          directorio del código a instalar
  --appimage=RUTA                        AppImage concreto a usar
  --prefijo=RUTA                         dónde instalarlo (~/.local)
  --base-url=URL                        de dónde descargar (si no está el
                                        proyecto al lado). También vale la
                                        variable de entorno INTACTPDF_BASE
  --sin-verificar                       no comprobar el sha256 de lo descargado
                                        (no se recomienda)
  --desinstalar                          quitar lo que puso este script
  -h, --help                            esto

Sin opciones hace lo razonable según lo que encuentre. Nunca pide contraseña
sin decir antes para qué.
FIN
}

# ───────────────────────────── argumentos ────────────────────────────────────

for arg in "$@"; do
    case "$arg" in
        --metodo=*)   METODO="${arg#*=}" ;;
        --si|-y)      AUTOINSTALAR=1 ;;
        --simular)    SIMULAR="lista" ;;
        --simular=*)  SIMULAR="${arg#*=}" ;;
        --solo-deps)  SOLO_DEPS=1 ;;
        --desde=*)    DESDE="${arg#*=}" ;;
        --appimage=*) APPIMAGE_DADO="${arg#*=}" ;;
        --prefijo=*)  PREFIJO="${arg#*=}" ;;
        --python=*)   PYTHON_FORZADO="${arg#*=}" ;;
        --con-gtk)    CON_GTK=1 ;;
        --con-flatpak) CON_FLATPAK=1 ;;
        --base-url=*) BASE_URL="${arg#*=}" ;;
        --sin-verificar) SIN_VERIFICAR=1 ;;
        --con-pipx)   CON_PIPX=1 ;;
        --desinstalar) DESINSTALAR=1 ;;
        -h|--help)    ayuda; exit 0 ;;
        *)            morir "opción desconocida: $arg  (prueba con --help)" ;;
    esac
done

# ─────────────────────────── el sistema ──────────────────────────────────────

OS_RELEASE="/etc/os-release"
[ -n "$SIMULAR" ] && [ "$SIMULAR" != "lista" ] && OS_RELEASE=""

# Tabla de recetas: familia|gestor|paquetes de la ventana.
# Tiene que coincidir con nucleo/dependencias.py — hay un test que lo comprueba,
# porque dos listas que se separan acaban mandando al usuario a un comando que
# ya no funciona.
RECETAS='debian|apt|python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1|pipx
fedora|dnf|python3-gobject gtk4 libadwaita|pipx
opensuse|zypper|python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1|python3-pipx
arch|pacman|python-gobject gtk4 libadwaita|python-pipx
alpine|apk|py3-gobject3 gtk4.0 libadwaita|py3-pipx'

receta_de() {   # receta_de FAMILIA -> "gestor|paquetes|paquete_pipx"
    # Se parte por el separador '|' y no por espacios: la lista de paquetes
    # lleva varios separados por espacios, y con `cut -d' '` se quedaba con el
    # primero («hacen falta: python3-gobject» en vez de los cuatro de openSUSE).
    printf '%s\n' "$RECETAS" | awk -F'|' -v f="$1" '$1 == f { print; exit }'
}

campo_de() {    # campo_de FAMILIA N -> el campo N de su receta
    receta_de "$1" | cut -d'|' -f"$2"
}

familia_de() {  # familia_de ID ID_LIKE
    case "$1" in
        debian|ubuntu|linuxmint|pop|raspbian|elementary|zorin|kali|mx|devuan|deepin|neon) echo debian ;;
        fedora|rhel|centos|rocky|almalinux|ol|amzn|scientific) echo fedora ;;
        opensuse*|sles|sled|suse) echo opensuse ;;
        arch|archarm|manjaro|manjaro-arm|endeavouros|cachyos|garuda|arcolinux) echo arch ;;
        alpine|postmarketos) echo alpine ;;
        *)  for t in $2; do
                case "$t" in
                    debian|ubuntu) echo debian; return ;;
                    fedora|rhel) echo fedora; return ;;
                    suse|opensuse) echo opensuse; return ;;
                    arch) echo arch; return ;;
                    alpine) echo alpine; return ;;
                esac
            done
            echo "" ;;
    esac
}

detectar() {
    if [ -z "$OS_RELEASE" ]; then
        # --simular: valores de mentira para probar la lógica en cualquier sitio
        case "$SIMULAR" in
            opensuse*|sles) ID_OS="opensuse-leap"; LIKE_OS="suse";
                NOMBRE_OS="openSUSE Leap 15.6 (simulado)" ;;
            fedora)         ID_OS="fedora"; LIKE_OS=""; NOMBRE_OS="Fedora (simulado)" ;;
            debian)         ID_OS="debian"; LIKE_OS=""; NOMBRE_OS="Debian (simulado)" ;;
            ubuntu)         ID_OS="ubuntu"; LIKE_OS="debian"; NOMBRE_OS="Ubuntu (simulado)" ;;
            arch)           ID_OS="arch"; LIKE_OS=""; NOMBRE_OS="Arch (simulado)" ;;
            alpine)         ID_OS="alpine"; LIKE_OS=""; NOMBRE_OS="Alpine (simulado)" ;;
            void|nixos)     ID_OS="$SIMULAR"; LIKE_OS=""; NOMBRE_OS="$SIMULAR (simulado)" ;;
            *)              ID_OS="$SIMULAR"; LIKE_OS=""; NOMBRE_OS="$SIMULAR (simulado)" ;;
        esac
    else
        ID_OS=""; LIKE_OS=""; NOMBRE_OS=""
        if [ -r "$OS_RELEASE" ]; then
            while IFS='=' read -r clave valor; do
                valor="$(printf '%s' "$valor" | tr -d '"'"'"'')"
                case "$clave" in
                    ID)          ID_OS="$valor" ;;
                    ID_LIKE)     LIKE_OS="$valor" ;;
                    PRETTY_NAME) NOMBRE_OS="$valor" ;;
                esac
            done < "$OS_RELEASE"
        fi
        [ -n "$NOMBRE_OS" ] || NOMBRE_OS="${ID_OS:-desconocido}"
    fi
    FAMILIA="$(familia_de "$ID_OS" "$LIKE_OS")"
}

glibc_version() {   # la que usa el AppImage como suelo: 2.28
    ldd --version 2>/dev/null | head -1 | sed 's/.* //' || echo "0"
}

version_menor() {   # version_menor A B -> cierto si A < B
    [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$1" ] &&
        [ "$1" != "$2" ]
}

# ─────────────────────────── qué hay instalado ───────────────────────────────

hay() { command -v "$1" >/dev/null 2>&1; }

hay_flatpak() {          # ¿hay Flatpak? (al simular lo dice --con-flatpak)
    if [ -n "$SIMULAR" ]; then
        [ "${CON_FLATPAK:-0}" = "1" ]
        return
    fi
    hay flatpak
}

hay_flatpak_builder() {  # ¿se puede construir un Flatpak aquí?
    if [ -n "$SIMULAR" ]; then
        [ "${CON_FLATPAK:-0}" = "1" ]
        return
    fi
    hay flatpak-builder
}

python_con_gtk() {
    # Se prueban varios intérpretes a propósito: es normal tener más de uno
    # (el de la distribución en /usr/bin y otro de pyenv, snap o compilado a
    # mano en /usr/local). Aquí, por ejemplo, el `python3` del PATH no tiene
    # PyGObject y `/usr/bin/python3` sí. Quedarse con el primero y decir «no
    # tienes GTK» cuando sí lo tienes es un error de los que hacen perder una
    # tarde entera.
    for cand in "$PYTHON_FORZADO" /usr/bin/python3 "$(command -v python3 2>/dev/null)" \
                "$(command -v python3.13 2>/dev/null)" "$(command -v python3.12 2>/dev/null)"; do
        [ -n "$cand" ] && [ -x "$cand" ] || continue
        if pygobject_en "$cand"; then printf '%s\n' "$cand"; return 0; fi
    done
    return 1
}

pygobject_en() {   # ¿este intérprete puede importar gi + Gtk 4?
    [ -n "$1" ] || return 1
    "$1" - <<'FIN' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
FIN
}

manifiesto_local() {   # ruta del manifiesto de Flatpak, si está al lado
    for f in "$DESDE/packaging/$ID_APP.json" "$AQUI/packaging/$ID_APP.json"; do
        [ -f "$f" ] && printf '%s\n' "$f" && return 0
    done
    return 1
}

flatpak_listo() {
    # ¿Se puede hacer algo con la vía Flatpak? La versión anterior pedía que la
    # aplicación YA estuviera instalada, que es al revés de lo que hace falta
    # para instalarla la primera vez, y cuando estaba instalada y no había
    # manifiesto al lado mandaba a Flathub a buscar algo que no está publicado.
    # Ahora son tres casos, y cada uno lleva a una acción que existe.
    hay_flatpak || return 1
    # 1. Hay manifiesto al lado y con qué construirlo: se construye.
    if [ -n "$(manifiesto_local)" ]; then
        hay_flatpak_builder && return 0
    fi
    # 2. Ya está instalada: no hay que instalar nada, se comprueba y se dice.
    if [ -z "$SIMULAR" ] && flatpak info "$ID_APP" >/dev/null 2>&1; then
        return 0
    fi
    # 3. Está publicada en Flathub: se baja de ahí.
    [ "$PUBLICADO_EN_FLATHUB" = "1" ] && return 0
    return 1
}

pipx_disponible() {
    if [ -n "$SIMULAR" ]; then
        [ "${CON_PIPX:-0}" = "1" ] || return 1
    fi
    hay pipx
}

# ─────────────────────────── elegir la vía ───────────────────────────────────

elegir_metodo() {
    case "$METODO" in
        flatpak)  M="flatpak";  RAZON="pedido a mano" ;;
        pipx)     M="pipx";     RAZON="pedido a mano" ;;
        appimage) M="appimage"; RAZON="pedido a mano" ;;
        auto)
            py="$(python_con_gtk || true)"
            if [ "$SIMULAR" != "" ] && [ "${CON_GTK:-0}" != "1" ]; then
                # Simulando: se finge que no hay GTK, para que la decisión no
                # dependa del sistema en el que se está probando el instalador.
                py=""
            fi
            if flatpak_listo; then
                M="flatpak"
                if [ -n "$(manifiesto_local || true)" ]; then
                    RAZON="el Flatpak ya está puesto y el manifiesto está al lado"
                elif [ "$PUBLICADO_EN_FLATHUB" = "1" ]; then
                    RAZON="el Flatpak ya está puesto"
                else
                    RAZON="ya está instalado; no hay nada que hacer"
                fi
            elif [ -n "$py" ] && pipx_disponible; then
                M="pipx"; RAZON="hay pipx y el sistema ya tiene GTK 4 y libadwaita"
            elif [ -n "$py" ]; then
                M="pip3"; RAZON="el sistema ya tiene GTK 4 y libadwaita"
            elif [ -n "$FAMILIA" ] && [ -n "$(receta_de "$FAMILIA")" ] && \
                 ! pipx_disponible; then
                M="deps"; RAZON="falta la pila de GTK y esta distribución tiene receta"
                PY_GTK="$py"
            elif [ -n "$(buscar_appimage_local)" ] || [ -n "$BASE_URL" ]; then
                M="appimage"; RAZON="no hay GTK en el sistema; el AppImage no lo necesita"
            elif [ -n "$FAMILIA" ] && [ -n "$(receta_de "$FAMILIA")" ]; then
                M="deps"; RAZON="falta la pila de GTK y esta distribución tiene receta"
            else
                M="appimage"; RAZON="distribución sin receta; el AppImage no necesita nada"
            fi ;;
        *) morir "--metodo=$METODO no existe (auto, flatpak, pipx, appimage)" ;;
    esac
    # El AppImage no puede hacer de ventana: no lleva la pila de GTK dentro.
    if [ "$M" = "appimage" ] && [ "$PREFIERE_VENTANA" = "1" ]; then
        M="appimage"
        AVISO_SIN_VENTANA=1
    fi
}

buscar_appimage_local() {
    for d in "$DESDE" "$AQUI" "$AQUI/dist" "$AQUI/.." "$AQUI/../dist" \
             "$PWD" "$PWD/dist"; do
        [ -n "$d" ] || continue
        for f in "$d"/IntactPDF-*.AppImage; do
            [ -f "$f" ] && printf '%s\n' "$f" && return 0
        done
    done
    return 1
}

buscar_appimage() {
    if [ -n "$APPIMAGE_DADO" ]; then
        [ -f "$APPIMAGE_DADO" ] && printf '%s\n' "$APPIMAGE_DADO" && return
        # Simulando, el fichero es un nombre fingido y no existe: se sigue.
        [ -n "$SIMULAR" ] && printf '%s\n' "$APPIMAGE_DADO" && return
        morir "no existe el AppImage $APPIMAGE_DADO"
    fi
    for d in "$DESDE" "$AQUI" "$AQUI/dist" "$AQUI/.." "$AQUI/../dist" \
             "$PWD" "$PWD/dist"; do
        [ -n "$d" ] || continue
        for f in "$d"/IntactPDF-*-x86_64.AppImage "$d"/IntactPDF-*.AppImage \
                 "$d"/IntactPDF-*-aarch64.AppImage; do
            [ -f "$f" ] && printf '%s\n' "$f" && return
        done
    done
    # Nada de descargar aquí: se descarga en el flujo principal. Hacerlo dentro
    # de una sustitución de orden es lo que borraba el fichero (ver
    # `preparar_descargas`). Si ya se bajó, está en $APPIMAGE_DADO.
    if [ -n "$APPIMAGE_DADO" ] && [ -f "$APPIMAGE_DADO" ]; then
        printf '%s\n' "$APPIMAGE_DADO" && return
    fi
    return 1
}

# ─────────────────────────── descargas ───────────────────────────────────────

suma_de() {     # suma_de FICHERO -> sha256, con lo que haya en el sistema
    if hay sha256sum; then sha256sum "$1" | cut -d' ' -f1
    elif hay shasum; then shasum -a 256 "$1" | cut -d' ' -f1
    elif hay openssl; then openssl dgst -sha256 "$1" | sed 's/.*= //'
    else echo ""; fi
}

bajar() {       # bajar URL DESTINO  (sin comprobar nada todavía)
    if hay curl; then
        curl -fsSL --retry 3 --connect-timeout 20 --max-time 900 -o "$2" "$1"
    elif hay wget; then
        wget -q -O "$2" "$1"
    else
        morir "hace falta curl o wget para descargar"
    fi
}

bajar_sumas() {
    [ -n "$TMP_SUMAS" ] && [ -f "$TMP_SUMAS" ] && return 0
    # Los nombres de variable van con prefijo A PROPÓSITO. En `sh` no hay
    # variables locales: todo lo que se asigna dentro de una función es global.
    # La primera versión de esto usaba `destino` aquí y también en `descargar`,
    # así que al verificar la suma se machacaba el destino del AppImage y el
    # instalador acababa copiando ¡el fichero de sumas! en lugar del AppImage.
    # Lo destapó la prueba de verdad, con `curl | sh`.
    sumas_destino="$DIR_DESCARGAS/SHA256SUMS"
    # Se baja a un nombre temporal y se mueve al final: una descarga cortada a
    # medias no puede quedar como si fuera la lista buena, porque de ella
    # depende que se acepte o no lo demás.
    bajar "$BASE_URL/SHA256SUMS" "$sumas_destino.parcial" || return 1
    mv -f "$sumas_destino.parcial" "$sumas_destino" || return 1
    TMP_SUMAS="$sumas_destino"
    return 0
}

verificar_suma() {  # verificar_suma NOMBRE FICHERO
    if [ "$SIN_VERIFICAR" = "1" ]; then
        ojo "sin comprobar la suma de $1 (--sin-verificar)"
        return 0
    fi
    if ! bajar_sumas; then
        morir "no se pudo descargar SHA256SUMS de $BASE_URL: no se puede
    comprobar lo descargado. (Con --sin-verificar se instala igual, pero no
    se recomienda: es la única comprobación de que lo que llega es lo que se
    publicó.)"
    fi
    esperado="$(awk -v n="$1" '($2 == n || $2 == "*" n) {print $1; exit}' \
                "$TMP_SUMAS")"
    if [ -z "$esperado" ]; then
        morir "SHA256SUMS no dice nada de $1: no se puede comprobar"
    fi
    real="$(suma_de "$2")"
    if [ -z "$real" ]; then
        ojo "no hay ninguna herramienta para calcular sha256; no se comprueba"
        return 0
    fi
    if [ "$real" != "$esperado" ]; then
        printf '\n' >&2
        malo "la suma de $1 NO cuadra: el fichero descargado no es el publicado"
        printf '    esperado: %s\n    obtenido: %s\n' "$esperado" "$real" >&2
        # El fichero malo NO se queda en la caché: si se quedara, la siguiente
        # ejecución lo daría por bueno por estar ya ahí.
        rm -f "$2"
        morir "se para por seguridad; no se ha instalado nada de ese fichero"
    fi
    hecho "suma de $1 comprobada"
}

descargar() {   # descargar NOMBRE -> deja la ruta en $DESCARGADO
    # Prefijos por lo mismo que en `bajar_sumas`: sin variables locales, dos
    # funciones que usen el mismo nombre se pisan.
    desc_nombre="$1"
    desc_destino="$DIR_DESCARGAS/$desc_nombre"
    paso "descargando $BASE_URL/$desc_nombre"
    bajar "$BASE_URL/$desc_nombre" "$desc_destino" ||
        morir "no se pudo descargar $BASE_URL/$desc_nombre"
    verificar_suma "$desc_nombre" "$desc_destino"
    DESCARGADO="$desc_destino"
}

preparar_descargas() {
    # Ya NO se usa un directorio temporal con `trap … EXIT`. Eso era un fallo
    # serio y difícil de ver: la descarga se hacía dentro de `$(buscar_appimage)`
    # y una sustitución de orden en `sh` es una subcáscara, así que el `trap`
    # pertenecía a la subcáscara y borraba el AppImage recién bajado al salir de
    # ella. El resultado eran instalaciones a medias con un «No such file or
    # directory» desconcertante. Ahora se baja a la caché del usuario, que
    # además tiene una ventaja: repetir el instalador no vuelve a bajar 61 MB.
    mkdir -p "$DIR_DESCARGAS" || return 1
}

nombre_appimage() {
    printf 'IntactPDF-%s-%s.AppImage' "$VERSION_APP" "$ARCH"
}

nombre_rueda() {
    printf 'intactpdf-%s-py3-none-any.whl' "$VERSION_APP"
}

preparar_remoto() {     # deja listo $APPIMAGE_DADO o $RUEDA según la vía
    [ -n "$BASE_URL" ] || return 1
    if [ "$SIMULAR" != "" ]; then
        # Simular no toca la red ni el disco: sólo dice qué haría. Sin esto, el
        # modo simulado intentaba descargar de verdad desde la URL que se le
        # pasara y fallaba con un «no se pudo descargar» al probarlo.
        case "$M" in
            appimage)
                paso "descargaría $BASE_URL/$(nombre_appimage)"
                APPIMAGE_DADO="$DIR_DESCARGAS/$(nombre_appimage)" ;;
            pipx|pip3)
                paso "descargaría $BASE_URL/$(nombre_rueda)"
                RUEDA="$DIR_DESCARGAS/$(nombre_rueda)" ;;
        esac
        hecho "simulado (no se descarga nada)"
        return 0
    fi
    preparar_descargas || morir "no se puede escribir en $DIR_DESCARGAS"
    case "$M" in
        appimage)
            if [ -n "$APPIMAGE_DADO" ] && [ -f "$APPIMAGE_DADO" ]; then
                return 0
            fi
            descargar "$(nombre_appimage)"
            APPIMAGE_DADO="$DESCARGADO" ;;
        pipx|pip3)
            descargar "$(nombre_rueda)"
            RUEDA="$DESCARGADO" ;;
    esac
    return 0
}

# ─────────────────────────── la instalación ──────────────────────────────────

# La orden de instalar, en UN solo sitio. Estaba escrita dos veces (una para
# simular y otra para ejecutar) y por eso la simulación decía «pacman install»,
# que no es una orden de pacman: el modo simulado enseñaba algo que el modo real
# nunca haría. Lo destapó el test que compara la tabla con la de `doctor`.
orden_instalar() {  # orden_instalar GESTOR PAQUETES -> orden sin sudo
    case "$1" in
        apt)    echo "apt install -y $2" ;;
        dnf)    echo "dnf install -y $2" ;;
        zypper) echo "zypper install -y $2" ;;
        pacman) echo "pacman -S --needed --noconfirm $2" ;;
        apk)    echo "apk add $2" ;;
        *)      echo "" ;;
    esac
}

ejecutar_con_privilegios() {    # ejecutar_con_privilegios "orden"
    if [ "$(id -u)" = "0" ]; then
        sh -c "$1"
    elif hay sudo; then
        ojo "necesita privilegios: sudo $1"
        sudo sh -c "$1"
    else
        morir "hace falta root (o sudo) para: $1"
    fi
}

confirmar() {
    [ "$AUTOINSTALAR" = "1" ] && return 0
    # Con `curl … | sh` la entrada estándar ES el propio script. Un `read` aquí
    # no leería del teclado: se comería el texto del script que queda por
    # ejecutar, y el resultado es un programa que se corta a la mitad sin decir
    # por qué. Es el fallo clásico de los instaladores de una línea. Si no hay
    # terminal, no se pregunta: se avisa y se sigue, que es lo que el usuario ha
    # pedido al escribir la tubería.
    if [ ! -t 0 ]; then
        printf '\n  %s\n' "$1"
        printf '  (sin terminal: se sigue sin preguntar)\n'
        return 0
    fi
    printf '\n  %s\n  ¿Sigo? [s/N] ' "$1"
    read -r respuesta || respuesta="n"
    case "$respuesta" in
        s|S|si|sí|y|Y) return 0 ;;
        *) return 1 ;;
    esac
}

instalar_deps() {
    [ -n "$(receta_de "$FAMILIA")" ] ||
        morir "no sé qué paquetes hacen falta en ${NOMBRE_OS}"
    gestor="$(campo_de "$FAMILIA" 2)"
    paquetes="$(campo_de "$FAMILIA" 3)"
    if [ -z "$SIMULAR" ]; then
        hay "$gestor" || morir "esta distribución usa $gestor, pero no está instalado"
    fi
    orden="$(orden_instalar "$gestor" "$paquetes")"
    paso "para la ventana hacen falta: $paquetes"
    if [ "$SIMULAR" != "" ]; then
        hecho "simulado: sudo $orden"
        return 0
    fi
    confirmar "Se van a instalar paquetes del sistema con sudo." || morir "cancelado"
    ejecutar_con_privilegios "$orden"
}

instalar_pipx() {
    hay pipx && return 0
    paquete_pipx="$(campo_de "$FAMILIA" 4)"
    gestor="$(campo_de "$FAMILIA" 2)"
    [ -n "$paquete_pipx" ] || return 1
    paso "no hay pipx; se instala ($paquete_pipx), que es la forma limpia de"
    paso "instalar una aplicación de Python: no toca el Python del sistema"
    orden="$(orden_instalar "$gestor" "$paquete_pipx")"
    if [ "$SIMULAR" != "" ]; then
        hecho "simulado: sudo $orden"
        return 0
    fi
    confirmar "Se va a instalar pipx con sudo." || return 1
    ejecutar_con_privilegios "$orden"
}

# Instalador del AppImage: copia, lanzador y entrada de menú.
instalar_appimage() {
    origen="$(buscar_appimage)" || morir "no encuentro ningún AppImage (mira --appimage=)"
    destino_dir="$PREFIJO/opt/intactpdf"
    mkdir -p "$destino_dir" "$PREFIJO/bin"
    destino="$destino_dir/$(basename "$origen")"
    paso "copiando el AppImage a $destino"
    if [ "$SIMULAR" = "" ]; then cp -f "$origen" "$destino"; chmod +x "$destino"; fi

    # Con FUSE se ejecuta tal cual; sin él, se extrae una vez y se ejecuta lo
    # extraído, que además arranca más rápido.
    usa_fuse=0
    if [ -e /dev/fuse ] && hay fusermount || hay fusermount3; then usa_fuse=1; fi
    if [ "$SIMULAR" != "" ]; then usa_fuse=1; fi

    if [ "$usa_fuse" = "1" ]; then
        orden="\"$destino\""
        hecho "la entrada de menú ejecutará el AppImage (hay FUSE)"
    else
        ojo "no hay FUSE: se extrae el AppImage una vez y se ejecuta lo extraído"
        if [ "$SIMULAR" = "" ]; then
            ( cd "$destino_dir" && "$destino" --appimage-extract >/dev/null )
            rmdir "$destino_dir/squashfs-root/usr/intactpdf" 2>/dev/null || true
        fi
        orden="\"$destino_dir/squashfs-root/AppRun\""
    fi

    paso "creando el lanzador $PREFIJO/bin/intactpdf"
    if [ "$SIMULAR" = "" ]; then
        cat > "$PREFIJO/bin/intactpdf" <<FIN
#!/bin/sh
# Lanzador puesto por instalar.sh. La consola del AppImage.
exec $orden "\$@"
FIN
        chmod +x "$PREFIJO/bin/intactpdf"
    fi
    hecho "$PREFIJO/bin/intactpdf"

    if [ "$USAR_MENU" = "1" ]; then
        paso "creando la entrada del menú de aplicaciones"
        if [ "$SIMULAR" = "" ]; then
            mkdir -p "$PREFIJO/share/applications"
            cat > "$PREFIJO/share/applications/$ID_APP.desktop" <<FIN
[Desktop Entry]
Type=Application
Name=$NOMBRE
Comment=Edita PDFs sin reconstruir el documento
Exec=$PREFIJO/bin/intactpdf
Terminal=true
Icon=$ID_APP
Categories=Office;Graphics;
FIN
        fi
        hecho "$PREFIJO/share/applications/$ID_APP.desktop"
        instalar_icono
    fi

    ojo "el AppImage lleva la CONSOLA, no la ventana: no incluye la pila de GTK"
    ojo "para la ventana hace falta la vía Flatpak o la de pipx"
}

instalar_icono() {
    icono=""
    for f in "$DESDE/icons/$ID_APP.svg" "$AQUI/packaging/icons/$ID_APP.svg" \
             "$AQUI/icons/$ID_APP.svg"; do
        [ -f "$f" ] && icono="$f" && break
    done
    [ -n "$icono" ] || return 0
    if [ "$SIMULAR" = "" ]; then
        mkdir -p "$PREFIJO/share/icons/hicolor/scalable/apps"
        cp -f "$icono" "$PREFIJO/share/icons/hicolor/scalable/apps/$ID_APP.svg"
    fi
    hecho "icono instalado"
}

instalar_pip() {
    codigo="$DESDE"
    [ -n "$codigo" ] || codigo="$AQUI"
    if [ ! -f "$codigo/pyproject.toml" ] && [ -z "${RUEDA:-}" ]; then
        if [ -n "$BASE_URL" ]; then
            preparar_remoto || morir "no se pudo descargar el paquete"
            codigo="$RUEDA"
        else
            morir "no encuentro el código a instalar. Dale el directorio del
    proyecto con --desde=RUTA, o la URL de las descargas con --base-url=URL
    (o con la variable INTACTPDF_BASE). Para la vía sin código:
    --metodo=appimage."
        fi
    fi
    if [ "$SIMULAR" = "" ]; then
        [ -e "$codigo" ] || morir "no existe $codigo"
    fi
    py="$(python_con_gtk || true)"
    [ -n "$py" ] || py="$(command -v python3 || true)"
    if [ -z "$py" ]; then
        morir "no hay ningún python3; usa --metodo=appimage o --metodo=flatpak"
    fi
    if [ "$SIMULAR" != "" ]; then
        hecho "simulado: pipx install --system-site-packages $codigo  (con $py)"
        instalar_menu_pip
        return 0
    fi
    # `--system-site-packages` NO es opcional aquí: PyGObject va atado a las
    # bibliotecas de GTK de la distribución y no se puede instalar con pip. Sin
    # ese flag, el entorno virtual de pipx nace aislado, ve el paquete pero NO
    # ve PyGObject, y el resultado es lo peor posible: una consola que funciona
    # y una ventana que dice «no está instalado PyGObject» cuando sí lo está.
    # Comprobado a mano en esta máquina antes de arreglarlo.
    if hay pipx; then
        paso "pipx install --system-site-packages $codigo"
        pipx install --force --system-site-packages "$codigo" ||
            morir "pipx falló (mira el mensaje de arriba)"
        hecho "intactpdf y intactpdf-gui instalados con pipx"
    else
        instalar_pipx || true
        if hay pipx; then
            paso "pipx install --system-site-packages $codigo"
            pipx install --force --system-site-packages "$codigo" || morir "pipx falló"
            hecho "intactpdf y intactpdf-gui instalados con pipx"
        else
            paso "$py -m pip install --user $codigo"
            if ! "$py" -m pip install --user --upgrade "$codigo" 2>&1 | tee /tmp/instalar_pip.log; then
                if grep -q "externally-managed" /tmp/instalar_pip.log 2>/dev/null; then
                    malo "tu distribución no deja instalar en el Python del sistema"
                    malo "(«externally-managed-environment», pasa en Debian 12 y"
                    malo "Ubuntu 23.04 y posteriores)"
                    printf '\n    La forma de hacerlo ahí es pipx:\n'
                    printf '        %s\n\n' "$(comando_pipx "$FAMILIA" || echo 'instala pipx')"
                fi
                morir "la instalación con pip falló"
            fi
            hecho "intactpdf y intactpdf-gui en $PREFIJO/bin"
        fi
    fi
    instalar_menu_pip
}

instalar_menu_pip() {
    [ "$USAR_MENU" = "1" ] || return 0
    paso "creando la entrada del menú de aplicaciones (abre la ventana)"
    if [ "$SIMULAR" = "" ]; then
        mkdir -p "$PREFIJO/share/applications"
        cat > "$PREFIJO/share/applications/$ID_APP.desktop" <<FIN
[Desktop Entry]
Type=Application
Name=$NOMBRE
Comment=Edita PDFs sin reconstruir el documento
Exec=$PREFIJO/bin/intactpdf-gui %f
MimeType=application/pdf;
Terminal=false
Icon=$ID_APP
Categories=Office;Graphics;
FIN
    fi
    hecho "entrada de menú instalada"
    instalar_icono
}

instalar_flatpak() {
    hay_flatpak || morir "no hay flatpak instalado (prueba --metodo=pipx)"
    manifiesto="$(manifiesto_local || true)"
    if [ -n "$manifiesto" ]; then
        hay_flatpak_builder || morir "hace falta flatpak-builder para construir el
    Flatpak a partir de $manifiesto; instálalo con el gestor de paquetes de tu
    distribución, o usa --metodo=pipx"
        paso "construyendo el Flatpak desde $manifiesto (tarda un rato)"
        raiz="$(dirname "$(dirname "$manifiesto")")"
        [ "$SIMULAR" = "" ] && flatpak-builder --user --install --force-clean \
            --disable-rofiles-fuse "$raiz/build-dir" "$manifiesto"
        hecho "flatpak run $ID_APP"
        return 0
    fi
    # Ya instalada y sin manifiesto al lado: no hay nada que hacer, y decirlo es
    # mejor que intentar bajarla de un sitio donde no está.
    if [ "$SIMULAR" = "" ] && flatpak info "$ID_APP" >/dev/null 2>&1; then
        hecho "ya está instalado ($ID_APP); no hay nada que hacer"
        return 0
    fi
    if [ "$PUBLICADO_EN_FLATHUB" = "1" ]; then
        paso "instalando desde Flathub"
        if [ "$SIMULAR" = "" ] && ! flatpak install -y --user flathub "$ID_APP"; then
            morir "Flathub no tiene $ID_APP. Comprueba la conexión, o instálalo
    desde el código con --desde=RUTA, o con --metodo=pipx"
        fi
        hecho "flatpak run $ID_APP"
        return 0
    fi
    # Ni manifiesto ni publicación: la vía Flatpak no puede servir ahora mismo,
    # y se dice por qué en vez de mandar a nadie a un error ajeno.
    morir "la vía Flatpak necesita el manifiesto del proyecto al lado
    (packaging/$ID_APP.json) para construirlo, y todavía no está publicado en
    Flathub. Usa --metodo=pipx, --metodo=appimage, o --desde=RUTA con el código"
}

refrescar_caches() {
    [ "$SIMULAR" != "" ] && return 0
    hay update-desktop-database &&
        update-desktop-database "$PREFIJO/share/applications" 2>/dev/null || true
    hay gtk-update-icon-cache &&
        gtk-update-icon-cache -qtf "$PREFIJO/share/icons/hicolor" 2>/dev/null || true
}

comprobar() {
    paso "comprobando que funciona de verdad"
    if [ "$SIMULAR" != "" ]; then
        hecho "simulado"
        return 0
    fi
    if [ "$M" = "flatpak" ]; then
        if flatpak run --command=intactpdf "$ID_APP" doctor >/dev/null 2>&1; then
            hecho "la consola del Flatpak responde"
        else
            # Sin portal ni permiso al home, la consola no ve ficheros: se
            # comprueba al menos que el programa arranca.
            if flatpak run --command=intactpdf "$ID_APP" --help >/dev/null 2>&1; then
                hecho "el Flatpak arranca (sin permiso a tus ficheros todavía)"
            else
                ojo "el Flatpak está instalado pero no responde; prueba a mano"
            fi
        fi
        return 0
    fi
    if [ -x "$PREFIJO/bin/intactpdf" ]; then
        if "$PREFIJO/bin/intactpdf" doctor >/dev/null 2>&1; then
            hecho "intactpdf doctor dice que todo está listo"
        else
            ojo "intactpdf está instalado pero doctor da avisos: ejecútalo tú"
        fi
    fi
    # Y que la ventana pueda abrirse de verdad, que es lo que se ha ido a
    # buscar: se le pregunta al lanzador, que no abre ninguna ventana.
    if [ "$PREFIERE_VENTANA" = "1" ] && [ -x "$PREFIJO/bin/intactpdf-gui" ]; then
        if salida="$("$PREFIJO/bin/intactpdf-gui" --comprobar 2>&1)"; then
            hecho "$salida"
        else
            ojo "la ventana no podría abrirse todavía:"
            printf '%s\n' "$salida" | sed 's/^/        /'
        fi
    fi
}

quitar_del_perfil() {   # el PATH que añadió arreglar_path(), si lo añadió
    perfil="$HOME/.profile"
    [ -f "$perfil" ] || return 0
    grep -qF "$MARCA_PATH" "$perfil" 2>/dev/null || return 0
    tmp="$perfil.intactpdf.$$"
    awk -v marca="$MARCA_PATH" '
        index($0, marca) { saltar = 4; next }        # la marca y sus tres líneas
        saltar > 0 { saltar--; next }
        { print }
    ' "$perfil" > "$tmp" && mv "$tmp" "$perfil"
    paso "PATH restaurado en $perfil"
}

desinstalar() {
    titulo "Quitando $NOMBRE"
    if hay flatpak && flatpak info "$ID_APP" >/dev/null 2>&1; then
        paso "flatpak uninstall -y $ID_APP"
        [ "$SIMULAR" = "" ] && flatpak uninstall -y --user "$ID_APP"
        hecho "Flatpak quitado"
    fi
    if hay pipx && pipx list 2>/dev/null | grep -q intactpdf; then
        paso "pipx uninstall intactpdf"
        [ "$SIMULAR" = "" ] && pipx uninstall intactpdf
        hecho "paquete de pipx quitado"
    fi
    for f in "$PREFIJO/bin/intactpdf" "$PREFIJO/bin/intactpdf-gui" \
             "$PREFIJO/share/applications/$ID_APP.desktop" \
             "$PREFIJO/share/applications/$ID_APP.cli.desktop" \
             "$PREFIJO/share/icons/hicolor/scalable/apps/$ID_APP.svg"; do
        if [ -e "$f" ] || [ -L "$f" ]; then
            [ "$SIMULAR" = "" ] && rm -f "$f"
            hecho "quitado $f"
        fi
    done
    if [ -d "$PREFIJO/opt/intactpdf" ]; then
        caso="$(basename "$(readlink -f "$PREFIJO/opt/intactpdf" 2>/dev/null)")"
        case "$caso" in
            intactpdf|"")
                [ "$SIMULAR" = "" ] && rm -rf "$PREFIJO/opt/intactpdf"
                hecho "quitado $PREFIJO/opt/intactpdf" ;;
            *)
                ojo "$PREFIJO/opt/intactpdf no es de este instalador: no lo toco" ;;
        esac
    fi
    quitar_del_perfil
    refrescar_caches
    printf '\n  Listo. Los paquetes del sistema (GTK y compañía) siguen puestos;\n'
    printf '  se quitan con el gestor de paquetes si no los quieres.\n\n'
}

# ─────────────────────────────── el programa ─────────────────────────────────

if [ "$SIMULAR" = "lista" ]; then
    printf '\n  Sistemas que se pueden simular: opensuse-leap, opensuse-tumbleweed,\n'
    printf '  fedora, debian, ubuntu, arch, alpine, void\n\n'
    exit 0
fi

if [ "$DESINSTALAR" = "1" ]; then
    detectar; desinstalar; exit 0
fi

titulo "$NOMBRE $VERSION_APP — instalador"

detectar
GLIBC="$(glibc_version)"
ARCH="$(uname -m)"
if [ "$SIMULAR" != "" ]; then
    GLIBC="2.38"; ARCH="x86_64"
    printf '    (simulando %s)\n' "$NOMBRE_OS"
fi

printf '\n  Sistema:  %s\n' "$NOMBRE_OS"
printf '  Familia:  %s\n' "${FAMILIA:-sin receta}"
printf '  glibc:    %s\n' "$GLIBC"
printf '  Arquitectura: %s\n' "$ARCH"

if [ "$FAMILIA" = "opensuse" ]; then
    if version_menor "$GLIBC" "2.28"; then
        ojo "glibc $GLIBC es anterior a 2.28: el AppImage no funcionará aquí."
        ojo "en openSUSE esto no pasa (Leap 15.6 trae 2.38 y Tumbleweed 2.44)."
    fi
fi

if [ "$SOLO_DEPS" = "1" ]; then
    PY_GTK="$(python_con_gtk || true)"
    # Al simular se finge que el sistema está limpio, salvo que se pida lo
    # contrario con --con-gtk. Si no, el resultado dependería de la máquina
    # donde se prueba el instalador y el simulador no probaría nada.
    if [ -n "$SIMULAR" ] && [ "${CON_GTK:-0}" != "1" ]; then PY_GTK=""; fi
    if [ -n "$PY_GTK" ]; then
        hecho "la pila de GTK ya está instalada"
        exit 0
    fi
    instalar_deps
    exit 0
fi

# ¿Quiere ventana o le basta la consola? Sin terminal (curl | sh) no se puede
# preguntar: se supone que quiere la ventana, que es lo que quiere todo el mundo.
PREFIERE_VENTANA=1
USAR_MENU=1
if [ -t 0 ] && [ "$AUTOINSTALAR" != "1" ]; then
    printf '\n  ¿Quieres la ventana o solo la consola?\n'
    printf '    [v] ventana (y consola)   [c] solo consola   [v] '
    read -r quiere || quiere="v"
    case "$quiere" in
        c|C|consola) PREFIERE_VENTANA=0; USAR_MENU=0 ;;
    esac
fi

elegir_metodo

printf '\n  Vía elegida: %s  (%s)\n' "$M" "$RAZON"
[ "${AVISO_SIN_VENTANA:-0}" = "1" ] && \
    ojo "aviso: esta vía instala la consola; la ventana necesita la vía Flatpak o pipx"

case "$M" in
    deps)
        instalar_deps
        M="pipx"
        printf '\n  Vía elegida: pipx  (ya está la pila de GTK)\n'
        instalar_pip
        ;;
    pipx)     instalar_pip ;;
    pip3)     instalar_pip ;;
    appimage)
        if [ -z "$APPIMAGE_DADO" ] && ! buscar_appimage_local >/dev/null 2>&1; then
            if [ -n "$BASE_URL" ]; then
                preparar_remoto || morir "no se pudo descargar el AppImage"
            else
                morir "no encuentro ningún AppImage al lado de este script.
    Pásale de dónde bajarlo con --base-url=URL (o la variable INTACTPDF_BASE)."
            fi
        fi
        instalar_appimage ;;
    flatpak)  instalar_flatpak ;;
esac

# ─────────────────────────── el PATH ────────────────────────────────────────
#
# pipx deja los dos comandos en `~/.local/bin`, que en muchas distribuciones no
# está en el PATH. El instalador ya lo avisaba, pero avisar no arregla nada: el
# primer mensaje de la primera instalación de verdad, en un Ubuntu 26.04, fue
# justo ese aviso, y quien lo lee no sabe si tiene que hacer algo. Ahora se
# ofrece arreglarlo, y con `--si` se hace.

MARCA_PATH="# IntactPDF: PATH añadido por su instalador"

arreglar_path() {
    case ":$PATH:" in
        *":$PREFIJO/bin:"*) return 0 ;;    # ya está: no hay nada que hacer
    esac
    [ -d "$PREFIJO/bin" ] || return 0      # si no hay comandos, qué vamos a añadir

    if [ -n "$SIMULAR" ]; then
        # Simular no toca NADA del sistema, y menos aún el fichero de arranque
        # del shell de quien lo ejecuta. Se dice lo que haría y se sigue.
        paso "añadiría $PREFIJO/bin al PATH (simulado, no se toca nada)"
        return 0
    fi

    # Con `--si` se hace sin preguntar: quien pide «instalar y ya» quiere que
    # funcione, no un aviso al final. Sin `--si`, se pregunta.
    if [ "$AUTOINSTALAR" != "1" ]; then
        printf '    %s/bin no está en el PATH. ¿Lo añado a %s? [s/N] ' \
            "$PREFIJO" "$HOME/.profile"
        read -r r || r="n"
        case "$r" in s|S|si|sí|y|Y) ;; *) ojo "no se toca el PATH; usa $PREFIJO/bin/intactpdf" ; return 0 ;; esac
    fi

    # Primero se le pide a pipx, que es quien sabe dónde pone las cosas y qué
    # ficheros de arranque usa cada shell. Sólo vale si el prefijo es el suyo:
    # `pipx ensurepath` añade siempre SU carpeta (~/.local/bin), así que con un
    # `--prefijo=` distinto escribiría la ruta equivocada.
    if hay pipx && [ "$PREFIJO" = "$HOME/.local" ]; then
        if pipx ensurepath ${PIPX_FUERZA:-} >/dev/null 2>&1; then
            hecho "$PREFIJO/bin añadido al PATH con «pipx ensurepath»"
            AVISO_PATH_NUEVO="$PREFIJO/bin"
            return 0
        fi
    fi

    # Y si no, se hace a mano en ~/.profile, que es el fichero que leen los
    # shells de entrada en casi todas las distribuciones. Con una marca, para
    # poder borrarlo desde `--desinstalar` y para no añadirlo dos veces.
    perfil="$HOME/.profile"
    # Ya está, venga de donde venga: puede haberlo puesto una ejecución anterior
    # de este instalador, o `pipx ensurepath` en la vía de pipx. Se busca la
    # CARPETA, no la marca, porque lo que importa es que quede en el PATH — y si
    # se añadiera otra vez, se sumarían líneas cada vez que alguien lo ejecute.
    if [ -f "$perfil" ] && grep -qF "$PREFIJO/bin" "$perfil" 2>/dev/null; then
        hecho "el PATH ya estaba configurado en $perfil"
        AVISO_PATH_NUEVO="$PREFIJO/bin"
        return 0
    fi
    {
        printf '\n%s\n' "$MARCA_PATH"
        # Las rutas de verdad, no `$HOME` a secas: el prefijo puede ser otro
        # (--prefijo=), y la primera versión escribía `$HOME/bin`, que no existe.
        printf 'case ":$PATH:" in\n'
        printf '    *":%s/bin:"*) ;;\n' "$PREFIJO"
        printf '    *) PATH="%s/bin:$PATH" ;;\n' "$PREFIJO"
        printf 'esac\nexport PATH\n'
    } >> "$perfil" || { ojo "no se pudo escribir en $perfil"; return 0; }
    hecho "$PREFIJO/bin añadido al PATH en $perfil"
    AVISO_PATH_NUEVO="$PREFIJO/bin"
}

AVISO_PATH_NUEVO=""
refrescar_caches
comprobar
# También la vía AppImage deja su lanzador en $PREFIJO/bin: sin PATH, el mismo
# problema con otro nombre.
case "$M" in pipx|pip3|appimage) arreglar_path ;; esac

titulo "Hecho"
case "$M" in
    flatpak)  printf '    Ventana:  flatpak run %s\n' "$ID_APP" ;;
    appimage) printf '    Consola:  %s/bin/intactpdf --help\n' "$PREFIJO"
              printf '    (el AppImage no trae la ventana; para eso, Flatpak o pipx)\n' ;;
    *)        printf '    Ventana:  %s/bin/intactpdf-gui\n' "$PREFIJO"
              printf '    Consola:  %s/bin/intactpdf doctor\n' "$PREFIJO"
              case ":$PATH:" in
                  *":$PREFIJO/bin:"*) ;;
                  *) if [ -n "$AVISO_PATH_NUEVO" ]; then
                         ojo "se ha añadido al PATH: abre un terminal nuevo (o ejecuta"
                         ojo "«. $HOME/.profile») para poder escribir «intactpdf» a secas"
                     else
                         ojo "$PREFIJO/bin no está en el PATH; añádelo o usa la ruta completa"
                     fi ;;
              esac ;;
esac
printf '\n'
