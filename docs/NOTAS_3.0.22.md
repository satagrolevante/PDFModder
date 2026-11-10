# PDF Modder 3.0.22 — Apertura más rápida y edición ampliada

La ventana inicial evita comprobar todos los archivos recientes y las rutas de
red antes de mostrarse. La biblioteca de firmas se carga al desplegar su panel;
los trabajadores evitan importar herramientas que todavía no necesitan. Abrir
un documento durante la consulta inicial de recuperaciones conserva la orden.

La edición comprueba los problemas gráficos del objeto seleccionado, para que
un elemento independiente de la misma página no bloquee el texto. La adaptación
automática puede ampliar el recorte del reemplazo conservando los recortes y
el contenido vecino. También se amplía el movimiento de texto recortado.

Se admiten más bloques etiquetados compatibles, encabezados y pies completos,
y apariciones de bloques gráficos reutilizados con capas o transparencia.
Se conservan sus propiedades y las demás apariciones del documento.

Buscar y reemplazar comparte el compositor y la elección de fuentes de la
edición directa. Busca frases entre líneas del mismo párrafo, sin unir columnas
o celdas. Los formularios analizan dependencias por campo y permiten elegir
fuentes completas sin ejecutar JavaScript ni recalcular campos dependientes.

Para ciertos bloques con codificaciones ambiguas aparece **Reconstruir este
bloque…**: permite revisar el texto y elegir una fuente completa antes de
aceptar. Retira los caracteres originales; no los oculta con un rectángulo.
La reconstrucción y la edición mantienen sus comprobaciones de integridad.

Se corrige el bloqueo al eliminar, extraer o reordenar páginas de documentos
con `/OutputIntents`. Se conservan el perfil ICC y la versión PDF. La combinación
de documentos con perfiles distintos sigue requiriendo una conversión de color.

Comprobaciones locales: **2.292 pruebas superadas y 11 reservadas para Windows**.
En el entorno Linux de pruebas, la primera ventana con recientes de latencia
simulada pasó de 1,54 a 0,42 segundos. Tres operaciones verificadas sobre la
factura aportada tardaron entre 0,47 y 1,51 segundos; se comprobaron también
guardado exacto y Deshacer/Rehacer. Son mediciones de este entorno, no tiempos
garantizados para cada equipo o PDF. La publicación exige además las pruebas
de Windows, el recorrido de interfaz y la comprobación del instalador real.

Se mantienen los tratamientos específicos de firmas digitales, permisos, XFA,
enlaces y anotaciones, y los controles sobre texto, fuentes, gráficos, imágenes,
estructura accesible, contenido vecino y bytes guardados. No se añade OCR.

[Apertura y edición: comportamiento y límites](MEJORAS_APERTURA_Y_EDICION.md).
[Operaciones de páginas y perfiles de color](PAGINAS_Y_PERFILES_COLOR.md).
