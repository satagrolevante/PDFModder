# PDF Modder 3.0.25 — Impresión desde el Explorador y 300 ppp

Al pulsar **Imprimir** en el menú contextual, PDF Modder reintenta brevemente
la lectura si detecta un cambio transitorio en el mismo archivo. Envía un solo
trabajo cuando consigue una copia estable. Si el archivo se sustituye o sigue
cambiando, el aviso de apertura indica que hay que esperar a que se guarde.

La impresión desde el Explorador prepara las páginas a un máximo de 300 ppp.
Esto evita la reducción típica a unos 498 ppp al preparar un A4 con un
controlador de 600 ppp o más. La impresora utiliza sus opciones de Windows
para papel, orientación, caras, color, resolución del dispositivo y copias.

En **Ctrl+P**, **Resolución** comienza en 300 ppp para cada impresora sin un
ajuste guardado. Si eliges otro valor, el diálogo lo recuerda para esa impresora
al enviar el trabajo, con la opción de recordar preferencias activada. Los PDF
con páginas grandes o con restricciones de impresión pueden requerir una
resolución menor.

Las pruebas dirigidas cubren la apertura transitoria, los archivos que siguen
cambiando, el envío con salida PDF simulada y la resolución del diálogo y del
Explorador. La entrega incluye instalador, portable y fuentes para Windows x64.
