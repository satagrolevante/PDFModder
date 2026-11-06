# Sustitución de texto recortado y elección de fuente

Correcciones incluidas en la versión 3.0.21.

## Comportamiento

- Se permite sustituir texto cuyo original ya estaba recortado. Se conservan
  los recortes del PDF y se comprueba que el resultado nuevo cabe y se pinta
  correctamente. No se amplían ni eliminan recortes automáticamente.
- Al sustituir o borrar todo el contenido visible de un campo se retiran
  también sus códigos ocultos, siempre que pueda verificarse que pertenecen
  al mismo ámbito de recorte. Se admite contenido dividido entre varios
  operadores. Dos ámbitos independientes con iguales coordenadas siguen siendo
  independientes.
- Al seleccionar y modificar una palabra se conservan los demás caracteres,
  incluidos los ocultos. Un cambio de formato sin cambiar el texto no elimina
  contenido oculto.
- Cuando no puede utilizarse la fuente del borrador aparece **Elegir fuente
  compatible…**. Permite escoger una fuente del catálogo o importar una TTF/OTF
  completa. Se verifica su cobertura y su permiso de incrustación. La elección
  modifica únicamente los fragmentos que usaban ese recurso, conserva tamaño,
  color y demás estilos, y se puede deshacer. Cancelar mantiene el borrador.
- Elegir una fuente no acepta la edición: primero se genera y valida la vista
  PDF; **Aceptar** incorpora después los bytes verificados al historial.

## Integridad

El texto oculto se identifica mediante el ámbito real de W/W* y la restauración
q/Q, la geometría conocida y la correspondencia de códigos con los glifos.
Los recortes desconocidos y los códigos ambiguos no se amplían por inferencia.
La eliminación mantiene el avance del cursor y los operadores vecinos.
La máscara de comparación visual no se amplía a las cajas de los caracteres
ocultos retirados. Se conservan las comprobaciones del texto, las fuentes, las
imágenes, los vectores, los enlaces, las anotaciones y la estructura accesible.

Los cuadros métricos verticales de una fuente elegida pueden exceder el recorte
aunque la tinta quepa. En ese caso se verifica la tinta del PDF resultante.
Si el texto nuevo sigue realmente cortado, la edición no se aplica.

## Comprobaciones realizadas

Pruebas sintéticas: sustitución y borrado completos, edición de palabras,
prefijos y sufijos ocultos, operadores separados, rotación de página, ámbitos
con iguales coordenadas, desbordamiento nuevo, fuentes parciales, elección y
cancelación de fuente, conservación de estilos, composición tipográfica,
vista previa, aceptación, guardado, reapertura y Deshacer.

En la factura aportada, cinco operaciones del trabajador real —sustitución de
la frase, edición de palabra, borrado, fuente alternativa y composición con
esa fuente— superaron la validación y el guardado. La preparación medida en
el entorno de pruebas fue de **0,61 a 1,47 segundos**; no es una garantía para
otros equipos o documentos. Se verificaron los bytes exactos guardados,
Deshacer/Rehacer, el original intacto y **cero diferencias de píxeles fuera de
la celda**. La factura y los resultados privados se mantienen fuera del código
publicable.
