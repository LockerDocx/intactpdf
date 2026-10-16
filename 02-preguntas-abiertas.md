# LinuxPDF Studio — Preguntas abiertas antes de tocar código

**Estado:** cerrado el 2026-10-15. Los 25 defaults quedan aceptados.
**Decisiones firmes:**
- **B1 Licencia → MIT/Apache con núcleo propio.** Fuera MuPDF y PyMuPDF (AGPL). El parser y el editor de streams se escriben.
- **B3 Fidelidad → ya no es una pregunta, es código.** `tools/medir_fidelidad.py` está implementado y ejecutado. Ver `03-validacion-empirica.md`.
- El resto de defaults (A1–A4, B2, C1–C9, D1–D5, E1–E5) se aceptan tal cual están propuestos abajo.

**Cómo usarlo:** esto queda como registro de por qué se decidió cada cosa.

---

## 0. Corrección previa: "no existe ninguna solución decente" no es exactamente cierto

Antes de construir nada sobre esa frase, hay que afinarla. Lo que existe hoy en Linux:

| Herramienta | Qué hace de verdad | Dónde falla |
|---|---|---|
| **LibreOffice Draw** | El rival real. Sí edita texto, imágenes y objetos en un PDF existente [11](https://www.fosslinux.com/43094/the-best-free-and-open-source-pdf-editors.htm) | **Reconstruye el documento.** Guarda como `.odg` y el PDF sale de un export [6](https://www.wps.com/blog/libreoffice-pdf-editor-how-to-edit-pdfs-free-in-draw/). Rompe párrafos en cajas de una línea, no hace reflow [7](https://www.reddit.com/r/libreoffice/comments/13jixcr/how_do_i_edit_a_pdf_in_libreoffice_it_treats/), sustituye fuentes y descuadra [8](https://www.oreateai.in/productivity/how-to-edit-pdf-files-for-free-using-libreoffice-draw). LibreOffice llegó a responder a un bug report que **"Draw no es un editor de PDF"** [9](https://www.howtogeek.com/why-pdfs-can-be-so-hard-to-edit-and-how-this-free-open-source-tool-makes-it-easier/) |
| **Inkscape** | Edición vectorial real por página | Es un editor de dibujo, no de documento; una página a la vez [5](https://updf.com/edit-pdf/linux-pdf-editor/) |
| **PDFedit** | El precedente exacto de esta idea: Qt, borra y añade texto e imágenes [10](https://ironpdf.com/blog/pdf-tools/open-source-pdf-editor/) | Basado en **Qt 3.x** [4](https://www.ubuntupit.com/best-linux-pdf-editor-reviewed-and-compared/). Abandonado. |
| **Okular / PDFsam / PDF Arranger** | Anotación y páginas | No tocan el contenido [1](https://www.pdnob.com/pdf-editor/best-open-source-pdf-editor.html) |
| **Master PDF Editor / Xodo PDF Studio** | Sí editan texto e imágenes existentes en Linux nativo [12](https://updf.com/edit-pdf/linux-pdf-editor/) | **Privativos.** Xodo es un lanzamiento reciente. |

> ⚠️ ~~Esto sale de fuentes web, no de haber ejecutado las herramientas.~~ **Medido el 2026-10-15** con LibreOffice 25.2.3.2 sobre un corpus de 11 PDFs: el round-trip `PDF → .odg → PDF` **sin editar nada** no deja ningún archivo idéntico, y destruye formularios, enlaces y el espacio CMYK en silencio. Detalles y cifras en `03-validacion-empirica.md`.

**Conclusión que cambia la idea:** el hueco no es "editar PDFs en Linux" (ya se puede, mal). El hueco es **"editar un PDF sin reconstruirlo"**. Ese es exactamente el criterio que el usuario puso en su propio brief: *guardar conservando el layout*. Y es el que LibreOffice falla por diseño, no por bug.

**Eso reescribe el eslogan y el test de aceptación del MVP:**
> Abre un PDF. Cambia una cosa. Guarda. Todo lo demás sigue byte a byte igual.

Si no podemos prometer eso, somos un LibreOffice Draw más bonito y el proyecto no tiene razón de ser.

---

## A. Identidad y ambición

**A1 — ¿Proyecto personal o producto?**
Side project que se mantiene los fines de semana, o algo con aspiración de comunidad/ingresos.
*Por qué importa:* decide si puedes permitirte AGPL (ver B1), si necesitas CI desde el día uno, y si el alcance se corta a lo divertido o a lo aburrido-y-necesario (empaquetado, tests de regresión, soporte).
**Default:** producto open source serio, sin monetización en v1.

**A2 — ¿Quién es el usuario primario?**
Candidatos: (a) el que arregla una factura/contrato puntual, (b) el administrativo que edita 20 PDFs al día, (c) el diseñador que toca artes finales, (d) el dev que necesita una librería CLI.
*Por qué importa:* son cuatro apps distintas. (a) quiere 5 botones; (b) quiere atajos y lotes; (c) quiere control vectorial fino; (d) no quiere GUI.
**Default:** (a) + (b). "El que recibe un PDF y tiene que cambiar algo sin tener el original." Diseñador y CLI quedan fuera.

**A3 — ¿Cuál es el enemigo a batir?**
LibreOffice Draw (gratis, ya instalado) o Master PDF Editor / Xodo (privativos, completos).
*Por qué importa:* contra Draw ganas en fidelidad y pierdes en features. Contra Master PDF ganas en libertad y pierdes en madurez. No puedes ganar en los dos ejes a la vez en v1.
**Default:** LibreOffice Draw. Es el que tiene el 90 % de los usuarios y el fallo estructural.

**A4 — ¿Qué nombre?**
`LinuxPDF Studio` es genérico, SEO-hostil y suena a visor. Además hay precedentes de nombres ocupados en este espacio.
**Default:** proponer 5 candidatos con dominio y nombre de paquete libres, antes de publicar nada.

---

## B. Las tres decisiones que bloquean la arquitectura

**B1 — ¿Licencia?** ⛔ *bloqueante*
- GPL a propósito → puedes usar **MuPDF** o **PyMuPDF**, que ya traen edición real de objetos. Ahorras meses.
- MIT/Apache → descartas ambas (AGPL). Vas con **PDFium** o **Poppler** y escribes el parser/editor de streams tú.
*Por qué importa:* no es reversible después. Y es la razón por la que este nicho está vacío: las librerías que saben editar son AGPL.
**Default:** MIT/Apache con núcleo propio. Más trabajo, pero es lo que hace que un proyecto así sobreviva y lo que un usuario de Linux valora.

**B2 — ¿Lenguaje y UI?** ⛔ *bloqueante*
- Python + PySide6 → prototipo en días, techo de rendimiento, dependencias pesadas para empaquetar.
- Rust + egui/Iced/Tauri → producto desde el día uno, iteración más lenta.
- C++ + Qt → el camino nativo clásico, mejor integración de escritorio, desarrollo más lento.
**Default:** **prototipo en Python para validar la selección de objetos (fase F1), núcleo de parseo/escritura en Rust desde el principio**, para no tirar el trabajo. Si prefieres un solo lenguaje, Rust entero.

**B3 — ¿Cómo garantizamos "nada más cambió"?** ⛔ *bloqueante, y es el producto*
Opciones: diff binario por objeto, render a imagen + diff de píxeles con umbral, o ambos.
*Por qué importa:* sin un test automático de fidelidad, cada feature nueva rompe silenciosamente PDFs que antes funcionaban. Este no es un extra: es el mecanismo que hace creíble la promesa.
**Default:** ambos, sobre un **corpus dorado** de PDFs reales y feos (ver D1), ejecutado en CI en cada commit.

---

## C. Modelo de producto (las que definen la experiencia)

**C1 — ¿Confirmamos edición in-place, no reconstrucción?**
Es decir: leemos el PDF, tocamos solo los objetos editados, guardamos con actualización incremental. Nunca pasamos por un modelo intermedio tipo Draw/ODG.
*Por qué importa:* es la decisión fundacional. Si un día cedemos y reconstruimos, perdimos la diferenciación.
**Default:** sí, innegociable. Si algo no se puede editar in-place, **no se edita** y se avisa.

**C2 — ¿Hasta dónde llega la edición de texto?** ⛔ *la más cara del proyecto*
Niveles posibles:
1. Solo reemplazar caracteres que ya existen en el subset de la fuente incrustada. Barato, pero inútil en la práctica.
2. Re-subsetting de la fuente + añadir glifos nuevos desde el sistema. Real, pero exige resolver de dónde sale el glifo que falta.
3. Reemplazo de tipografía completo. Fuera de alcance razonable.
Y ortogonal: **¿qué pasa si el texto nuevo es más largo?** Sin reflow se solapa o se corta.
**Default:** nivel 2, sin reflow, con aviso visual cuando el texto desborda su caja. Documentar la limitación en la UI, no solo en la web.

**C3 — ¿Qué es "un objeto" para el usuario?**
Cuando alguien hace clic en un logo hecho de 47 trazados: ¿selecciona un trazo, un grupo por color de relleno, un grupo por proximidad, o el logo entero?
*Por qué importa:* esta decisión determina si la herramienta se siente mágica o inutilizable. Es la diferencia entre "hago clic y lo muevo" y "tengo que seleccionar 47 cosas".
**Default:** agrupación heurística por proximidad + jerarquía visible (clic = grupo, Alt+clic = elemento, doble clic = entrar). Con posibilidad de agrupar/desagrupar manualmente.

**C4 — ¿Y las páginas escaneadas?**
Un PDF escaneado es una imagen. No hay texto que editar.
*Por qué importa:* es una fracción enorme de los PDFs reales (facturas, contratos firmados). Si no decides esto, el usuario abre su PDF, no pasa nada, y desinstala.
**Default:** v1 = detectar y decir claramente "esta página es una imagen, no tiene texto editable". **Sin OCR.** OCR como fase posterior, opcional y delegando a OCRmyPDF/Tesseract, nunca integrado en el núcleo.

**C5 — ¿Se puede añadir contenido nuevo?**
El usuario pidió manipular lo existente. Añadir texto/imágenes nuevos no lo pidió.
*Por qué importa:* añadir es mucho más fácil que editar, y es una tentación. Pero si lo haces, la gente lo usará como herramienta de anotación y te pedirán anotaciones, y acabas siendo Okular.
**Default:** fuera de v1. Solo manipulación de lo existente.

**C6 — ¿Modelo de guardado?**
Sobrescribir el original, guardar como, o ambos. Y qué pasa al cerrar con cambios sin guardar.
**Default:** "Guardar" hace actualización incremental sobre el original con backup automático (`archivo.pdf~`); "Guardar como" siempre disponible; aviso al cerrar con cambios.

**C7 — ¿Qué hacemos con una firma digital presente?**
Cualquier modificación la invalida.
*Por qué importa:* un usuario que edita un contrato firmado y no se entera tiene un problema legal, no técnico.
**Default:** detectar al abrir, avisar con un banner persistente, dejar editar bajo confirmación explícita, y marcar el resultado como "firma invalidada". Nunca silencioso.

**C8 — ¿Qué pasa con formularios, capas (OCG), anotaciones y documentos cifrados?**
**Default:** cifrado → abrir con contraseña, no tocar permisos. Formularios → preservar intactos, no editarlos. Capas → preservar. Anotaciones → preservar y avisar si una edición las afecta. Todo esto es "no romper", no "soportar".

**C9 — ¿Soporte de idiomas del contenido?**
Latino básico, o también CJK / árabe / hebreo (RTL).
*Por qué importa:* CJK y RTL multiplican la complejidad del manejo de fuentes y de la edición de texto. Es un multiplicador de coste grande.
**Default:** v1 = latino + acentos + símbolos comunes. CJK/RTL declarado fuera de alcance y documentado.

---

## D. Alcance técnico y calidad

**D1 — ¿Con qué PDFs probamos?** ⛔
Un PDF que generas tú con ReportLab siempre funciona. El proyecto vive o muere con PDFs reales: factura de un banco, contrato con formularios, folleto con degradados y transparencias, un PDF/A de imprenta, uno con fuentes subseteadas raras, uno de 400 páginas.
**Default:** corpus dorado de ~20 PDFs reales bajo `tests/corpus/`, con licencia o de dominio público, y CI que los recorre en cada commit.

**D2 — ¿Qué pasa con los objetos huérfanos?**
Si borras una imagen, ¿eliminas también el XObject del archivo (el PDF adelgaza) o lo dejas colgando?
**Default:** eliminar objetos huérfanos al guardar, con opción de "compactar" explícita.

**D3 — ¿Objetivo de rendimiento?**
¿Qué tamaño de PDF debe abrir en menos de 2 segundos? ¿Debe funcionar con 1000 páginas?
**Default:** 100 páginas en <2 s, 1000 páginas usable. Render lazy por página.

**D4 — ¿Multi-selección y operaciones en lote?**
Mover 5 objetos a la vez, alinear, distribuir.
**Default:** v1 = selección múltiple y mover/borrar en grupo. Alinear/distribuir fuera.

**D5 — ¿Precisión de la selección?**
¿Clic exacto sobre el píxel pintado, o caja contenedora? Un texto fino es difícil de pinchar.
**Default:** caja contenedora con tolerancia, más hit-testing real sobre el trazado para vectores.

---

## E. Empaquetado y comunidad

**E1 — ¿Cómo se instala?** ⛔ para que "funciona en Linux" sea verdad
Flatpak, AppImage, paquete nativo por distro, Snap.
*Por qué importa:* un editor de PDF depende de librerías de render y de **fuentes del sistema**. Sin sandbox bien resuelto, "funciona en mi máquina" es el destino.
**Default:** **Flatpak primero** (runtime de GNOME/KDE con fuentes resueltas), AppImage como segunda opción. Paquetes nativos después.

**E2 — ¿Qué va en el primer release público?**
**Default:** F1 + F2 + F3: abrir, seleccionar, mover, redimensionar, borrar objetos, guardar fiel. **Sin edición de texto.** Es un release honesto, demostrable y ya es mejor que nada.

**E3 — ¿Telemetría?**
**Default:** cero. Ni opcional. Es un argumento de venta en Linux.

**E4 — ¿Localización de la interfaz?**
**Default:** inglés + español + alemán desde el inicio (el usuario que originó la idea escribe en alemán; es un detalle que cuesta poco y se nota).

**E5 — ¿Cómo medimos que funciona?**
¿Qué señal te dice que vale la pena seguir?
**Default:** que 10 personas ajenas abran un PDF propio, editen algo y guarden sin que se rompa. No estrellas de GitHub.

---

## F. Fuera de alcance, para que quede por escrito

Todo esto está fuera hasta que se pida explícitamente: OCR, firmas, formularios editables, anotaciones, comprimir, dividir/unir/reordenar páginas, convertir a otros formatos, colaboración, nube, versión móvil, versión Windows/macOS, plugin/API pública, edición por lotes, IA de ningún tipo.

---

## Resumen rápido: los defaults en una tabla

| # | Pregunta | Default propuesto |
|---|---|---|
| A1 | Ambición | Open source serio, sin monetizar en v1 |
| A2 | Usuario | El que recibe un PDF y debe cambiar algo |
| A3 | Rival | LibreOffice Draw |
| A4 | Nombre | Cambiarlo; proponer 5 |
| B1 | Licencia | MIT/Apache + núcleo propio |
| B2 | Stack | Prototipo Python, núcleo Rust |
| B3 | Fidelidad | Diff binario + diff de píxeles en CI |
| C1 | Modelo | In-place, innegociable |
| C2 | Texto | Re-subsetting, sin reflow, aviso de desborde |
| C3 | Objeto | Agrupación heurística + jerarquía |
| C4 | Escaneados | Detectar y avisar. Sin OCR en v1 |
| C5 | Añadir contenido | Fuera de v1 |
| C6 | Guardado | Incremental + backup automático |
| C7 | Firmas | Detectar, avisar, confirmar |
| C8 | Forms/capas/cifrado | Preservar, no soportar |
| C9 | Idiomas | Solo latino en v1 |
| D1 | Corpus | ~20 PDFs reales en CI |
| D2 | Huérfanos | Eliminar al guardar |
| D3 | Rendimiento | 100 págs <2 s |
| D4 | Multi-selección | Sí; alinear no |
| D5 | Selección | Caja con tolerancia + hit-test |
| E1 | Empaquetado | Flatpak primero |
| E2 | Release 1 | Sin edición de texto |
| E3 | Telemetría | Cero |
| E4 | i18n | EN + ES + DE |
| E5 | Éxito | 10 usuarios externos editando sin romper |
