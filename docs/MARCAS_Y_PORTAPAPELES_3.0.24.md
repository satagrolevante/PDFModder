# Marcas, inserción y portapapeles 3.0.24

El orden predeterminado de un elemento nuevo es `page_end`; una petición explícita
`page_start` conserva su significado. No se pide una segunda confirmación de orden
para texto nuevo. Una imagen informativa sigue utilizando su descripción alternativa.

El compositor crea temporalmente un párrafo de posicionamiento con MCID propio.
Solo se exporta el texto solicitado. Se compara el PDF final con los bytes originales
y con la estructura planificada; se verifican la desaparición del ancla, los caracteres,
los recursos, los gráficos y los píxeles vecinos. Esto permite reutilizar códigos
originales de fuentes parciales al copiar y pegar dentro del mismo documento.

Las marcas inline sin StructTreeRoot se conservan. Se reconocen descripciones
ActualText, idioma y asociaciones OCG/OCMD registradas de visibilidad simple. No se
convierte el texto a imagen ni se eliminan etiquetas o capas para desbloquearlo.
Una sustitución parcial con descripción lógica distinta requiere seleccionar el
bloque completo. Los ámbitos con roles, idiomas o capas independientes conservan
sus límites. Las relaciones dinámicas o ambiguas mantienen su diagnóstico.

La prueba de fuentes del portapapeles conserva el modelo completo de la página,
retira solo la selección y reproduce esa selección en una copia. Se comprueba así
la fuente sin confundir los caracteres vecinos con un fallo de fidelidad. Los
programas de fuentes y CMaps se identifican exactamente; la normalización numérica
acepta solo la equivalencia de representación binaria de 32 bits utilizada por el
serializador. Se mantiene la compatibilidad con identidades de versiones anteriores
cuando coinciden sus recursos originales.

El instalador confirma éxito únicamente después del trabajo y del informe final.
Utiliza un temporizador de interfaz de tres segundos, sin un diálogo modal que
obligue a pulsar Aceptar. El error no inicia ese temporizador.
