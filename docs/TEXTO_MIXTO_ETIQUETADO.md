# Texto sin marcar en documentos etiquetados

Incluido en PDF Modder 3.0.23.

Algunos exportadores añaden el título de impresión, la dirección web o el número
de página fuera del árbol de accesibilidad de un PDF etiquetado. Esa condición
del original ya no bloquea toda la edición. No se eliminan etiquetas ni se
inventan propietarios MCID para el texto que carecía de ellos.

La edición nativa distingue los caracteres de una etiqueta, los artefactos
explícitos y el texto realmente exterior a cualquier ámbito marcado. Se pueden
cambiar, borrar y dar formato a estos últimos, conservando su clasificación.
La validación del resultado comprueba también el texto y la posición de los
contenidos etiquetados vecinos y detecta que un reemplazo se asigne por error a
un artefacto. Las propiedades semánticas desconocidas mantienen sus controles.

El análisis de páginas reutilizado conserva el diagnóstico de texto sin marcar
del original, pero solo cuando su contenido y sus recursos se han probado
idénticos; una página modificada se analiza de nuevo.

También se corrige un falso bloqueo al modificar o mover ciertos textos:
MuPDF puede escribir un decimal con otra representación del mismo valor binario
de 32 bits. La comparación de recursos admite exclusivamente esa equivalencia
finita, manteniendo exactos los programas de fuentes, CMaps, claves y códigos
enteros. Los cambios numéricos reales siguen rechazándose. No se aplica esta
excepción al comparar operadores ni propiedades de accesibilidad. Se conservan
las comprobaciones finales de caracteres, tipografía, gráficos, píxeles y bytes
guardados.

Comprobaciones del PDF aportado: modificaciones del asunto, números, correo,
fecha, cabecera y pie; borrados de palabra y oración; formato; movimiento de
texto etiquetado y sin marcar; tres reemplazos de búsqueda; y preparación,
aceptación, guardado exacto y Deshacer/Rehacer desde el trabajador real. Los
trece recorridos han pasado, manteniendo la estructura original. Las once
ediciones individuales se midieron entre 0,83 y 1,77 segundos en el entorno
Linux de pruebas. El reemplazo de tres coincidencias, incluidos tres reintentos
con elección explícita de fuente, tardó 8,95 segundos. No son tiempos
garantizados para todos los equipos o documentos.

Las pruebas automáticas incluyen edición desde la interfaz, reapertura,
propietarios mezclados, revisiones obsoletas, manipulación de la clasificación
accesible, páginas de control y cambios indebidos en fuentes y codificaciones.
Los documentos privados, copias compatibles y resultados de prueba no forman
parte de las fuentes publicables.
