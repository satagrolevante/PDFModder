# Interfaz nativa de Windows — PDF Modder 2.0.0

Comprobación del 3 de octubre de 2026 en este equipo Windows x64. El recorrido usa la plataforma real `windows` de Qt, una ventana y el proceso PDF normal, con dos copias del corpus digital sintético. No utiliza `offscreen` ni documentos privados.

## Incidencia corregida

La primera ejecución del ejecutable anterior agotó el límite: la primera apertura terminó a los 96,269 s y la prueba falló a los 106,431 s. El diagnóstico con trazas periódicas localizó el hilo de la interfaz en `_refresh_clipboard_v170`, consultando `QMimeData.hasFormat/hasText/hasImage`. Esas consultas al proveedor OLE del portapapeles externo provocaban esperas también al refrescar los botones.

El refresco en Windows ahora utiliza exclusivamente los formatos anunciados mediante `IsClipboardFormatAvailable`. El contenido se solicita al ejecutar Pegar. La corrección no vacía ni reemplaza el portapapeles. Si no se puede consultar su disponibilidad, se permite intentar Pegar y su validación explícita decide si el contenido es utilizable.

Microsoft documenta esta función para habilitar el comando Pegar: [IsClipboardFormatAvailable](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-isclipboardformatavailable). Los nombres de los formatos propios y PNG corresponden al [registro MIME de Qt para Windows](https://github.com/qt/qtbase/blob/dev/src/plugins/platforms/windows/qwindowsmimeregistry.cpp).

## Alcance y evidencia

- Fuente corregida: nueve pasos nativos aprobados en 5,545 s (`output/native-diagnostic-v200/smoke.json`).
- Regresión y cambios de 2.0.0: 44 pruebas dirigidas aprobadas, sin omisiones ni fallos (`output/pytest-v200-results.xml`); doce cubren la consulta de formatos sin acceder al portapapeles real.
- Ejecutable final: nueve pasos nativos aprobados en 4,953 s (`output/packaged-v200-smoke.json`), con plataforma Qt real, huella del ejecutable y extracción independiente del PDF guardado.
- Instalación aislada: `INSTALACION-VERIFICADA.json` en la entrega identifica el instalador y el recorrido del ejecutable instalado.

El recorrido verifica apertura en Lectura, compatibilidad visible, aceptación única, pestañas independientes, cancelación, conservación del render, deshacer y rehacer exactos y guardado de texto real, conservando otra aparición de la fecha y los archivos originales. La captura sirve de complemento al contenido extraído y las comprobaciones del PDF.

Esta prueba no acredita todas las herramientas ni todos los PDFs reales, otro equipo físico, una firma con certificado personal o una impresora física. Los informes de la entrega son la evidencia de las ejecuciones efectivamente completadas.
