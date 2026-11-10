# Apertura y ampliación de la edición

Incluido en PDF Modder 3.0.22.

## Apertura

La construcción de la ventana ya no comprueba la disponibilidad de cada PDF
reciente. Una ruta de red desconectada se comprueba cuando se abre, en el
trabajador. Firmas carga su biblioteca al desplegar el apartado. Los procesos
de PDF y la consulta inicial de recuperaciones evitan cargar la interfaz,
fuentes, imágenes y criptografía innecesariamente. La recuperación efectiva
mantiene las comprobaciones completas de archivos y huellas. Las órdenes de
abrir se conservan si coinciden con una consulta de recuperación.

Mediciones de procesos nuevos, Linux/Qt offscreen:

| Comprobación | Antes | Después |
| --- | ---: | ---: |
| Primera ventana, recientes con latencia simulada | 1,5422 s | 0,4169 s |
| Primera ventana al abrir PDF | 0,5253 s | 0,3869 s |
| Primera página preparada | 1,0992 s | 0,8014 s |

Son mediciones de las fuentes en este entorno, no del instalador en un PC Windows.

## Edición

- Se comprueba el estado gráfico del texto seleccionado para permitir ediciones
  normales aunque haya máscaras, sobreimpresión o modos de fusión en otro
  objeto. Las propiedades del elemento realmente afectado siguen verificándose.
- La adaptación automática puede crear un recinto privado para el reemplazo,
  ampliando solo su recorte. Los recortes y caracteres vecinos conservan sus
  operadores; no se revela texto antiguo oculto. Mover texto recortado conserva
  su máscara y puede incluir varios operadores y el final oculto del campo.
- Se admiten bloques con varias marcas compatibles del mismo significado y
  composición avanzada dentro de párrafos etiquetados existentes. Se conservan
  relaciones, orden de lectura y ActualText. Una caja de encabezado o pie puede
  crecer cuando se selecciona todo su contenido, conservando sus propiedades.
- La edición de una aparición de un Form reutilizado conserva los grupos de
  transparencia y las capas mediante aislamiento y restauración de su recinto.
  Las otras apariciones y el catálogo de capas se mantienen. También se reconoce
  el texto de un Form que hereda la etiqueta de su bloque de página.
- Buscar y reemplazar utiliza el mismo compositor que la edición directa,
  conserva formatos y ofrece el selector compartido de fuente por coincidencia.
  Puede buscar frases entre líneas de un párrafo, sin saltar entre columnas o
  celdas. Los cambios múltiples se preparan como una única revisión verificable.
- El editor de formularios usa dependencias por campo. Permite cambiar campos
  independientes aunque haya cálculos ajenos, sin ejecutar JavaScript. Ofrece
  fuentes completas para texto, listas, desplegables y campos de casillas; su
  apariencia usa el programa realmente elegido y lo conserva al volver a editar.
- Cuando la codificación original no se puede reutilizar, una selección elegible
  ofrece **Reconstruir este bloque…**. Se elige explícitamente una fuente y se
  revisa el texto. Se retiran los caracteres originales, no se tapan; el borrador
  se puede cancelar y Aceptar sigue siendo necesario. La eliminación intermedia
  y el PDF final se comparan con el original. Hay pruebas con CMaps personalizados
  y fuentes Type3 que impiden el sondeo ordinario.

## Límites y verificaciones

No se adivinan relaciones accesibles externas, cálculos dinámicos, asociaciones
de capas ambiguas ni el significado de bloques con roles distintos. Los campos
dependientes no se recalculan automáticamente. XFA, firmas activas, permisos,
anotaciones y enlaces siguen utilizando sus tratamientos específicos. La
reconstrucción no sustituye esos tratamientos semánticos. El texto de una imagen
escaneada continúa siendo distinto de su capa OCR; no se añade OCR nuevo.

Se mantienen las validaciones del texto, fuentes, recursos, gráficos, imágenes,
formularios, etiquetas, metadatos, contenido vecino y bytes exactos guardados.
Los documentos privados y los artefactos de prueba quedan fuera de las fuentes
publicables.
