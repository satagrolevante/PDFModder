# PDF Modder 2.0.2

## Apertura predeterminada de PDFs en Windows

La actualización anterior retiraba la carpeta vieja y podía dejar Windows apuntando
a su `PDFModder.exe`. El instalador ahora registra la ruta nueva antes de retirar
la anterior. Mantiene tanto la asociación heredada `Applications\PDFModder.exe`
como el identificador estable `PDFModder.Document`, con icono, comando de apertura,
extensión admitida y capacidades para Aplicaciones predeterminadas.

No cambia `UserChoice` ni impone un lector predeterminado. Si PDF Modder ya estaba
elegido, su comando se actualiza; si estaba elegido otro lector, continúa elegido.
Para una elección inicial: Configuración → Aplicaciones → Aplicaciones
predeterminadas → buscar `.pdf` → PDF Modder. Windows solicita esa elección al usuario.

Si no se puede registrar la nueva ruta, el instalador advierte y conserva la copia
anterior. Al desinstalar, sólo retira sus asociaciones si todavía apuntan exactamente
a esa instalación. Desinstalar una versión anterior conserva el registro de la nueva.

Referencias oficiales: [registro de aplicaciones](https://learn.microsoft.com/en-us/windows/win32/shell/app-registration)
y [configuración de aplicaciones predeterminadas](https://support.microsoft.com/es-es/windows/apps/change-default-apps-in-windows).

## Permitir solapamiento explícitamente

Entra en **Herramientas**, despliega **Propiedades y herramientas avanzadas**, localiza
**Selección** y marca **Permitir superponer texto** antes de mover texto o iniciar
**Agregar texto**. Los dos contenidos siguen existiendo: revisa su legibilidad.

Para añadir desde **Agregar texto con propiedades…**, pulsa la zona deseada y marca
**Permitir solapamiento sobre texto, imágenes o líneas** en el diálogo. Pulsa
**Previsualizar**, revisa el PDF modificado y confirma con **Aceptar ✓** sobre la página.

Esta autorización no elimina los límites de página, recortes incompatibles ni los
bloqueos para proteger enlaces, anotaciones o estructuras incompatibles.
Las imágenes no tienen una casilla equivalente.

## Verificación dirigida

Se verifica el código C# de producción mediante una raíz de registro temporal aislada:
comando anterior y nuevo, rutas con espacios, conservación de `UserChoice` y de otros
lectores, fallo de registro y desinstalación de copias antiguas y de la copia propietaria.
Se compila el ejecutable y se comprueba su recorrido nativo con documentos sintéticos.
Los informes de la entrega indican los resultados; no se repite todo el corpus histórico
ni se instala la copia de prueba como lector del usuario.
