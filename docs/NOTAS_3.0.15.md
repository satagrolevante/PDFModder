# PDFModder 3.0.15 — inserción y movimiento de texto

Cambios incluidos en el instalador público de la versión 3.0.16.

## Comportamiento

- El texto seleccionado se puede arrastrar desde su interior en el modo
  Seleccionar. No hace falta acertar en un borde estrecho. Los tiradores
  siguen redimensionando; Mayús + arrastrar selecciona caracteres y el doble
  clic conserva la edición. El modo Lectura conserva la selección para copiar.
- «Permitir solapamiento automáticamente» comienza activado para texto nuevo,
  edición, movimientos y formato. Permite las superposiciones compatibles
  conservando el contenido vecino y avisa cuando se producen. Se puede
  desactivar; la redistribución del texto vecino sigue siendo opcional.
- Añadir texto valida una sola vez el PDF final contra el original. El ancla
  temporal ya no provoca una segunda validación completa.
- Mover texto propio sin subrayados actualiza los operadores y sus metadatos
  en una escritura, sin retirar ni reconstruir decoraciones inexistentes.
- El análisis de operadores y los sondeos de recursos se reutilizan sólo para
  sus entradas exactas. La caché conserva datos inmutables, entrega objetos
  nuevos a cada consumidor y separa lectores estrictos y tolerantes. Los casos
  no compatibles o que exceden el presupuesto usan el analizador habitual.
  Presupuesto estimado: 48 MiB de sintaxis y 8 MiB de evidencias por sesión
  activa; se vacía al suspender o cerrar el documento.

## Integridad

Se siguen verificando los bytes exactos que se aplican: texto, posición,
tipografía, aspecto fuera de las zonas modificadas, imágenes, vectores,
campos, metadatos, marcadores, estructura y lectura independiente.
Antes de aislar contenido de un Form se comprueban los permisos y firmas
del original. Los recortes, bordes de página y campos interactivos conservan
sus comprobaciones. Activar el solapamiento no desactiva estas verificaciones.

## Medición con el adjunto

El archivo probado tiene 3 páginas y 1,7 MB. Su contenido original contiene
miles de dibujos vectoriales y ningún glifo de texto extraíble. Cada página
incluye aproximadamente 2 MB de operadores decodificados. El mensaje de
renderizado incluía también análisis de selección, fuentes e imágenes; el
renderizado de píxeles no era la causa principal de la demora.

Misma inserción sintética, fuente incluida, posición, desplazamiento y zoom.
Procesos independientes para la versión original y la corregida, sin
perfilador. Los totales incluyen preparación, aplicación y actualización
de la página:

| Operación | 3.0.14 | 3.0.15 | Reducción |
|---|---:|---:|---:|
| Añadir texto y actualizar página | 30,18 s | 15,44 s | 48,8 % |
| Mover texto y actualizar página | 32,39 s | 12,47 s | 61,5 % |

Son mediciones de este entorno, no un plazo garantizado en otro equipo.
Las operaciones devolvieron un informe verificado y el hash del adjunto
permaneció intacto. Los documentos vectoriales complejos siguen necesitando
varios segundos. El texto original dibujado como contornos no se convierte
automáticamente en texto editable.

## Comprobaciones

Pruebas de transacciones finales, rechazo de daños, metadatos de texto y
grupos, recortes, fuentes y composición, permisos originales, cancelación,
aislamiento y límites de caché, gestos con rotación/recorte/zoom, solapamiento,
diálogos e integración con el worker. Comprobación gráfica del código fuente
con `scripts/release_v300.py --source-ui-only --headless-qa` satisfactoria.

Las pruebas usan documentos sintéticos. El adjunto y los perfiles de medida
permanecen fuera del código distribuido.
