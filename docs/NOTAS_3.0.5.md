# PDF Modder 3.0.5

Reduce el trabajo repetido al preparar y aceptar cambios de texto, conservando
las comprobaciones del PDF y la aceptación de la misma revisión validada.

Añade al menú contextual del Explorador **Convertir a PDF** para DOC/DOCX y
**Combinar archivos PDF** para selecciones de PDF. La conversión local utiliza
Word o LibreOffice instalado, se puede cancelar y guarda sin sobrescribir. La
combinación permite revisar y ordenar todos los seleccionados antes de crear el
documento nuevo. En Windows 11 aparecen en **Mostrar más opciones**.
[Requisitos, uso y límites](MENU_CONTEXTUAL.md).

- Los borradores sustituidos se detienen en puntos seguros del proceso. El
  último cambio tiene prioridad y los resultados o errores antiguos no cambian
  la vista, el PDF ni el historial. Las llamadas nativas ya iniciadas terminan
  antes del siguiente punto de cancelación.
- Aceptar el mismo borrador que se está calculando conserva ese trabajo. Una
  revisión ya validada y una solicitud idéntica reutilizan sus bytes y su informe;
  un cambio de texto, formato o área requiere validar el nuevo resultado.
- El análisis de una fuente verificada se conserva entre borradores. Hay una
  fuente y un candidato como máximo en esta caché global, con un presupuesto
  inicial estimado de 160 MiB por grafo. El analizador puede resolver más objetos
  después; estas estimaciones no representan un límite exacto de RAM. Cerrar o
  suspender una sesión libera sus análisis retenidos.
- Las páginas con contenido y recursos idénticos reutilizan huellas completas
  vinculadas al SHA-256 de la revisión y a los límites de análisis. Los lectores
  PDF permanecen privados. Las huellas se limitan a cuatro revisiones y 8 MiB.
- Los ámbitos de texto BT/ET y Forms comprobados reutilizan hasta 2048 huellas,
  únicamente cuando se demuestra que la página y sus recursos son los mismos.
  Los resultados incompletos, cancelados o de lectores de otra revisión no
  autorizan la reutilización. Una prueba incierta conserva la comprobación completa.
- La edición de texto evita buscar objetos duplicados y recomprimir todo el
  documento para cada borrador. Retira objetos huérfanos y compacta referencias;
  conserva los filtros de los flujos existentes. Se valida, acepta y guarda el
  mismo resultado, y las ediciones sucesivas no acumulan sus flujos antiguos.

Se mantienen las verificaciones de texto, posiciones, fuentes, pintura, recortes,
enlaces, recursos, estructura accesible, metadatos, marcadores y páginas ajenas.
Las pruebas públicas utilizan PDF sintéticos; los documentos privados de medición
no forman parte de la entrega.

## Medición antes y después

Comparación con 3.0.4 en el mismo entorno Linux, sin otras pruebas pesadas en
paralelo y con el canal de cancelación activo. Los tiempos corresponden a validar
borradores sobre la misma revisión, después de abrir y preparar la selección.

| Documento | Operación | 3.0.4 | 3.0.5 |
| --- | --- | ---: | ---: |
| Documento A, 122 páginas | Primer borrador | 9,48 s | 5,95 s |
| Documento A, 122 páginas | Otro borrador distinto | 14,83 s | 5,37 s |
| Documento B, 9 páginas | Primer borrador | 0,57 s | 0,57 s |
| Documento B, 9 páginas | Otro borrador distinto | 0,58 s | 0,39 s |

Aceptar una revisión ya validada tarda aproximadamente 0,071 s en A y 0,002 s
en B, sin incluir la posterior actualización visual. Son mediciones de
estos cambios y este entorno, no una garantía para todos los PDF o equipos Windows.

Las comprobaciones independientes conservaron páginas ajenas, vecinos, metadatos,
XML, marcadores y originales. El archivo resultante de esta prueba ocupa un
20,84 % más en A y un 0,91 % más en B que con 3.0.4: evitar la búsqueda
global de duplicados reduce tiempo a cambio de un resultado menos compactado.
Se verificaron también ediciones sucesivas sin acumulación de flujos antiguos.

## Verificación

Pasan 272 pruebas dirigidas y el recorrido general de interfaz desde las fuentes.
Se completaron dos recorridos adicionales de Qt con los documentos de medición:
edición rápida que sustituye un borrador en curso, aceptación del último cambio,
guardado, reapertura y deshacer. Los originales permanecen intactos. Las pruebas
incluyen cancelación en un proceso real, protección frente a lectores y pruebas
de otra revisión, recursos o semánticas alterados, límites de caché y escritura
exacta del resultado validado. Esta verificación Linux fuera de pantalla no
acredita todavía el instalador ni un escritorio Windows.

La cancelación es cooperativa y los cambios complejos siguen teniendo un coste.
Esta revisión está preparada en las fuentes, pendiente de compilación y
publicación del instalador Windows.
