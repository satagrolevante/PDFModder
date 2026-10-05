# PDF Modder 2.0.0

Esta versión implementa las mejoras solicitadas 1, 2, 3, 4, 6, 7, 8, 10, 12,
14, 17 y 18. Funciona localmente en Windows x64. El archivo original se conserva.

## Uso de las herramientas nuevas

- **Pestañas:** Abrir, arrastrar uno o varios PDF o abrir un reciente crea pestañas
  independientes. Cada una conserva página, zoom e historial. Acepta o cancela
  un borrador antes de cambiar de pestaña. Comparar dos documentos muestra sus
  páginas actuales con zoom y desplazamiento vertical vinculado.
- **Compatibilidad:** selecciona texto en Herramientas. El panel comprueba su
  recurso y muestra si es editable, condicional o bloqueado, con una acción
  concreta. El compositor sigue validando los nuevos caracteres y el resultado.
- **Aceptar texto:** doble clic abre el editor. Aceptar / Ctrl+Intro valida y
  aplica una sola operación; Cancelar / Escape conserva el estado previo. Una
  validación fallida conserva lo escrito. Guardar como exporta una copia.
- **Celda o párrafo:** Edición del contenido → Delimitar párrafo / celda.
  Dibuja su área, ajusta margen interior y alineación, y escribe. Intro crea
  párrafo; Mayús+Intro crea línea. El cuadro mantiene sus dimensiones y tamaño
  de fuente. Desbordamiento exige ampliar el área o modificar formato explícito.
  Para importes elige Derecha; el panel habitual mantiene anclaje decimal.
- **Fuentes:** el inspector presenta recurso original, programa incrustado,
  contornos, cobertura y certeza. Se añaden fuentes OTF estáticas CFF con métricas
  y codificación verificables. NFC compone acentos equivalentes dentro del tramo.
- **Imagen girada:** su recorte se expresa en los ejes propios de la imagen,
  conservando píxeles, alfa y demás instancias. Restablecer proporciones cambia
  a Encajar, conservando su marco. Los ppp efectivos ayudan a valorar ampliaciones.
- **Formulario:** Propiedades y herramientas avanzadas → Campos de formulario.
  Elige un campo, modifica valor o posición/tamaño y revisa el PDF previo a
  aceptar. Guardar conserva campos rellenables y sus datos canónicos.
- **Censura definitiva:** dibuja y revisa zonas en sus páginas, genera el PDF
  realmente censurado, acepta y guarda una copia. Se eliminan texto/OCR y
  píxeles cubiertos; no se conservan como una revisión anterior de la copia.
  Otras apariciones legítimas, adjuntos y metadatos requieren revisión separada.
- **Imprimir:** Ctrl+P permite elegir páginas, papel, orientación, tamaño real
  o ajuste y resolución, con vista previa y diálogo de impresora de Windows.
  Se prepara por páginas con memoria limitada. La impresión usa imágenes
  renderizadas; Guardar como y Extraer conservan texto/vector en PDF.
- **Recuperar trabajo:** después de un cierre inesperado se ofrecen checkpoints
  locales de historial y borradores. Revísalos antes de guardar. No se almacenan
  contraseñas ni claves privadas. Cerrar descartando borra esa recuperación.

## Compatibilidad e integridad

Las instancias Form se aíslan antes de modificar operadores. No cambia el
recurso compartido original. Transparencia de grupo, capas o estructura de
accesibilidad ambigua siguen requiriendo un tratamiento específico de la
instancia afectada. Detalles en COMPATIBILIDAD_FUENTES_V200.md.

Los formularios con cálculos JavaScript conservan sus scripts y orden de
cálculo; cambiar valores que necesitan ejecutar dichos cálculos se bloquea.
XFA, firmas, botones y grupos de radio requieren soporte adicional. La censura
bloquea zonas con estructuras que puedan dejar datos ocultos o dañar vecinos;
los PDF etiquetados requieren una copia sin etiquetas. Detalles en
GUIA_MEDIOS_FORMULARIOS_CENSURA_V200.md.

La comprobación previa no acredita compatibilidad universal. Las comprobaciones
dirigidas usan documentos sintéticos reproducibles y extracción independiente;
el corpus privado del usuario no se ha vuelto a revisar completo para esta versión.

## Construcción reproducible

En Windows 11 con Python 3.12 x64:

```powershell
.\scripts\install.ps1 -Development
.\.venv\Scripts\python.exe scripts/release_v170.py --tests tests/test_form_instances_v200.py tests/test_cff_extension_v200.py tests/test_preflight_fonts_v200.py tests/test_cell_v200.py tests/test_forms_redaction_media_v200.py tests/test_workspace_recovery_v200.py tests/test_printing_v200.py
```

La construcción recopila licencias y fuentes correspondientes, ejecuta sólo
esas pruebas y el recorrido GUI v200, y crea instalador, desinstalador y portable
en `releases/v2.0.0`. GitHub Actions usa el mismo procedimiento y publica el
manifiesto público de actualizaciones.
