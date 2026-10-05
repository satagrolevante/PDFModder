# Compatibilidad de texto y fuentes en 2.0.0

## Instancias Form

Un Form XObject puede contener una cabecera, una celda o una página vectorial
reutilizada varias veces. Su mera presencia ya no bloquea toda la página.
Al editar su texto, PDF Modder identifica la invocación seleccionada mediante
un sondeo descartado, copia sus operadores al contenido local de esa página y
asigna nombres locales a sus recursos. Conserva la matriz, el límite de recorte
y su posición en el orden de dibujo. Los objetos compartidos originales no se
modifican y las otras invocaciones mantienen su `Do` y recursos.

Antes de editar, se exige que esa preparación reproduzca todos los caracteres,
sus estilos, imágenes y vectores, y la apariencia completa de la página, sin
excluir ninguna región. Después se utiliza la validación habitual del cambio.
La misma preparación sirve al panel y al editor por fragmentos.

Soporte demostrado con documentos sintéticos: Forms anidados, dos apariciones
del mismo recurso en una página, otra aparición en una segunda página,
sustitución de una fecha, movimiento y texto directo ajeno al Form. El resultado
se reabre y se contrasta con el extractor independiente pypdf.

Límites que siguen siendo explícitos: Form seleccionado con grupo de
transparencia (`/Group`), capa opcional (`/OC`), referencia externa (`/Ref`),
relaciones de estructura etiquetada o referencias recursivas; transformaciones
de texto que el compositor todavía no reproduce. Una edición que cruza su
recorte original continúa bloqueada. El sondeo está limitado a 16 niveles y
250 000 operaciones para evitar contenido recursivo o desmesurado.

## Fuentes CFF y caracteres compuestos

Se añade una ruta para OpenType estáticas con contornos CFF y glifos por nombre.
En ella se incrusta el programa OTF completo sin cambiar un byte y se define una
codificación PDF por nombres de glifo, con ToUnicode y avances comprobados.
No convierte CFF a TrueType ni rasteriza las letras. Está disponible al elegir
una OTF adecuada y, cuando el PDF conserva el programa completo con permisos
verificables, para su reutilización exacta. Los recursos antiguos se conservan.

La ruta requiere cmap Unicode, métricas coherentes, permiso de incrustación
editable y fuente estática. CFF CID parcial sin cmap sigue admitiendo solamente
los códigos originales y recursos complementarios que el motor pueda verificar.
CFF2/variable y marcas sin avance que requieren composición avanzada permanecen
pendientes. El límite de codificación simple es 254 caracteres distintos por
fragmento. Se comprueba específicamente ñ, acentos y €.

Texto escrito con una letra y un acento Unicode separado se compone mediante
NFC cuando existe un carácter equivalente, por ejemplo `n` + tilde → `ñ`.
El informe registra esa normalización. En el editor rico se hace dentro de cada
fragmento, sin mezclar fuentes o formatos entre fragmentos. Marcas que no pueden
componerse no se insertan mediante una posición o glifo inventados.

## Inspector y comprobación previa

El inspector añade tipo de contorno (TrueType, CFF, CFF2), disponibilidad de
reinserción Unicode, necesidad de códigos originales y caracteres ausentes.
También lee familia, variante y versión del CFF bruto cuando estén declaradas.
Un programa CFF extraído sin tabla OS/2 no permite deducir derechos fsType: se
mantiene ese dato como desconocido. Una huella identifica el programa concreto,
pero el nombre de familia, la versión o una coincidencia nominal local no
demuestran por sí solos la identidad de sus contornos.

`compatibility_v200.preflight_text(data, page, ids, new_text=None, resolver=None)`
devuelve un estado disponible/condicional/bloqueado, acciones concretas,
evidencia del recurso y cobertura del texto solicitado. Comprueba códigos
originales o una codificación nueva aislada. Su resultado no sustituye la
validación final de contenido y apariencia. No modifica la copia de trabajo.

## Pruebas dirigidas

- 5 pruebas de instancias Form: aislamiento, sustitución, movimiento, texto
  ajeno al Form y bloqueo local de grupo de transparencia.
- 4 pruebas de comprobación previa, NFC, ausencia de glifo y editor rico Form.
- 2 pruebas CFF: codificación/extracción/render conservando el programa y
  rechazo preciso de carácter ausente.
- Regresiones relacionadas: 15 pruebas de recortes, 12 de extensión TrueType
  y 23 del inspector/resolución de fuentes, todas correctas.

Estos resultados cubren el corpus sintético reproducible. No equivalen a
compatibilidad universal ni a una comprobación nueva de todas las facturas
privadas del usuario.

API y formatos contrastados con documentación oficial:

- https://pymupdf.readthedocs.io/en/latest/document.html
- https://pymupdf.readthedocs.io/en/latest/recipes-low-level-interfaces.html
- https://fonttools.readthedocs.io/en/latest/cffLib/index.html
- https://fonttools.readthedocs.io/en/latest/ttLib/tables/_c_m_a_p.html
