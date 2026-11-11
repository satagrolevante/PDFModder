# PDF Modder 3.0.24 — Instalador y edición, copia y pegado de PDF etiquetados

El instalador muestra **«Instalación completada correctamente»** y cierra su
ventana automáticamente a los tres segundos. La confirmación aparece después
de comprobar los archivos y guardar el informe. Si hay un error, la ventana
permanece abierta con su diagnóstico.

Al añadir o pegar texto en un PDF etiquetado se elige automáticamente el final
de la página como posición de lectura. Se añade un párrafo verificado y se
conservan las etiquetas, relaciones y el contenido anterior. El pegado con
formato ya no entra por una ruta que rechazaba todos los documentos etiquetados.
También se admiten fronteras de lectura verificables en páginas vacías.

Se amplía la edición de marcas sin árbol accesible: ActualText, idioma y capas
opcionales registradas. El texto nuevo conserva su pertenencia a la capa; el
subrayado también sigue su visibilidad. Las descripciones ActualText se actualizan
con el texto, y los bloques completos compatibles se pueden sustituir juntos.
Las propiedades desconocidas de otro objeto ya no bloquean un texto independiente.

Se corrigen varios problemas del portapapeles: la prueba de fidelidad de la
fuente contaba incorrectamente los caracteres vecinos como un fallo; la identidad
de una fuente podía cambiar por redondeos equivalentes del guardado; y ciertas
fuentes estándar se trataban erróneamente como archivos OpenType al pegar palabras
con «fi». El texto externo utiliza también la inserción independiente, evitando
el aviso genérico de contenido marcado después de otras modificaciones.

Las pruebas sobre el PDF aportado incluyen editar, copiar, pegar con formato
después de otra edición, pegar texto externo, guardar y Deshacer/Rehacer. Se han
comprobado tanto el original etiquetado como una copia de prueba sin etiquetas;
el archivo original permanece intacto. Las comprobaciones de Windows incluyen
el mensaje de éxito, su cierre automático y la permanencia del diagnóstico en
caso de fallo.

Se mantienen las comprobaciones del resultado final, las fuentes y sus códigos,
el contenido vecino, la estructura accesible y los bytes exactos guardados. Los
documentos privados y los resultados de prueba quedan fuera de las fuentes.
