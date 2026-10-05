# Imágenes, formularios y censura en 2.0.0

## Imágenes

El editor de imagen permite volver a recortar una instancia después de girarla
libremente. El marco rectangular se expresa como un cuadrilátero en las
coordenadas de un padre inclinado; no se aproxima por un rectángulo más grande.
Se conserva el recurso de píxeles y su máscara alfa, el orden de dibujo y las
otras instancias. El recorte conserva los píxeles originales y es recuperable;
no constituye una censura de datos.

«Restablecer proporciones» selecciona Encajar con escala uniforme, conservando
el marco y el giro elegidos. El diálogo muestra la resolución efectiva en ppp,
calculada a partir de los píxeles del recorte y su escala física. El aviso bajo
150 ppp es orientativo para ampliaciones, no una garantía de calidad impresa.
El PDF realmente modificado se valida antes de aceptar. Recortes heredados no
rectangulares, máscaras externas, sobreimpresión y matrices no invertibles
siguen requiriendo un tratamiento específico. En imágenes etiquetadas sólo se
admiten transformaciones cuya relación Figure/Alt o Artifact permanece intacta;
sustituir su significado requiere revisar también el texto alternativo.

## Campos de formulario

En Herramientas → Campos de formulario se listan todos los widgets AcroForm,
con su página, nombre, tipo y valor. Se puede cambiar el valor de texto, una
casilla o una opción de lista; también posición y dimensiones en milímetros.
«Previsualizar campo», «Aplicar cambio» y «Guardar como» crean una copia que
continúa siendo rellenable. Se contrastan el árbol canónico de campos, el valor
del widget, su apariencia normal, las páginas y los elementos no afectados.
Los widgets huérfanos o nombres canónicos ambiguos no se reparan a ciegas.

Los scripts, opciones y orden de cálculo se conservan. El programa no ejecuta
JavaScript PDF: con cálculos o validaciones se permite mover/redimensionar
campos conservando su apariencia, y se bloquean cambios de valor que podrían
dejar resultados incoherentes. XFA, firmas existentes, botones de acción y
grupos de radio tienen un aviso específico. Un campo de firma vacío no se
edita como texto; la firma se realiza mediante la herramienta de firma.

## Censura definitiva

Herramientas → Censura definitiva permite dibujar y revisar una lista de zonas
en distintas páginas, incluidas páginas giradas. La previsualización aplica
eliminación real de caracteres visibles y de OCR invisible, blanqueo de los
píxeles de imagen cubiertos y eliminación de vectores completamente contenidos.
El relleno negro identifica visualmente el área ya eliminada. Las zonas que
cortan un vector ajeno deben ampliarse o ajustarse; las anotaciones que pueden
conservar información deben retirarse antes. Las etiquetas/ActualText, capas
ocultas, XFA y formularios requieren una copia compatible revisada.

Después de aplicar y guardar una copia, la escritura completa elimina revisiones
anteriores y objetos no usados. Se comprueba que no quede texto en las zonas ni
un recurso original de imagen censurada cuya totalidad de apariciones se haya
seleccionado. Otras apariciones legítimas de una imagen o palabra permanecen:
para eliminar el dato en todo el documento hay que revisar todas sus apariciones.
Adjuntos y metadatos no se limpian automáticamente. El original y el historial
local siguen conteniendo los datos anteriores; sólo la copia exportada debe
compartirse como censurada.

## Comprobaciones dirigidas

Se ejercitaron seis casos del motor: valor/posición/guardado AcroForm, casilla,
conservación de cálculo al mover, recorte tras 27° con alfa y otra instancia,
eliminación conjunta de texto/OCR/píxeles sin revisión anterior y bloqueo de
anotación superpuesta. El valor de AcroForm se contrastó con pypdf; las zonas
ajenas se compararon a 144 ppp con tolerancia 8/255. El formulario se guardó y
reabrió. También se comprobó la entrada de los diálogos con Qt offscreen,
incluida la transformación de una zona dibujada en página rotada y el control
de proporciones/ppp. Esto demuestra el corpus generado, no todos los formularios
ni todas las imágenes de terceros.

API oficiales verificadas: https://pymupdf.readthedocs.io/en/latest/widget.html
y https://pymupdf.readthedocs.io/en/latest/page.html (Widget.update, FormFonts,
apply_redactions con opciones explícitas y clean_contents).
