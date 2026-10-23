# PDF Modder 3.0.9

## Impresión en un único cuadro

**Archivo → Imprimir…** y **Ctrl+P** abren las opciones de impresión con la vista
preliminar integrada. Se puede imprimir directamente desde esa ventana, sin el
paso obligatorio de preparar/aceptar otra vista previa ni el segundo cuadro de
confirmación de Windows.

Conserva la elección de impresora, color/grises, doble cara, páginas e intervalos,
copias, agrupación, papel, orientación, escala y resolución. Los intervalos se
refieren directamente a las páginas originales. Las capacidades del controlador
y las restricciones del documento siguen comprobándose antes de imprimir.

La vista preliminar carga una página a 120 ppp y mantiene su imagen propia. Los
cambios de presentación reutilizan esa imagen. Solo al pulsar Imprimir se preparan
las páginas del trabajo a la resolución solicitada. Una petición de impresión
espera a la vista preliminar en curso y descarta sus respuestas obsoletas.

Cancelar durante la preparación impide enviar el resultado posterior; un cambio
de documento o revisión también invalida el resultado. Las actualizaciones de
vista preliminar no pueden borrar las imágenes preparadas para imprimir.

Si no hay impresoras, la vista preliminar está disponible y la impresión queda
desactivada. Una impresora virtual puede pedir la ubicación del archivo resultante.
No se altera el contenido del PDF de trabajo.

[Uso y límites](GUIA_V309.md). Estas mejoras se integran en la entrega 3.0.10;
no se publicó un instalador independiente 3.0.9.

Comprobaciones: 43 pruebas dirigidas correctas y recorrido Qt completo con una
sola ventana, navegación de la vista preliminar, cancelación y salida PDF de dos
páginas en escala de grises. Las pruebas no envían trabajos a impresoras físicas.
