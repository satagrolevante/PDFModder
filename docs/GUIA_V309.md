# Impresión — PDF Modder 3.0.9

Pulse **Ctrl+P** o **Archivo → Imprimir…**. Acepte o cancele el texto que esté
escribiendo antes de imprimir.

Las opciones y la vista preliminar aparecen en una sola ventana de la aplicación.
Puede pulsar **Imprimir** directamente, sin abrir ni aceptar otra vista previa ni
confirmar un segundo menú de impresión de Windows.

1. Elija una impresora instalada. Si no hay ninguna, la vista preliminar continúa
   disponible y el botón Imprimir permanece desactivado.
2. Elija **Color** o **Escala de grises**, **Una cara** o **Doble cara**, las copias
   y si se agrupan. Color y doble cara respetan las capacidades del controlador.
3. Elija **Todas las páginas**, **Página actual** o un intervalo, por ejemplo
   `1,3-5`. Se conserva el orden indicado; los números corresponden siempre a las
   páginas originales del documento. Una página repetida se incluye una vez.
4. Ajuste papel, orientación, escala y resolución. La vista preliminar integrada
   refleja los cambios y ofrece flechas, número de página, zoom y ajuste de página.
5. Pulse **Imprimir**. Se preparan las páginas seleccionadas con la resolución
   elegida y se envían directamente a esa impresora. Cancelar durante la
   preparación impide enviar el resultado cuando termine.

La vista preliminar prepara solo una página a 120 ppp y conserva su imagen en
memoria. Cambiar color, papel o escala no vuelve a analizar el PDF. El trabajo de
impresión tiene prioridad sobre las vistas preliminares pendientes; estas no
pueden borrar los archivos listos para imprimir. Los límites del motor siguen
siendo 1000 páginas por trabajo, 1 GB de imágenes temporales y una resolución
limitada por memoria y permisos PDF.

La doble cara automática requiere hardware y controlador compatibles. Cuando el
controlador no gestiona varias copias a doble cara, se solicita una copia por
trabajo para evitar mezclar sus caras. No hay secuencia manual de reinserción.

Se imprime la apariencia renderizada por página. **Guardar como** conserva el
PDF vectorial y seleccionable. Tamaño real puede recortar contenido si el papel
es menor; el color físico y los márgenes dependen de la impresora. Un controlador
virtual puede pedir el nombre del archivo de destino al recibir el trabajo.

Las pruebas utilizan salida PDF local de QPrinter y documentos sintéticos, sin
enviar trabajos a impresoras físicas. Se comprueban el diálogo único, la impresión
directa, los rangos, copias, orientación, grises y la cancelación.
