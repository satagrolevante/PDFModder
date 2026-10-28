# PDFModder 3.0.16 — edición ágil y adaptación automática

Entrega Windows x64 con instalador, versión portable y código fuente.
Disponible desde **Buscar actualizaciones** mediante el manifiesto de integridad
y el instalador publicados en GitHub Releases. Incluye las mejoras de 3.0.15.

## Cambios

El texto nuevo compatible se escribe como contenido PDF nativo independiente.
Los dibujos, imágenes y operadores originales se conservan. Los movimientos
y las modificaciones completas o parciales de ese texto trabajan sobre su
contenido pequeño, en lugar de reconstruir toda la página. Se conserva la
selección, la tipografía y el texto real extraíble, sin rasterizarlo.

Las fuentes y sus vistas de edición se vinculan a los recursos reales del
documento. Los recursos idénticos se reutilizan al incorporar una modificación.
Las rutas anteriores siguen atendiendo las selecciones que necesitan su
tratamiento específico: contenido original, enlaces, formularios y etiquetas.

Las imágenes se escriben sin deduplicar ni recomprimir todo el documento.
Las páginas no modificadas se comprueban mediante identidad de sus grafos,
evitando renderizarlas otra vez. Se elimina una exploración gráfica repetida.

La sintaxis original se reutiliza por stream y por política de lectura.
Los resúmenes de ámbitos se conservan aparte, para que comprobar páginas
intactas no expulse el análisis completo de la página activa. Se mantienen
límites estimados de 64 MiB para sintaxis, 8 MiB para evidencias de recursos
y 2 MiB para resúmenes. Se vacían al suspender o cerrar la sesión.

## Ajustes automáticos

«Permitir solapamiento automáticamente» y «Adaptar el área automáticamente»
comienzan activados. Según la operación, se amplía el área o la altura y el
texto se reparte en líneas dentro de los límites conocidos de página y recorte.
Se conservan fuente, tamaño, posición inicial y contenido vecino. No se reduce
la letra ni se mueve otro texto para forzar que quepa.

La política se transmite al editor sobre la página, propiedades, celdas,
redimensionado, formato copiado y portapapeles. Se puede desactivar y la
recuperación de borradores conserva esa decisión. La corrección explícita de
la capa OCR buscable conserva su tratamiento existente; no se añade OCR.

## Integridad

Se verifica el resultado exacto que se aplica. La identidad independiente de
los streams y recursos originales puede demostrar que los gráficos permanecen
intactos sin volver a convertir miles de vectores a objetos Python. Continúan
las comprobaciones de glifos, formato, posiciones, píxeles fuera de las regiones
editadas, campos, anotaciones, enlaces, metadatos, marcadores y estructura.

Los metadatos propios sirven para localizar contenido, no para autorizarlo:
se comprueban los glifos reales, los operadores y las decoraciones. Un estado
gráfico, recorte o contenido marcado heredado conserva la ruta que sabe
tratarlo. Los permisos y firmas se revisan sobre el original antes de aislar
contenidos. Los casos desconocidos y presupuestos excedidos usan las
comprobaciones completas.

## Medición con el PDF adjunto

Prueba sin perfilador, con el documento abierto y la página disponible en
edición. Misma secuencia y tipografía incluida; procesos independientes para
3.0.15 y 3.0.16. Cada tiempo incluye preparación, aplicación y actualización
de página. El hash del adjunto permanece intacto.

| Acción | Código 3.0.15 | Código 3.0.16 |
|---|---:|---:|
| Añadir texto | 19,81 s | 3,87 s |
| Modificar texto | 12,21 s | 2,32 s |
| Mover texto | 14,07 s | 2,50 s |
| Modificar una palabra | — | 2,49 s |
| Mover una parte del texto | — | 2,68 s |
| Borrar una palabra | — | 2,45 s |
| Añadir texto con ajuste de líneas | — | 2,54 s |
| Borrar un párrafo | — | 2,57 s |
| Añadir una imagen | 9,45 s | 4,41 s |
| Mover una imagen | 10,16 s | 2,87 s |
| Recortar y girar una imagen | 11,64 s | 2,84 s |

Las pruebas de imagen usan imágenes añadidas editables. Las imágenes originales
del adjunto con recortes no reproducibles mantienen sus protecciones. Estas
mediciones pertenecen al entorno de prueba: otros documentos y equipos pueden
necesitar más tiempo. La ruta rápida de texto nuevo se aplica donde se puede
demostrar la independencia de su contenido; las rutas generales siguen disponibles.

## Comprobaciones

Pruebas específicas de texto completo/parcial, borrado, recursos de fuente,
subrayados, imágenes, color/transparencia, recortes, páginas rotadas, permisos,
formularios, etiquetas, recuperación, caché y cancelación. Las pruebas negativas
incluyen metadatos falsificados, vectores añadidos ajenos, recortes heredados,
desbordamiento de página, cambios de recursos y daños en los bytes finales.

Comprobación gráfica del código fuente mediante
`scripts/release_v300.py --source-ui-only --headless-qa` satisfactoria.
Los PDF y las mediciones privadas permanecen fuera del código distribuido.
