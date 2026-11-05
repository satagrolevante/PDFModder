# PDF Modder 3.0.20 — Firmas compactas e Imprimir desde el Explorador

Esta entrega mejora el apartado Firmas y añade la impresión directa desde el
menú contextual de los PDF en Windows.

## Firmas

El apartado Firmas de EDITAR empieza plegado, igual que los demás apartados.
Su cabecera incorpora el icono vectorial de firma, del mismo estilo que los
demás iconos y compatible con los temas claro y oscuro.

Las miniaturas pasan de 210 × 64 a 170 × 44 píxeles y las filas ocupan menos
altura. Esto permite ver más firmas a la vez. Se conservan el nombre, el aviso
con el nombre completo, la selección y el arrastre a la página. Los dibujos
guardados mantienen su resolución y su transparencia originales.

## Imprimir desde Windows

El instalador registra Imprimir para un PDF seleccionado en el menú contextual
del Explorador. Envía directamente el documento completo a la impresora
predeterminada de Windows, sin vista previa ni diálogo de opciones de impresión.
Utiliza un dispositivo nuevo con la configuración predeterminada del controlador:
papel, orientación, color, caras, copias y sus opciones privadas. No aplica ni
modifica los perfiles de impresión guardados en PDF Modder.

La apertura y el envío se coordinan con la carga de páginas. La orden queda
ligada al archivo, a la pestaña y a su revisión; una apertura fallida, la
cancelación de la contraseña o un cambio de pestaña no deben imprimir otro PDF.

Se reutiliza la preparación por página, sus permisos y el envío en segundo plano
existentes. El estado aparece en la aplicación; la falta de impresora o los
errores se informan sin elegir otro destino ni reintentar el trabajo. Cerrar
durante el envío solicita cancelarlo y espera al hilo que utiliza la impresora.
Imprimir desde los menús de la aplicación conserva su diálogo y sus preferencias.

El menú se registra por usuario. No cambia las aplicaciones predeterminadas.
Una actualización renueva su ruta y la desinstalación retira únicamente la acción
que todavía pertenece a esa instalación. El registro y su restauración se
comprueban en el ensayo aislado de Windows.

Las pruebas de impresión automatizadas utilizan una salida PDF para comprobar
el envío, la paginación y las cancelaciones sin consumir papel. No acreditan
el resultado físico de cada modelo de impresora.
