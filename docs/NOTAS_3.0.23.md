# PDF Modder 3.0.23 — Edición de PDF con texto parcialmente etiquetado

Se corrige el bloqueo «PDF etiquetado: hay texto sin etiqueta ni marca de
artefacto» cuando un documento contiene cabeceras o pies de impresión fuera
de su árbol de accesibilidad. Esa condición del original ya no impide editar
el resto del documento.

Permite modificar, borrar y dar formato al texto nativo que ya estaba sin
etiquetar, conservándolo como tal. Se mantienen las etiquetas existentes y se
verifica que el reemplazo no cambie la pertenencia ni la posición de contenido
vecino. Los artefactos y las propiedades semánticas especiales conservan sus
comprobaciones específicas.

También se corrige un falso aviso de modificación de fuentes o recursos al
editar o mover ciertos textos. Se reconoce el redondeo del guardado únicamente
cuando representa el mismo valor binario de 32 bits. Los programas de fuentes,
las codificaciones y los códigos enteros siguen comparándose exactamente.

La corrección cuenta con 290 comprobaciones automáticas locales superadas y
13 recorridos de edición sobre el PDF aportado, incluidos correo, fecha,
cabecera, pie, borrado, movimiento, reemplazo, guardado y Deshacer/Rehacer.
La entrega exige además las pruebas dirigidas en Windows, el recorrido de
interfaz y las comprobaciones del ejecutable y del instalador real.

Se conservan las verificaciones de integridad, contenido vecino y bytes exactos
guardados. Los documentos privados y las copias de prueba quedan fuera de las
fuentes publicadas.
