# PDF Modder 3.0.0

Esta versión amplía la apertura, selección, edición y guardado con algoritmos
basados en el contenido y la geometría del PDF. No utiliza reglas para facturas,
formularios de una entidad ni nombres de archivos concretos. Mantiene el OCR
externo: abre el PDF con su capa buscable ya incorporada.

## Abrir y trabajar con documentos grandes

Al abrir, la copia original se captura en un archivo de trabajo inmutable y su
huella se calcula por bloques. La lectura y el render pueden abrir directamente
esa copia, sin mantener el PDF completo en memoria. La primera página tiene
prioridad; las dimensiones de las demás páginas se corrigen al necesitarlas.
La lista de páginas se representa con un modelo virtual y las miniaturas se
preparan cerca de la zona visible. Las cachés mantienen límites de memoria.

La copia y la huella requieren leer el archivo original completo antes de usar
la sesión. Por eso el inicio todavía depende del tamaño y la velocidad del disco;
esta versión no promete la apertura instantánea de archivos arbitrariamente grandes.
Al activar las herramientas se realizan las comprobaciones necesarias para editar.
Cambiar páginas o pestañas conserva la sesión, el historial y la copia original.

## Seleccionar lo que se quiere cambiar

Seleccione un alcance y pulse el texto: **Palabra**, **Línea**, **Párrafo** o
**Celda**. **Ampliar alcance** y **Reducir alcance** permiten corregir la selección
sin volver a empezar. Ctrl+clic añade o quita fragmentos. El alcance **Grupo del PDF**
conserva la selección según los bloques originales para los documentos que la necesitan.

Palabras, líneas y párrafos usan espacios, distancias, tamaño, dirección y barreras
gráficas. Las celdas necesitan un recinto cerrado reconocido en los trazos de la
página. Las columnas y los recintos sirven como límites de selección. Una tabla
sin bordes o una agrupación visual ambigua puede requerir elegir fragmentos o
corregir el área manualmente: la inferencia geométrica no decide el significado
del documento.

Un borrador que no cabe conserva lo escrito y señala el desbordamiento.
**Ampliar área…** cambia sus dimensiones; **Redistribuir líneas** reorganiza los
saltos suaves manteniendo los párrafos; **Cambiar tamaño…** aplica un tamaño
elegido expresamente. Estas opciones no cambian la letra silenciosamente.
La vista del PDF real y la validación final comprueban el resultado.

## Guardar y cerrar

| Acción | Resultado |
|---|---|
| **Guardar**, Ctrl+S | Utiliza el último destino de esa pestaña; si todavía no existe, pide crear una copia. |
| **Guardar como…**, Ctrl+Mayús+S | Permite elegir otro destino y lo recuerda para esa pestaña. |
| **Guardar todo**, Ctrl+Alt+S | Reúne los documentos con cambios y sus destinos; los valida y escribe por separado. |
| **Guardar** al cerrar | Aplica y valida el borrador pendiente, guarda el documento y después cierra. |
| **Descartar** al cerrar | Cierra la sesión sin escribir sus cambios pendientes. |
| **Cancelar** al cerrar | Mantiene la pestaña, sus cambios y su borrador. |

El cierre de la aplicación reúne todas las pestañas pendientes. Los borradores de
una pestaña inactiva se validan antes de guardarlos. Un fallo de composición,
validación o escritura interrumpe el cierre y conserva el trabajo pendiente.
Antes de instalar una actualización se ofrecen las mismas opciones para todas
las pestañas. Las sesiones permanecen abiertas si se cancela o si el instalador
no supera su verificación.
En Guardar todo, los documentos escritos antes de un fallo permanecen guardados;
los restantes continúan abiertos. La aplicación no declara que todas las escrituras
sean una única transacción de disco.

El archivo de entrada permanece protegido. Los destinos de un guardado por lotes
deben ser diferentes entre sí y de los originales abiertos. Un PDF firmado requiere
las operaciones específicas compatibles; Guardar no elude sus restricciones.
En Lectura, Guardar como permite crear una copia exacta del archivo sin preparar
las fuentes ni recomponer sus páginas; así conserva también su cifrado y sus firmas.

## Editar objetos PDF

**Editar objetos PDF…**, Ctrl+Mayús+G, presenta las apariciones reales de texto,
imágenes, vectores y Forms, incluidos los objetos anidados. Elija una aparición,
una operación y pulse **Previsualizar**; después acepte o cancele el resultado.

Puede **Mover**, **Cambiar escala**, **Girar**, **Duplicar** o **Modificar propiedades**
cuando la aparición lo permite. El giro y la escala toman el centro como referencia;
el desplazamiento usa coordenadas de la página. Las propiedades incluyen opacidad,
colores de relleno o trazo y grosor, según el tipo de objeto. El desplazamiento se
expresa en milímetros; el grosor se expresa en puntos PDF.

El motor identifica rangos de operadores y matrices. Cuando el recurso está
compartido, una edición interior copia únicamente la cadena de Forms de la aparición
elegida. Conserva recursos, BBox, matrices, grupos de transparencia, capas, recortes y
claves adicionales; las demás apariciones permanecen vinculadas a sus recursos
originales. Las transformaciones mantienen el contenido vectorial y el texto buscable.

Las propiedades disponibles pertenecen al objeto seleccionado: elegir un Form no
convierte todos sus componentes en una sola fuente o color. Los enlaces, campos y
anotaciones superpuestos se comprueban antes de transformar. Una matriz degenerada,
geometría no verificable, firmas, XFA o relaciones de accesibilidad que necesiten
reasignación pueden impedir una operación. Duplicar contenido etiquetado necesita
nuevas relaciones semánticas y se limita cuando no se pueden conservar correctamente.

## Tipografía y escrituras

La composición OpenType usa HarfBuzz para las sustituciones y posiciones de glifos,
y el algoritmo bidireccional Unicode para ordenar las escrituras. Mantiene una
correspondencia entre texto lógico, grupos de caracteres y glifos PDF para seleccionar,
editar y copiar ligaduras, marcas combinantes y texto de derecha a izquierda dentro
de PDF Modder. En texto mixto de derecha a izquierda y de izquierda a derecha,
otros lectores pueden extraer un orden distinto: sus criterios de lectura no son
idénticos aunque los códigos Unicode de los grupos estén presentes en el PDF.
La ruta sencilla de texto compatible sigue disponible.

Las fuentes variables se utilizan mediante una instancia estática con valores
explícitos de sus ejes. La fuente debe contener los caracteres y permitir la
incrustación necesaria. La aplicación no elige una fuente parecida ni simula una
variante ausente. Elija una fuente completa cuando el PDF sólo contiene un subconjunto
que no cubre el texto nuevo. El render del PDF generado es la referencia frente
al borrador de Qt.

La composición avanzada requiere fuentes SFNT con contornos TrueType, incluidas
sus instancias variables. La edición sencilla conserva la compatibilidad previa
con CFF y Type 1; para una composición compleja con esas fuentes se solicita una
fuente completa con contornos TrueType. La recomposición avanzada de contenido
etiquetado, el subrayado y la opacidad de texto distinta de 1 siguen limitados
cuando no se pueden conservar y verificar. El aviso indica la propiedad o la
ruta alternativa necesaria. El texto girado se puede transformar desde el editor
de objetos, según su compatibilidad.

No se garantiza el reemplazo de cualquier escritura en cualquier programa
tipográfico: una codificación incompleta, una fuente dañada o restricciones de
incrustación pueden impedirlo. La ampliación tampoco convierte las transformaciones
de objetos en edición semántica de diagramas ni ofrece una aplicación de OCR.

## Compatibilidad por operación

La compatibilidad se muestra para la acción y selección concreta. Un documento
puede permitir leer, copiar, rellenar campos o transformar una aparición aunque
otra edición de texto necesite ajustes o no sea verificable.
El texto exterior a campos AcroForm se puede editar conservando sus valores,
apariencias, recursos y cálculos. Si la selección toca un campo, se ofrece su
editor específico. Las operaciones de páginas con campos siguen limitadas a lo
que puede conservarse y comprobarse de forma completa.

| Estado | Qué hacer |
|---|---|
| **Disponible** | Puede iniciar la operación y validar su resultado. |
| **Necesita ajustes** | Revise el motivo y la acción indicada: fuente completa, área, selección o ruta específica. |
| **No compatible** | La acción actual no puede conservar de forma verificable las relaciones o restricciones requeridas. |

Los avisos conservan el borrador y explican el motivo. Una operación disponible
todavía debe superar las comprobaciones del PDF resultante; la apariencia y los
elementos vecinos no se dan por correctos sólo porque el documento pueda abrirse.

## Construcción y comprobación

El protocolo de esta versión es `scripts/release_v300.py`. En Windows, con el
entorno instalado:

```powershell
.venv/Scripts/python.exe scripts/release_v300.py --headless-qa --tests tests
```

El protocolo ejecuta pytest sobre la selección indicada, recorre la GUI y el
proceso PDF, construye el ejecutable, repite el recorrido congelado y comprueba
una instalación y desinstalación aisladas. Genera el instalador, el portable, las
fuentes, licencias, informes y SHA-256 en `releases/v3.0.0`. Omitir `--tests` utiliza
las pruebas de comportamiento nuevas cuyos nombres incluyen `v300`.

Desde Linux, `--source-only --headless-qa --tests tests` comprueba fuentes y GUI.
El ejecutable Windows y el instalador se construyen en Windows/Python 3.12 x64.
El modo offscreen verifica Qt sin un escritorio interactivo; el informe distingue
esa prueba de una ejecución nativa sobre el escritorio de Windows. Para esta última,
ejecute el protocolo sin `--headless-qa` en una cuenta de prueba de Windows.

`package_v300.py` exige evidencia de la revisión y ejecutable actuales, incluyendo
apertura progresiva, selección, compatibilidad, guardado por lotes, cierre,
transformación de un objeto y composición tipográfica extraída independientemente.
Los resultados históricos no se reutilizan. `ENTREGA.json` registra los resultados
realmente obtenidos y sus límites; esta guía no acredita por sí sola una compilación.

GitHub Actions construye los cambios de una rama y conserva artefactos. Sólo una
ejecución manual con `publish=true` desde `main` publica un release. Los documentos,
fuentes, certificados y preferencias personales permanecen fuera del paquete.
