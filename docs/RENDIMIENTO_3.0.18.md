# Rendimiento y compatibilidad de PDFModder 3.0.18

Comparación del código fuente 3.0.17 → 3.0.18. Las mediciones preceden a la compilación Windows. La versión 3.0.18 se publicó el 3 de noviembre de 2026, con regresiones específicas, recorrido GUI, instalación/desinstalación e integración nativa comprobados en Windows.

## Alcance de la medición

Pruebas en Linux, 3 vCPU y límite de memoria de 10 GiB, Python 3.12, Qt offscreen y MuPDF. Se ejecutó una acción cada vez, sin bancos de prueba concurrentes. Cada caso tiene una sola muestra salvo las repeticiones identificadas. Las cifras son observaciones de este equipo, no percentiles ni garantías de tiempo.

La caché del sistema operativo se mantuvo normal, sin vaciarla. Una sesión nueva significa caché de aplicación nueva, no disco ni sistema operativo fríos. Los recorridos del motor usan Session sin GUI/IPC; los recorridos de interfaz usan MainWindow real con su worker y Qt offscreen. La edición incluye selección cuando consta, preparación/validación, confirmación y actualización de página; la preparación inicial se mide aparte.

Se excluyen los directorios initial-pre-scopefix, pre-pin-measurements, pre-image-reuse-measurements y otros perfiles diagnósticos de los tiempos de las acciones. La muestra de guardado real se selecciona explícitamente y solo aporta su tiempo de guardar, sin tiempos de preparación ni campos diagnósticos de perfilado.

## Seis mejoras y límites

1. Reutilización de análisis y comprobaciones de contenido, recursos y etiquetas ligados a la revisión exacta; los casos ambiguos conservan la validación completa.
2. Escritura de transacciones sin recomprimir y deduplicar todo el documento en cada operación; se verifican los bytes finales.
3. Evidencia privada de validación para guardar cambios reales, con escritura exacta, fsync, lectura/hash y reemplazo atómico.
4. Preparación conservada al aceptar, deshacer y regresar a pestañas, con límites de caché y preparación diferida de imágenes y fuentes.
5. Publicación inmediata del texto visible al copiar y preparación posterior del formato portable; el corte mantiene su comprobación previa.
6. Reutilización del contexto de impresión y transporte RGB progresivo, con decodificación y pintura en un hilo dedicado y progreso/cancelación.

Estas rutas mantienen comprobaciones de identidad, estructura y contenido. La caché estimada no limita toda la memoria del proceso. La salida puede ocupar más que una copia recomprimida. Las mejoras de compatibilidad se comprueban por separado del tiempo.

## Respuesta de la interfaz

El recorrido GUI final contiene 119 acciones. El mayor intervalo registrado por la sonda del bucle fue 129,132 ms; el recuento de intervalos superiores a 100 ms fue 1. La sonda tiene un intervalo nominal de 20 ms. Estos intervalos miden capacidad de respuesta, no la duración total de la operación.

| Documento | Acción | 3.0.17 | 3.0.18 |
| --- | --- | --- | --- |
| Ficha cliente (3 páginas) | Abrir y mostrar primera página | 0,924 s | 0,852 s |
| Ficha cliente (3 páginas) | Entrar en EDITAR por primera vez | 3,223 s | 1,798 s |
| Ficha cliente (3 páginas) | Ir a página siguiente en edición | 3,261 s | 1,729 s |
| Ficha cliente (3 páginas) | Volver a EDITAR ya preparado | 0,066 s | 0,095 s |
| DSA rev35 (122 páginas) | Abrir y mostrar primera página | 0,231 s | 0,243 s |
| DSA rev35 (122 páginas) | Entrar en EDITAR por primera vez | 5,949 s | 5,517 s |
| DSA rev35 (122 páginas) | Ir a página siguiente en edición | 0,807 s | 1,151 s |
| DSA rev35 (122 páginas) | Copiar selección visible | 1,250 s | 0,003 s |
| DSA rev35 (122 páginas) | Volver a EDITAR ya preparado | 0,098 s | 0,077 s |
| LABCOLOR (9 páginas) | Abrir y mostrar primera página | 0,344 s | 0,345 s |
| LABCOLOR (9 páginas) | Entrar en EDITAR por primera vez | 0,593 s | 0,471 s |
| LABCOLOR (9 páginas) | Ir a página siguiente en edición | 0,318 s | 0,225 s |
| LABCOLOR (9 páginas) | Copiar selección visible | 0,435 s | 0,003 s |
| LABCOLOR (9 páginas) | Volver a EDITAR ya preparado | 0,207 s | 0,178 s |
| DSA rev36 (123 páginas) | Abrir y mostrar primera página | 0,182 s | 0,217 s |
| DSA rev36 (123 páginas) | Entrar en EDITAR por primera vez | 5,498 s | 5,887 s |
| DSA rev36 (123 páginas) | Ir a página siguiente en edición | 0,800 s | 0,597 s |
| DSA rev36 (123 páginas) | Copiar selección visible | 0,670 s | 0,003 s |
| DSA rev36 (123 páginas) | Volver a EDITAR ya preparado | 0,086 s | 0,081 s |
| Ficha cliente (3 páginas) | Cambiar de pestaña preparada | 3,181 s | 0,120 s |
| DSA rev35 (122 páginas) | Cambiar de pestaña preparada | 5,777 s | 0,076 s |
| Ficha cliente (3 páginas) | Cambiar de pestaña preparada · 2 | 3,835 s | 0,116 s |
| LABCOLOR (9 páginas) | Cambiar de pestaña preparada | 0,740 s | 0,196 s |
| DSA rev35 (122 páginas) | Cambiar de pestaña preparada · 2 | 6,036 s | 0,093 s |
| LABCOLOR (9 páginas) | Cambiar de pestaña preparada · 2 | 0,697 s | 0,188 s |
| Varias pestañas | Cerrar pestaña con otras abiertas | 6,918 s | 0,161 s |
| Varias pestañas | Cerrar pestaña con otras abiertas · 2 | 3,544 s | 0,206 s |
| Varias pestañas | Cerrar pestaña con otras abiertas · 3 | 0,113 s | 0,120 s |

Cambios entre pestañas ya preparadas: 6 muestras, máximo 0,196 s; 0 superan el objetivo orientativo de 0,2–0,3 s.

Arranque de este recorrido, desde las importaciones hasta mostrar la ventana: 0,594 s → 0,467 s. Es una muestra por versión, con la caché normal del sistema operativo.

| Memoria conjunta GUI + worker | 3.0.17 | 3.0.18 |
| --- | --- | --- |
| Pico muestreado | 638,758 MiB | 627,832 MiB |
| Antes de cerrar la ventana | 524,113 MiB | 608,480 MiB |

Los presupuestos de caché limitan los valores retenidos, no todo el RSS. El pico y la memoria final se muestrean en puntos concretos del recorrido, sin afirmar que sean el máximo absoluto del proceso.

## Edición y guardado

| Documento | Acción | 3.0.17 | 3.0.18 | Cambio medible |
| --- | --- | --- | --- | --- |
| Ficha cliente (3 páginas) | Preparar primera página de edición (motor) | 2,659 s | 3,501 s | -31,7 % |
| Ficha cliente (3 páginas) | Añadir texto | 3,592 s | 3,648 s | -1,5 % |
| Ficha cliente (3 páginas) | Modificar texto añadido | 1,872 s | 1,963 s | -4,9 % |
| Ficha cliente (3 páginas) | Mover texto añadido | 1,896 s | 1,625 s | +14,3 % |
| Ficha cliente (3 páginas) | Borrar palabra añadida | 3,714 s | 2,017 s | +45,7 % |
| Ficha cliente (3 páginas) | Borrar párrafo añadido | 3,957 s | 2,034 s | +48,6 % |
| Ficha cliente (3 páginas) | Añadir imagen | 2,844 s | 3,054 s | -7,4 % |
| Ficha cliente (3 páginas) | Mover imagen añadida | 3,020 s | 3,162 s | -4,7 % |
| Ficha cliente (3 páginas) | Redimensionar imagen añadida | 2,809 s | 3,241 s | -15,4 % |
| Ficha cliente (3 páginas) | Girar imagen añadida | 2,946 s | 3,282 s | -11,4 % |
| Ficha cliente (3 páginas) | Reemplazar imagen añadida | 2,915 s | 3,523 s | -20,9 % |
| Ficha cliente (3 páginas) | Borrar imagen añadida | 3,638 s | 3,800 s | -4,5 % |
| Ficha cliente (3 páginas) | Guardar copia tras el recorrido (bytes distintos) | 2,619 s | 0,013 s | +99,5 % |
| DSA rev35 (122 páginas) | Preparar primera página de edición (motor) | 5,680 s | 5,020 s | +11,6 % |
| DSA rev35 (122 páginas) | Modificar fecha original | 8,491 s | 4,784 s | +43,7 % |
| DSA rev35 (122 páginas) | Modificar pie original | error · 0,342 s | 3,666 s | sin ratio |
| DSA rev35 (122 páginas) | Modificar correo original | 8,898 s | 5,697 s | +36,0 % |
| DSA rev35 (122 páginas) | Borrar palabra original | 9,435 s | 5,415 s | +42,6 % |
| DSA rev35 (122 páginas) | Mover palabra original | error · 6,214 s | 5,686 s | sin ratio |
| DSA rev35 (122 páginas) | Borrar párrafo original | 9,373 s | 6,095 s | +35,0 % |
| DSA rev35 (122 páginas) | Añadir texto | error · 4,912 s | 6,754 s | sin ratio |
| DSA rev35 (122 páginas) | Modificar texto añadido | sin muestra equivalente | 4,689 s | sin ratio |
| DSA rev35 (122 páginas) | Mover texto añadido | sin muestra equivalente | 3,962 s | sin ratio |
| DSA rev35 (122 páginas) | Borrar palabra añadida | sin muestra equivalente | 5,304 s | sin ratio |
| DSA rev35 (122 páginas) | Borrar párrafo añadido | sin muestra equivalente | 4,913 s | sin ratio |
| DSA rev35 (122 páginas) | Añadir imagen | error · 0,036 s | 6,075 s | sin ratio |
| DSA rev35 (122 páginas) | Mover imagen añadida | sin muestra equivalente | 3,478 s | sin ratio |
| DSA rev35 (122 páginas) | Redimensionar imagen añadida | sin muestra equivalente | 3,939 s | sin ratio |
| DSA rev35 (122 páginas) | Girar imagen añadida | sin muestra equivalente | 4,213 s | sin ratio |
| DSA rev35 (122 páginas) | Reemplazar imagen añadida | sin muestra equivalente | error · 0,047 s | sin ratio |
| DSA rev35 (122 páginas) | Borrar imagen añadida | sin muestra equivalente | 5,119 s | sin ratio |
| DSA rev35 (122 páginas) | Guardar el original restaurado tras deshacer | 2,969 s | sin muestra equivalente | sin ratio |
| DSA rev35 (122 páginas) | Guardar copia tras el recorrido (bytes distintos) | sin muestra equivalente | 0,041 s | sin ratio |
| DSA rev36 (123 páginas) | Preparar primera página de edición (motor) | 5,791 s | 7,264 s | -25,4 % |
| DSA rev36 (123 páginas) | Modificar fecha original | 7,647 s | 5,001 s | +34,6 % |
| DSA rev36 (123 páginas) | Modificar pie original | error · 0,367 s | 3,884 s | sin ratio |
| DSA rev36 (123 páginas) | Modificar correo original | 8,072 s | 5,215 s | +35,4 % |
| DSA rev36 (123 páginas) | Borrar palabra original | 10,457 s | 5,991 s | +42,7 % |
| DSA rev36 (123 páginas) | Mover palabra original | error · 6,567 s | 5,758 s | sin ratio |
| DSA rev36 (123 páginas) | Borrar párrafo original | 10,927 s | 5,778 s | +47,1 % |
| DSA rev36 (123 páginas) | Añadir texto | error · 6,179 s | 7,603 s | sin ratio |
| DSA rev36 (123 páginas) | Modificar texto añadido | sin muestra equivalente | 4,394 s | sin ratio |
| DSA rev36 (123 páginas) | Mover texto añadido | sin muestra equivalente | 4,664 s | sin ratio |
| DSA rev36 (123 páginas) | Borrar palabra añadida | sin muestra equivalente | 4,332 s | sin ratio |
| DSA rev36 (123 páginas) | Borrar párrafo añadido | sin muestra equivalente | 4,685 s | sin ratio |
| DSA rev36 (123 páginas) | Añadir imagen | error · 0,034 s | 5,751 s | sin ratio |
| DSA rev36 (123 páginas) | Mover imagen añadida | sin muestra equivalente | 3,385 s | sin ratio |
| DSA rev36 (123 páginas) | Redimensionar imagen añadida | sin muestra equivalente | 4,244 s | sin ratio |
| DSA rev36 (123 páginas) | Girar imagen añadida | sin muestra equivalente | 3,629 s | sin ratio |
| DSA rev36 (123 páginas) | Reemplazar imagen añadida | sin muestra equivalente | error · 0,058 s | sin ratio |
| DSA rev36 (123 páginas) | Borrar imagen añadida | sin muestra equivalente | 5,531 s | sin ratio |
| DSA rev36 (123 páginas) | Guardar el original restaurado tras deshacer | 1,538 s | sin muestra equivalente | sin ratio |
| DSA rev36 (123 páginas) | Guardar copia tras el recorrido (bytes distintos) | sin muestra equivalente | 0,046 s | sin ratio |
| DSA rev36 (123 páginas) | Guardar DSA rev36 con la fecha modificada | 2,513 s | 0,041 s | +98,4 % |
| LABCOLOR (9 páginas) | Preparar primera página de edición (motor) | 0,334 s | 0,393 s | -17,5 % |
| LABCOLOR (9 páginas) | Modificar fecha original | 1,607 s | 1,497 s | +6,8 % |
| LABCOLOR (9 páginas) | Modificar pie original | 1,552 s | 1,729 s | -11,4 % |
| LABCOLOR (9 páginas) | Borrar palabra original | 0,487 s | 0,677 s | -39,1 % |
| LABCOLOR (9 páginas) | Mover palabra original | 0,527 s | 0,587 s | -11,2 % |
| LABCOLOR (9 páginas) | Borrar párrafo original | error · 0,085 s | 0,696 s | sin ratio |
| LABCOLOR (9 páginas) | Añadir texto | 1,251 s | 1,329 s | -6,3 % |
| LABCOLOR (9 páginas) | Modificar texto añadido | 1,774 s | 1,779 s | -0,3 % |
| LABCOLOR (9 páginas) | Mover texto añadido | 1,535 s | 1,714 s | -11,7 % |
| LABCOLOR (9 páginas) | Borrar palabra añadida | 1,365 s | 1,320 s | +3,2 % |
| LABCOLOR (9 páginas) | Borrar párrafo añadido | 1,451 s | 1,366 s | +5,9 % |
| LABCOLOR (9 páginas) | Añadir imagen | 0,732 s | 0,793 s | -8,3 % |
| LABCOLOR (9 páginas) | Mover imagen añadida | 0,725 s | 0,937 s | -29,2 % |
| LABCOLOR (9 páginas) | Redimensionar imagen añadida | 0,790 s | 1,060 s | -34,1 % |
| LABCOLOR (9 páginas) | Girar imagen añadida | 0,763 s | 0,859 s | -12,5 % |
| LABCOLOR (9 páginas) | Reemplazar imagen añadida | 0,817 s | 0,894 s | -9,3 % |
| LABCOLOR (9 páginas) | Borrar imagen añadida | 0,742 s | 0,847 s | -14,2 % |
| LABCOLOR (9 páginas) | Guardar copia tras el recorrido (bytes distintos) | 0,201 s | 0,008 s | +96,1 % |

El porcentaje expresa reducción del tiempo: un valor negativo es una regresión medida. Los errores anteriores que pasan a completarse son mejoras de compatibilidad; sus tiempos de rechazo no sirven para calcular aceleración.

En 3.0.17, las copias DSA del recorrido edit_* tenían exactamente el SHA-256 del original: se habían deshecho las ediciones y las adiciones fallaron. Se rotulan como guardado del original restaurado y no se comparan con un guardado real de cambios. La fila de fecha modificada, cuando se incluye, usa copias distintas del original y cambio de fecha verificado de forma independiente; excluye los tiempos del perfilador.

Un hash distinto al final de edit_* solo acredita bytes diferentes: las adiciones y borrados del recorrido pueden restaurar visualmente el contenido inicial. Por eso esa fila se denomina copia tras el recorrido. La prueba de un cambio visible real se limita a la fecha modificada y comprobada por extracción independiente.

De 63 ediciones completadas, 25 superan el umbral orientativo usado para revisar esta muestra: 2 s para ficha/LABCOLOR y 5 s para los DSA complejos. Los objetivos de 1–2 s en ediciones habituales y 2–5 s en complejas siguen siendo objetivos, no garantías.

| Documento | Acción que supera el objetivo | Tiempo | Objetivo de revisión |
| --- | --- | --- | --- |
| Ficha cliente (3 páginas) | Añadir texto | 3,648 s | ≤2 s |
| Ficha cliente (3 páginas) | Borrar palabra añadida | 2,017 s | ≤2 s |
| Ficha cliente (3 páginas) | Borrar párrafo añadido | 2,034 s | ≤2 s |
| Ficha cliente (3 páginas) | Añadir imagen | 3,054 s | ≤2 s |
| Ficha cliente (3 páginas) | Mover imagen añadida | 3,162 s | ≤2 s |
| Ficha cliente (3 páginas) | Redimensionar imagen añadida | 3,241 s | ≤2 s |
| Ficha cliente (3 páginas) | Girar imagen añadida | 3,282 s | ≤2 s |
| Ficha cliente (3 páginas) | Reemplazar imagen añadida | 3,523 s | ≤2 s |
| Ficha cliente (3 páginas) | Borrar imagen añadida | 3,800 s | ≤2 s |
| DSA rev35 (122 páginas) | Borrar palabra original | 5,415 s | ≤5 s |
| DSA rev35 (122 páginas) | Mover palabra original | 5,686 s | ≤5 s |
| DSA rev35 (122 páginas) | Borrar párrafo original | 6,095 s | ≤5 s |
| DSA rev35 (122 páginas) | Modificar correo original | 5,697 s | ≤5 s |
| DSA rev35 (122 páginas) | Añadir texto | 6,754 s | ≤5 s |
| DSA rev35 (122 páginas) | Borrar palabra añadida | 5,304 s | ≤5 s |
| DSA rev35 (122 páginas) | Añadir imagen | 6,075 s | ≤5 s |
| DSA rev35 (122 páginas) | Borrar imagen añadida | 5,119 s | ≤5 s |
| DSA rev36 (123 páginas) | Modificar fecha original | 5,001 s | ≤5 s |
| DSA rev36 (123 páginas) | Borrar palabra original | 5,991 s | ≤5 s |
| DSA rev36 (123 páginas) | Mover palabra original | 5,758 s | ≤5 s |
| DSA rev36 (123 páginas) | Borrar párrafo original | 5,778 s | ≤5 s |
| DSA rev36 (123 páginas) | Modificar correo original | 5,215 s | ≤5 s |
| DSA rev36 (123 páginas) | Añadir texto | 7,603 s | ≤5 s |
| DSA rev36 (123 páginas) | Añadir imagen | 5,751 s | ≤5 s |
| DSA rev36 (123 páginas) | Borrar imagen añadida | 5,531 s | ≤5 s |

## Operaciones de páginas y documento

La medición final seleccionó nueve operaciones de la batería de referencia: propiedades, giro, recorte, extracción, reordenación, borrado y combinación. No se sustituyen las operaciones omitidas por resultados de ensayos parciales. Cada caso abre una sesión aislada; el tiempo mostrado excluye esa preparación inicial e incluye confirmar y refrescar cuando corresponde.

| Documento | Acción | 3.0.17 | 3.0.18 |
| --- | --- | --- | --- |
| DSA rev36 (123 páginas) | Modificar propiedades del documento | 7,079 s | 6,071 s |
| DSA rev36 (123 páginas) | Girar página | 45,681 s | 8,124 s |
| DSA rev36 (123 páginas) | Recortar página | 33,201 s | 7,390 s |
| DSA rev36 (123 páginas) | Extraer página | 8,158 s | 4,042 s |
| Ficha cliente (3 páginas) | Girar página | 9,589 s | 2,825 s |
| Ficha cliente (3 páginas) | Reordenar páginas | 11,638 s | 4,512 s |
| Ficha cliente (3 páginas) | Borrar página | 6,502 s | 1,819 s |
| Ficha cliente (3 páginas) | Extraer página | 3,482 s | 0,039 s |
| Ficha cliente (3 páginas) | Combinar con LABCOLOR | 10,444 s | 2,888 s |

## Impresión y firmas

El banco anterior imprimía con Session y QPrinter a PDF directamente. El banco nuevo usa MainWindow, IPC y el hilo de impresión reales, también con QPrinter a PDF. Se muestran ambos tiempos, sin un ratio estricto entre rutas. En particular, los 45,116 s anteriores de DSA rev36 no permiten por sí solos afirmar una aceleración proporcional de la aplicación.

| Documento | Acción | Muestra | 3.0.17 | 3.0.18 |
| --- | --- | --- | --- | --- |
| Ficha cliente (3 páginas) | Imprimir a dispositivo PDF | 3 páginas · 300 ppp | 2,443 s | 1,550 s |
| Ficha cliente (3 páginas) | Imprimir a dispositivo PDF | 1 página · 600 ppp | 1,047 s | sin muestra equivalente |
| Ficha cliente (3 páginas) | Colocar firma manuscrita y actualizar página |  | 2,787 s | 4,830 s |
| Ficha cliente (3 páginas) | Vista previa de firma digital visible | repetición 1 | 0,439 s | 0,403 s |
| Ficha cliente (3 páginas) | Vista previa de firma digital visible | repetición 2 | 0,196 s | 0,188 s |
| Ficha cliente (3 páginas) | Firma digital visible y guardado |  | 3,184 s | 2,111 s |
| Ficha cliente (3 páginas) | Firma digital invisible y guardado |  | 0,205 s | 0,160 s |
| DSA rev35 (122 páginas) | Imprimir a dispositivo PDF | 3 páginas · 300 ppp | 1,114 s | 0,633 s |
| DSA rev35 (122 páginas) | Imprimir a dispositivo PDF | 1 página · 600 ppp | 0,896 s | sin muestra equivalente |
| DSA rev35 (122 páginas) | Colocar firma manuscrita y actualizar página |  | error · 0,033 s | 6,817 s |
| DSA rev35 (122 páginas) | Vista previa de firma digital visible | repetición 1 | error · 0,070 s | 0,350 s |
| DSA rev35 (122 páginas) | Firma digital visible y guardado |  | error · 0,076 s | 5,520 s |
| DSA rev35 (122 páginas) | Firma digital invisible y guardado |  | 11,465 s | 0,273 s |
| DSA rev36 (123 páginas) | Imprimir a dispositivo PDF | 123 páginas · 300 ppp | 45,116 s | 27,674 s |
| DSA rev36 (123 páginas) | Imprimir a dispositivo PDF | 1 página · 600 ppp | 0,981 s | sin muestra equivalente |
| DSA rev36 (123 páginas) | Colocar firma manuscrita y actualizar página |  | error · 0,032 s | 7,992 s |
| DSA rev36 (123 páginas) | Vista previa de firma digital visible | repetición 1 | error · 0,592 s | 1,102 s |
| DSA rev36 (123 páginas) | Firma digital visible y guardado |  | error · 0,066 s | 7,277 s |
| DSA rev36 (123 páginas) | Firma digital invisible y guardado |  | 10,679 s | 0,282 s |
| LABCOLOR (9 páginas) | Imprimir a dispositivo PDF | 3 páginas · 300 ppp | 1,055 s | 0,720 s |
| LABCOLOR (9 páginas) | Imprimir a dispositivo PDF | 1 página · 600 ppp | 0,923 s | sin muestra equivalente |
| LABCOLOR (9 páginas) | Colocar firma manuscrita y actualizar página |  | 0,460 s | 1,056 s |
| LABCOLOR (9 páginas) | Vista previa de firma digital visible | repetición 1 | 0,156 s | 0,165 s |
| LABCOLOR (9 páginas) | Vista previa de firma digital visible | repetición 2 | 0,190 s | 0,155 s |
| LABCOLOR (9 páginas) | Firma digital visible y guardado |  | 0,372 s | 0,509 s |
| LABCOLOR (9 páginas) | Firma digital invisible y guardado |  | 0,160 s | 0,164 s |
| DSA rev35 (122 páginas) | Vista previa de firma digital visible | repetición 2 | sin muestra equivalente | 0,336 s |
| DSA rev36 (123 páginas) | Vista previa de firma digital visible | repetición 2 | sin muestra equivalente | 0,353 s |

| Documento | Páginas / ppp | Primera página enviada | Máximo intervalo GUI | Intervalos >100 ms |
| --- | --- | --- | --- | --- |
| Ficha cliente (3 páginas) | 3 / 300 | 0,543 s | 299,982 ms | 3 |
| DSA rev35 (122 páginas) | 3 / 300 | 0,205 s | 140,839 ms | 3 |
| DSA rev36 (123 páginas) | 123 / 300 | 0,244 s | 198,583 ms | 124 |
| LABCOLOR (9 páginas) | 3 / 300 | 0,257 s | 172,565 ms | 3 |

El envío en un hilo dedicado no consiguió mantener todos los intervalos de la interfaz por debajo de 100 ms con el backend PDF de Qt. Una sonda separada, sin uso como comparación de rendimiento, registró `QPainter.drawImage` durante 0,261 s y un hueco del bucle GUI coincidente de 0,263 s. Esto acota el trabajo pendiente a ese tramo del backend en este entorno; no demuestra cómo responderá un controlador físico de Windows. La evidencia está en `output/audit-app-v318/print-gap-probe/result.json`.

El ensayo de firma ejecuta dos vistas previas visibles y después firma primero de forma visible y luego invisible en la misma sesión. Los tiempos de firma y guardado aprovechan la preparación anterior; la firma invisible indicada no representa una primera operación en frío. La preparación inicial de la sesión se mide por separado en los datos completos.

En los DSA de referencia las vistas previas visibles se rechazaban; por ello, la firma invisible anterior no tuvo la misma preparación reutilizable. Esos tiempos tampoco se usan para calcular una aceleración estricta.

Las firmas criptográficas usan un PFX sintético de prueba. Los resultados de integridad y cobertura de bytes se conservan en el JSON; no prueban confianza externa del certificado. No se ensayaron impresora física, controladores, doble cara física, almacén de certificados ni PIN humano de Windows. La conservación estructural etiquetada no equivale a certificación PDF/UA.

## Compatibilidad e integridad

| Documento | Caso | 3.0.17 | 3.0.18 |
| --- | --- | --- | --- |
| DSA rev35 (122 páginas) | Modificar pie original | error | correcto |
| DSA rev35 (122 páginas) | Mover palabra original | error | correcto |
| DSA rev35 (122 páginas) | Añadir texto | error | correcto |
| DSA rev35 (122 páginas) | Añadir imagen | error | correcto |
| DSA rev36 (123 páginas) | Modificar pie original | error | correcto |
| DSA rev36 (123 páginas) | Mover palabra original | error | correcto |
| DSA rev36 (123 páginas) | Añadir texto | error | correcto |
| DSA rev36 (123 páginas) | Añadir imagen | error | correcto |
| LABCOLOR (9 páginas) | Borrar párrafo original | error | correcto |
| DSA rev35 (122 páginas) | Colocar firma manuscrita y actualizar página | error | correcto |
| DSA rev35 (122 páginas) | Firma digital visible y guardado | error | correcto |
| DSA rev36 (123 páginas) | Colocar firma manuscrita y actualizar página | error | correcto |
| DSA rev36 (123 páginas) | Firma digital visible y guardado | error | correcto |

El contenido repartido entre streams se interpreta de forma conjunta. Se comprobaron los pies y los movimientos etiquetados, y el borrado del párrafo LABCOLOR con estilos distintos. Las restricciones de imágenes originales que no pueden aislarse siguen registradas como no compatibles. Reemplazar una imagen añadida en los DSA etiquetados conserva un bloqueo por la asignación/remapeo de etiquetas: aparece expresamente como error de compatibilidad en la tabla de pendientes; añadirla, moverla, escalarla, girarla y borrarla se evalúan por separado.

Las 22 comprobaciones registradas de los archivos fuente indican SHA-256 original sin cambios. Los hashes completos y los de las copias guardadas figuran en comparacion.json.

| Documento | Bytes de la copia edit_* diferentes del original |
| --- | --- |
| Ficha cliente (3 páginas) | sí |
| DSA rev35 (122 páginas) | sí |
| DSA rev36 (123 páginas) | sí |
| LABCOLOR (9 páginas) | sí |

## Pruebas y casos pendientes

Verificación final del código fuente completada. Las cifras siguientes corresponden a pruebas específicas; no se suman ejecuciones que comparten casos.

- Regresiones finales de los 13 archivos de prueba nuevos y ocho grupos relacionados: 208 pruebas correctas, sin fallos ni errores; 17,27 s. La selección de archivos figura en output/audit-app-v318/finish_audit.py
- Revisión independiente de anotaciones y operaciones de página: 82 pruebas correctas; incluye tres casos de matrices de apariencia alteradas que deben rechazar extracción, organización y recorte
- Recorrido de interfaz con los cuatro documentos y tres pestañas preparadas: 119 acciones correctas; originales intactos; comprobación adicional del cierre con LABCOLOR terminada con salida 0
- Operaciones de página tras la última corrección: 9 casos seleccionados correctos, con comprobación funcional y originales intactos
- Impresión y firmas: Recorrido terminado sin errores: salida PDF con 123 páginas, firmas manuales y firmas con certificado visible/invisible en los cuatro documentos; integridad criptográfica comprobada con certificado sintético
- Prueba de aplicación por GUI y proceso de trabajo: 19 pasos correctos; fuente 3.0.18, cierre normal, 7.915 s (`python scripts/release_v300.py --source-ui-only --headless-qa`)
- Guardado con modificación visible: Fecha cambiada confirmada mediante extracción independiente; SHA distinto en copia, original intacto y guardado atómico verificado
- Revisión del diff: git diff --check sin incidencias

Las pruebas se realizaron en Linux con Qt offscreen. No verifican un instalador Windows, impresoras físicas, controladores ni el almacén de certificados de Windows.
El recorrido GUI completo guardó sus 119 resultados y encontró al salir un fallo reproducible del portapapeles del backend Qt offscreen incluso sin PDFModder. Se corrigió únicamente el cierre del banco de pruebas, y se comprobó una salida normal adicional. Evidencia en qt-offscreen-clipboard-shutdown.json.
La salida QPrinter.PdfFormat conserva pausas breves en QPainter.drawImage pese al hilo dedicado. El diagnóstico aislado y sus límites se conservan en print-gap-probe/result.json.
Sustituir imágenes añadidas en los DSA etiquetados sigue rechazándose por falta de remapeo de etiquetas; los resultados medidos lo indican expresamente. Los tiempos objetivo no se alcanzan en todas las operaciones.

Resultados de acciones medidas, sin contar los totales anidados: 2 error, 1 no aplica, 361 correcto, 3 no compatible.

| Grupo | Documento | Acción | Estado | Motivo |
| --- | --- | --- | --- | --- |
| edit | Ficha cliente (3 páginas) | Mover imagen original | no compatible | La imagen hereda un recorte no rectangular o de texto; esta instancia no puede aislarse con garantías. |
| edit | DSA rev35 (122 páginas) | Mover imagen original | no compatible | Esta instancia no tiene un ámbito aislado q/cm/Do/Q; puede estar dentro de un formulario o una transformación compleja. |
| edit | DSA rev35 (122 páginas) | Reemplazar imagen añadida | error | PDF etiquetado: Modificar imágenes necesita asignar o remapear etiquetas nuevas; esta operación todavía no está habilitada. Sí puedes editar texto existente compatible. |
| edit | DSA rev36 (123 páginas) | Mover imagen original | no compatible | Esta instancia no tiene un ámbito aislado q/cm/Do/Q; puede estar dentro de un formulario o una transformación compleja. |
| edit | DSA rev36 (123 páginas) | Reemplazar imagen añadida | error | PDF etiquetado: Modificar imágenes necesita asignar o remapear etiquetas nuevas; esta operación todavía no está habilitada. Sí puedes editar texto existente compatible. |

Los recorridos GUI completos de referencia y candidato guardaron sus 119 acciones y terminaron después con código 139 al destruir el portapapeles Qt offscreen. Se reprodujo el mismo fallo en un programa mínimo de Qt sin importar PDFModder: salida 139 sin limpiar su portapapeles sintético y salida 0 al limpiarlo. El ajuste se aplicó solo al banco de pruebas, después de medir, y un recorrido adicional de cierre con LABCOLOR terminó con código 0. Los 119 tiempos finales se conservan; no se sustituyen por los del recorrido parcial de cierre. La aplicación conserva su portapapeles normal.

La reproducción mínima y el cambio del banco están documentados en `output/audit-app-v318/qt-offscreen-clipboard-shutdown.json`; el recorrido adicional figura en `output/audit-app-v318/run-shutdown-check-94cd94a3/result.json`.

## Evidencia reproducible

Los datos completos y sus fases están en [comparacion.json](../output/audit-app-v318/comparacion.json) y [comparacion.csv](../output/audit-app-v318/comparacion.csv). Los porcentajes solo aparecen cuando ambas acciones se completaron y coinciden su contexto registrado. Las diferencias de recorrido y los casos sin equivalente permanecen explícitos.

Entradas finales incluidas:

- `output/audit-app-v318/edit_ficha.json`
- `output/audit-app-v318/edit_dsa35.json`
- `output/audit-app-v318/edit_dsa36.json`
- `output/audit-app-v318/edit_labcolor.json`
- `output/audit-app-v318/run-final-ea4bb04c/result.json`
- `output/audit-app-v318/extra-results.json`
- `output/audit-app-v318/print-sign/print_sign_results.json`
- `output/audit-app-v318/spot-original-date-d385f9cd/result.json`

Generado en UTC: 2026-10-29T22:42:04.150297+00:00.
