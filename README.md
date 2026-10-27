# IntactPDF

Editor estructural de PDF para Linux diseñado para modificar elementos existentes sin reconstruir el documento.

## El problema con los editores tradicionales

Cuando abres un PDF en LibreOffice Draw, Inkscape u otras herramientas convencionales y guardas, el archivo completo se reconstruye desde cero:

- Se recalculan y rescriben los flujos de contenido de todas las páginas.
- Se convierten o aplanan espacios de color CMYK y perfiles de imprenta a RGB.
- Se descartan metadatos, formularios AcroForm, firmas electrónicas y capas de contenido opcional (OCG).
- Las fuentes incrustadas se sustituyen o desajustan en su espaciado métrico.
- En pruebas con un corpus de control de 12 documentos reales, abrir y guardar un PDF sin realizar ninguna modificación en LibreOffice Draw altera entre el 0,4 % y el 11,8 % de los píxeles de cada página.

## Principio de diseño: actualización incremental

IntactPDF implementa el mecanismo estándar de actualización incremental (ISO 32000-1, §7.5.6):

1. **Prefijo idéntico:** El archivo resultante conserva exactamente los mismos bytes originales al inicio. Las modificaciones y los nuevos objetos se indexan al final en una tabla de referencias cruzadas (`xref`) y un nuevo `trailer`. Si el prefijo binario no cambia, el resto del documento original permanece matemáticamente inalterado.
2. **Verificación visual:** Antes de confirmar el guardado, un motor independiente (`pdfium`) renderiza la página resultante y comprueba que el contenido sigue visible y que ningún píxel fuera de la región seleccionada ha cambiado.
3. **Escritura atómica y respaldos:** Las operaciones de guardado sobre el archivo original utilizan una fase intermedia temporal (`staging`) y generan automáticamente una copia de respaldo (`archivo.pdf~`).

## Capturas de la interfaz

La interfaz gráfica utiliza GTK4 y Libadwaita, organizada mediante una cinta de opciones contextual que adapta sus controles según el tipo de elemento seleccionado.

| Vista inicial e inspección de objetos | Selección y cuadro delimitador |
| :---: | :---: |
| ![Vista inicial](docs/capturas/01-recien-abierto.png) | ![Selección](docs/capturas/02-seleccion.png) |

| Pestaña Objeto (Mover, Escalar, Sustituir imagen) | Pestaña Texto (Edición con ajuste tipográfico) |
| :---: | :---: |
| ![Cinta Objeto](docs/capturas/06-cinta-objeto.png) | ![Cinta Texto](docs/capturas/07-cinta-texto.png) |

| Pestaña Página (Rotación incremental) | Previsualización de texto modificado |
| :---: | :---: |
| ![Cinta Página](docs/capturas/08-cinta-pagina.png) | ![Texto modificado](docs/capturas/04-texto-cambiado.png) |

## Funcionalidades principales

### Edición e inserción tipográfica
- Sustitución directa de bytes cuando la longitud y la codificación coinciden con la original.
- Segmentación tipográfica precisa de sub-bloques de texto: cuando dos palabras contiguas usan tipografías, fuentes o tamaños distintos dentro de un mismo bloque, se tratan como objetos independientes preservando intacta la fuente y métrica de cada una.
- Inserción de nuevo texto (`add-text`): añade nuevas líneas de texto en coordenadas exactas incrustando subconjuntos limpios de fuentes del sistema de forma incremental.
- Compensación métrica de espaciado (`Tc`) opcional para textos con variaciones de longitud, evitando desbordamientos de bloque.

### Manipulación e inserción de imágenes
- Inserción de nueva imagen (`add-image`): inserta una nueva imagen externa (PNG, JPEG, WebP) en coordenadas y dimensiones exactas con soporte de canal alfa y máscara `/SMask` ISO 32000.
- Sustitución de imagen (`replace-image`): reemplaza un XObject de imagen existente por un nuevo archivo, conservando la posición, matriz de transformación y dimensiones del elemento original.
- Extracción de imagen (`extract-image`): si la imagen está codificada como JPEG (`/DCTDecode`), extrae directamente el flujo binario original sin decodificar ni recomprimir; para el resto de formatos, exporta a PNG sin pérdidas.

### Transformaciones geométricas y estructura
- Desplazamiento de objetos mediante coordenadas numéricas en puntos tipográficos (`pt`) o arrastre interactivo con el ratón.
- Escalado proporcional preservando el estado gráfico del resto de la página.
- Rotación de páginas (`rotate`): giro puntual en 90°, 180° o 270° modificando exclusivamente la entrada `/Rotate` del diccionario de página en la revisión incremental y acumulando rotaciones heredadas desde nodos padre `/Pages`.
- Eliminación de operadores en el flujo de contenido sin alterar los offsets del resto del archivo.

### Seguridad y revisión
- Alerta de firmas digitales: advertencia visual preventiva si el documento contiene estructuras de firma electrónica (`/Sig`, `/ByteRange`, `/AcroForm`), avisando de que cualquier modificación puede invalidar las firmas existentes.
- Purga de revisiones (`compact`): al ser un guardado incremental, los elementos borrados continúan residiendo en las revisiones anteriores del binario. El comando `compact` purga el historial previo y reescribe solo los objetos activos en un archivo limpio.
- Descifrado (`decrypt`): remueve el cifrado en documentos protegidos con contraseña de lectura conocida antes de la edición.

### Ergonomía y atajos
- Zoom continuo mediante `Ctrl + Rueda del ratón` y atajos directos (`Ctrl++`, `Ctrl+-`, `Ctrl+0`).
- Copia directa al portapapeles del texto del objeto seleccionado (`Ctrl+C`).
- Historial completo de Deshacer (`Ctrl+Z`) y Rehacer (`Ctrl+Shift+Z` / `Ctrl+Y`).

## Instalación

### Método 1: Instalador automático

```bash
./instalar.sh
```

El script analiza la distribución Linux, comprueba las dependencias del sistema y configura la integración en el escritorio.

### Método 2: Instalación de usuario sin permisos de root

En distribuciones como openSUSE, Fedora, Debian, Ubuntu o Arch Linux, puedes instalarlo en tu directorio personal sin privilegios de administrador:

```bash
# 1. Crear entorno virtual de usuario con acceso a librerías del sistema
python3 -m venv ~/.local/share/intactpdf-env --system-site-packages

# 2. Instalar el paquete en modo editable
~/.local/share/intactpdf-env/bin/pip install -e .

# 3. Configurar el PATH (si no está incluido)
echo 'export PATH="$HOME/.local/share/intactpdf-env/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# 4. Ejecutar
intactpdf-gui            # Interfaz gráfica
intactpdf info doc.pdf   # Línea de comandos
```

Para la interfaz gráfica se requieren las bibliotecas GTK4 del sistema (`python3-gobject`, `typelib-1_0-Gtk-4_0`, `typelib-1_0-Adw-1`). La herramienta de terminal (`intactpdf`) es plenamente funcional en sistemas sin entorno gráfico.

### Método 3: Paquete Flatpak

```bash
flatpak-builder --user --install --force-clean build-dir packaging/io.github.lockerdocx.IntactPDF.json
flatpak run io.github.lockerdocx.IntactPDF
```

## Uso por línea de comandos (CLI)

IntactPDF incluye una interfaz de terminal pensada para automatización y entornos de servidor:

```bash
# Inspección y diagnóstico
intactpdf tutorial                                         # Guía interactiva paso a paso
intactpdf doctor                                           # Comprobar dependencias y entorno
intactpdf info documento.pdf                               # Metadatos, revisiones y firmas
intactpdf list documento.pdf --pagina 0                    # Listar objetos y coordenadas

# Inserción de texto e imágenes
intactpdf add-text doc.pdf --texto "Nota añadida" --x 100 --y 500 --tamano 14 -o salida.pdf
intactpdf add-image doc.pdf --imagen firma.png --x 150 --y 200 --ancho 120 --alto 60 -o salida.pdf

# Manipulación de imágenes
intactpdf replace-image doc.pdf --xobject Im1 --imagen logo.png -o salida.pdf
intactpdf extract-image doc.pdf --xobject Im1 -o logo_extraido.png

# Rotación y transformaciones
intactpdf rotate doc.pdf --pagina 0 --angulo 90 -o rotado.pdf
intactpdf move doc.pdf --object 3 --dx 15 --dy -10 -o movido.pdf
intactpdf scale doc.pdf --object 3 --factor 1.15 -o escalado.pdf
intactpdf delete doc.pdf --object 5 -o limpio.pdf

# Edición de texto
intactpdf edit doc.pdf --object 2 --text "Texto actualizado" -o editado.pdf

# Modificación sobre el archivo original (con copia de respaldo .pdf~)
intactpdf edit doc.pdf --object 2 --text "Texto actualizado" --in-place

# Compactación y descifrado
intactpdf compact editado.pdf -o compactado.pdf            # Purgar revisiones anteriores
intactpdf decrypt cifrado.pdf -p "contraseña" -o libre.pdf # Remover protección de lectura
intactpdf check salida.pdf                                 # Validar estructura y renderizado
```

## Validación y pruebas

La suite de pruebas valida tanto la lógica interna como la preservación visual y matemática del documento:

```bash
# Pruebas unitarias e integración
pytest tests/ -v

# Validación visual sobre el corpus de prueba
python3 tools/test_aceptacion.py
```

Resultados de la suite:
- 123 pruebas unitarias aprobadas (0 fallos, 4 omitidas correspondientes a artefactos de empaquetado release).
- 19 de 19 casos de aceptación visual superados: 0 píxeles alterados fuera del área seleccionada.
- Verificación de prefijo binario idéntico en las 19 operaciones del corpus de control.

## Estructura del proyecto

- `nucleo/`: motor de parseo, cálculo geométrico, manejo tipográfico y guardado incremental.
- `gui/`: interfaz gráfica en GTK4 y Libadwaita (cinta de opciones, vista previa y lienzo).
- `corpus/`: conjunto de documentos PDF de prueba diseñados para validar casos límite de edición.
- `packaging/`: manifiestos para Flatpak, AppImage y archivos `.desktop` de integración.
- `tests/`: suite de pruebas automatizadas unitarias, de integración y fidelidad visual.
- `tools/`: utilidades para generación del corpus, inspección de streams y benchmarks.

## Autoría y Licencia

**Autor y creador original:** [Gerard Morales](https://github.com/LockerDocx)  
**Proyecto original oficial:** [https://github.com/LockerDocx/intactpdf](https://github.com/LockerDocx/intactpdf)

Este software es código abierto distribuido bajo la licencia **GNU Affero General Public License v3.0 (AGPL-3.0-or-later)**. Consulta el archivo [LICENSE](LICENSE) para conocer el texto íntegro y oficial de la licencia.

### Términos de uso y atribución:
- Todo trabajo derivado, adaptación, despliegue o servicio de red que incorpore este código debe mantener de forma obligatoria y visible la atribución al autor original (**Gerard Morales**) y el enlace al repositorio oficial (**LockerDocx/intactpdf**).
- El nombre del proyecto, marcas asociadas e identidad visual pertenecen a su autor original y no pueden ser utilizados con fines comerciales o de confusión pública sin autorización previa expresa.
- Si utilizas o referencias este proyecto, enlaza siempre a la fuente oficial autorizada.
