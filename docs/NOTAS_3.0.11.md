# PDF Modder 3.0.11

## Interfaz y navegación

El botón **EDITAR** activa Edición y vuelve a Lectura al pulsarlo otra vez.
La barra prioriza **Página anterior · X de N · Página siguiente**, **EDITAR**,
**Mano**, **Seleccionar** y **Resaltar cambios**. El número admite escritura y
salto con Intro; las peticiones de navegación se conservan durante el renderizado.
Los botones de Guardar como, Guardar todo, Propiedades, Cifrado y Volver a Lectura
salen de la barra. Las acciones de archivo se mantienen en **Archivo**.

**Mano** arrastra exclusivamente la vista, con cursor abierto/cerrado. Seleccionar,
Escribir y Mover recuperan sus funciones habituales al salir de Mano. Los controles
respetan los bloqueos de borradores y operaciones de modificación; los cursores de
las barras de desplazamiento siguen siendo flechas. **Resaltar cambios** también
muestra las marcas en el lector continuo, sin modificar las imágenes del PDF.

El panel **Páginas / Recientes** se contrae y despliega con una flecha. Conserva
pestaña, selección, desplazamiento y anchura. El PDF gana espacio sin cambiar
su zoom. Su estado se sincroniza con **Vista > Panel de páginas y recientes**.

## Configuración

**Impresión > Recordar preferencias por impresora**, activado inicialmente,
conserva papel, orientación, escala, color, doble cara, resolución y agrupación.
Cada impresora dispone de su perfil; las opciones se guardan tras enviar
correctamente un trabajo. Cancelar no guarda cambios. Intervalos y copias se
eligen para cada trabajo; el controlador vuelve a verificar color y doble cara.
Las preferencias son locales, acotadas y se escriben de forma atómica.

**Aspecto > Tema claro / Tema oscuro** cambia inmediatamente los controles,
menús, cuadros e iconos y recuerda la elección. Los colores del PDF y el formato
del texto editado se conservan. El editor sobre la página mantiene una superficie
clara para representar los colores reales del documento.

## Selección de texto

El orden geométrico se analiza una vez por modelo/revisión de página. Se reutilizan
las posiciones de los caracteres y se evitan redibujados cuando el extremo no cambia.
El resaltado de caracteres contiguos utiliza menos objetos gráficos; los caracteres
seleccionados se mantienen intactos. Durante el arrastre, los avisos a los paneles
se agrupan en intervalos de 16 ms y se completan al soltar, copiar o iniciar edición.
Las cachés de lectura conservan los límites anteriores de páginas y memoria.

En una prueba sintética de 8.000 caracteres, 30 consultas al orden del texto
pasaron de 625,38 ms al repetir el análisis a 0,02 ms al reutilizarlo. Es una medida
del análisis geométrico, no del tiempo total de selección ni una garantía para
cualquier documento.

## Comprobaciones

Pruebas dirigidas de lectura/copia y selección entre páginas, columnas y recintos;
reutilización e invalidación del análisis; notificaciones y selección final;
preferencias independientes por impresora y capacidades del controlador; temas y
conservación de las imágenes del PDF; navegación durante el renderizado; Mano;
menús y panel contraíble. Una prueba de impresión genera un PDF local y comprueba
el orden/tamaño de las páginas y que el original permanece intacto. No se envían
trabajos a impresoras físicas.

Revisión visual de ambos temas y de la barra a 1280 × 850. En la prueba local,
la ventana sintética se preparó en unos 353 ms y el cambio de tema en unos 86 ms;
estas medidas no incluyen abrir/renderizar un PDF real.

Entrega Windows x64 con instalador, versión portable y código fuente. El canal
**Buscar actualizaciones** utiliza el instalador y su manifiesto de integridad
publicados en GitHub Releases.
