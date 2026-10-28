# PDF Modder 3.0.14

## Impresión multipágina y doble cara

El envío nativo configura una hoja común antes de iniciar el trabajo y mantiene
su tamaño durante la impresión. Se elimina el cambio de papel que Qt para Windows
rechazaba al comenzar la segunda página. Las páginas de distinto tamaño u
orientación se ajustan y, en modo automático, se rotan dentro de esa hoja sin
alterar el orden de las caras. La opción de tamaño PDF usa como referencia la
primera página seleccionada.

La vista preliminar utiliza el mismo tamaño, orientación, márgenes y cálculo de
rotación que el envío nativo. La doble cara automática se negocia después de
establecer la orientación de la hoja.

## Preparación progresiva y cancelación

Se prepara y envía una página cada vez, con avance visible. Cada respuesta se
comprueba contra la sesión, revisión y página solicitadas; las respuestas antiguas
no pueden iniciar ni continuar un trabajo distinto. Las imágenes temporales se
liberan después de utilizarlas.

Cancelar sigue disponible durante la preparación y entre páginas enviadas. Un
control independiente detiene el renderizado en su siguiente punto seguro. La
cola de Windows se consulta mediante un identificador exclusivo del trabajo;
antes de solicitar su cancelación se vuelve a comprobar la cola, el identificador
y el documento, sin seleccionar trabajos ajenos. Si Windows no permite confirmar
la retirada, se indica al usuario que compruebe la cola.

Una llamada individual de renderizado o del controlador debe terminar antes de
atender el siguiente punto de cancelación. La cancelación no puede deshacer hojas
que la impresora ya haya producido.

## Opciones, errores y vista previa

- Los valores iniciales de papel, orientación, color y doble cara se toman del
  controlador cuando no existe un perfil propio; se conservan los perfiles y el
  valor de resolución anterior.
- Se avisa si una preferencia guardada deja de estar admitida por el controlador.
- **Propiedades de la impresora…** es opcional. Devuelve al cuadro principal y
  conserva el dispositivo configurado; el trabajo se envía al pulsar **Imprimir**
  en PDFModder. No hay una segunda confirmación obligatoria.
- Las opciones comunes se comprueban con Qt y, en Windows, se negocian con el
  controlador mediante DEVMODE cuando no se acaba de validar una configuración
  privada en el diálogo nativo.
- Los errores de impresora no disponible permanecen visibles y deshabilitan
  Imprimir; no se confunden con errores de intervalos.
- Cambiar de página oculta la imagen anterior mientras se actualiza la vista.
  Cambiar color, papel o escala conserva los píxeles de la misma página/revisión,
  incluso cuando su preparación estaba en curso.

## Anotaciones

La preparación utiliza una copia privada del documento para respetar las
banderas de impresión de anotaciones y campos de formulario. Se incluyen los
elementos destinados solo a imprimir y se excluyen los no imprimibles, ocultos o
invisibles. Sus apariencias y los bytes del PDF original se conservan.

## Alcance y comprobaciones

Se mantienen la rasterización RGB, el límite de 24 megapíxeles, los límites de
resolución y las reglas de permisos de propietario. No se añaden pares/impares,
orden inverso ni doble cara manual guiada.

Las pruebas incluyen la restricción de papel activo del motor nativo, igualdad
entre composición de vista previa y envío, márgenes del controlador, negociación
dúplex, cancelación exclusiva del trabajo propio, anotaciones y formularios,
integridad del original y salida PDF. En un documento real de 123 páginas se
canceló después de la primera sin preparar las 122 restantes. También se ejecutó
el recorrido completo de la interfaz. La impresión física con el controlador del
usuario requiere comprobación en su equipo.

Entrega Windows x64 con instalador, versión portable y código fuente. El canal
**Buscar actualizaciones** utiliza el instalador y su manifiesto de integridad
publicados en GitHub Releases.
