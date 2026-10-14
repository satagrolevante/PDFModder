# PDF Modder 3.0.3

Amplía la edición general de PDF y corrige los bloqueos encontrados en la auditoría
de un documento extenso. Los archivos del usuario y las copias de prueba no se
incluyen en esta entrega.

- Edición y borrado de pies de página dentro de recortes rectangulares compatibles,
  conservando los operadores, fuentes y avances de los caracteres vecinos. La
  comprobación distingue márgenes tipográficos de tinta realmente recortada.
- Edición posterior a Quitar etiquetas cuando los marcadores conservados son
  compatibles. Mantiene las restricciones de propiedades semánticas o capas que
  requieran una actualización específica.
- Correos y texto enlazado compatibles se editan conjuntamente con su área activa.
  Un correo que identifica al destinatario de `mailto:` actualiza también ese
  destinatario; las etiquetas de enlaces con otro significado conservan el destino.
  Al borrar por completo el texto enlazado, se desactiva el área y se informa de
  los metadatos que se conservan. La edición ordinaria no sustituye a la censura.
- Borrar con Supr utiliza la transacción de texto nativa cuando corresponde, como
  el editor. Los párrafos incorporan sus líneas de continuación y prefieren el
  ámbito lógico verificado en documentos etiquetados.
- Detección de celdas con bordes rectangulares finos rellenos, además de trazados.
- Corrección de falsos solapamientos por residuos numéricos y de rechazos debidos
  a la representación escrita de números o diccionarios PDF. Las fuentes,
  referencias, recursos, flujos, imágenes y páginas ajenas siguen verificándose.
- Edición nativa de texto que comparte una etiqueta con gráficos, conservación
  de atributos de tabla compatibles y borrado de fragmentos en varias etiquetas
  sin alterar su estructura. Las sustituciones ambiguas conservan sus límites.
- La comprobación de compatibilidad tiene en cuenta enlaces y anotaciones antes
  de presentar una selección como editable.
- Opción de solapamiento visible junto al borrador, que actualiza la vista previa
  al activarla o desactivarla y se conserva al recuperar la edición pendiente.
- Redistribución del texto vecino dentro del párrafo, una celda detectada o el
  área elegida. Incorpora el texto y los formatos vecinos al mismo borrador,
  conservando los párrafos explícitos y las separaciones de párrafo detectadas
  entre vecinos. Aceptar aplica una única operación que
  puede deshacerse; el PDF conserva su estado anterior hasta ese momento.

La redistribución actúa sobre el texto incorporado al borrador. Se comprueban
los límites de página, los recortes y la estructura del documento; los enlaces
compartidos, las decoraciones y los ámbitos semánticos ambiguos requieren una
edición compatible o ajustar la selección.

La compilación Windows incluye comprobaciones dirigidas a estos cambios, recorrido
de interfaz fuera de pantalla y pruebas de instalación y desinstalación. Las
comprobaciones no acreditan todos los PDF posibles ni un escritorio físico concreto.

[Instalador Windows x64](https://github.com/satagrolevante/PDFModder/releases/download/v3.0.3/PDFModder-v3.0.3-Instalar.exe) · [Portable](https://github.com/satagrolevante/PDFModder/releases/download/v3.0.3/PDFModder-v3.0.3-Windows-x64.zip) · [Código fuente](https://github.com/satagrolevante/PDFModder/releases/download/v3.0.3/PDFModder-v3.0.3-codigo.zip)

El manifiesto público de la entrega habilita **Buscar actualizaciones**, con
comprobación de tamaño y SHA-256 del instalador cuando se publique esta revisión.
