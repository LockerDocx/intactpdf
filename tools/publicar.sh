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
    hay curl || morir "hace falta curl, y no está"
    [ -n "${GITHUB_TOKEN:-}" ] || morir "hace falta un token de GitHub con permiso
    para crear versiones en $repo. Se pasa así:

        GITHUB_TOKEN=ghp_… $0 --github=$repo

    (Se crea en https://github.com/settings/tokens; basta con el permiso de
    repositorio. En un CI suele estar ya en la variable GITHUB_TOKEN.)"

    api="https://api.github.com/repos/$repo"
    cabeceras_auth="Authorization: Bearer $GITHUB_TOKEN"

    # 1. ¿Existe el repositorio y sirve el token? Sin esto, el fallo que se ve
    #    después («creando la versión») no dice cuál de las dos cosas falla.
    codigo="$(curl -sS -o /dev/null -w '%{http_code}' -H "$cabeceras_auth" \
        -H "Accept: application/vnd.github+json" "$api")"
    case "$codigo" in
        200) hecho "el repositorio $repo existe y el token sirve" ;;
        404) if [ "$SI" != "1" ]; then
                 printf '    El repositorio $repo no existe. ¿Lo creo público? [s/N] '
                 read -r r || r="n"
                 case "$r" in s|S|si|sí|y|Y) ;; *) morir "cancelado" ;; esac
             fi
             paso "creando el repositorio $repo"
             curl -sS -X POST -H "$cabeceras_auth" -H "Accept: application/vnd.github+json" \
                 https://api.github.com/user/repos \
                 -d "{\"name\":\"${repo#*/}\",\"description\":\"Editor de PDF para Linux que no reconstruye el documento.\",\"private\":false}" \
                 >/dev/null || morir "no se pudo crear el repositorio"
             hecho "repositorio creado" ;;
        401|403) morir "el token no vale para $repo (contesta $codigo)" ;;
        *) morir "no se pudo consultar $repo (contesta $codigo)" ;;
    esac

    # 2. La versión. Si ya existe, se reutiliza: publicar dos veces la misma
    #    versión es lo que pasa cuando hay que rehacer un AppImage, y no puede
    #    ser un error.
    etiqueta="v$VERSION"
    paso "preparando la versión $etiqueta"
    cuerpo="IntactPDF $VERSION.

## Instalar

    curl -sSL https://github.com/$repo/releases/latest/download/instalar.sh | sh

El instalador mira la distribución, elige la vía que mejor viene (Flatpak, pipx
o AppImage), **comprueba el sha256 de lo que descarga** y verifica al final que
el programa funciona. Las sumas están en \`SHA256SUMS\`.

En este zip va, además del instalador:

- \`IntactPDF-$VERSION-$ARQUITECTURA.AppImage\` — la consola, sin instalar nada
  (61 MB; la ventana necesita la vía Flatpak o pipx).
- \`intactpdf-$VERSION-py3-none-any.whl\` — el paquete de Python, para pipx o pip."
    json_cuerpo="$(python3 - "$etiqueta" "$cuerpo" <<'PYFIN'
import json, sys
print(json.dumps({"tag_name": sys.argv[1], "name": "IntactPDF " + sys.argv[1][1:],
                  "body": sys.argv[2], "draft": False, "prerelease": False}))
PYFIN
)"
    respuesta="$(curl -sS -X POST -H "$cabeceras_auth" -H "Accept: application/vnd.github+json" \
        "$api/releases" -d "$json_cuerpo")"
    id_version="$(printf '%s' "$respuesta" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null)"
    if [ -z "$id_version" ]; then
        # 422 = ya existe esa etiqueta. Entonces se reutiliza su id.
        id_version="$(curl -sS -H "$cabeceras_auth" -H "Accept: application/vnd.github+json" \
            "$api/releases/tags/$etiqueta" |
            python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null)"
        [ -n "$id_version" ] || morir "no se pudo crear ni encontrar la versión $etiqueta"
        hecho "la versión $etiqueta ya existía: se actualizan sus ficheros"
    else
        hecho "versión $etiqueta creada"
    fi

    # 3. Los ficheros. Se borra el que ya estuviera con el mismo nombre (GitHub
    #    no permite subir dos veces el mismo nombre) y se sube el nuevo.
    for f in "$PUBLICO"/*.AppImage "$PUBLICO"/*.whl "$PUBLICO/instalar.sh" \
             "$PUBLICO/SHA256SUMS"; do
        [ -f "$f" ] || continue
        nombre="$(basename "$f")"
        [ "$SIMULAR" = "1" ] && { echo "    (simulado) subiría $nombre"; continue; }
        id_viejo="$(curl -sS -H "$cabeceras_auth" -H "Accept: application/vnd.github+json" \
            "$api/releases/$id_version/assets" |
            python3 -c "
import json, sys
for a in json.load(sys.stdin):
    if a['name'] == '$nombre': print(a['id']); break
" 2>/dev/null)"
        if [ -n "$id_viejo" ]; then
            curl -sS -X DELETE -H "$cabeceras_auth" \
                "https://api.github.com/repos/$repo/releases/assets/$id_viejo" >/dev/null
        fi
        printf '    subiendo %s (%s)… ' "$nombre" "$(du -h "$f" | cut -f1)"
        curl -sS -X POST -H "$cabeceras_auth" -H "Content-Type: application/octet-stream" \
            --data-binary "@$f" \
            "https://uploads.github.com/repos/$repo/releases/$id_version/assets?name=$nombre" \
            >/dev/null || morir "falló la subida de $nombre"
        echo "hecho"
    done

    base="https://github.com/$repo/releases/latest/download"
    printf '\n    Publicado. Para instalar:\n\n      curl -sSL %s/instalar.sh | sh\n\n' "$base"
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
