# IntactPDF

[![CI](https://github.com/LockerDocx/intactpdf/actions/workflows/ci.yml/badge.svg)](https://github.com/LockerDocx/intactpdf/actions)
[![License: MIT OR Apache-2.0](https://img.shields.io/badge/License-MIT%20OR%20Apache--2.0-blue.svg)](LICENSE-MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](pyproject.toml)
[![UI: GTK4 + Libadwaita](https://img.shields.io/badge/UI-GTK4%20%2B%20Libadwaita-purple.svg)](gui/ventana.py)

**Editor de PDF nativo para Linux que modifica objetos sin reconstruir el documento.**

---

## 🎯 ¿Por qué existe IntactPDF?

Cuando abres un PDF en LibreOffice Draw, Inkscape o muchos editores convencionales y guardas, ocurre un desastre silencioso: **el documento entero es parseado, transformado a un modelo vectorial ajeno y reconstruido desde cero**.

El resultado empírico comprobado:
- Se destruyen perfiles CMYK e imprenta comercial.
- Se pierden metadatos, formularios AcroForm y capas OCG.
- Las fuentes incrustadas se sustituyen o desalinean.
- Un documento sin editar alterado por LibreOffice Draw cambia entre el **0.4% y el 11.8% de los píxeles de cada página**.

### La Promesa IntactPDF

> **«Modifica exactamente lo que seleccionas. Preserva el 100% de todo lo demás.»**

1. **Guardado incremental estricto (ISO 32000-1 §7.5.6):** El fichero resultante **comienza byte a byte por los datos exactos del original**. Las ediciones y nuevos objetos se indexan al final en una tabla xref incremental.
2. **Prueba de humo y preservación de tinta:** Antes de confirmar el guardado, un motor independiente (`pdfium`) renderiza la página y comprueba que sigue visible y que ningún píxel fuera de la región seleccionada ha cambiado.
3. **Escritura atómica con copia de seguridad:** Guardado seguro por etapas temporales (`staging`) y creación automática de respaldo (`archivo.pdf~`).

---

## 📸 Interfaz Gráfica (GTK4 + Libadwaita)

IntactPDF incluye una interfaz moderna adaptada a los estándares de GNOME / Libadwaita con **cinta de opciones contextual**:

| Vista Inicial | Selección e Inspección de Objetos |
| :---: | :---: |
| ![Recién abierto](docs/capturas/01-recien-abierto.png) | ![Selección](docs/capturas/02-seleccion.png) |

| Pestaña Objeto (Mover, Escalar, Reemplazar Imagen) | Pestaña Texto (Edición con preservación tipográfica) |
| :---: | :---: |
| ![Cinta Objeto](docs/capturas/06-cinta-objeto.png) | ![Cinta Texto](docs/capturas/07-cinta-texto.png) |

---

## ⚡ Características Principales

- **Edición de texto quirúrgica:** Sustitución directa de bytes (nivel 1a), compresión/expansión de cadenas con ajuste métrico de espaciado `Tc` (nivel 1b) o incrustación de subconjuntos de fuentes del sistema sin tocar las fuentes del documento original (nivel 2).
- **Gestión completa de imágenes:**
  - **Sustitución de imagen:** Cambia un logotipo, foto o firma por una nueva imagen (PNG/JPG) manteniendo exactamente las dimensiones, matriz de transformación y posición en el documento.
  - **Extracción de imagen:** Exporta ilustraciones incrustadas con su resolución nativa a disco.
- **Transformaciones geométricas:** Desplazamiento preciso en puntos (`pt`), arrastre con el ratón y escalado porcentual.
- **Eliminación y redacción segura:** Borrado de operadores en el stream y comando `compact` para purgar irreversiblemente el historial de revisiones previas y objetos descartados.
- **Seguridad legal:** Detección automática y alerta persistente (`Adw.Banner`) si el documento contiene firmas digitales criptográficas (`/Sig`, `/ByteRange`).
- **Navegación fluida:** Zoom continuo mediante `Ctrl + Rueda del ratón`, atajos rápidos (`Ctrl++`, `Ctrl+-`, `Ctrl+0`) y copia de texto seleccionado al portapapeles (`Ctrl+C`).
- **Historial de edición:** Sistema robusto de **Deshacer (`Ctrl+Z`)** y **Rehacer (`Ctrl+Shift+Z` / `Ctrl+Y`)** gestionado en memoria de sesión.
- **Gestión de orientación:** Rotación puntual de páginas en 90°, 180° o 270° mediante actualización pura del diccionario `/Rotate`.
- **Descifrado integrado:** Comando `decrypt` para remover cifrados compatibles antes de la edición incremental.

---

## 🚀 Instalación y Uso

### 1. Instalación Universal sin permisos de root (Recomendado)

En cualquier distribución Linux moderna (incluyendo **openSUSE Leap**, **openSUSE Tumbleweed**, Fedora, Debian, Ubuntu o Arch):

```bash
# Opción A: Mediante el instalador automático
./instalar.sh

# Opción B: Con un entorno virtual de usuario (sin root)
python3 -m venv ~/.local/share/intactpdf-env --system-site-packages
~/.local/share/intactpdf-env/bin/pip install -e .
mkdir -p ~/.local/bin
ln -sf ~/.local/share/intactpdf-env/bin/intactpdf ~/.local/bin/intactpdf
ln -sf ~/.local/share/intactpdf-env/bin/intactpdf-gui ~/.local/bin/intactpdf-gui
```

> **Nota para openSUSE:** Para ejecutar la interfaz gráfica GTK4, asegúrate de contar con la pila base de PyGObject (generalmente disponible de serie o en el repositorio de usuario). Si solo dispones de Python básico, la línea de comandos `intactpdf` funciona al 100% sin dependencias gráficas.

### 2. Paquete Flatpak (Sandbox aislado)

```bash
flatpak-builder --user --install --force-clean \
    build-dir packaging/io.github.lockerdocx.IntactPDF.json

# Ejecutar la aplicación
flatpak run io.github.lockerdocx.IntactPDF
```

---

## 💻 Uso por Línea de Comandos (CLI)

IntactPDF ofrece un conjunto completo de comandos independientes de la GUI para servidores, guiones o automatizaciones:

```bash
# Diagnóstico y estado del entorno
intactpdf doctor

# Inspeccionar metadatos y objetos de una página
intactpdf info documento.pdf
intactpdf list documento.pdf --pagina 0

# Sustituir una imagen conservando el layout original
intactpdf replace-image documento.pdf --xobject Im1 --imagen nuevo_logo.png -o salida.pdf

# Extraer imagen incrustada a disco
intactpdf extract-image documento.pdf --xobject Im1 -o logo_extraido.png

# Rotar una página 90 grados
intactpdf rotate documento.pdf --pagina 0 --angulo 90 -o rotado.pdf

# Editar texto en el run de texto 2
intactpdf edit documento.pdf --object 2 --text "Factura Rectificada" -o editado.pdf

# Guardado seguro sobre el original con backup .pdf~
intactpdf edit documento.pdf --object 2 --text "Nuevo Texto" --in-place

# Purgar historial previo y objetos eliminados (compactación / redacción)
intactpdf compact editado.pdf -o final_limpio.pdf

# Descifrar PDF protegido
intactpdf decrypt cifrado.pdf -p "secreto123" -o descifrado.pdf
```

---

## 🧪 Batería de Pruebas y Calidad

El proyecto dispone de una infraestructura de pruebas de regresión y fidelidad visual:

```bash
# Ejecución de la suite completa de pruebas unitarias e integradas
python3 -m pytest tests/ -v

# Validación visual sobre el corpus dorado (19 casos críticos de edición)
python3 tools/test_aceptacion.py
```

### Métricas de Validación Empírica
- **118 pruebas unitarias aprobadas**, 0 fallos.
- **19/19 casos de aceptación visual**: 0 píxeles alterados fuera de la caja delimitadora en comparación con el documento original.
- **Prefijo intacto (19/19)**: Verificación criptográfica de que cada archivo editado conserva íntegramente la cabecera y el cuerpo binario de su versión predecesora.

---

## 📄 Licencia

Este proyecto está bajo licencia doble **MIT OR Apache-2.0**.
El núcleo es 100% propio (sin dependencias con copyleft como AGPL / MuPDF).
