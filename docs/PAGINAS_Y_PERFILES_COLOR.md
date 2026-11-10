# Operaciones de páginas con perfiles de color de salida

Incluido en PDF Modder 3.0.22.

El catálogo `/OutputIntents` describe las condiciones de color del documento.
Su presencia no impide eliminar, extraer o reordenar páginas. Estas operaciones
conservan el catálogo original, sus atributos y todos los bytes decodificados
del perfil ICC. La validación comprueba esa conservación además del contenido,
los recursos, los enlaces, las anotaciones y la apariencia de las páginas.

Se conserva también la versión PDF del origen al reordenar páginas y en el
escritor de documentos etiquetados, para no bajar el encabezado a una versión
anterior a la que requiere el perfil conservado.

Al importar páginas de otro documento se exige que sus condiciones de salida
coincidan con las del catálogo que se conserva. Si difieren —incluida la ausencia
de un perfil en uno de los archivos— se informa de que hace falta una conversión
de color. No se pierde ni sustituye silenciosamente el perfil de otro origen.

Pruebas: eliminación, extracción, reordenación, documentos etiquetados, unión de
perfiles iguales y rechazo de perfiles distintos. Se simula también la pérdida
del perfil, la modificación de sus bytes y de su identificador para comprobar
que los validadores rechazan esos resultados.

Con el documento aportado, de seis páginas, se ensayaron borrados de la primera,
una intermedia, la última y varias páginas, así como extracción y reordenación.
Se verificaron operadores y texto, metadatos, XMP, el perfil ICC y las imágenes
de todas las páginas conservadas a 144 ppp. El recorrido del trabajador real
incluyó borrado, guardado de los bytes exactos y Deshacer/Rehacer. El original
permanece intacto. El documento privado y los resultados están fuera de las
fuentes publicables.
