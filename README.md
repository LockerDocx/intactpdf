# IntactPDF

Editor de PDF para Linux que **no reconstruye el documento**.

Lo que hace distinto a LibreOffice Draw, Master PDF Editor y compañía: cuando
guardas, el fichero de salida **empieza por los bytes del original**. Los objetos
que cambian se añaden al final como actualización incremental (especificación
PDF, §7.5.6). Si el prefijo del fichero es idéntico al original, es imposible que
haya cambiado cualquier otra cosa.

Medido sobre un corpus de **12 PDFs** hechos para romper editores: **19
ediciones** (borrar un vector, mover y redimensionar una imagen CMYK, cambiar un
texto, escalar texto rotado) con **0 píxeles alterados fuera de la región
editada**, y la geometría de la página comprobada con **pdfium**, un motor que no
comparte ni una línea con este proyecto.

El mismo corpus **sin editar nada** pasa por LibreOffice Draw y cambia entre el
0,4 % y el 11,8 % de los píxeles de cada página, además de destruir CMYK, canales
alfa, formularios y dimensiones de página.

## Instalar

```bash
./instalar.sh
```

El instalador mira en qué distribución estás, elige la vía que mejor te viene y
lo deja puesto, con su entrada en el menú de aplicaciones. No hace falta saber
nada de antemano, y tampoco hace falta root: solo pide contraseña si tiene que
instalar la pila de GTK del sistema, y avisa antes de hacerlo.

```
  Sistema:  openSUSE Leap 15.6
  Familia:  opensuse
  glibc:    2.38
  Vía elegida: deps  (falta la pila de GTK y esta distribución tiene receta)
  → para la ventana hacen falta: python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1
  → pipx install --system-site-packages .
    ✓ la ventana puede abrirse: GTK 4.14, libadwaita 1.4, PyGObject 3.44
```

Opciones útiles: `--metodo=flatpak|pipx|appimage`, `--si` (sin preguntar),
`--solo-deps` (solo lo que falta para la ventana), `--desinstalar`, y
`--simular=opensuse-leap` para ver qué haría en otro sistema sin tenerlo delante.

### Con una línea, desde una URL

`instalar.sh` funciona **como fichero suelto**: se puede bajar de cualquier sitio
y ejecutar sin tener el proyecto al lado. Con `--base-url=` (o la variable
`INTACTPDF_BASE`) baja lo que necesita —el AppImage o el paquete de Python— y
**comprueba el sha256 contra `SHA256SUMS` antes de instalar**:

```bash
curl -sSL https://github.com/LockerDocx/intactpdf/releases/latest/download/instalar.sh | sh
curl -sSL https://github.com/LockerDocx/intactpdf/releases/latest/download/instalar.sh | sh -s -- --metodo=appimage
```

**No hace falta decirle de dónde descargar**: el script que se publica lleva
dentro su propia dirección (`BASE_URL_DEFECTO`), porque un script que llega por
una tubería no tiene forma de saber de dónde ha venido.

Si el fichero de sumas no está, o la suma no cuadra, **se para y no instala
nada**; `--sin-verificar` lo salta, pero hay que pedirlo. Las descargas quedan en
`~/.cache/intactpdf/descargas`, así que reintentar no vuelve a bajar 61 MB.

Esto está **probado de verdad** contra un servidor: publicación real a una
carpeta servida por HTTP, `curl | sh` **sin argumentos** desde ahí (AppImage
descargado, suma comprobada, instalado y `doctor` conforme), instalación por pipx
lo mismo, y una prueba con el fichero alterado a propósito que acabó en «la suma
NO cuadra» y cero instalaciones. Lo único que falta para que haya una URL pública
es **publicar**, y eso es una decisión de nombre y de cuenta:

```bash
python3 tools/comprobar_nombres.py            # ¿qué nombres están libres?
tools/publicar.sh --comprobar                 # ¿está todo listo para subir?
tools/publicar.sh --github=usuario/repo --si  # publicar y dar la URL
```

Ver [docs/distribucion.md](docs/distribucion.md) § «Publicar» para las cinco
trampas del `curl | sh`: `sh` sin variables locales, un `trap` que borraba la
descarga recién hecha, `sh -n` que valida sintaxis pero no lógica, que ejecutar el
script desde el repositorio **no** reproduce un `curl | sh`, y que la vía Flatpak
no podía funcionar así (mandaba a Flathub a por algo no publicado).

**Son dos programas y tres vías.** `intactpdf-gui` abre la ventana y `intactpdf` es
la consola; las dos entran en el mismo paquete.

| vía | trae la ventana | necesita root | funciona en |
|---|---|---|---|
| **Flatpak** | sí | no | cualquier distribución |
| **pipx** | sí | solo para instalar GTK si falta | cualquiera con Python 3.9+ |
| **AppImage** | **no**, solo la consola | no | glibc 2.28 o posterior |

La vía AppImage no trae la ventana porque dentro de un AppImage habría que meter
la pila entera de GTK; para eso está el Flatpak, que ya la lleva. El instalador
lo dice claramente en vez de dejar al usuario con una ventana que no arranca.

### A mano

Flatpak, que es la vía que funciona en cualquier distribución (también en
openSUSE Leap 15.6 y Tumbleweed, que es lo que se preguntaba):

```bash
flatpak-builder --user --install --force-clean \
    build-dir packaging/io.github.lockerdocx.IntactPDF.json
flatpak run io.github.lockerdocx.IntactPDF                              # la ventana
flatpak run --command=intactpdf io.github.lockerdocx.IntactPDF doctor    # la consola
```

pipx, para quien no quiera un runtime entero. Necesita la pila de GTK del
sistema, y los nombres de los paquetes cambian de una distribución a otra:

```bash
# openSUSE
sudo zypper install python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1
# Debian, Ubuntu, Mint       sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
# Fedora, RHEL, Rocky        sudo dnf install python3-gobject gtk4 libadwaita
# Arch, Manjaro              sudo pacman -S python-gobject gtk4 libadwaita

pipx install --system-site-packages .
intactpdf-gui
```

`--system-site-packages` **no es opcional**: PyGObject va atado a las
bibliotecas de GTK de la distribución y no se puede instalar con pip, así que
sin ese flag el entorno de pipx ve el paquete pero no ve PyGObject. El resultado
es lo peor posible: una consola que funciona y una ventana que dice «no está
instalado PyGObject» cuando sí lo está.

`pip install --user .` solo vale en distribuciones que lo permitan: Debian 12,
Ubuntu 23.04 y posteriores se niegan con «externally-managed-environment». Ahí la
vía es pipx, y el instalador lo dice si te pasa.

### AppImage (sin instalar nada, solo consola)

```bash
packaging/appimage/construir.sh
dist/IntactPDF-0.1.0-x86_64.AppImage doctor
```

61 MB, probado. Hereda la glibc 2.28 que exige pikepdf: RHEL/Rocky 8+, Debian
10+, Ubuntu 20.04+, openSUSE Leap 15.6 (2.38) y Tumbleweed (2.44). Para glibc más
antigua, la vía es Flatpak.

## Usar

### La ventana

```bash
intactpdf-gui                     # o `flatpak run io.github.lockerdocx.IntactPDF`
intactpdf-gui factura.pdf         # abre un fichero directamente
```

![La cinta de opciones](docs/capturas/01-recien-abierto.png)

Arriba hay una **cinta con todas las opciones**, agrupadas por para qué sirven,
en cinco pestañas: **Inicio** (lo de todos los días), **Objeto** (mover, escalar,
borrar), **Texto** (editar la tipografía que ya hay), **Página** (navegar y ver
las medidas) y **Ver** (zoom y paneles).

Dos cosas de la cinta que no son adorno:

- **lo que no aplica se apaga, no se esconde** — con una imagen seleccionada,
  «Editar texto» está apagado pero se ve, igual que en Word;
- **no hay ningún botón de algo que el programa no sepa hacer.** La cinta enseña
  las opciones que existen.

Con el ratón: se pincha un objeto para seleccionarlo (volver a pinchar en el
mismo sitio pasa al siguiente candidato), se arrastra para moverlo, doble clic
sobre una imagen o un vector para redimensionarlo y sobre un texto para
cambiarlo. Ctrl+O, Ctrl+S, Ctrl+Z, Ctrl+E y Supr. También se puede soltar un PDF
encima de la ventana.

Lo que se ve es lo que se guardaría: la vista previa se construye con las
ediciones pendientes, no con el fichero del disco.

Y no todo se hace desde la ventana: **Información, Fuentes y Comprobar** de la
pestaña Página son los mismos comandos de la consola (`info`, `fonts`, `check`),
no una copia. Si se arregla uno, se arreglan los dos.

### La consola

```bash
intactpdf doctor                          # ¿está todo listo?
intactpdf info factura.pdf                # qué hay dentro
intactpdf list factura.pdf                # objetos de la página, con índice
intactpdf fonts factura.pdf               # fuentes y qué admiten

# operar sobre el objeto 12
intactpdf delete factura.pdf --object 12 -o limpio.pdf
intactpdf move   factura.pdf --object 12 --dx 20 --dy -10 -o mueve.pdf
intactpdf scale  factura.pdf --object 12 --factor 1.5 -o grande.pdf
intactpdf edit   factura.pdf --object 3 --text "otra cosa" -o texto.pdf
intactpdf check  texto.pdf                # validar la salida
```

`--dry-run` dice qué haría sin escribir. Sin `-o`, hace falta `--in-place`, que
deja un `.bak`.

## Estado

Las cinco fases del MVP están implementadas y medidas (informes `01`–`07`).

| | |
|---|---|
| corpus | 12 PDFs, 16 páginas |
| tests unitarios | 103, 0 fallos |
| casos de aceptación | 19/19, 0 píxeles fuera, prefijo intacto 19/19 |
| geometría contra pdfium | 16/16 páginas |
| Flatpak | construido y probado dentro del sandbox, ventana incluida |
| AppImage | construido y probado |
| ventana GTK4 + libadwaita | funcionando, con cinta de opciones |
| instalador | `instalar.sh`: detecta la distribución, elige vía y **verifica las sumas** de lo que descarga |
| capturas | 10 en `docs/capturas/`, generadas por `tools/capturas_gui.py` |

**La ventana funciona y el paquete la abre.** Al pulsar el icono arranca
`intactpdf-gui`; la consola sigue dentro del mismo Flatpak y se alcanza con
`flatpak run --command=intactpdf io.github.lockerdocx.IntactPDF`.

Lo que falta para publicar en Flathub: elegir el nombre (los cinco candidatos ya
están comprobados contra PyPI, GitHub, Flathub y DNS — ver
[docs/distribucion.md](docs/distribucion.md) § «El nombre»), y `appstream` con
capturas servidas desde una URL.

Y lo que falta en el editor, por orden de importancia: guardar encima del
fichero original desde la ventana (ahora guarda copia), la compactación del
fichero (fase F5) y probarlo con PDFs reales, no solo con el corpus.

## Licencia

MIT o Apache-2.0, a elegir. El núcleo es propio: nada de MuPDF ni PyMuPDF, que
son AGPL.
