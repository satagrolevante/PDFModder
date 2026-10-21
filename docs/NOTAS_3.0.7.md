# PDF Modder 3.0.7

## Comprobación diaria de actualizaciones

La opción **Configuración → Comprobar actualizaciones automáticamente cada día**
está activada por defecto y conserva la elección al cerrar o actualizar la app.

Al primer inicio de cada día según la fecha local del PC, la app consulta el
manifiesto público de su repositorio `satagrolevante/PDFModder`. La consulta se
inicia después de mostrar la ventana y se ejecuta en un hilo independiente, sin
esperar al motor PDF ni bloquear la interfaz. No envía documentos, texto, rutas
de archivos ni contraseñas.

Si hay una versión estable posterior a la instalada, ofrece:

- **Actualizar ahora**: abre el actualizador y comienza la descarga. Conserva las
  comprobaciones de tamaño y SHA-256 y el flujo de Guardar / Descartar / Cancelar
  antes de cerrar la app y ejecutar el instalador.
- **Más tarde (mañana)**: no vuelve a avisar ese día, aunque cierres y abras la
  app. Volverá a comprobar al primer inicio del día siguiente. Cerrar el aviso o
  pulsar Esc tiene el mismo efecto.

Si no hay novedades, falta conexión o GitHub no responde, no aparece ningún
mensaje automático. La consulta no se repite automáticamente ese día, incluso
si falla. **Buscar actualizaciones** permite intentarlo manualmente en cualquier
momento, también con la opción automática desactivada o el aviso pospuesto.

El aviso espera a que la ventana esté activa y no se esté escribiendo, guardando,
firmando, convirtiendo documentos ni usando otro diálogo. Abrir el actualizador
manualmente retira el aviso automático pendiente y aprovecha la consulta que ya
estuviera en curso.

La fecha se guarda antes de consultar y se coordina mediante un bloqueo breve
entre instancias, evitando varias consultas automáticas el mismo día. Las
preferencias se escriben de forma atómica. Desactivar la opción cancela la
consulta automática pendiente y retira su aviso; al cerrar la app se cancelan
las operaciones del actualizador. Los modos de comprobación del ejecutable
siguen sin lanzar consultas automáticas.

Se han completado 65 pruebas dirigidas de preferencias, concurrencia, arranque,
avisos, aplazamiento, guardado antes de actualizar y navegación de búsqueda. Las
respuestas de GitHub se simulan en las pruebas; no se descargan ni ejecutan
instaladores durante ellas.

El instalador Windows x64 está disponible en GitHub Releases y mediante
**Buscar actualizaciones**. La entrega se publica después de comprobar las
fuentes, el ejecutable, la instalación y desinstalación y el canal público de
actualizaciones. La comprobación de la GUI en CI usa Qt offscreen.
