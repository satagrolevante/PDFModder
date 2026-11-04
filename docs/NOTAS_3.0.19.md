# PDF Modder 3.0.19 — progreso de actualización y combinación de PDF firmados

Esta entrega permite combinar PDF firmados en una copia de consulta y muestra
el progreso durante las fases de actualización e instalación.

## Combinación de documentos

Combinar permite crear una copia de consulta a partir de PDF firmados, con
sellos de tiempo, campos de formulario o etiquetas de accesibilidad. La app
explica que las firmas originales no certifican el resultado. Las apariencias
de los campos se fijan como contenido PDF, sin convertir las páginas en imágenes.
Si es necesario retirar etiquetas, se informa de la pérdida de esa estructura;
el original accesible se conserva. No se debilita la protección de edición del
documento firmado.

Desde una sesión firmada o de lectura, el resultado abre una pestaña nueva y
pendiente de guardar. La combinación sobre una sesión editable conserva su
historial de deshacer. Se impide guardar el resultado sobre cualquiera de los
archivos de entrada, incluso después de recuperar una sesión interrumpida.

Los archivos con el mismo contenido se señalan, pero se mantiene cada aparición
seleccionada. Los errores de una fuente identifican su nombre. Se verifican
metadatos, texto, geometría, enlaces y apariencia antes de aceptar la copia y el
combinado. Las firmas digitales y declaraciones de conformidad que dejen de ser
ciertas no se trasladan como válidas. Las características no reproducibles se
rechazan con una explicación; no se omiten silenciosamente.

## Progreso de actualización

La aplicación mantiene visible la barra durante la consulta de versiones, la
descarga, la comprobación de integridad y la preparación de los documentos para
cerrar. La descarga muestra su propio porcentaje; las fases cuyo total no puede
medirse usan una barra animada y un mensaje de estado.

El instalador de una actualización abre automáticamente su ventana de progreso.
Muestra la espera de cierre de la aplicación, la copia y comprobación de los
archivos, el registro y la retirada de versiones anteriores. La ventana sigue
respondiendo durante estas operaciones y no puede cerrarse mientras modifica la
instalación. Un desinstalador antiguo puede trabajar de forma silenciosa: la
ventana principal del instalador conserva la barra y el estado de esa retirada.

Se conservan las comprobaciones de integridad, los informes de instalación, las
restricciones de las carpetas y procesos que se pueden retirar, y la protección
de los documentos y archivos modificados. Los errores y las retiradas incompletas
siguen mostrándose. El modo `--silent` explícito se conserva para automatización.

El flujo de publicación compila y comprueba el ejecutable, el instalador y su
ventana de progreso en Windows. Las pruebas locales de Qt usan el modo offscreen.
