# PDF Modder 2.0.3: canal de satagrolevante

El repositorio principal y el canal de nuevas versiones son
[satagrolevante/PDFModder](https://github.com/satagrolevante/PDFModder).
Las descargas deben ser públicas para usar Buscar actualizaciones sin cuentas.
Los certificados, preferencias y documentos personales no se publican.

## Actualizar instalaciones anteriores

Las versiones anteriores consultan `jfeagpt/PDFModder`. Se publica allí una
versión puente con el mismo instalador y manifiesto de 2.0.3. Al instalarlo,
las próximas consultas usan satagrolevante. Si la versión puente todavía no está
publicada, se puede descargar e instalar 2.0.3 desde el repositorio principal.
El instalador conserva la retirada automática de la versión anterior y el
registro de apertura de PDF implementados en 2.0.2.

El manifiesto mantiene el esquema 1, nombre, tamaño y SHA-256 del instalador.
La aplicación construye la URL dentro de su repositorio configurado y rechaza
URLs de otros repositorios. No se añade ninguna credencial a PDF Modder.

## Compilar y publicar

`.github/workflows/windows-release.yml` compila en Windows con Python 3.12 x64,
dependencias fijadas y comprobaciones dirigidas del actualizador. La comprobación
de interfaz en CI usa Qt offscreen: no equivale a una comprobación manual del
escritorio de Windows. Los informes acompañan la entrega.

La publicación usa el token temporal de GitHub Actions con permiso de escritura
de contenido. El release permanece como borrador hasta subir y validar sus
assets; el publicador no reemplaza archivos de una entrega existente.

No se repite el corpus PDF histórico para un cambio del canal de descarga.
ENTREGA.json y VERIFICACION-ENTREGA.txt delimitan las comprobaciones de cada
instalador. Las pruebas locales no acreditan por sí solas su publicación remota.
