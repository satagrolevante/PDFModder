# Impresión — PDF Modder 2.0.1

Pulse **Ctrl+P** o **Imprimir / vista previa**. Acepte o cancele el texto que esté escribiendo antes de imprimir.

1. Elija una impresora instalada en Windows. Si no hay ninguna, podrá preparar la vista previa; para imprimir necesitará una impresora disponible.
2. Elija **Color** o **Escala de grises**. Los grises se aplican realmente a las imágenes enviadas al dispositivo y se muestran en la vista previa. El PDF de trabajo conserva sus colores.
3. Elija **Todas las páginas**, **Página actual** o **Páginas concretas / intervalos**, por ejemplo `1,3-5`. Se conserva el orden indicado; una página repetida en los intervalos se incluye una vez. Las copias se indican aparte.
4. Elija **Una cara**, **Doble cara · borde largo (tipo libro)** o **Doble cara · borde corto (tipo calendario)**. En una página vertical, borde largo corresponde a encuadernación lateral; borde corto a pasar la hoja hacia arriba. En horizontal cambian los bordes físicos: el selector utiliza siempre borde largo/corto, evitando nombres ambiguos.
5. Indique copias y si se agrupan, papel (A4, A3, Carta o tamaño original), orientación, ajuste al área imprimible o tamaño real y resolución entre 72 y 600 ppp.
6. Pulse **Preparar vista previa**. Las flechas y el número de página permiten recorrer las hojas seleccionadas. La cabecera identifica la página original; ± y los botones de ajuste cambian la visualización. Sólo una página se mantiene en la vista previa, aunque los archivos de impresión seleccionados se preparan temporalmente en disco.
7. Pulse **Imprimir…**. Windows ofrece la confirmación y las propiedades del controlador. Si se cambia el rango allí, sus números corresponden a las hojas seleccionadas: para el intervalo original `2,5-7`, la hoja 1 es la página original 2 y la hoja 4 la original 7. Los cambios explícitos de papel y orientación del controlador prevalecen al imprimir.

## Compatibilidad y límites

Las opciones de color y doble cara se ajustan a las capacidades declaradas por el controlador. Una impresora monocroma no permite color; si no admite el modo de doble cara solicitado, ese modo se deshabilita. Si el controlador no informa de sus capacidades, se permite pedirlas, pero no se afirma que el equipo físico las ejecute.

La doble cara automática exige hardware/controlador compatibles. Cuando el controlador no gestiona múltiples copias, se bloquean varias copias a doble cara para evitar emparejar anversos y reversos de copias diferentes; imprima una copia por trabajo. No se implementa una secuencia manual de reinserción de papel.

La impresión envía imágenes renderizadas por página, con resolución limitada por memoria y permisos PDF. Guardar como sigue conservando texto y gráficos vectoriales. No equivale a impresión vectorial/PostScript, perfiles ICC profesionales o modo folleto. Tamaño real puede recortar contenido si supera el área imprimible.

Las comprobaciones usan salida PDF local de QPrinter y corpus sintético, sin enviar trabajos a impresoras físicas. La ejecución física del dúplex, los márgenes del controlador y la correspondencia de color deben contrastarse en la impresora que se utilice.

APIs oficiales: [QPrinter](https://doc.qt.io/qtforpython-6/PySide6/QtPrintSupport/QPrinter.html), [QPrinterInfo](https://doc.qt.io/qtforpython-6/PySide6/QtPrintSupport/QPrinterInfo.html), [QPrintPreviewWidget](https://doc.qt.io/qtforpython-6/PySide6/QtPrintSupport/QPrintPreviewWidget.html), [QPrintDialog](https://doc.qt.io/qtforpython-6/PySide6/QtPrintSupport/QPrintDialog.html).
