# PDF Modder 3.0.10

## Navegación con controles estables

El renderizado de páginas, la precarga, las miniaturas y las consultas de lectura
continúan en el proceso PDF separado. Su ocupación deja de desactivar los controles
generales de navegación, zoom, búsqueda, apertura, impresión y guardado.

Los distintos paneles aportan sus reglas a un cálculo de disponibilidad. Solo se
aplica el estado final de cada control, conservando las señales de Qt para los
cambios reales y evitando las alternancias intermedias entre activo y gris.

Al recorrer páginas o cambiar el zoom mientras se prepara una imagen, se conserva
el último destino. Las pulsaciones de ampliar/reducir se acumulan desde el zoom
solicitado. Las vistas antiguas no pueden sustituir la página y el zoom elegidos.
Las órdenes de vista tienen prioridad sobre la precarga y las miniaturas.

Las búsquedas y los saltos entre resultados conservan sus peticiones pendientes.
Guardar, abrir, imprimir y otros comandos generales esperan al trabajador cuando
hay una consulta de lectura en curso; no se envían trabajos incompatibles en
paralelo. Los comandos de historial conservan el orden de varias pulsaciones.

Se mantienen los bloqueos durante el guardado, la aplicación de cambios, la
preparación de borradores, la firma y las operaciones estructurales. La edición
de una página espera a su modelo y escala correctos. Cambiar de documento o de
revisión invalida una petición antigua; solo las revisiones resultantes de las
órdenes de historial encoladas pueden continuar su propia secuencia.

## Comprobaciones

En un PDF sintético de 123 páginas, los mismos tres saltos produjeron seis
renderizados y 18 cálculos de disponibilidad. Antes, Guardar cambió de estado
36 veces; después, ningún control general observado cambió de estado durante
la navegación. La geometría de la barra se mantuvo estable.

Las pruebas cubren navegación y ajuste de anchura en edición, zoom acumulado,
búsqueda durante la carga, guardado solicitado durante el renderizado, órdenes
de historial consecutivas, invalidación de resultados antiguos y conservación
de los PDF originales. Esta mejora de interfaz no elimina el tiempo necesario
para renderizar una página compleja.

Se han superado 92 pruebas dirigidas y el recorrido completo de la interfaz
con Qt offscreen. La entrega incluye pruebas del guardado, lectura, búsqueda,
impresión integrada y operaciones de edición, sin enviar trabajos físicos a
impresoras. También se comprueba que un fallo de renderizado no deje otras
órdenes esperando un ajuste de anchura pendiente.

Incluye también el cuadro único de impresión preparado en 3.0.9. Entrega Windows
x64 con instalador, versión portable y código fuente. El canal **Buscar
actualizaciones** utiliza el instalador y el manifiesto de integridad publicados
en GitHub Releases.
