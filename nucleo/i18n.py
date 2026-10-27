"""Internacionalización (i18n) para IntactPDF.

Idiomas soportados:
- es: Español (predeterminado / nativo)
- en: English
- de: Deutsch
- zh: 中文 (简体中文)

Detecta automáticamente el idioma del sistema a través de las variables de entorno
(LANG, LC_ALL, LC_MESSAGES) y permite fijar o cambiar el idioma en caliente tanto
en la interfaz gráfica (GUI) como en la línea de comandos (CLI).
"""
from __future__ import annotations

import locale
import os
from typing import Any

IDIOMAS_DISPONIBLES = {
    "es": "Español",
    "en": "English",
    "de": "Deutsch",
    "zh": "简体中文",
}

_CADENAS: dict[str, dict[str, str]] = {
    "es": {
        # Ventana principal
        "app_titulo": "IntactPDF",
        "bienvenida_titulo": "Bienvenido a IntactPDF",
        "bienvenida_subtitulo": (
            "Modifica texto, imágenes y figuras de tus documentos PDF "
            "preservando el 100% del archivo original."
        ),
        "paso1_tit": "1. Abre o arrastra tu PDF",
        "paso1_desc": "Abre cualquier documento arrastrándolo a esta ventana o mediante el botón Abrir.",
        "paso2_tit": "2. Haz clic sobre lo que quieras cambiar",
        "paso2_desc": "Pincha en textos, imágenes o vectores. Con clics sucesivos se ciclan capas superpuestas.",
        "paso3_tit": "3. Edita con tranquilidad",
        "paso3_desc": "Sustituye logotipos, corrige textos y gira páginas manteniendo intacto el 100% del diseño original.",
        "btn_abrir_pdf": "Abrir archivo PDF",
        "btn_guia_tutorial": "Guía Rápida / Tutorial",
        "banner_firma": "Documento firmado digitalmente: Cualquier edición invalidará la firma criptográfica existente.",
        "panel_lateral_titulo": "Objetos de la página",
        "fila_cajas_titulo": "Marcar todos los objetos",
        "fila_cajas_sub": "Un contorno tenue en cada cosa seleccionable",

        # Cinta - Pestañas
        "tab_inicio": "Inicio",
        "tab_objeto": "Objeto",
        "tab_texto": "Texto",
        "tab_pagina": "Página",
        "tab_ver": "Ver",

        # Cinta - Grupos
        "grp_documento": "Documento",
        "grp_objeto": "Objeto",
        "grp_mover": "Mover",
        "grp_tamano": "Tamaño",
        "grp_imagen": "Imagen",
        "grp_borrar": "Borrar",
        "grp_seleccion": "Selección",
        "grp_edicion": "Edición",
        "grp_tipografia": "Tipografía",
        "grp_reglas": "Reglas",
        "grp_medidas": "Medidas",
        "grp_girar": "Girar",
        "grp_herramientas": "Herramientas",
        "grp_zoom": "Zoom",
        "grp_paneles": "Paneles",
        "grp_entorno": "Entorno",
        "grp_idioma": "Idioma",

        # Botones y acciones
        "btn_abrir": "Abrir",
        "btn_abrir_tip": "Abrir un PDF (Ctrl+O)",
        "btn_guardar": "Guardar",
        "btn_guardar_tip": "Guardar sobre el original (Ctrl+S)",
        "btn_guardar_como": "Guardar como",
        "btn_guardar_como_tip": "Guardar en otro fichero (Ctrl+Mayús+S)",
        "btn_deshacer": "Deshacer",
        "btn_deshacer_tip": "Deshacer el último cambio (Ctrl+Z)",
        "btn_rehacer": "Rehacer",
        "btn_rehacer_tip": "Rehacer el cambio deshecho (Ctrl+Y)",
        "btn_borrar": "Borrar",
        "btn_borrar_tip": "Borrar el objeto seleccionado (Supr)",
        "btn_editar_texto": "Editar texto",
        "btn_editar_texto_tip": "Cambiar el texto seleccionado (Ctrl+E)",
        "btn_escalar": "Escalar",
        "btn_escalar_tip": "Redimensionar el objeto seleccionado (doble clic)",
        "btn_extraer": "Extraer",
        "btn_extraer_tip": "Guardar imagen seleccionada en archivo",
        "btn_reemplazar": "Reemplazar",
        "btn_reemplazar_tip": "Sustituir la imagen por otra conservando posición",
        "btn_girar_der_tip": "Girar 90° a la derecha",
        "btn_girar_izq_tip": "Girar 90° a la izquierda",
        "btn_info": "Información",
        "btn_info_tip": "Qué hay dentro del documento",
        "btn_fuentes": "Fuentes",
        "btn_fuentes_tip": "Fuentes de esta página y qué admiten",
        "btn_comprobar": "Comprobar",
        "btn_comprobar_tip": "Validar el fichero con libqpdf",
        "btn_compactar": "Compactar",
        "btn_compactar_tip": "Purgar historial de revisiones (redacción segura)",
        "btn_diagnostico": "Diagnóstico",
        "btn_diagnostico_tip": "Comprobar que están las dependencias y las fuentes",
        "btn_zoom_ancho": "Ajustar ancho",
        "btn_zoom_ancho_tip": "Ajustar el zoom al ancho de la ventana",
        "btn_zoom_real": "100 %",
        "btn_zoom_real_tip": "Un punto del PDF, un píxel en pantalla (Ctrl+0)",
        "btn_ayuda_tip": "Guía didáctica y atajos de teclado",
        "chk_panel_objetos": "Panel de objetos",
        "chk_panel_objetos_tip": "Enseñar u ocultar la lista de objetos",
        "chk_marcar_todo": "Marcar todo lo seleccionable",
        "chk_marcar_todo_tip": "Un contorno tenue en cada objeto que se puede pinchar",
        "chk_ajustar_espaciado": "Ajustar el espaciado",
        "chk_ajustar_espaciado_tip": (
            "Desactivado por omisión para mantener la tipografía natural. "
            "Actívalo solo si deseas forzar que el texto ocupe exactamente el ancho previo."
        ),
        "regla_tipografia_titulo": "No se sustituye la tipografía",
        "regla_tipografia_desc": (
            "Se conserva la tipografía del documento: no se cambia nunca en silencio.\n\n"
            "Si al texto nuevo le falta un glifo, se incrusta un subconjunto de una fuente "
            "del sistema como fuente APARTE y la fuente original no se toca, para que el resto "
            "del documento siga siendo byte a byte el mismo."
        ),
        "sel_nada": "nada seleccionado",

        # Diálogos
        "dlg_editar_texto_tit": "Editar el texto",
        "dlg_editar_texto_sw": "Ajustar espaciado al ancho original",
        "dlg_editar_texto_sw_sub": "Forzar que el nuevo texto ocupe el mismo ancho horizontal (puede alterar separación de letras)",
        "dlg_escalar_tit": "Redimensionar",
        "dlg_escalar_pct": "% del tamaño actual",
        "dlg_descartar_tit": "¿Guardar los cambios antes de salir?",
        "dlg_descartar_desc": "Si cierras sin guardar, perderás las modificaciones realizadas.",
        "dlg_descartar_btn_descartar": "Descartar",
        "dlg_descartar_btn_cancelar": "Cancelar",
        "dlg_descartar_btn_guardar": "Guardar",

        # Tutorial GUI
        "tut_titulo": "Guía y Tutorial de IntactPDF",
        "tut_pag1_tit": "Primeros Pasos",
        "tut_pag1_grp_tit": "Cómo editar tu PDF de forma segura",
        "tut_pag1_grp_desc": (
            "IntactPDF solo modifica exactamente lo que seleccionas. El resto del archivo "
            "se conserva 100% idéntico mediante guardado incremental ISO 32000."
        ),
        "tut_row_sel_tit": "Selección fácil y precisa",
        "tut_row_sel_sub": "Haz clic sobre cualquier palabra, imagen o forma. Si hay elementos superpuestos, vuelve a hacer clic en el mismo punto para ciclar entre ellos.",
        "tut_row_txt_tit": "Edición de texto natural",
        "tut_row_txt_sub": "Haz doble clic en una palabra o pulsa Ctrl+E. Escribe el texto nuevo; la tipografía se conserva de forma natural sin distorsionar el espaciado.",
        "tut_row_mov_tit": "Mover y transformar",
        "tut_row_mov_sub": "Arrastra con el ratón para desplazar un objeto, o usa la pestaña «Objeto» para moverlo por puntos exactos (pt) o escalarlo.",

        "tut_pag2_tit": "Imágenes y Páginas",
        "tut_pag2_grp_tit": "Gestión de logotipos e ilustraciones",
        "tut_row_rep_tit": "Sustituir una imagen",
        "tut_row_rep_sub": "Selecciona la imagen y pulsa «Reemplazar» en la cinta Objeto. La nueva foto o logotipo encajará en las coordenadas y tamaño exactos del original, preservando transparencias.",
        "tut_row_ext_tit": "Extraer imágenes a disco",
        "tut_row_ext_sub": "Pulsa «Extraer» para guardar cualquier imagen del PDF en formato PNG o JPG nativo.",
        "tut_row_rot_tit": "Girar páginas",
        "tut_row_rot_sub": "En la pestaña «Página», usa los botones de rotación para reorientar cualquier página al instante sin alterar el resto.",

        "tut_pag3_tit": "Atajos de teclado",
        "tut_pag3_grp_tit": "Atajos rápidos de teclado",
        "tut_sh_abrir": "Abrir un archivo PDF",
        "tut_sh_guardar": "Guardar sobre el archivo original (con respaldo .pdf~)",
        "tut_sh_guardar_como": "Guardar como copia en otro archivo",
        "tut_sh_editar": "Editar el texto del objeto seleccionado",
        "tut_sh_deshacer": "Deshacer el último cambio",
        "tut_sh_rehacer": "Rehacer el cambio",
        "tut_sh_copiar": "Copiar el texto seleccionado al portapapeles",
        "tut_sh_zoom_scroll": "Zoom continuo centrado",
        "tut_sh_zoom_keys": "Aumentar, reducir o ajustar zoom al 100%",
        "tut_sh_borrar": "Borrar el objeto seleccionado",
        "tut_sh_doble_clic": "Editar texto o escalar objeto",
    },

    "en": {
        # Main Window
        "app_titulo": "IntactPDF",
        "bienvenida_titulo": "Welcome to IntactPDF",
        "bienvenida_subtitulo": (
            "Modify text, images, and shapes in PDF documents "
            "while preserving 100% of the original file bytes."
        ),
        "paso1_tit": "1. Open or drag your PDF",
        "paso1_desc": "Open any document by dragging it onto this window or using the Open button.",
        "paso2_tit": "2. Click what you want to change",
        "paso2_desc": "Click on text, images, or vectors. Successive clicks cycle through overlapping layers.",
        "paso3_tit": "3. Edit with confidence",
        "paso3_desc": "Replace logos, modify text, and rotate pages while keeping 100% of the original design intact.",
        "btn_abrir_pdf": "Open PDF File",
        "btn_guia_tutorial": "Quick Guide / Tutorial",
        "banner_firma": "Digitally signed document: Any modification will invalidate the cryptographic signature.",
        "panel_lateral_titulo": "Page Objects",
        "fila_cajas_titulo": "Highlight all objects",
        "fila_cajas_sub": "A faint outline around every selectable element",

        # Ribbon - Tabs
        "tab_inicio": "Home",
        "tab_objeto": "Object",
        "tab_texto": "Text",
        "tab_pagina": "Page",
        "tab_ver": "View",

        # Ribbon - Groups
        "grp_documento": "Document",
        "grp_objeto": "Object",
        "grp_mover": "Move",
        "grp_tamano": "Size",
        "grp_imagen": "Image",
        "grp_borrar": "Delete",
        "grp_seleccion": "Selection",
        "grp_edicion": "Editing",
        "grp_tipografia": "Typography",
        "grp_reglas": "Rules",
        "grp_medidas": "Metrics",
        "grp_girar": "Rotate",
        "grp_herramientas": "Tools",
        "grp_zoom": "Zoom",
        "grp_paneles": "Panels",
        "grp_entorno": "Environment",
        "grp_idioma": "Language",

        # Buttons & actions
        "btn_abrir": "Open",
        "btn_abrir_tip": "Open a PDF (Ctrl+O)",
        "btn_guardar": "Save",
        "btn_guardar_tip": "Save over original (Ctrl+S)",
        "btn_guardar_como": "Save As",
        "btn_guardar_como_tip": "Save as a different file (Ctrl+Shift+S)",
        "btn_deshacer": "Undo",
        "btn_deshacer_tip": "Undo last change (Ctrl+Z)",
        "btn_rehacer": "Redo",
        "btn_rehacer_tip": "Redo undone change (Ctrl+Y)",
        "btn_borrar": "Delete",
        "btn_borrar_tip": "Delete selected object (Del)",
        "btn_editar_texto": "Edit text",
        "btn_editar_texto_tip": "Change selected text (Ctrl+E)",
        "btn_escalar": "Scale",
        "btn_escalar_tip": "Resize selected object (double click)",
        "btn_extraer": "Extract",
        "btn_extraer_tip": "Save selected image to file",
        "btn_reemplazar": "Replace",
        "btn_reemplazar_tip": "Replace image preserving position",
        "btn_girar_der_tip": "Rotate 90° right",
        "btn_girar_izq_tip": "Rotate 90° left",
        "btn_info": "Info",
        "btn_info_tip": "Document structure and metadata",
        "btn_fuentes": "Fonts",
        "btn_fuentes_tip": "Page fonts and character support",
        "btn_comprobar": "Check",
        "btn_comprobar_tip": "Validate file with libqpdf",
        "btn_compactar": "Compact",
        "btn_compactar_tip": "Purge revision history (secure redaction)",
        "btn_diagnostico": "Diagnostics",
        "btn_diagnostico_tip": "Check system dependencies and fonts",
        "btn_zoom_ancho": "Fit width",
        "btn_zoom_ancho_tip": "Fit page zoom to window width",
        "btn_zoom_real": "100 %",
        "btn_zoom_real_tip": "One PDF point equals one screen pixel (Ctrl+0)",
        "btn_ayuda_tip": "Interactive guide and keyboard shortcuts",
        "chk_panel_objetos": "Object panel",
        "chk_panel_objetos_tip": "Show or hide the object list",
        "chk_marcar_todo": "Highlight selectable objects",
        "chk_marcar_todo_tip": "A faint outline around every clickable element",
        "chk_ajustar_espaciado": "Adjust character spacing",
        "chk_ajustar_espaciado_tip": (
            "Disabled by default to preserve natural typography. "
            "Enable only if you need the new text to match the exact previous width."
        ),
        "regla_tipografia_titulo": "Typography is preserved",
        "regla_tipografia_desc": (
            "The document's original fonts are never altered or silently substituted.\n\n"
            "If new text requires missing glyphs, a subset from a system font is embedded "
            "as a separate resource without modifying the original font stream."
        ),
        "sel_nada": "nothing selected",

        # Dialogs
        "dlg_editar_texto_tit": "Edit Text",
        "dlg_editar_texto_sw": "Fit to original width",
        "dlg_editar_texto_sw_sub": "Force new text to occupy previous bounding width (may alter character spacing)",
        "dlg_escalar_tit": "Resize",
        "dlg_escalar_pct": "% of current size",
        "dlg_descartar_tit": "Save changes before closing?",
        "dlg_descartar_desc": "If you close without saving, your modifications will be lost.",
        "dlg_descartar_btn_descartar": "Discard",
        "dlg_descartar_btn_cancelar": "Cancel",
        "dlg_descartar_btn_guardar": "Save",

        # Tutorial GUI
        "tut_titulo": "IntactPDF Guide & Tutorial",
        "tut_pag1_tit": "Getting Started",
        "tut_pag1_grp_tit": "How to edit your PDF safely",
        "tut_pag1_grp_desc": (
            "IntactPDF only modifies exactly what you select. The rest of the document "
            "remains 100% byte-for-byte identical via ISO 32000 incremental update."
        ),
        "tut_row_sel_tit": "Precise & Easy Selection",
        "tut_row_sel_sub": "Click any word, image, or shape. If elements overlap, click repeatedly on the same spot to cycle through layers.",
        "tut_row_txt_tit": "Natural Text Editing",
        "tut_row_txt_sub": "Double-click a word or press Ctrl+E. Type the new text; natural typography is preserved without awkward spacing distortions.",
        "tut_row_mov_tit": "Move & Transform",
        "tut_row_mov_sub": "Drag with your mouse to reposition an object, or use the 'Object' tab to move by exact points (pt) or scale.",

        "tut_pag2_tit": "Images & Pages",
        "tut_pag2_grp_tit": "Managing logos and figures",
        "tut_row_rep_tit": "Replace an image",
        "tut_row_rep_sub": "Select an image and click 'Replace' on the Object tab. The new photo or logo automatically adopts the exact coordinates and dimensions while keeping transparency.",
        "tut_row_ext_tit": "Extract images to disk",
        "tut_row_ext_sub": "Click 'Extract' to save any embedded PDF image in native PNG or JPG format.",
        "tut_row_rot_tit": "Rotate pages",
        "tut_row_rot_sub": "On the 'Page' tab, use the rotation buttons to reorient any page instantly without modifying other pages.",

        "tut_pag3_tit": "Shortcuts",
        "tut_pag3_grp_tit": "Keyboard Shortcuts",
        "tut_sh_abrir": "Open a PDF document",
        "tut_sh_guardar": "Save over original file (with .pdf~ backup)",
        "tut_sh_guardar_como": "Save copy to a new file",
        "tut_sh_editar": "Edit selected text object",
        "tut_sh_deshacer": "Undo last change",
        "tut_sh_rehacer": "Redo undone change",
        "tut_sh_copiar": "Copy selected text to clipboard",
        "tut_sh_zoom_scroll": "Smooth centered zoom",
        "tut_sh_zoom_keys": "Zoom in, zoom out, or reset to 100%",
        "tut_sh_borrar": "Delete selected object",
        "tut_sh_doble_clic": "Edit text or scale object",
    },

    "de": {
        # Hauptfenster
        "app_titulo": "IntactPDF",
        "bienvenida_titulo": "Willkommen bei IntactPDF",
        "bienvenida_subtitulo": (
            "Bearbeiten Sie Texte, Bilder und Formen in PDF-Dokumenten "
            "unter vollständiger Bewahrung der originalen Dateistruktur."
        ),
        "paso1_tit": "1. PDF öffnen oder hineinziehen",
        "paso1_desc": "Öffnen Sie Dokumente per Drag-and-Drop in dieses Fenster oder über die Schaltfläche Öffnen.",
        "paso2_tit": "2. Gewünschtes Element anklicken",
        "paso2_desc": "Klicken Sie auf Text, Bilder oder Vektoren. Wiederholtes Klicken wechselt durch überlagerte Ebenen.",
        "paso3_tit": "3. Sorgenfrei bearbeiten",
        "paso3_desc": "Tauschen Sie Logos aus, korrigieren Sie Texte und drehen Sie Seiten bei 100% unverändertem Layout.",
        "btn_abrir_pdf": "PDF-Datei öffnen",
        "btn_guia_tutorial": "Kurzanleitung / Tutorial",
        "banner_firma": "Digital signiertes Dokument: Jede Bearbeitung macht die kryptografische Signatur ungültig.",
        "panel_lateral_titulo": "Seitenobjekte",
        "fila_cajas_titulo": "Alle Objekte hervorheben",
        "fila_cajas_sub": "Ein feiner Umriss um jedes auswählbare Objekt",

        # Menüband - Registerkarten
        "tab_inicio": "Start",
        "tab_objeto": "Objekt",
        "tab_texto": "Text",
        "tab_pagina": "Seite",
        "tab_ver": "Ansicht",

        # Menüband - Gruppen
        "grp_documento": "Dokument",
        "grp_objeto": "Objekt",
        "grp_mover": "Verschieben",
        "grp_tamano": "Größe",
        "grp_imagen": "Bild",
        "grp_borrar": "Löschen",
        "grp_seleccion": "Auswahl",
        "grp_edicion": "Bearbeitung",
        "grp_tipografia": "Typografie",
        "grp_reglas": "Regeln",
        "grp_medidas": "Maße",
        "grp_girar": "Drehen",
        "grp_herramientas": "Werkzeuge",
        "grp_zoom": "Zoom",
        "grp_paneles": "Leisten",
        "grp_entorno": "Umgebung",
        "grp_idioma": "Sprache",

        # Schaltflächen & Aktionen
        "btn_abrir": "Öffnen",
        "btn_abrir_tip": "PDF öffnen (Strg+O)",
        "btn_guardar": "Speichern",
        "btn_guardar_tip": "Original überschreiben (Strg+S)",
        "btn_guardar_como": "Speichern unter",
        "btn_guardar_como_tip": "Als neue Datei speichern (Strg+Umschalt+S)",
        "btn_deshacer": "Rückgängig",
        "btn_deshacer_tip": "Letzte Änderung rückgängig machen (Strg+Z)",
        "btn_rehacer": "Wiederholen",
        "btn_rehacer_tip": "Rückgängig gemachte Änderung wiederholen (Strg+Y)",
        "btn_borrar": "Löschen",
        "btn_borrar_tip": "Ausgewähltes Objekt löschen (Entf)",
        "btn_editar_texto": "Text bearbeiten",
        "btn_editar_texto_tip": "Ausgewählten Text ändern (Strg+E)",
        "btn_escalar": "Skalieren",
        "btn_escalar_tip": "Objektgröße anpassen (Doppelklick)",
        "btn_extraer": "Extrahieren",
        "btn_extraer_tip": "Ausgewähltes Bild in Datei speichern",
        "btn_reemplazar": "Ersetzen",
        "btn_reemplazar_tip": "Bild unter Beibehaltung der Position austauschen",
        "btn_girar_der_tip": "90° im Uhrzeigersinn drehen",
        "btn_girar_izq_tip": "90° gegen den Uhrzeigersinn drehen",
        "btn_info": "Info",
        "btn_info_tip": "Dokumentenstruktur und Metadaten",
        "btn_fuentes": "Schriften",
        "btn_fuentes_tip": "Schriftarten dieser Seite und Glyphenunterstützung",
        "btn_comprobar": "Prüfen",
        "btn_comprobar_tip": "Datei mit libqpdf validieren",
        "btn_compactar": "Bereinigen",
        "btn_compactar_tip": "Revisionsverlauf entfernen (sichere Redaktion)",
        "btn_diagnostico": "Diagnose",
        "btn_diagnostico_tip": "Systemabhängigkeiten und Schriften überprüfen",
        "btn_zoom_ancho": "Breite anpassen",
        "btn_zoom_ancho_tip": "Zoom an Fensterbreite anpassen",
        "btn_zoom_real": "100 %",
        "btn_zoom_real_tip": "Ein PDF-Punkt entspricht einem Bildschirmpixel (Strg+0)",
        "btn_ayuda_tip": "Kurzanleitung und Tastenkombinationen",
        "chk_panel_objetos": "Objektleiste",
        "chk_panel_objetos_tip": "Objektliste ein- oder ausblenden",
        "chk_marcar_todo": "Auswählbare Objekte markieren",
        "chk_marcar_todo_tip": "Feiner Rahmen um alle anklickbaren Elemente",
        "chk_ajustar_espaciado": "Zeichenabstand anpassen",
        "chk_ajustar_espaciado_tip": (
            "Standardmäßig deaktiviert für natürliche Typografie. "
            "Aktivieren Sie dies nur, wenn der neue Text exakt die vorherige Breite ausfüllen soll."
        ),
        "regla_tipografia_titulo": "Typografie bleibt erhalten",
        "regla_tipografia_desc": (
            "Die Originalschriften des Dokuments werden niemals stillschweigend verändert.\n\n"
            "Falls neue Zeichen fehlen, wird eine Teilmenge einer Systemschrift als "
            "separate Ressource eingebettet, ohne die Originalschrift anzutasten."
        ),
        "sel_nada": "nichts ausgewählt",

        # Dialoge
        "dlg_editar_texto_tit": "Text bearbeiten",
        "dlg_editar_texto_sw": "An Originalbreite anpassen",
        "dlg_editar_texto_sw_sub": "Erzwingt dieselbe Breite (kann Zeichenabstände verändern)",
        "dlg_escalar_tit": "Größe anpassen",
        "dlg_escalar_pct": "% der aktuellen Größe",
        "dlg_descartar_tit": "Änderungen vor dem Schließen speichern?",
        "dlg_descartar_desc": "Wenn Sie ohne Speichern schließen, gehen alle Änderungen verloren.",
        "dlg_descartar_btn_descartar": "Verwerfen",
        "dlg_descartar_btn_cancelar": "Abbrechen",
        "dlg_descartar_btn_guardar": "Speichern",

        # Tutorial GUI
        "tut_titulo": "IntactPDF Anleitung & Tutorial",
        "tut_pag1_tit": "Erste Schritte",
        "tut_pag1_grp_tit": "Sichere PDF-Bearbeitung",
        "tut_pag1_grp_desc": (
            "IntactPDF verändert ausschließlich die ausgewählten Objekte. Der Rest der "
            "Datei bleibt dank ISO 32000 inkrementeller Speicherung exakt bitgenau erhalten."
        ),
        "tut_row_sel_tit": "Einfache & präzise Auswahl",
        "tut_row_sel_sub": "Klicken Sie auf ein Wort, Bild oder eine Form. Wiederholtes Klicken wechselt nahtlos durch überlagerte Ebenen.",
        "tut_row_txt_tit": "Natürliche Textbearbeitung",
        "tut_row_txt_sub": "Doppelklicken Sie auf ein Wort oder drücken Sie Strg+E. Die Typografie bleibt natürlich erhalten.",
        "tut_row_mov_tit": "Verschieben & Skalieren",
        "tut_row_mov_sub": "Ziehen Sie Objekte mit der Maus oder nutzen Sie den Reiter 'Objekt' für exakte Punktverschiebungen.",

        "tut_pag2_tit": "Bilder & Seiten",
        "tut_pag2_grp_tit": "Verwaltung von Logos und Abbildungen",
        "tut_row_rep_tit": "Bild ersetzen",
        "tut_row_rep_sub": "Wählen Sie ein Bild und klicken Sie auf 'Ersetzen'. Das neue Bild übernimmt exakt Position, Größe und Transparenzen.",
        "tut_row_ext_tit": "Bilder exportieren",
        "tut_row_ext_sub": "Klicken Sie auf 'Extrahieren', um beliebige Bilder als PNG oder JPG auf Festplatte zu speichern.",
        "tut_row_rot_tit": "Seiten drehen",
        "tut_row_rot_sub": "Nutzen Sie im Reiter 'Seite' die Drehen-Schaltflächen zur sofortigen Neuausrichtung beliebiger Seiten.",

        "tut_pag3_tit": "Tastenkombinationen",
        "tut_pag3_grp_tit": "Häufige Tastenkürzel",
        "tut_sh_abrir": "PDF-Datei öffnen",
        "tut_sh_guardar": "Originaldatei speichern (mit .pdf~ Sicherung)",
        "tut_sh_guardar_como": "Als Kopie speichern",
        "tut_sh_editar": "Ausgewählten Text bearbeiten",
        "tut_sh_deshacer": "Letzte Aktion rückgängig",
        "tut_sh_rehacer": "Aktion wiederholen",
        "tut_sh_copiar": "Ausgewählten Text in Zwischenablage kopieren",
        "tut_sh_zoom_scroll": "Stufenloser zentrierter Zoom",
        "tut_sh_zoom_keys": "Vergrößern, verkleinern oder auf 100% zurücksetzen",
        "tut_sh_borrar": "Ausgewähltes Objekt löschen",
        "tut_sh_doble_clic": "Text bearbeiten oder Objekt skalieren",
    },

    "zh": {
        # 主窗口
        "app_titulo": "IntactPDF",
        "bienvenida_titulo": "欢迎使用 IntactPDF",
        "bienvenida_subtitulo": (
            "在修改 PDF 文本、图像和矢量形状的同时，"
            "100% 保持原始文件字节与排版完整。"
        ),
        "paso1_tit": "1. 打开或拖入 PDF",
        "paso1_desc": "将任意 PDF 文件拖入此窗口，或点击“打开”按钮。",
        "paso2_tit": "2. 点击想要修改的元素",
        "paso2_desc": "点击文本、图像或形状。连续点击可循环选择重叠图层中的元素。",
        "paso3_tit": "3. 放心编辑保存",
        "paso3_desc": "替换 Logo、修改文本、旋转页面，完全不破坏原文件的其他任何部分。",
        "btn_abrir_pdf": "打开 PDF 文件",
        "btn_guia_tutorial": "快速指南 / 教程",
        "banner_firma": "数字签名文档：任何修改都将使现有的加密电子签名失效。",
        "panel_lateral_titulo": "页面对象",
        "fila_cajas_titulo": "标记所有可选对象",
        "fila_cajas_sub": "在每个可选元素周围显示微弱轮廓",

        # 功能区 - 标签页
        "tab_inicio": "开始",
        "tab_objeto": "对象",
        "tab_texto": "文本",
        "tab_pagina": "页面",
        "tab_ver": "视图",

        # 功能区 - 分组
        "grp_documento": "文档",
        "grp_objeto": "对象",
        "grp_mover": "移动",
        "grp_tamano": "大小",
        "grp_imagen": "图像",
        "grp_borrar": "删除",
        "grp_seleccion": "当前选择",
        "grp_edicion": "编辑",
        "grp_tipografia": "排版与字体",
        "grp_reglas": "排版规则",
        "grp_medidas": "页面尺寸",
        "grp_girar": "旋转",
        "grp_herramientas": "工具",
        "grp_zoom": "缩放",
        "grp_paneles": "面板",
        "grp_entorno": "运行环境",
        "grp_idioma": "语言 (Language)",

        # 按钮与操作
        "btn_abrir": "打开",
        "btn_abrir_tip": "打开 PDF 文件 (Ctrl+O)",
        "btn_guardar": "保存",
        "btn_guardar_tip": "保存并覆盖原文件 (Ctrl+S)",
        "btn_guardar_como": "另存为",
        "btn_guardar_como_tip": "另存为新文件 (Ctrl+Shift+S)",
        "btn_deshacer": "撤消",
        "btn_deshacer_tip": "撤消上一步修改 (Ctrl+Z)",
        "btn_rehacer": "恢复",
        "btn_rehacer_tip": "恢复已撤消的操作 (Ctrl+Y)",
        "btn_borrar": "删除",
        "btn_borrar_tip": "删除所选对象 (Del)",
        "btn_editar_texto": "编辑文本",
        "btn_editar_texto_tip": "修改所选文本内容 (Ctrl+E)",
        "btn_escalar": "缩放",
        "btn_escalar_tip": "调整所选对象尺寸 (双击)",
        "btn_extraer": "提取图像",
        "btn_extraer_tip": "将所选图像保存到本地文件",
        "btn_reemplazar": "替换图像",
        "btn_reemplazar_tip": "替换图像并保持原位置与透明度",
        "btn_girar_der_tip": "顺时针旋转 90°",
        "btn_girar_izq_tip": "逆时针旋转 90°",
        "btn_info": "文档信息",
        "btn_info_tip": "查看文档结构与元数据",
        "btn_fuentes": "字体列表",
        "btn_fuentes_tip": "查看本页字体及字形支持情况",
        "btn_comprobar": "验证检查",
        "btn_comprobar_tip": "使用 libqpdf 校验文件完整性",
        "btn_compactar": "压缩精简",
        "btn_compactar_tip": "清除历史修订版本（安全擦除）",
        "btn_diagnostico": "系统诊断",
        "btn_diagnostico_tip": "检查依赖库和系统字体",
        "btn_zoom_ancho": "适应宽度",
        "btn_zoom_ancho_tip": "缩放页面以适应窗口宽度",
        "btn_zoom_real": "100 %",
        "btn_zoom_real_tip": "以 1:1 实际比例显示 (Ctrl+0)",
        "btn_ayuda_tip": "使用教程与快捷键指南",
        "chk_panel_objetos": "对象列表面板",
        "chk_panel_objetos_tip": "显示或隐藏对象列表侧栏",
        "chk_marcar_todo": "标记所有可点选对象",
        "chk_marcar_todo_tip": "在所有可编辑对象周围绘制淡轮廓线",
        "chk_ajustar_espaciado": "调整字距以适应原宽",
        "chk_ajustar_espaciado_tip": (
            "默认关闭以保持字体的自然排版。"
            "仅当需要新文本严格填满原有宽度范围时再开启。"
        ),
        "regla_tipografia_titulo": "严格保持原始字体",
        "regla_tipografia_desc": (
            "IntactPDF 绝不悄悄替换原有字体。\n\n"
            "若新文本缺少某些字符字形，将从系统字体中提取字形子集作为独立资源嵌入，"
            "原字体流保持绝对一致。"
        ),
        "sel_nada": "未选择任何对象",

        # 对话框
        "dlg_editar_texto_tit": "编辑文本",
        "dlg_editar_texto_sw": "调整字距以填满原文本宽度",
        "dlg_editar_texto_sw_sub": "强制使新文本与原文本宽度一致（可能会改变字母间距）",
        "dlg_escalar_tit": "调整大小",
        "dlg_escalar_pct": "%（当前尺寸的百分比）",
        "dlg_descartar_tit": "退出前是否保存修改？",
        "dlg_descartar_desc": "如果未保存直接关闭，所有未保存的修改都将丢失。",
        "dlg_descartar_btn_descartar": "放弃修改",
        "dlg_descartar_btn_cancelar": "取消",
        "dlg_descartar_btn_guardar": "保存",

        # 教程 GUI
        "tut_titulo": "IntactPDF 使用指南与教程",
        "tut_pag1_tit": "新手入门",
        "tut_pag1_grp_tit": "如何安全精准地编辑 PDF",
        "tut_pag1_grp_desc": (
            "IntactPDF 仅修改您明确选中的对象。文件的其余部分"
            "通过 ISO 32000 增量更新机制保持 100% 原始字节不变。"
        ),
        "tut_row_sel_tit": "直观精准的对象选择",
        "tut_row_sel_sub": "点击任意文字、图片或图形。如果有重叠图层，在同一点连续点击即可在重叠元素间循环切换。",
        "tut_row_txt_tit": "自然的原生文字编辑",
        "tut_row_txt_sub": "双击文本或按 Ctrl+E 即可输入新文字，默认保持自然字距，不拉伸变形。",
        "tut_row_mov_tit": "平移与尺寸变换",
        "tut_row_mov_sub": "用鼠标直接拖动对象，或使用“对象”选项卡按精确点数（pt）微调位置与缩放比例。",

        "tut_pag2_tit": "图像与页面",
        "tut_pag2_grp_tit": "商标 Logo 与插图管理",
        "tut_row_rep_tit": "替换现有图像",
        "tut_row_rep_sub": "选中图片后点击“替换”按钮，新图片或 Logo 将完美继承原始坐标、尺寸与透明度通道。",
        "tut_row_ext_tit": "提取图片到磁盘",
        "tut_row_ext_sub": "点击“提取”按钮，可将文档中的任意内嵌图片以无损 PNG 或 JPG 格式保存。",
        "tut_row_rot_tit": "单页快捷旋转",
        "tut_row_rot_sub": "在“页面”标签页中，使用 90° 旋转按钮可即时校正单页方向，其他页面完全不受影响。",

        "tut_pag3_tit": "键盘快捷键",
        "tut_pag3_grp_tit": "高频快捷键速查",
        "tut_sh_abrir": "打开 PDF 文件",
        "tut_sh_guardar": "覆盖保存原文件（自动生成 .pdf~ 备份）",
        "tut_sh_guardar_como": "另存为新文件副本",
        "tut_sh_editar": "编辑当前所选文本",
        "tut_sh_deshacer": "撤消上一步修改",
        "tut_sh_rehacer": "恢复已撤消的操作",
        "tut_sh_copiar": "复制所选文本到剪贴板",
        "tut_sh_zoom_scroll": "以鼠标位置为中心平滑缩放",
        "tut_sh_zoom_keys": "放大、缩小或重置为 100% 实际大小",
        "tut_sh_borrar": "删除所选对象",
        "tut_sh_doble_clic": "快速编辑文本或缩放对象",
    },
}

_IDIOMA_ACTIVO: str = "es"


def detectar_idioma_sistema() -> str:
    """Detecta el código de idioma del entorno (es, en, de, zh)."""
    env_lang = (
        os.environ.get("INTACTPDF_LANG")
        or os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or ""
    ).lower()

    if env_lang.startswith("es"):
        return "es"
    elif env_lang.startswith("de"):
        return "de"
    elif env_lang.startswith("zh"):
        return "zh"
    elif env_lang.startswith("en"):
        return "en"

    # Intento con locale estándar de Python
    try:
        loc = locale.getlocale()[0]
        if loc:
            loc = loc.lower()
            if loc.startswith("es"):
                return "es"
            elif loc.startswith("de"):
                return "de"
            elif loc.startswith("zh"):
                return "zh"
            elif loc.startswith("en"):
                return "en"
    except Exception:
        pass

    return "es"


def fijar_idioma(idioma: str) -> None:
    """Fija el idioma activo para traducciones."""
    global _IDIOMA_ACTIVO
    if idioma in IDIOMAS_DISPONIBLES:
        _IDIOMA_ACTIVO = idioma


def idioma_actual() -> str:
    """Devuelve el código de idioma activo."""
    return _IDIOMA_ACTIVO


def t(clave: str, idioma: str | None = None, **kwargs: Any) -> str:
    """Obtiene la traducción de una clave en el idioma especificado o activo."""
    lang = idioma or _IDIOMA_ACTIVO
    if lang not in _CADENAS:
        lang = "es"

    texto = _CADENAS[lang].get(clave)
    if texto is None:
        # Fallback al español
        texto = _CADENAS["es"].get(clave, clave)

    if kwargs:
        try:
            return texto.format(**kwargs)
        except Exception:
            return texto
    return texto


def tutorial_cli(idioma: str | None = None) -> str:
    """Devuelve el texto completo del tutorial para terminal en el idioma indicado."""
    lang = idioma or _IDIOMA_ACTIVO
    if lang == "en":
        return """
================================================================================
                    INTACTPDF QUICK GUIDE & TUTORIAL
================================================================================

IntactPDF modifies existing objects (text, images, vector shapes) without
rebuilding the rest of the document. The output file preserves 100% of the
original bytes using standard ISO 32000-1 incremental updates.

1. GRAPHICAL INTERFACE (Recommended for visual editing):
   To open the desktop app with interactive preview and mouse editing:
     $ intactpdf-gui
     $ intactpdf-gui document.pdf

2. INSPECT WHAT A PAGE CONTAINS:
   To list all objects with their index, type, bounding box, and details:
     $ intactpdf list document.pdf --pagina 0

3. EDIT LOCALIZED TEXT:
   To modify text object #2 while keeping the original document intact:
     $ intactpdf edit document.pdf --object 2 --text "New Text" -o output.pdf
   To overwrite the original file with an automatic backup (.pdf~):
     $ intactpdf edit document.pdf --object 2 --text "New Text" --in-place

4. REPLACE OR EXTRACT IMAGES:
   To replace a logo maintaining exact scale, position, and transparency:
     $ intactpdf replace-image doc.pdf --xobject Im1 --imagen new_logo.png --in-place
   To extract an embedded image to PNG or JPG:
     $ intactpdf extract-image doc.pdf --xobject Im1 -o extracted_logo.png

5. ROTATE PAGES:
   To rotate 90 degrees clockwise without altering other pages:
     $ intactpdf rotate doc.pdf --pagina 0 --angulo 90 --in-place

6. PURGE HISTORY AND DELETED OBJECTS (Compact):
   To remove previous revisions and export a clean, optimized PDF:
     $ intactpdf compact doc.pdf -o clean.pdf

================================================================================
"""
    elif lang == "de":
        return """
================================================================================
                    INTACTPDF KURZANLEITUNG & TUTORIAL
================================================================================

IntactPDF bearbeitet vorhandene Objekte (Texte, Bilder, Vektoren), ohne den
Rest des Dokuments neu aufzubauen. Die Ausgabedatei bewahrt 100% der
Originalbytes durch standardkonforme ISO 32000-1 inkrementelle Aktualisierungen.

1. GRAFISCHE BENUTZEROBERFLÄCHE (Empfohlen für visuelle Bearbeitung):
   Starten Sie die Benutzeroberfläche mit Dokumentvorschau und Menüband:
     $ intactpdf-gui
     $ intactpdf-gui dokument.pdf

2. SEITENINHALT INSPEZIEREN:
   Auflisten aller Objekte mit Index, Typ und Koordinaten:
     $ intactpdf list dokument.pdf --pagina 0

3. TEXT GEZIELT BEARBEITEN:
   Ändern des Textobjekts #2 unter vollständiger Wahrung des restlichen Layouts:
     $ intactpdf edit dokument.pdf --object 2 --text "Neuer Text" -o ausgabe.pdf
   Überschreiben der Originaldatei mit automatischem Backup (.pdf~):
     $ intactpdf edit dokument.pdf --object 2 --text "Neuer Text" --in-place

4. BILDER ERSETZEN ODER EXTRAHIEREN:
   Austauschen eines Firmenlogos unter Beibehaltung der exakten Position:
     $ intactpdf replace-image doc.pdf --xobject Im1 --imagen neues_logo.png --in-place
   Extrahieren eines eingebetteten Bildes nach PNG oder JPG:
     $ intactpdf extract-image doc.pdf --xobject Im1 -o logo.png

5. SEITEN DREHEN:
   Drehen einer Einzelseite um 90 Grad im Uhrzeigersinn:
     $ intactpdf rotate doc.pdf --pagina 0 --angulo 90 --in-place

6. REVISIONSVERLAUF BEREINIGEN (Kompaktieren / Sichere Redaktion):
   Entfernen früherer Revisionsstände für ein sauberes, kompaktes PDF:
     $ intactpdf compact doc.pdf -o bereinigt.pdf

================================================================================
"""
    elif lang == "zh":
        return """
================================================================================
                    INTACTPDF 快速使用指南与教程
================================================================================

IntactPDF 可以在不重建文档其他部分的前提下，精准修改现有对象（文本、
图像、矢量图形）。通过符合 ISO 32000-1 标准的增量保存机制，输出文件
100% 完整保留原始文档的所有原有字节。

1. 图形界面（推荐日常可视化编辑使用）：
   启动带有实时渲染预览和功能区菜单的桌面窗口：
     $ intactpdf-gui
     $ intactpdf-gui document.pdf

2. 检查页面所含对象：
   列出页面上所有对象及其索引编号、类型和坐标范围：
     $ intactpdf list document.pdf --pagina 0

3. 修改局部文本：
   修改指定对象编号（例如 #2）的文字，其他文本与排版完全不受影响：
     $ intactpdf edit document.pdf --object 2 --text "新内容" -o 输出.pdf
   直接保存并覆盖原文件（自动生成 .pdf~ 安全备份）：
     $ intactpdf edit document.pdf --object 2 --text "新内容" --in-place

4. 替换或提取图像：
   替换 Logo 并保持原本的精确位置、缩放尺寸与透明通道：
     $ intactpdf replace-image doc.pdf --xobject Im1 --imagen 新Logo.png --in-place
   将 PDF 内嵌图片无损导出到本地 PNG 或 JPG：
     $ intactpdf extract-image doc.pdf --xobject Im1 -o 导出图片.png

5. 旋转页面：
   单页顺时针旋转 90 度：
     $ intactpdf rotate doc.pdf --pagina 0 --angulo 90 --in-place

6. 清除历史修订版本（压缩精简 / 安全擦除）：
   彻底删除历史旧版本，生成紧凑干净的独立 PDF：
     $ intactpdf compact doc.pdf -o 干净版.pdf

================================================================================
"""
    else:
        return """
================================================================================
                    TUTORIAL Y GUÍA RÁPIDA DE INTACTPDF
================================================================================

IntactPDF modifica objetos existentes (textos, imágenes, formas) sin reconstruir
el resto del documento. El archivo de salida conserva el 100% de los bytes
originales al inicio mediante actualización incremental estándar (ISO 32000-1).

1. INTERFAZ GRÁFICA (Recomendada para uso visual):
   Para abrir la ventana con previsualización, selección con ratón y cinta:
     $ intactpdf-gui
     $ intactpdf-gui documento.pdf

2. CONSULTAR QUÉ CONTIENE UNA PÁGINA:
   Para listar todos los objetos con su índice, tipo y coordenadas:
     $ intactpdf list documento.pdf --pagina 0

3. EDITAR TEXTO LOCALIZADO:
   Para modificar el texto del objeto #2 sin alterar la tipografía del resto:
     $ intactpdf edit documento.pdf --object 2 --text "Nuevo texto" -o salida.pdf
   Para sobrescribir sobre el original creando respaldo automático (.pdf~):
     $ intactpdf edit documento.pdf --object 2 --text "Nuevo texto" --in-place

4. SUSTITUIR O EXTRAER IMÁGENES:
   Para cambiar un logotipo manteniendo la posición y escala exacta:
     $ intactpdf replace-image doc.pdf --xobject Im1 --imagen nuevo_logo.png --in-place
   Para extraer una imagen incrustada a disco en PNG o JPG:
     $ intactpdf extract-image doc.pdf --xobject Im1 -o logo_extraido.png

5. GIRAR PÁGINAS:
   Para rotar 90 grados en el sentido de las agujas del reloj:
     $ intactpdf rotate doc.pdf --pagina 0 --angulo 90 --in-place

6. PURGAR HISTORIAL Y OBJETOS BORRADOS (Compactar):
   Para eliminar revisiones anteriores y dejar un PDF limpio y optimizado:
     $ intactpdf compact doc.pdf -o limpio.pdf

================================================================================
"""


# Inicialización automática al cargar el módulo
_IDIOMA_ACTIVO = detectar_idioma_sistema()
