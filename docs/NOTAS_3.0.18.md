# PDFModder 3.0.18 — preparación reutilizable y edición de PDF extensos

Esta entrega incluye las firmas de 3.0.17 y las mejoras de preparación,
validación y compatibilidad descritas a continuación.

## Edición y comprobaciones

Las páginas y recursos sin cambios se comparan mediante huellas del grafo PDF
resuelto. Girar, recortar, extraer y reorganizar páginas mantienen sus controles
de geometría, anotaciones, destinos, catálogo y accesibilidad. Cuando no puede
probarse la identidad, se ejecuta la comprobación completa anterior.

Las transacciones de edición eliminan los objetos inalcanzables sin volver a
deduplicar y comprimir todos los recursos del documento. Los bytes resultantes
se verifican antes de aplicarlos y se guardan sin otra reescritura. El PDF puede
ocupar algo más que una copia recomprimida; se evita ese coste en cada cambio.

El análisis de etiquetas reconstruye siempre el árbol y las relaciones del
candidato con su propio lector. Solo reutiliza resúmenes inmutables de sintaxis
cuyos contenidos y recursos coinciden exactamente. Esta prueba semántica no
sustituye la comprobación visual. Los presupuestos de memoria y los casos
ambiguos conservan la ruta de análisis completo.

Se corrige el contenido repartido entre varios streams: los operandos,
diccionarios y ámbitos gráficos se interpretan conjuntamente. Esto permite
añadir texto, imágenes y firmas manuales en los DSA ensayados, y manipular las
imágenes nuevas sin cambiar los bloques originales.

La adaptación automática respeta los excesos de métricas de fuente ya
verificados por sus píxeles, sin ampliar el recorte real ni omitir la validación
de tinta. Se corrige así el pie ensayado. Borrar texto con estilos distintos
elimina sus operadores sin exigir una fuente o estilo únicos.

Mover texto etiquetado conserva los estilos reconocidos y actualiza las cajas
semánticas cuando puede verificarse su propiedad. Las estructuras desconocidas
o compartidas que no se pueden actualizar con garantías mantienen sus controles.

## Páginas, pestañas y portapapeles

La preparación se conserva al aceptar, deshacer y regresar a una pestaña. Cada
entrada está ligada a los bytes exactos de su revisión; las vistas del original
también incluyen la página de procedencia para evitar confusiones tras reordenar.
La caché compartida retiene hasta tres sesiones y 256 MiB estimados de valores,
con límites adicionales por tipo. Este presupuesto no es un límite total de
memoria del proceso: los lectores y los análisis globales tienen límites propios.
Al expulsar una entrada se conserva el historial y se vuelve a preparar al usarla.

La página se muestra sin esperar al inventario completo de imágenes y fuentes.
Sus herramientas solicitan el inventario correspondiente cuando lo necesitan y
descartan respuestas de otra sesión, página o revisión.
El primer clic sobre una imagen en la herramienta combinada prepara su
inventario y conserva la selección solicitada. El trabajo de fondo espera
durante diálogos, colocaciones y gestos para no perder una orden al aceptar.
En el modo explícito de movimiento, los controles de tamaño ya no capturan
todo el interior de un texto pequeño cuando se muestra con poco zoom.

Copiar una selección visible publica inmediatamente su texto disponible. El
formato portable se prepara después. Pegar dentro de PDFModder espera ese formato
para conservar las fuentes; cortar sigue asegurando que el contenido puede
recuperarse antes de borrarlo. Una copia posterior impide que una respuesta
antigua sobrescriba el portapapeles.

## Guardado, firma e impresión

El guardado reutiliza comprobaciones completas mediante evidencia privada por
sesión, ligada a la revisión y a la política de validación. Los indicadores de
interfaz y los informes recuperados no autorizan esa reutilización. Se mantienen
la escritura exacta, fsync, el hash de los bytes escritos, la reapertura y el
reemplazo atómico. Sin evidencia válida se vuelve a comprobar todo.

La preparación para firmar se conserva con un presupuesto de memoria. La firma
visible con certificado puede incorporarse a un PDF etiquetado mediante una
anotación asociada al árbol de accesibilidad y al ParentTree antes de firmar.
Se comprueban las relaciones anteriores y la integridad criptográfica de los
bytes finales. No implica certificación PDF/UA ni validación de confianza externa.

La impresión reutiliza un lector privado por revisión y evita comprimir y
descomprimir PNG para cada página. La decodificación, pintura y envío se ejecutan
en un hilo dedicado, con progreso y cancelación confirmada. Se conservan los
ajustes de doble cara y las propiedades privadas del controlador. El procesamiento
es progresivo y conserva los límites de resolución y permisos existentes.

## Verificación y mediciones

Las comparaciones antes/después, el alcance de las pruebas y los límites del
entorno se documentan en [Rendimiento 3.0.18](RENDIMIENTO_3.0.18.md).
La verificación final incluye 208 pruebas de regresión, 119 acciones del recorrido
de interfaz y los 19 pasos de la prueba de aplicación por GUI y proceso de trabajo.
Los objetivos de respuesta son criterios de medición, no tiempos garantizados.
Algunas inserciones y operaciones de página en los DSA todavía superan cinco
segundos. Sustituir imágenes añadidas en esos PDF etiquetados sigue requiriendo
un remapeo de etiquetas que aún no está habilitado. La salida PDF del sistema de
impresión conserva pausas puntuales de interfaz, medidas en el informe.
La impresión física, los controladores y el almacén de certificados de Windows
necesitan comprobarse en Windows; las pruebas locales usan salida PDF y
certificados sintéticos.
