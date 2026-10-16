# Empaquetado

Aquí está todo lo necesario para que IntactPDF llegue a un equipo donde no
hay Python, ni pip, ni nada instalado. El documento que explica las decisiones es
[`../docs/distribucion.md`](../docs/distribucion.md); esto es el manual de
mantenimiento.

**Para instalar en el equipo de alguien, el punto de entrada es
[`../instalar.sh`](../instalar.sh)**, no esta carpeta: mira la distribución,
elige vía y lo deja puesto. Lo de aquí es lo que usa el instalador y lo que hay
que mantener cuando suben de versión las dependencias.

## Qué hay

```
packaging/
├── io.github.lockerdocx.IntactPDF.json          el manifiesto de Flatpak
├── python3-deps.json                 los wheels con URL y sha256 (GENERADO)
├── generar_deps_pip.py               lo genera
├── io.github.lockerdocx.IntactPDF.desktop       lanzador de la ventana (el del icono)
├── io.github.lockerdocx.IntactPDF.cli.desktop   lanzador de la consola
├── io.github.lockerdocx.IntactPDF.metainfo.xml  metadatos para las tiendas
├── icons/io.github.lockerdocx.IntactPDF.svg     icono
└── appimage/construir.sh             construye el AppImage
```

## Flatpak

```bash
flatpak-builder --user --install --force-clean --disable-rofiles-fuse \
    build-dir packaging/io.github.lockerdocx.IntactPDF.json
flatpak run io.github.lockerdocx.IntactPDF                            # la ventana
flatpak run --command=intactpdf io.github.lockerdocx.IntactPDF doctor  # la consola
```

`--disable-rofiles-fuse` es para contenedores de construcción donde no hay FUSE.
En un equipo normal no hace falta.

### Cuando suban de versión las dependencias

Los wheels están fijados con URL y sha256 en `python3-deps.json`, que es
**generado**. No se edita a mano:

```bash
python3 packaging/generar_deps_pip.py
```

El script descarga los wheels, pregunta a PyPI sus URLs y recalcula los hashes.
Un manifiesto de Flatpak no puede descargar nada durante la construcción, así que
esos hashes son la única garantía de que se construye con lo mismo que se probó.

Si hay que subir de versión, se cambian las constantes del principio de
`generar_deps_pip.py` y se regenera.

### Dos cosas que ya costaron un rato

**El runtime trae Python 3.14.** `org.gnome.Platform//51` va sobre Freedesktop
SDK 26.08 y su Python es el 3.14. Las wheels `cp313` no valen. Si el manifiesto
falla con «no matching distribution found» al instalar dependencias, es esto.

**Los permisos de fichero no se suman como uno espera.** Con
`--filesystem=home:ro` más `--filesystem=xdg-documents`, **no** se puede escribir
en Documentos: el permiso de solo lectura sobre el directorio padre anula el
específico, y al guardar salta «Read-only file system». Se comprobó a mano. Por
eso no hay una versión «estrecha» hecha de carpetas sueltas: o el portal, o
`home` entero.

**El manifiesto no pide `home`.** El acceso lo concede el portal de ficheros a
través del diálogo de la ventana, documento a documento. Consecuencia que hay que
tener presente: **dentro del Flatpak, la consola solo funciona sobre ficheros del
propio sandbox**. Para usarla sobre los del anfitrión, o un portal presente
(`flatpak run --command=intactpdf --file-forwarding io.github.lockerdocx.IntactPDF @@ x.pdf @@ list`)
o el permiso a mano en esa máquina
(`flatpak override --user --filesystem=home io.github.lockerdocx.IntactPDF`). En un
contenedor de pruebas sin portal, quitando el permiso la consola contesta «no
existe el fichero»; es correcto y es exactamente lo que se ve.

### Antes de enviarlo a Flathub

- [ ] Cambiar el identificador `io.github.lockerdocx.IntactPDF` por el definitivo (tiene que
      estar bajo un dominio o un repositorio de GitHub que controles).
- [ ] Cambiar las URL `example.invalid` del `metainfo.xml` y del `pyproject.toml`.
- [ ] Añadir capturas de pantalla al `metainfo.xml`. Ya están hechas (diez, en
      `../docs/capturas/`, generadas con `tools/capturas_gui.py`), pero AppStream
      no acepta ficheros locales: hay que servirlas desde una URL.
- [ ] Poner el `developer id` del `metainfo.xml` (obligatorio en Flathub): es el
      dominio o el usuario de GitHub de quien publica, o sea el mismo dato
      pendiente del identificador.
- [ ] Pasar `appstreamcli validate` sobre el metainfo. (Ya pasa; queda el
      `developer-id`, que es el mismo dato que el identificador.)
- [ ] Quitar las tres comprobaciones pendientes de la lista: que `flatpak-builder`
      construya limpio en un contenedor recién creado.

## AppImage

```bash
packaging/appimage/construir.sh
# -> dist/IntactPDF-0.1.0-x86_64.AppImage
```

Descarga un Python portátil, instala dentro la aplicación y sus dependencias,
mete las fuentes DejaVu y empaqueta. Tarda medio minuto.

Dos detalles que no son opcionales aunque lo parezcan: el script de consola que
genera pip lleva un shebang con la ruta absoluta del intérprete de construcción,
que dentro del AppImage no existe (el AppRun falla con un «not found» que
desconcierta porque el fichero sí está); y `appimagetool` se ejecuta con
`--appimage-extract-and-run` porque en un contenedor no hay FUSE.

**Un AppImage no arregla el problema de glibc.** Hereda la glibc 2.28 que exige
pikepdf: funciona en RHEL/Rocky 8+, Debian 10+ y Ubuntu 20.04+, y no en CentOS 7
ni Debian 9. Está explicado en `docs/distribucion.md`.

## Comprobar un paquete antes de publicarlo

```bash
# ¿arranca la ventana?
flatpak run io.github.lockerdocx.IntactPDF            # sin argumentos: pantalla de inicio
flatpak run io.github.lockerdocx.IntactPDF x.pdf      # con un fichero (mira los permisos)

# ¿arranca la consola y encuentra todo?
flatpak run --command=intactpdf io.github.lockerdocx.IntactPDF doctor
dist/IntactPDF-0.1.0-x86_64.AppImage doctor

# ¿edita de verdad, dentro del sandbox?
# (con el permiso home, o con --file-forwarding si hay portal)
cd ~/Documents && cp /ruta/a/corpus/02_fuente_subset.pdf .
flatpak run --command=intactpdf io.github.lockerdocx.IntactPDF edit 02_fuente_subset.pdf \
    --object 0 --text "Letras con acento: ó, í, ñ y €." -o fuera.pdf
flatpak run --command=intactpdf io.github.lockerdocx.IntactPDF check fuera.pdf
```

Los dos últimos pasos son los que importan. El primero, porque la ventana sin
argumentos es lo que ve quien pulsa el icono, y un fallo ahí no se descubre
usando la consola. El segundo, porque escribe un carácter que **no** está en el
subconjunto de la fuente incrustada y obliga a incrustar un subconjunto nuevo
desde una fuente del sistema: si las fuentes no viajan dentro del paquete, esto
falla en Flatpak y funciona fuera de él.

Para comprobar la ventana sin escritorio (en un contenedor, en un CI) hay un modo
de captura que no necesita ni servidor X de verdad:

```bash
Xvfb :99 -screen 0 1400x950x24 &
DISPLAY=:99 /usr/bin/python3 -m gui.ventana corpus/05_cmyk_imprenta.pdf \
    --captura /tmp/ventana.png
```

Ojo con el intérprete: la ventana necesita **PyGObject**, que en Debian y Ubuntu
está instalado para `/usr/bin/python3` y no para el `python3` que instala pip.
Dentro del Flatpak ese problema no existe.
