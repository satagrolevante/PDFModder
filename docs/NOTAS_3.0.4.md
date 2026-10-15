# PDF Modder 3.0.4

Corrige bloqueos detectados al editar dos documentos de 122 y 9 páginas. Los
originales y las copias de prueba son privados y no forman parte de la entrega.

- Reconoce recortes rectangulares dibujados mediante segmentos y combinaciones
  compatibles de rectángulos. Permite editar números, unidades y texto en esas
  celdas, conservando los trazados y operadores de recorte originales.
- Tolera referencias MCID repetidas al mismo propietario verificado y ciertos
  artefactos gráficos desconectados del árbol activo. Conserva su estructura
  original; las referencias ambiguas entre propietarios distintos siguen
  requiriendo revisión.
- Permite borrar texto bajo recortes complejos mediante sus códigos originales,
  sin añadir pintura ni reconstruir el recorte. Los caracteres vecinos conservan
  sus posiciones.
- Permite borrar texto que el PDF pinta simultáneamente con relleno y trazo.
  Verifica ambas apariencias y elimina sus códigos una sola vez, conservando el
  modo de pintura y el estado gráfico de los caracteres restantes.
- Actualiza subrayados originales compatibles junto con su texto. Comprueba la
  relación entre las etiquetas, el rectángulo dibujado y el texto; mantiene el
  color, grosor, posición vertical y orden de pintura del subrayado, y adapta su
  anchura. Los marcos, decoraciones ambiguas y propiedades semánticas adicionales
  conservan las restricciones correspondientes.

Las comprobaciones incluyen edición de fechas, correos y sus enlaces, pies de
página, números y unidades, cambios de palabras, borrado de párrafos y cambios
de formato. Se verifica el guardado y la reapertura, los metadatos, los marcadores,
las páginas ajenas y el contenido vecino. Los originales permanecen intactos.
Las pruebas públicas utilizan documentos sintéticos.

En esta revisión pasan 154 pruebas dirigidas desde las fuentes y el recorrido
general de interfaz con Qt fuera de pantalla en Linux. También se verificaron
edición, aceptación, guardado, reapertura y deshacer con copias de ambos documentos.
La compilación Windows comprueba por separado el ejecutable y la instalación y
desinstalación; las pruebas fuera de pantalla no acreditan un escritorio físico.

La edición sigue dependiendo de los operadores y recursos de cada PDF. La nueva
operación de texto con relleno y trazo admite borrado; su sustitución y
redistribución no están ampliadas. El texto vertical, las semánticas ambiguas y
las decoraciones cuya propiedad no pueda comprobarse requieren otra operación
compatible. No se garantiza edición universal.

La entrega incluye instalador Windows x64, versión portable y código fuente. El
manifiesto público habilita **Buscar actualizaciones**, con comprobación de
tamaño y SHA-256 del instalador. La publicación depende de las comprobaciones
automatizadas de esta revisión.
