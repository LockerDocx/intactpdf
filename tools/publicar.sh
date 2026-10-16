#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
#  IntactPDF — publicar una versión
#
#  Sube el instalador, el AppImage, el paquete de Python y el fichero de sumas
#  al sitio desde el que se instala con una línea:
#
#      curl -sSL https://…/instalar.sh | sh
#
#  Uso:
#
#      tools/publicar.sh --comprobar                  ¿está todo listo?
#      tools/publicar.sh --github=usuario/repo        publicar en GitHub
#      tools/publicar.sh --servidor=user@host:/var/www/intactpdf
#      tools/publicar.sh --base-url=https://… --simular
#
#  Antes de subir nada hace tres comprobaciones que evitan publicar una versión
#  rota: que los artefactos existan, que el sha256 del fichero de sumas cuadre
#  con lo que hay, y que el instalador DENTRO del fichero de sumas sea el mismo
#  que se va a subir. Publicar un instalador y un fichero de sumas que no se
#  corresponden deja a todo el mundo con un error de suma que no puede
#  entender.
# ─────────────────────────────────────────────────────────────────────────────
set -eu
LC_ALL=C
export LC_ALL

VERSION="0.1.0"
ARQUITECTURA="$(uname -m)"
AQUI="$(cd "$(dirname "$0")/.." && pwd)"
PUBLICO="$AQUI/dist/publico"

MODO=""
DESTINO=""
BASE_URL=""
SIMULAR=0
SI=0
URL_CONOCIDA=""     # la dirección definitiva, que se escribe DENTRO del script

titulo() { printf '\n\033[1m%s\033[0m\n' "$*"; }
paso()   { printf '  → %s\n' "$*"; }
hecho()  { printf '    \033[32m✓\033[0m %s\n' "$*"; }
ojo()    { printf '    \033[33m!\033[0m %s\n' "$*"; }
malo()   { printf '    \033[31m✗\033[0m %s\n' "$*" >&2; }
morir()  { malo "$*"; exit 1; }

ayuda() {
    cat <<'FIN'
Publicar IntactPDF para que se instale con `curl | sh`

Opciones:
  --comprobar                        solo mirar si está todo listo
  --github=USUARIO/REPO              publicar como "release" en GitHub
  --servidor=DESTINO                 copiar por rsync/scp (user@host:/ruta)
  --base-url=URL                     dónde quedará publicado (para dejar
                                     constancia y para --simular)
  --simular                          no subir nada; decir qué haría
  --si                                no preguntar
  -h, --help                        esto

Ejemplos:
  tools/publicar.sh --comprobar
  tools/publicar.sh --github=intactpdf/studio --si
  tools/publicar.sh --servidor=yo@mi-servidor:/var/www/intactpdf --si
FIN
}

for arg in "$@"; do
    case "$arg" in
        --comprobar)   MODO="comprobar" ;;
        --github=*)    MODO="github"; DESTINO="${arg#*=}" ;;
        --servidor=*)  MODO="servidor"; DESTINO="${arg#*=}" ;;
        --base-url=*)  BASE_URL="${arg#*=}" ;;
        --simular)     SIMULAR=1 ;;
        --si|-y)       SI=1 ;;
        -h|--help)     ayuda; exit 0 ;;
        *)             morir "opción desconocida: $arg  (prueba con --help)" ;;
    esac
done

hay() { command -v "$1" >/dev/null 2>&1; }

case "$MODO" in
    github)   URL_CONOCIDA="https://github.com/$DESTINO/releases/latest/download" ;;
    servidor) URL_CONOCIDA="$BASE_URL" ;;
    *)        URL_CONOCIDA="$BASE_URL" ;;
esac

# ─────────────────────── preparar el directorio público ─────────────────────

preparar() {
    titulo "Preparando lo que se publica"
    mkdir -p "$PUBLICO"

    paso "construyendo el paquete de Python"
    if [ "$SIMULAR" = "1" ]; then
        echo "    (simulado)"
    else
        rm -f "$PUBLICO"/*.whl
        ( cd "$AQUI" && python3 -m pip wheel --quiet --no-deps \
            --no-build-isolation -w "$PUBLICO" . ) ||
            morir "no se pudo construir el paquete"
        # El nombre lo fija quien consume: el instalador busca exactamente este.
        rueda="$(ls "$PUBLICO"/*.whl 2>/dev/null | head -1)"
        [ -n "$rueda" ] || morir "no se generó ninguna rueda"
        [ "$(basename "$rueda")" = "intactpdf-$VERSION-py3-none-any.whl" ] ||
            mv "$rueda" "$PUBLICO/intactpdf-$VERSION-py3-none-any.whl"
    fi
    hecho "intactpdf-$VERSION-py3-none-any.whl"

    appimage="$AQUI/dist/IntactPDF-$VERSION-$ARQUITECTURA.AppImage"
    if [ -f "$appimage" ]; then
        cp -f "$appimage" "$PUBLICO/" 2>/dev/null || true
        hecho "$(basename "$appimage")"
    else
        ojo "no encuentro $appimage: construye el AppImage con"
        ojo "packaging/appimage/construir.sh (la vía AppImage no se publicará)"
    fi

    # El instalador se publica **con su propia dirección dentro**, en
    # BASE_URL_DEFECTO. De eso depende que el «curl | sh» funcione sin
    # argumentos: el script no puede saber de dónde lo han bajado, así que se lo
    # tiene que decir quien publica. Es la única diferencia entre el fichero del
    # repositorio y el que se sube, y comprobar() lo verifica línea a línea.
    if [ -n "$URL_CONOCIDA" ] && [ "$SIMULAR" = "0" ]; then
        sed "s|^BASE_URL_DEFECTO=.*|BASE_URL_DEFECTO=\"$URL_CONOCIDA\"|" \
            "$AQUI/instalar.sh" > "$PUBLICO/instalar.sh"
        grep -q "^BASE_URL_DEFECTO=\"$URL_CONOCIDA\"" "$PUBLICO/instalar.sh" ||
            morir "no se pudo escribir la dirección dentro de instalar.sh"
        hecho "instalar.sh (con la dirección $URL_CONOCIDA dentro)"
    elif [ -n "$URL_CONOCIDA" ]; then
        # Simulando NO se escribe: dejar una dirección fingida dentro del
        # fichero que se va a publicar es exactamente el fallo que este script
        # tiene que evitar, y ya se dio una vez (con la dirección de prueba
        # dentro, las sumas dejaron de cuadrar y la publicación se paró sola).
        cp -f "$AQUI/instalar.sh" "$PUBLICO/instalar.sh"
        hecho "instalar.sh"
        ojo "simulado: le escribiría dentro la dirección $URL_CONOCIDA"
    else
        cp -f "$AQUI/instalar.sh" "$PUBLICO/instalar.sh"
        hecho "instalar.sh"
        ojo "sin dirección por defecto: quien haga «curl | sh» tendrá que pasar"
        ojo "--base-url=URL o INTACTPDF_BASE (o publicar con --github/--servidor)"
    fi

    paso "calculando las sumas"
    if [ "$SIMULAR" = "0" ]; then
        ( cd "$PUBLICO" && sha256sum *.AppImage *.whl instalar.sh > SHA256SUMS )
    else
        echo "    (simulado)"
    fi
    hecho "SHA256SUMS"
}

comprobar() {
    titulo "Comprobando que se puede publicar"
    fallos=0

    [ -f "$PUBLICO/instalar.sh" ] || { malo "falta instalar.sh"; fallos=$((fallos+1)); }
    [ -f "$PUBLICO/SHA256SUMS" ] || { malo "falta SHA256SUMS"; fallos=$((fallos+1)); }
    [ -f "$PUBLICO/intactpdf-$VERSION-py3-none-any.whl" ] ||
        { malo "falta el paquete de Python"; fallos=$((fallos+1)); }
    if [ ! -f "$PUBLICO/IntactPDF-$VERSION-$ARQUITECTURA.AppImage" ]; then
        ojo "falta el AppImage (la vía AppImage no funcionará)"
    fi

    if [ -f "$PUBLICO/SHA256SUMS" ]; then
        paso "recalculando las sumas y comparando"
        if ( cd "$PUBLICO" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ); then
            hecho "las sumas cuadran con los ficheros"
        else
            malo "el fichero de sumas NO cuadra con lo que hay en $PUBLICO"
            ( cd "$PUBLICO" && sha256sum -c SHA256SUMS 2>&1 | grep -v ': OK' | head -5 )
            fallos=$((fallos+1))
        fi
    fi

    # Que la suma de instalar.sh sea la del fichero que se va a subir: es el que
    # ejecuta la gente, y el único que se puede comparar contra el que se probó.
    if [ -f "$PUBLICO/instalar.sh" ] && [ -f "$AQUI/instalar.sh" ]; then
        a="$(mktemp)"; b="$(mktemp)"
        sed '/^BASE_URL_DEFECTO=/d' "$AQUI/instalar.sh" > "$a"
        sed '/^BASE_URL_DEFECTO=/d' "$PUBLICO/instalar.sh" > "$b"
        if cmp -s "$a" "$b"; then
            hecho "el instalar.sh publicado es el del repositorio, salvo la dirección"
        else
            malo "el instalar.sh publicado NO es el del repositorio"
            diff "$a" "$b" | head -5
            fallos=$((fallos+1))
        fi
        rm -f "$a" "$b"
        # Y que la dirección que lleva dentro sea la buena, no una de pruebas.
        lleva="$(sed -n 's/^BASE_URL_DEFECTO="\(.*\)"$/\1/p' "$PUBLICO/instalar.sh")"
        if [ "$SIMULAR" = "1" ]; then
            # Simulando no se escribe nada dentro, así que aquí sólo se informa.
            if [ -n "$URL_CONOCIDA" ]; then
                ojo "simulado: al publicar le escribiría dentro «$URL_CONOCIDA»"
            elif [ -z "$lleva" ]; then
                ojo "no lleva dirección por defecto: el «curl | sh» pedirá --base-url"
            fi
        elif [ -n "$URL_CONOCIDA" ]; then
            if [ "$lleva" = "$URL_CONOCIDA" ]; then
                hecho "lleva dentro la dirección $lleva"
            else
                malo "lleva dentro «$lleva» y debería llevar «$URL_CONOCIDA»"
                fallos=$((fallos+1))
            fi
        elif [ -n "$lleva" ]; then
            ojo "lleva dentro una dirección de otra publicación: «$lleva»"
            ojo "vuelve a publicar con --github/--servidor, o bórrala a mano"
        else
            ojo "no lleva dirección por defecto (el «curl | sh» pedirá --base-url)"
        fi
    fi

    paso "comprobando que el instalador funciona sin nada al lado"
    # La prueba que de verdad quita el miedo: se ejecuta el instalador como lo
    # haría un desconocido, desde un directorio vacío y sin el proyecto cerca.
    # Se le da la URL como se la dará el «curl | sh» de verdad: eso es lo que
    # hay que probar, porque desde una carpeta vacía el instalador no tiene el
    # código al lado y tiene que bajárselo.
    # Con el script COPIADO a la carpeta vacía, que es la única forma de
    # reproducir de verdad un «curl | sh»: el instalador localiza el proyecto a
    # partir de su propio fichero, así que ejecutarlo desde su ruta original
    # encuentra el proyecto aunque el directorio actual esté vacío.
    carpeta="$(mktemp -d)"
    cp "$PUBLICO/instalar.sh" "$carpeta/instalar.sh"
    # Se decide según lo que lleve DENTRO el fichero que se acaba de copiar, no
    # según lo que sepamos nosotros: en un simulacro no se le escribe dentro.
    si_lleva="$(sed -n 's/^BASE_URL_DEFECTO="\(.*\)"$/\1/p' "$carpeta/instalar.sh")"
    if [ -n "$si_lleva" ]; then
        entorno=""     # con la dirección dentro no hay que pasarle nada
    else
        entorno="INTACTPDF_BASE=https://ejemplo.invalid/intactpdf"
    fi
    if ( cd "$carpeta" && env $entorno sh ./instalar.sh --simular=opensuse-leap --si \
         >/dev/null 2>&1 ); then
        hecho "arranca y decide bien desde una carpeta vacía, sin el proyecto al lado"
    else
        malo "el instalador falla al ejecutarlo desde una carpeta vacía:"
        ( cd "$carpeta" && env $entorno sh ./instalar.sh --simular=opensuse-leap --si 2>&1 |
            tail -6 ) | sed 's/^/        /'
        fallos=$((fallos+1))
    fi
    rm -rf "$carpeta"

    echo
    if [ "$fallos" -eq 0 ]; then
        hecho "todo listo para publicar"
        return 0
    fi
    malo "$fallos problema(s): no se publica así"
    return 1
}

# ─────────────────────────────── subir ──────────────────────────────────────

subir_github() {
    repo="$DESTINO"
    hay gh || morir "hace falta la herramienta «gh» (GitHub CLI), y no está.
    Se instala con el gestor de paquetes de tu distribución, o desde
    https://cli.github.com. Después: gh auth login"

    paso "¿está autenticado gh?"
    gh auth status >/dev/null 2>&1 || morir "gh no está autenticado: ejecuta «gh auth login»"

    paso "¿existe el repositorio $repo?"
    if gh repo view "$repo" >/dev/null 2>&1; then
        hecho "ya existe"
    else
        if [ "$SI" != "1" ]; then
            printf '    No existe. ¿Lo creo público? [s/N] '
            read -r r || r="n"
            case "$r" in s|S|si|sí|y|Y) ;; *) morir "cancelado" ;; esac
        fi
        paso "creando $repo"
        gh repo create "$repo" --public \
            --description "Editor de PDF para Linux que no reconstruye el documento" ||
            morir "no se pudo crear el repositorio"
        hecho "repositorio creado"
    fi

    etiqueta="v$VERSION"
    paso "publicando la versión $etiqueta con los ficheros"
    ficheros=""
    for f in "$PUBLICO"/*.AppImage "$PUBLICO"/*.whl "$PUBLICO/instalar.sh" \
             "$PUBLICO/SHA256SUMS"; do
        [ -f "$f" ] && ficheros="$ficheros $f"
    done
    # shellcheck disable=SC2086
    gh release create "$etiqueta" $ficheros \
        --title "IntactPDF $VERSION" \
        --notes "Instalación: curl -sSL https://github.com/$repo/releases/latest/download/instalar.sh | sh" ||
        gh release upload "$etiqueta" $ficheros --clobber

    base="https://github.com/$repo/releases/latest/download"
    hecho "publicado en $base"
    printf '\n    Para instalar:\n\n      curl -sSL %s/instalar.sh | sh\n\n' "$base"
    return 0
}

subir_servidor() {
    destino="$DESTINO"
    hecho_rsync=0
    if hay rsync; then
        paso "rsync a $destino"
        [ "$SIMULAR" = "1" ] || rsync -av --delete "$PUBLICO/" "$destino/" ||
            morir "rsync falló"
        hecho_rsync=1
    elif hay scp; then
        paso "scp a $destino"
        [ "$SIMULAR" = "1" ] || scp "$PUBLICO"/* "$destino/" || morir "scp falló"
        hecho_rsync=1
    fi
    [ "$hecho_rsync" = "1" ] || morir "hace falta rsync o scp"
    if [ -n "$BASE_URL" ]; then
        printf '\n    Para instalar:\n\n      curl -sSL %s/instalar.sh | sh\n\n' "$BASE_URL"
    else
        printf '\n    Los ficheros están en %s; el «curl | sh» es:\n\n' "$destino"
        printf '      curl -sSL https://TU-DOMINIO/instalar.sh | sh\n\n'
    fi
}

# ─────────────────────────────── el programa ────────────────────────────────

case "$MODO" in
    comprobar)
        preparar
        comprobar
        ;;
    "")
        titulo "Qué se puede hacer"
        printf '    %s --comprobar                              ¿está todo listo?\n' "$0"
        printf '    %s --github=usuario/repo --si               publicar en GitHub\n' "$0"
        printf '    %s --servidor=user@host:/ruta --si          publicar por rsync\n\n' "$0"
        printf '    (ninguna opción sube nada: hay que decir a dónde)\n\n'
        ;;
    github)
        preparar
        comprobar || exit 1
        if [ "$SIMULAR" = "1" ]; then
            printf '\n  (simulado: no se sube nada)\n'
            printf '  El «curl | sh» quedaría así:\n\n'
            printf '    curl -sSL https://github.com/%s/releases/latest/download/instalar.sh | sh\n\n' "$DESTINO"
            exit 0
        fi
        subir_github
        ;;
    servidor)
        preparar
        comprobar || exit 1
        subir_servidor
        ;;
esac
