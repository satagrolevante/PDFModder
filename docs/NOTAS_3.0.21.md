# PDF Modder 3.0.21 — Edición de campos recortados y fuentes incompletas

Se corrige el bloqueo «Un carácter original está parcialmente oculto por el
recorte» al sustituir texto que ya estaba recortado en el documento original.
Se comprueba que el texto nuevo sea correcto, manteniendo los recortes y la
validación del contenido vecino.

Al seleccionar y sustituir o borrar el campo completo se retira también su
contenido oculto verificable. Al seleccionar una palabra se conserva el resto
del campo, incluido su contenido oculto. Se admiten campos repartidos entre
varios operadores, sin confundir ámbitos independientes de recorte.

Cuando la fuente parcial no permite escribir los caracteres solicitados,
aparece **Elegir fuente compatible…**. Permite escoger una fuente del catálogo
o importar una TTF/OTF completa. La elección es explícita, conserva los demás
estilos y puede deshacerse. El PDF se previsualiza y valida antes de aceptar;
cancelar mantiene el borrador.

Se conservan las comprobaciones de texto, fuentes, imágenes, vectores, enlaces,
anotaciones, estructura accesible y bytes guardados. Si el texto nuevo queda
realmente cortado, la operación no se aplica.

Las pruebas locales incluyen 110 casos de edición, recortes, fuentes, interfaz,
guardado y reutilización de validaciones. Cinco operaciones sobre la factura
aportada superaron la aceptación, guardado, reapertura y Deshacer/Rehacer, con
cero diferencias de píxeles fuera de la celda y el original intacto. Su
preparación se midió entre 0,61 y 1,47 segundos en el entorno de pruebas; los
tiempos pueden variar según el equipo y el documento.

[Detalles de comportamiento y comprobaciones](TEXTO_RECORTADO_Y_FUENTES.md).
