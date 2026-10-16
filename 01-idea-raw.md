# LinuxPDF Studio — Idea en crudo (fase raw)

**Origen:** comentario de `c4pl4b` en r/SideProject.
**Fase:** estructurar la idea tal cual la pide el usuario. Sin roadmap, sin mercado, sin monetización.

---

## 0. El pedido, literal

> Ich suche für Linux ein Tool, um PDF-Dokumente zu bearbeiten:
> Texte manipulieren
> die Größe der Vektoren/Bilder zu ändern beziehungsweise diese zu löschen
> Es gibt keine ordentliche Lösung

Desglose palabra por palabra:

| Fragmento original | Qué pide exactamente |
|---|---|
| `für Linux` | Binario/empaquetado para Linux. No web, no Windows-first. |
| `um PDF-Dokumente zu bearbeiten` | Editar **el documento existente**, no generar uno nuevo. |
| `Texte manipulieren` | Manipular texto: contenido y, por extensión razonable, posición/tamaño/estilo del texto ya escrito. |
| `die Größe der Vektoren/Bilder zu ändern` | Redimensionar imágenes **y** trazados vectoriales. O sea: el modelo de objeto trata imagen y vector como entidades seleccionables equivalentes. |
| `beziehungsweise diese zu löschen` | Borrar esos mismos objetos. |
| `Es gibt keine ordentliche Lösung` | Su criterio de calidad no es "que exista algo", es "que funcione bien sobre un PDF real". El listón es el PDF sucio, no el generado por LaTeX. |

**Lo que NO dice:** convertir, OCR, firmar, formularios, comprimir, dividir/unir, colaborar, nube. Todo eso queda fuera hasta que él lo pida.

---

## 1. Requisitos funcionales (RF)

Solo los derivados del texto. Numerados para poder tacharlos.

- **RF1 — Abrir.** Cargar un PDF local y verlo tal cual: multi-página, zoom, scroll, páginas rotadas, tamaños de página mixtos.
- **RF2 — Seleccionar.** Clic sobre un elemento visible → queda seleccionado, con su caja visible. Un elemento = un objeto del PDF: un bloque/run de texto, una imagen (XObject), o un grupo de trazados vectoriales.
- **RF3 — Mover.** Arrastrar el objeto seleccionado a otra posición.
- **RF4 — Redimensionar.** Cambiar tamaño con manijas, imagen y vector por igual, manteniendo proporción por defecto y permitiendo romperla.
- **RF5 — Eliminar.** Borrar imagen, vector o texto seleccionado. La página no se recoloca: queda el hueco (el usuario decide qué hacer con él).
- **RF6 — Editar texto.** Cambiar el contenido de un bloque de texto in situ. Con la condición explícita del propio brief: *"cuando la estructura del PDF lo permita"*.
- **RF7 — Guardar conservando el layout.** Al abrir de nuevo el archivo, todo lo que el usuario no tocó debe verse **píxel a píxel igual**. Esto no es un detalle: es el requisito que define el proyecto.

### Derivados necesarios (no los pidió, pero RF1–RF7 no existen sin ellos)
- **RF8 — Undo/redo.** Sin esto, RF5 (borrar) es destructivo y nadie usa la herramienta.
- **RF9 — Panel de propiedades del objeto.** Tipo, tamaño, posición, página. Es la única forma de que "seleccionar" sea útil para algo más que mirar.
- **RF10 — Aviso de pérdida irreversible.** Si el PDF está firmado digitalmente o tiene capas, editar rompe algo. Decirlo antes de dejar editar, no después.

### Fuera de alcance (explícito, para no crecer solo)
- Reflow de texto. El texto no se reacomoda. Si cambias 3 palabras por 10, se solapan o se cortan. **Es una limitación aceptada y documentada, no un bug.**
- Reemplazo de tipografía / instalar fuentes nuevas.
- OCR, formularios, firmas, anotaciones, marcas de agua automáticas.
- Edición de páginas (reordenar, extraer, dividir, unir, rotar).
- Export a otro formato.

---

## 2. Lo que realmente está pidiendo (lectura técnica)

El usuario describe un **editor de objetos sobre el stream de contenido**, no un procesador de texto.

Un PDF no es un documento, es una lista de instrucciones de dibujo por página (`Tj`, `TJ`, `Do`, `re`, `l`, `c`, `f`, `cm`, `q`/`Q`…). "Editar un PDF" significa:

1. **Parsear** el stream de contenido de la página → lista de objetos con su estado gráfico.
2. **Renderizar** la página y saber, para cada píxel, qué objeto lo pintó → esto da la selección.
3. **Modificar** los operadores de ese objeto (su matriz `cm`, sus coordenadas, su texto, o eliminar la secuencia entera).
4. **Reserializar** el stream y guardar con **actualización incremental**, para no tocar nada que no se haya editado.

Ahí está el 9/10 de dificultad técnica. No es la UI. Es el paso 2 y el 4.

---

## 3. Restricciones que impone el formato

| Restricción | Consecuencia directa sobre el MVP |
|---|---|
| El texto viene en fragmentos arbitrarios (kerning manual, divisiones por operador) | Un "párrafo" visible pueden ser 40 objetos. Hay que agrupar para que RF6 sea usable. |
| Fuentes incrustadas **subconjuntadas** | Si el usuario escribe una letra que no está en el subset, no se puede pintar. O se re-subsetea la fuente, o se bloquea ese carácter y se avisa. |
| Texto con modos de renderizado raros (invisible, clipping, relleno+trazo) | RF6 debe detectar "esto no es texto editable normal" y no intentarlo. |
| Vectores con clip paths, patrones, shadings, transparency groups | Redimensionar un vector puede requerir transformar también su clip. Caso difícil → en MVP: detectar y marcar como "no seguro de editar". |
| Imágenes con máscaras (SMask), separaciones CMYK, JPX/CCITT | RF4 funciona, pero el render de prueba debe cubrir estos casos o fallará en PDFs de imprenta. |
| Firmas digitales | Cualquier modificación invalida la firma. RF10. |
| Compresión de streams y objetos en object streams | Se resuelve con la librería, pero hay que verificarlo con PDFs reales, no con los que generas tú. |

---

## 4. MVP en fases, cada una demostrable

| Fase | Qué entrega | Demo |
|---|---|---|
| **F0** | Abrir + renderizar + navegar (RF1) | Abre un PDF de 200 páginas sin romperse. |
| **F1** | Parseo del stream + selección con caja + panel (RF2, RF9) | Clic en una imagen → aparece su caja y sus datos. **Esta es la fase que demuestra que el proyecto es viable.** |
| **F2** | Mover y eliminar imagen/vector (RF3, RF5 parcial, RF8) | Borras un logo, guardas, reabres: el logo no está y el resto está idéntico. |
| **F3** | Redimensionar imagen y vector (RF4) | Estiras una foto y un rectángulo; se guardan bien. |
| **F4** | Editar texto donde se pueda (RF6) + detección de "no editable" | Cambias una palabra de una factura; el resto no se mueve. |
| **F5** | Guardado incremental robusto (RF7) | Diff binario: solo cambian los objetos tocados. |

**Criterio único de MVP terminado:** un usuario abre un PDF real con texto e imágenes, selecciona una imagen, la redimensiona, borra un vector, cambia un texto, guarda, reabre → sus cambios están y **nada más cambió**.

---

## 5. Decisiones abiertas (bloquean el diseño, no la idea)

1. **Stack.** Cuatro caminos, ninguno gratis:
   - **Poppler + Qt** → LGPL/GPL limpio, pero Poppler es visor: no trae edición de stream. Escribes el editor tú.
   - **PDFium + UI propia** → el mejor render, licencia BSD-friendly, pero de nuevo cero soporte de edición.
   - **MuPDF** → sí tiene edición real de objetos, pero es **AGPL**: te obliga a GPL en todo el proyecto.
   - **PyMuPDF + Qt (PySide6)** → iteración rapidísima para el MVP; misma trampa AGPL (PyMuPDF) si luego quieres licencia permisiva.
   → **Decisión clave: ¿el proyecto es GPL a propósito, o se necesita licencia permisiva?** Eso elige la librería, no al revés.
2. **Lenguaje/UI.** Python para validar en semanas vs. Rust/C++/Qt para producto. Se puede empezar en uno y portar F1.
3. **Distribución.** Flatpak es casi obligatorio para que "funciona en Linux" sea verdad (dependencias de render, fuentes).
4. **Nombre.** `LinuxPDF Studio` es genérico y SEO-hostil (se confunde con PDF Linux / Linux PDF viewer). Vale la pena un nombre propio antes de publicar nada.

---

## 6. Puntuación del brief, comentada una a una

| Criterio | Valor | Comentario en crudo |
|---|---|---|
| Problema específico | 10/10 | Correcto. El usuario enumera features, no deseos. Es un spec, no un lamento. |
| Utilidad | 9/10 | Correcto. Editar PDFs en Linux sin software privativo es un agujero real y repetido. |
| Encaje open source | 10/10 | Correcto, y además es la razón por la que no hay solución: la edición choca con licencias AGPL de las librerías que sí saben editar. |
| Dificultad técnica | 9/10 | Correcto, y está mal ubicada: la dificultad no está en "PDF", está en **selección de objetos + reserialización fiel**. |
| Posibilidad de MVP | 6/10 | **Discutible hacia arriba.** Si el MVP se corta en F2–F3 (mover/borrar/redimensionar objetos) y se deja fuera el reflow de texto, es un 8. Baja a 6 solo si el MVP incluye RF6 completo. |
| Diferenciación | 7/10 | Correcto, con matiz: la diferenciación no es "otro editor", es **"el que no te reconstruye el documento"**. Ese es el eslogan y el test de aceptación. |

---

## 7. Siguiente paso natural

Construir **F1 (selección de objetos)** como prototipo desechable sobre un PDF real y sucio (una factura escaneada-mezclada, un folleto con vectores y degradados). Si la selección funciona ahí, el proyecto existe. Si no funciona ahí, nada de lo demás importa.
