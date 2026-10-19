# 9 · Mejoras de madurez, estabilidad y producto

Tras la auditoría empírica de ingeniería inversa sobre la versión 0.1.0 (commit `cbc4828`),
se abordaron minuciosamente los puntos críticos donde IntactPDF no completaba su propuesta
de valor frente a otros editores. Cada mejora fue implementada, testeada en caliente,
ajustada tras fallos reales y consolidada con su correspondiente lección aprendida.

---

## 1. Guardar sobre el archivo original en GUI con copia de respaldo automática (`.pdf~`)

### El problema
La interfaz gráfica forzaba siempre la acción «Guardar como» a un archivo nuevo (`*-editado.pdf`).
El diseño fundacional (§C6 de `02-preguntas-abiertas.md`) estipulaba que «Guardar» debía realizar
una actualización incremental sobre el archivo original con backup automático (`archivo.pdf~`),
y que «Guardar como» debía estar disponible para exportar a otra ruta.

Sobrescribir el mismo archivo con el código previo era de alto riesgo: si la verificación de tinta
fallaba, la función hacía `unlink(ruta_salida)`, lo que en guardado in-place habría destruido
el documento original del usuario.

### La solución
1. **Escritura por fase atómica (staging)** en `nucleo/guardar.py`:
   - El archivo modificado se escribe primero en un temporal en la misma carpeta (`.archivo.pdf.uuid.tmp`).
   - Se ejecuta `verificar_que_se_ve()`. Si falla o lanza excepción, el temporal se destruye y el archivo original permanece **100% intacto**.
   - Si la verificación pasa:
     - Si es el mismo archivo y `crear_backup=True`, se genera `archivo.pdf~`.
     - Se ejecuta `tmp.replace(destino)` de forma atómica.
2. **Soporte en el modelo `gui/modelo.py`**:
   - `Sesion.guardar(destino=None, crear_backup=True)`: si `destino is None`, asume `self.ruta`.
   - Limpia el historial de deshacer, actualiza `_datos_al_abrir = self.datos`, resetea `hay_cambios` a `False` e informa en la barra de estado de la creación de la copia previa.
3. **Soporte en la ventana `gui/ventana.py`**:
   - `Ctrl+S` / Botón «Guardar»: guarda in-place sobre el archivo abierto.
   - `Ctrl+Shift+S` / Botón «Guardar como»: solicita destino con `Gtk.FileDialog`.

### Lección aprendida y fallo depurado
- **Fallo:** En el primer intento en `gui/modelo.py`, se escribió `self.pila_deshacer.clear()`.
  La clase `Sesion` utiliza `self.historial`, por lo que saltó un `AttributeError`.
- **Causa:** Asumir el nombre del atributo sin contrastar con la dataclass `Sesion`.
- **Corrección:** Usar `self.historial.clear()`, actualizar `self._datos_al_abrir` e invalidar la caché de versión.
- **Lección:** Las operaciones de guardado in-place deben resetear la línea base de comparación (`_datos_al_abrir`) para que `hay_cambios` refleje con precisión que el documento en disco ya contiene todas las ediciones pendientes.

---

## 2. Eliminación segura y purga de historial (`compactar_pdf` y CLI `compact`)

### El problema
El guardado incremental por especificación no destruye revisiones pasadas: los objetos borrados
y los textos anteriores siguen existiendo en los bytes iniciales del archivo. En entornos
administrativos, legales o de privacidad, esto impide una redacción segura de datos confidenciales.

### La solución
1. Implementación de `compactar_pdf(ruta_entrada, ruta_salida)` en `nucleo/guardar.py`:
   - Utiliza `pikepdf.open()` y `pdf.save(compress_streams=True, linearize=False)`.
   - Purga todas las revisiones intermedias, objetos no referenciados y reconstruye una tabla xref limpia y unificada.
   - Devuelve `InformeCompactado` con bytes originales, finales, ahorro y páginas.
2. Subcomando CLI en `nucleo/cli.py`:
   - `intactpdf compact documento.pdf -o compactado.pdf`
3. Integración en la GUI (`gui/ventana.py`):
   - Botón «Compactar» en la pestaña «Página» (grupo Herramientas) y acción en la aplicación.

### Lección aprendida y fallo depurado
- **Fallo:** En un primer diseño, el botón «Compactar» se añadió como botón grande en el grupo
  «Documento» de la pestaña «Inicio». Al correr `pytest tests/test_gui.py`, el test `test_la_cinta_cabe_en_la_ventana`
  falló: la pestaña «Inicio» medía 1.235 px frente al ancho máximo de 1.172 px (`1180 - 8`).
- **Causa:** La cinta tiene una restricción estricta de usabilidad: todas las pestañas deben caber
  completas sin scroll horizontal en la resolución mínima admitida.
- **Corrección:** Reubicar «Compactar» en la pestaña «Página» (donde están las herramientas de análisis del documento),
  manteniendo en «Inicio» únicamente los esenciales de edición.
- **Lección:** Las interfaces de escritorio gobernadas por contratos de tamaño estricto requieren
  respetar la jerarquía espacial; una herramienta de mantenimiento global pertenece a la pestaña del documento,
  no a la barra de acciones rápidas de edición puntual.

---

## 3. Descifrado para habilitar edición en PDFs protegidos (`descifrar_pdf` y CLI `decrypt`)

### El problema
Un PDF cifrado (incluso con contraseña vacía o estándar) no se puede modificar incrementalmente
en claro sin romper la lectura de los visores externos. IntactPDF los rechazaba para evitar
corromperlos, pero no ofrecía al usuario una vía directa de resolución dentro del ecosistema.

### La solución
1. Implementación de `descifrar_pdf(ruta_entrada, ruta_salida, password="")` en `nucleo/guardar.py`.
2. Subcomando CLI en `nucleo/cli.py`:
   - `intactpdf decrypt cifrado.pdf [-p PASSWORD] -o descifrado.pdf`
3. Tras generar el PDF descifrado, el documento entra directamente en el flujo de edición incremental
   quirúrgica con 100% de compatibilidad.

---

## 4. Resolución de fuentes estándar mediante alias admisibles

### El problema
En `nucleo/sustitucion_fuente.py`, existía un diccionario `ALIAS_ADMISIBLES` que mapeaba familias
clásicas (`helvetica` -> `LiberationSans`, `Arial`, `DejaVuSans`), pero la función `_candidatos_ordenados`
nunca lo consultaba. Al buscar fuentes universales como `Helvetica` en Linux, la búsqueda devolvía `None`,
bloqueando innecesariamente la edición de texto de nivel 2.

### La solución
Se conectó `ALIAS_ADMISIBLES` dentro de `_candidatos_ordenados`: si el nombre solicitado no se encuentra
exacto, explora los reemplazos métricamente admisibles respetando la variante negrita (`Bold`).
Ahora, un texto en `Helvetica` encuentra automáticamente `DejaVuSans.ttf` o `LiberationSans.ttf` del sistema.

---

## 5. Lanzador híbrido GUI para AppImage

### El problema
El AppImage empaquetaba exclusivamente el CLI para evitar el peso y la fragilidad de PyGObject/GTK4.
Si un usuario lo ejecutaba desde el menú de aplicaciones o hacía doble clic, la aplicación terminaba sin abrir ventana.

### La solución
Se mejoró el script `AppRun` en `packaging/appimage/construir.sh`:
- Detecta si se invocó con `--gui` o sin argumentos desde el entorno de escritorio.
- Inspecciona si el Python del sistema cuenta con `gi` (PyGObject + GTK4 + libadwaita).
- Si está presente, combina las bibliotecas aisladas de Python del AppImage con el motor GTK del anfitrión y lanza la GUI con `python3 -m gui.lanzar "$@"`.
- Si no está presente, delega de manera limpia y transparente en el CLI del Python portátil interno.

---

## 6. Las 6 Nuevas Mejoras de Competitividad y Usabilidad

Siguiendo la demanda del mercado frente a editores como Master PDF Editor, Acrobat y Okular, se han integrado las 6 funciones clave manteniendo el principio rector: **cero reconstrucción del documento, preservación byte a byte e intervenciones puramente incrementales**.

### 6.1. Reemplazo de imagen existente (`reemplazar_imagen` / CLI `replace-image` / GUI Objeto)
- **Problema:** El usuario a menudo necesita actualizar un logotipo obsoleto, una fotografía de producto o un sello sin alterar la maquetación.
- **Implementación:**
  - En el PDF, las imágenes se invocan vía `XObject` (`/Im1 Do`). La función `reemplazar_imagen()` localiza el `(num, gen)` de dicho XObject en los recursos de la página.
  - Convierte la nueva imagen (PNG/JPEG) a un stream PDF `/Filter /FlateDecode` con su `/ColorSpace` nativo (`DeviceRGB`, `DeviceGray`, `DeviceCMYK`).
  - Redefine ese `(num, gen)` en la actualización incremental sin tocar el stream de contenido de la página ni los operadores de posición y escala.
  - Se expone en el CLI (`intactpdf replace-image documento.pdf --xobject Im1 --imagen nueva.png`) y en la GUI (botón «Reemplazar» en pestaña «Objeto»).
- **Lección aprendida:** Mantener el stream de página intacto garantiza que la matriz de transformación previa `cm` y los recortes `W` se apliquen a la nueva imagen automáticamente con 100% de precisión geométrica.

### 6.2. Copiar texto al portapapeles (`Ctrl+C`)
- **Problema:** Al seleccionar un fragmento de texto en el lienzo, el atajo estándar `Ctrl+C` no realizaba ninguna acción.
- **Implementación:**
  - Registrado `<Control>c` en el controlador de atajos de `Ventana`.
  - Cuando `seleccion.tipo == "texto"`, extrae `seleccion.texto` y lo inyecta en el portapapeles del sistema mediante `Gdk.Display.get_default().get_clipboard().set(texto)`.

### 6.3. Zoom continuo centrado (`Ctrl + Scroll` y atajos `Ctrl++`, `Ctrl+-`, `Ctrl+0`)
- **Problema:** El zoom exigía desplazarse con el puntero hasta los botones de la cinta de opciones, perjudicando la agilidad en revisiones de detalle.
- **Implementación:**
  - Incorporado `Gtk.EventControllerScroll` en el widget `Lienzo`.
  - Comprueba la máscara `Gdk.ModifierType.CONTROL_MASK`: ajusta el factor de escala dinámicamente (`* 1.15` al subir, `/ 1.15` al bajar).
  - Añadidos atajos de teclado universales: `<Control>plus` y `<Control>equal` (acercar), `<Control>minus` (alejar) y `<Control>0` (tamaño real 100%).

### 6.4. Alerta persistente de Firma Digital (`tiene_firma_digital` y `Adw.Banner`)
- **Problema:** Modificar un documento con firma digital (aunque sea de forma incremental válida) rompe la validez legal ante visores criptográficos sin previo aviso.
- **Implementación:**
  - Función `tiene_firma_digital()` en `nucleo/guardar.py` que comprueba campos `/FT /Sig` en `/AcroForm`, anotaciones de tipo firma en páginas y secuencias `/ByteRange`.
  - En la interfaz gráfica, un `Adw.Banner` en la barra superior se revela automáticamente al abrir el archivo informando: *«Documento firmado digitalmente: guardar modificaciones invalidará la validez legal de las firmas.»*

### 6.5. Extracción de imagen a disco (`extraer_imagen` / CLI `extract-image` / GUI Objeto)
- **Problema:** Necesidad de guardar ilustraciones o fotografías incrustadas en el PDF con su resolución original sin pérdidas ni capturas de pantalla.
- **Implementación:**
  - Función `extraer_imagen()` que recupera el objeto `pikepdf.PdfImage` y lo exporta a PNG o JPEG nativo con resolución íntegra.
  - Integrado comando CLI `intactpdf extract-image documento.pdf --xobject Im1 -o salida.png` y botón «Extraer» en la pestaña «Objeto».

### 6.6. Rotación puntual de página (`rotar_pagina` / CLI `rotate` / GUI Página)
- **Problema:** PDFs de contratos o facturas escaneadas con páginas giradas 90° o 180°.
- **Implementación:**
  - En lugar de reescribir la página o rotar vectores, redefine de forma incremental el diccionario del objeto página (`num_pag, gen_pag`) sumando el ángulo a la clave `/Rotate` módulo 360.
  - Preserva 100% el prefijo del documento binario.
  - Añadidos botones rápidos de giro de 90° (horario y antihorario) en la pestaña «Página» (grupo «Girar») y comando CLI `intactpdf rotate`.

### 6.7. Deshacer y Rehacer completo (`Ctrl+Z`, `Ctrl+Shift+Z` y `Ctrl+Y`)
- **Problema:** En el flujo de trabajo cotidiano, el usuario necesita revertir o reaplicar modificaciones accidentales antes de persistir en disco.
- **Implementación:**
  - El modelo [`Sesion`](file:///home/gerard.morales.7ea/Documents/antigravity/kind-nobel/gui/modelo.py) gestiona dos pilas acopladas: `historial` (deshacer) y `pila_rehacer` (rehacer).
  - Al ejecutar `deshacer()`, el estado actual se transfiere a `pila_rehacer` antes de retroceder al anterior.
  - Al ejecutar `rehacer()`, el estado se recupera de `pila_rehacer` y se vuelve a inyectar en `historial`.
  - Cualquier nueva modificación bifurcada en `_apuntar()` purga automáticamente `pila_rehacer`.
  - Atajos integrados en la GUI: `<Control>z` para deshacer, y `<Control><Shift>z` / `<Control>y` para rehacer.

---

## 7. Verificación Empírica de Redacción Segura

Para responder a la exigencia de que la compactación garantice la eliminación irrecuperable de información:
- Se implementó la prueba automatizada `test_compactar_demuestra_eliminacion_irreversible_de_datos` en `tests/test_guardado_seguro.py`.
- **Procedimiento verificado:**
  1. Se genera un PDF con una cadena sensible confidencial (`SECRETO_BANCARIO_IBAN_...`).
  2. Se modifica incrementalmente sobrescribiendo el objeto con texto censurado.
  3. **Comprobación 1:** En el fichero incremental, el secreto *sigue presente* en los bytes históricos de la revisión inicial (`assert secreto in inc.read_bytes()`).
  4. Se ejecuta `compactar_pdf(inc, comp)`.
  5. **Comprobación 2:** Se escanean todos los bytes binarios del archivo compactado y se verifica la ausencia absoluta de la cadena (`assert secreto not in comp.read_bytes()`), validando la purga total de revisiones huérfanas y objetos históricos.

---

## 8. Resultados de Verificación Final de la Suite

- **Pruebas unitarias (`pytest tests/`)**: **118 pasadas**, 4 omitidas (3 por artefactos de distribución `dist/` no construidos aún, 1 por binario opcional `qpdf`), **0 fallos**.
- **Aceptación empírica (`tools/test_aceptacion.py`)**: **19/19 casos aprobados**, 0 píxeles alterados fuera de región permitida.
- **Validación sintáctica de scripts**: `packaging/appimage/construir.sh` y `instalar.sh` verificados sin errores (`bash -n` y `sh -n`).


