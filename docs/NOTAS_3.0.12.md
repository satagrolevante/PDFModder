# PDF Modder 3.0.12

## Panel derecho al activar EDITAR

Se corrige la desaparición del panel derecho después de contraer o desplegar
**Páginas / Recientes** en modo Lectura. El divisor guardaba una anchura cero
para las herramientas ocultas; al entrar en Edición Qt las consideraba visibles,
pero mantenía ese espacio colapsado.

**EDITAR** recupera ahora una anchura útil y restaura la anchura anterior del
panel, entre sus límites habituales. El panel derecho no puede quedar colapsado
al ajustar el divisor. La transición Lectura/Edición gestiona su visibilidad en
un único punto, también cuando espera a que termine una carga de página.

Se conservan las secciones y herramientas anteriores, el estado del panel
izquierdo y el zoom del documento.

## Comprobaciones

20 pruebas dirigidas superadas: contracción/restauración del panel izquierdo
durante Lectura y posterior pulsación de EDITAR; recuperación de una anchura cero;
conservación de la anchura elegida; visibilidad de las secciones y de sus botones;
alternancia entre modos y órdenes solicitadas durante la carga de páginas.
Las tres nuevas comprobaciones reproducían el fallo antes de la corrección.

Entrega Windows x64 con instalador, versión portable y código fuente. El canal
**Buscar actualizaciones** utiliza el instalador y su manifiesto de integridad
publicados en GitHub Releases.
