# PDF Modder 3.0.8

## Menús superiores

- **Archivo**: abrir, recuperar trabajo, guardar, guardar como, guardar todo,
  exportar, imprimir, compartir, propiedades, firma, cifrado, cerrar y salir.
- **Edición**: deshacer/rehacer, portapapeles, búsqueda y resultados, reemplazar,
  edición de texto e imágenes, inserción de contenido y edición de celdas y objetos.
- **Formato**: tipografía de la selección, fuente, tamaño, negrita, cursiva,
  subrayado, color, alineación, espaciado, sangrías, tabulaciones, opciones
  tipográficas, copia de formato y transformaciones de imagen.
- **Páginas**: organizar, rotar, insertar, reemplazar, eliminar, extraer,
  recortar, dividir y combinar.
- **Herramientas avanzadas**: propiedades, seguridad, firmas, objetos, inspector
  de fuentes, formularios, censura, etiquetas de accesibilidad y comparación.
- **Vista**: lectura, herramientas, miniaturas, zoom, ajuste de página y anchura,
  original y resaltado de cambios.
- **Configuración**: comprobación diaria de actualizaciones y búsqueda manual.

Los menús reutilizan las acciones de los paneles y sus controles de disponibilidad.
Las operaciones de edición requieren activar Herramientas. Los controles directos
de fuente, estilo y párrafo se habilitan durante la escritura sobre la página;
**Tipografía / formato…** conserva el diálogo de formato de una selección.
Negrita y cursiva siguen requiriendo variantes reales de la fuente.

Cerrar documento (Ctrl+W) y Salir mantienen Guardar / Descartar / Cancelar y
la validación de los borradores. Compartir ofrece **Copiar archivo** para pegarlo
como adjunto y **Abrir carpeta**. Si hay cambios pendientes, usa el mismo guardado
validado; cancelar o fallar el guardado impide compartir una copia anterior.
La aplicación no envía el documento automáticamente.

## Vista inicial y miniaturas

Al abrir un documento nuevo, se calcula el zoom de anchura con la geometría de
la primera página antes de renderizarla. No se analiza todo el documento ni se
genera una segunda imagen para ajustar el zoom. Las pestañas conservan el zoom
que haya elegido el usuario al volver a ellas.

Las miniaturas se adaptan al ancho útil del panel, incluida su barra de
desplazamiento, manteniendo el ancho del apartado izquierdo. El tamaño de
renderizado también se adapta; la lista continúa siendo virtual y solo se
generan las miniaturas visibles.

Entrega Windows x64 con instalador, versión portable y código fuente. El canal
**Buscar actualizaciones** utiliza el instalador y su manifiesto de integridad
publicados en GitHub Releases.

## Comprobaciones

88 pruebas dirigidas correctas con Qt offscreen: menús y selección de texto,
guardado y cierre, compartir un borrador real, búsqueda, lectura, actualizaciones,
apertura a anchura y lista virtual. La ventana real verifica el primer renderizado
ajustado y las miniaturas ampliadas; la lista se prueba también con 100.000 páginas
virtuales. Esta comprobación no sustituye la compilación y prueba del instalador Windows.
