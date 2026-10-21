# PDF Modder 3.0.6

La lupa abre un panel lateral de búsqueda, disponible tanto en Lectura como en
Edición. Escribe el texto y pulsa Enter o Buscar.

- Muestra el total y el índice del resultado activo: «Resultado 3 de 18».
- Ofrece flechas para ir al anterior o siguiente resultado; al llegar al extremo,
  continúa por el otro. F3 y Mayús+F3 hacen lo mismo.
- Cada fila muestra la página y el contexto de la coincidencia. Pulsarla desplaza
  el documento a la posición del texto, incluso si está al final de una página.
- Resalta el resultado activo en naranja, con borde, y los demás en amarillo.
- Permite distinguir mayúsculas y buscar palabras completas. El texto de la
  consulta se interpreta literalmente, incluidos correos y signos de puntuación.
- Ctrl+F abre el panel y enfoca la consulta. Esc desde la búsqueda cierra el panel
  y retira sus resaltados. Vaciar el campo también limpia los resultados.

Las apariciones se cuentan de forma individual, aunque estén muy próximas o
ocupen varias líneas. Se normalizan ligaduras y formas Unicode compatibles y se
admiten palabras con guion de corte. Las frases pueden continuar entre líneas de
un mismo bloque; no se unen bloques independientes, para evitar coincidencias
falsas entre columnas. Se utiliza el texto extraíble o la capa OCR ya existente.

La búsqueda se ejecuta en el proceso PDF serial, sobre la copia inmutable en
disco, sin inventariar fuentes, reescribir el PDF ni cambiar su historial. La
lista usa filas virtuales y los resaltados se dibujan en las páginas cargadas
y visibles. Navegar por los
resultados de una página ya cargada no repite su análisis.

Cambiar la consulta invalida el trabajo anterior. Si el proceso está ocupado,
solo queda pendiente la consulta más reciente. Cerrar el panel o la ventana
cancela la búsqueda en puntos seguros. Cambiar de documento, de revisión o de
vista original elimina las coincidencias anteriores. La restauración diferida
del desplazamiento de una pestaña no deshace un salto de búsqueda ni accede a un
lector que ya se ha cerrado.

Las pruebas sintéticas cubren el contador, navegación y clic a la posición,
atajos, consultas obsoletas, campos de opciones a través del proceso PDF,
rotación, recorte de página, contexto Unicode, capas OCR, resultados vacíos,
10.000 filas y conservación de originales e historial. Se completaron además
comprobaciones de búsqueda de solo lectura con los dos documentos privados de
medición; estos documentos no se incluyen en las fuentes ni en la distribución.

Las barras de desplazamiento vertical y horizontal muestran el cursor de flecha
tanto en Lectura como en Edición, sin alterar el cursor de la herramienta dentro
del PDF.

Tras instalar correctamente la nueva versión, el instalador retira las copias
anteriores verificadas de PDF Modder y los instaladores antiguos reconocidos de
su caché de actualizaciones. Conserva los archivos personales y los archivos de
programa que hayan sido modificados. Las copias que estén en uso o no se puedan
verificar se conservan. Si una retirada no termina, deja una advertencia en el
informe de instalación. El espacio recuperado depende de las copias existentes
en cada PC.

Esta entrega está disponible mediante **Buscar actualizaciones**. Tras comprobar
el instalador y el manifiesto públicos, se retiran las publicaciones anteriores
de GitHub; se conservan las etiquetas y el historial del código.
