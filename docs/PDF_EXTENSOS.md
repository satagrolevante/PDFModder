# Edición de PDF extensos

La entrada en Herramientas y la comprobación de una selección repetían el análisis completo de los PDF etiquetados. Las comprobaciones comparten ahora una revisión inmutable, identificada por SHA-256. Se conserva como máximo una estructura, con un presupuesto estimado de 128 MiB; si lo supera, se conserva únicamente el resultado de validación. Cerrar el documento libera su caché.

El editor reutiliza el modelo de la página actual. Las comprobaciones de mover, escalar, girar o duplicar objetos se solicitan al elegir la operación. La edición nativa de un encabezado marcado como artefacto conserva su envoltorio y verifica sus límites declarados. Los párrafos con atributos básicos de espaciado, sangrías, alineación y escritura horizontal conservan esos atributos. Las selecciones ambiguas, las propiedades semánticas incompatibles y las clases o geometrías sin verificar siguen bloqueadas.

En documentos con líneas próximas, las cajas tipográficas nominales pueden solaparse antes de editar. La comprobación distingue esos solapamientos originales de una invasión nueva: sólo admite la intersección con el mismo vecino que siga cubierta por los rectángulos originales de la selección, con la tolerancia geométrica existente. Los huecos entre fragmentos no se convierten en un área autorizada.

Las operaciones que modifican el árbol lógico mantienen modelos privados. Se conservan las comprobaciones del PDF resultante: texto, páginas, imágenes, geometría, campos, etiquetas y apariencia. La página editada siempre pasa la validación visual completa. En las demás páginas, una huella SHA-256 independiente permite evitar el renderizado sólo si coinciden todo el contenido, los recursos, las anotaciones, los atributos heredados y las dependencias globales de representación. Referencias ambiguas, ciclos, codificaciones desconocidas o límites de recursos agotados conservan la comprobación completa. El informe distingue esta prueba de identidad de una medición de píxeles.

La comparación global de etiquetas y relaciones sigue siendo obligatoria. Para comprobar su texto lógico, las páginas con identidad demostrada tampoco necesitan otra extracción y otra prueba de pertenencia de cada glifo a su etiqueta. La página editada y las páginas sin prueba de identidad conservan esas verificaciones completas.

Guardar como escribe exactamente los bytes de la revisión actual en un archivo temporal, comprueba su integridad y legibilidad y lo sustituye de forma atómica. Así evita otra reescritura y otro renderizado de todas las páginas. El original no se sobrescribe.

La verificación de esta corrección utiliza regresiones sintéticas focalizadas y una prueba local de abrir, editar, guardar y reabrir un documento de 123 páginas. Los documentos del usuario y sus copias de prueba no se incorporan al repositorio.

En este entorno Linux, la preparación en el motor pasó de 18,6 a 4,7 segundos al entrar en edición y de 19 a 0,17 segundos al preparar una selección. La prueba final de interfaz Qt fuera de pantalla editó un encabezado en la página 1 y un párrafo en la 61, comprobó identidad en las 122 páginas restantes de cada operación y verificó texto y píxeles de las páginas de control 2, 20 y 123. Guardó y reabrió la copia desde una ventana nueva y confirmó que el original seguía idéntico.

En esa prueba final, abrir el editor tardó menos de un segundo, aplicar y validar los cambios entre 10,7 y 13,3 segundos, guardar la copia 2,3 segundos y reabrirla 0,6 segundos. Estas cifras corresponden a las pruebas del código en Linux; no son mediciones del instalador en un escritorio físico de Windows. La entrega 3.0.1 incluye esta corrección y su informe de construcción y comprobaciones.

La versión 3.0.2 amplía los atributos de disposición compatibles: acepta cuadros
de tablas que siguen conteniendo el texto y actualiza cuadros ajustados a contenido
exclusivamente textual. Los atributos compartidos se copian localmente; sus otras
referencias y las clases permanecen intactas. También conserva la cabecera PDF y
comprueba los metadatos completos y los destinos de marcadores al quitar etiquetas.

Aceptar utiliza los bytes ya validados para la vista previa sólo si coinciden todos
los campos del borrador y la revisión del documento. La nueva prueba Qt del mismo
documento de 123 páginas editó una fecha de portada dentro de una tabla etiquetada,
retiró etiquetas y deshizo esa operación, editó texto en la página 61, guardó y
reabrió la copia. Conservó metadatos, las páginas de control y el archivo original.
Aceptar la fecha con su vista previa validada tardó 0,51 segundos; generar esa
vista previa tardó 10,48 segundos. Aceptar el otro cambio directamente, incluida
su validación nueva, tardó 9,47 segundos. Quitar etiquetas tardó 11,79 segundos.
Son mediciones de código en Linux con Qt fuera de pantalla; una validación nueva
de un documento extenso sigue requiriendo varios segundos.
