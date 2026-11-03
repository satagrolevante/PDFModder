# PDFModder 3.0.17 — firmas manuscritas reutilizables

Cambios preparados en el código fuente, pendientes de compilar y publicar.

## Firmas en el panel de edición

El apartado **Firmas** permite crear dibujos con el ratón, guardarlos con un
nombre y una miniatura, renombrarlos y eliminarlos de la biblioteca. El dibujo
se conserva en negro y con fondo transparente. Se puede deshacer el último
trazo o borrar el dibujo completo antes de guardarlo. No se añade la opción
de iniciales.

La biblioteca se guarda en la carpeta de datos locales del usuario de Windows,
dentro de `firmas`. No se envía a servicios externos. Eliminar una firma de la
biblioteca no retira las firmas ya incorporadas a documentos.

Arrastra una miniatura hasta el documento o pulsa **Colocar firma manual** y
elige el lugar con un clic. La firma se incorpora mediante la edición validada
de imágenes: se puede mover, redimensionar, girar, eliminar y deshacer. Al
colocarla se selecciona el modo de imágenes para facilitar su manipulación
incluso cuando se superpone a texto. No necesita certificado ni obliga a
firmar digitalmente. Guarda el PDF para conservarla en el archivo.

En PDF etiquetados, la firma nueva se identifica como una figura con su nombre
al final del orden de lectura de la página. Su eliminación retira también su
descripción y su asociación de accesibilidad, sin renumerar otros contenidos.
Las figuras originales con relaciones o estructuras compartidas mantienen
sus comprobaciones específicas.

## Firmas con certificado

El panel ofrece accesos a **Firmar con certificado visible** y **Firmar con
certificado invisible**. Ambos utilizan el flujo existente de certificados de
Windows o archivos PFX/P12 y guardan una copia firmada.

El sello visible permite incorporar opcionalmente una firma manuscrita de la
biblioteca. Conserva el titular, los datos del certificado y la fecha. La vista
previa utiliza el mismo dibujo que la firma final. Las miniaturas muestran
un fondo blanco en ambos temas de interfaz, mientras que el PDF conserva la
transparencia real del dibujo.

La opción invisible es una firma digital normal, sin sello gráfico y sin
certificación DocMDP. Se conserva la comprobación de integridad criptográfica
de los bytes finales y el tratamiento actual de confianza, revocación y sello
de tiempo. No se almacenan contraseñas ni claves privadas en la biblioteca.

## Comprobaciones

85 pruebas específicas de firmas, interfaz y disponibilidad de acciones
superadas. Recorrido gráfico del código fuente en modo de prueba satisfactorio.
Las firmas con certificado se verifican con certificados sintéticos de prueba.

En `ficha cliente.pdf`, con el documento y la página preparados, el motor
validó, aplicó y volvió a renderizar las operaciones siguientes: añadir firma
2,51 s, mover 2,58 s, girar 3,09 s y eliminar 2,77 s. Se comprobó el guardado,
la conservación de las imágenes originales y que el archivo de origen no
cambió. Son mediciones del entorno de prueba, no un límite de tiempo garantizado.
