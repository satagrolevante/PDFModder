# Convertir documentos y combinar PDF desde el Explorador

Estas acciones se registran al instalar PDF Modder 3.0.5. La carpeta portable por
sí sola no registra menús. En Windows 11 abre **Mostrar más opciones** dentro del
menú contextual, o utiliza **Mayús + F10**.

## Convertir a PDF

Selecciona uno o varios archivos DOC o DOCX y pulsa **Convertir a PDF**. PDF Modder
utiliza Microsoft Word si está instalado y disponible; si no, busca LibreOffice
instalado. Si no encuentra ninguno, indica el requisito. No descarga programas
ni envía documentos a servicios externos. Si Word falla al convertir, muestra el
error sin cambiar silenciosamente de motor.

La conversión se hace en segundo plano sobre una copia temporal. Puedes cancelarla.
Los originales se conservan y cada PDF se guarda junto al documento, usando
`nombre (1).pdf`, `nombre (2).pdf`… si el nombre ya existe. Un único resultado se
abre en la aplicación; un lote muestra la lista de resultados y sus errores.
Cancelar no borra los PDF cuya conversión ya terminó.

Se verifican la cabecera, la apertura y el número de páginas del PDF con dos
lectores antes de guardarlo. Esta comprobación acredita que el resultado puede
abrirse, no que cada elemento sea visualmente idéntico a Word. La paginación y el
formato dependen del motor, las fuentes y los recursos del documento. Los archivos
protegidos, dañados o que requieran intervención pueden fallar; se informa del
error sin sustituirlos por una conversión de texto plano. El límite inicial es de
180 segundos por documento.

## Combinar archivos PDF

Selecciona varios PDF y pulsa **Combinar archivos PDF**. La aplicación abre la
selección completa en una lista donde puedes añadir, quitar y ordenar archivos.
Después de combinar, el documento nuevo queda abierto para revisarlo y guardarlo
con **Guardar como…**. Los PDF de origen permanecen intactos. Si seleccionas un
solo PDF, puedes añadir otros en el diálogo. Esta acción admite únicamente PDF;
los DOC y DOCX deben convertirse antes.

## Instalación y límites

El menú es del usuario que instala la aplicación. La actualización renueva las
rutas y la desinstalación retira solamente las acciones que todavía pertenecen
a esa instalación. No modifica las aplicaciones predeterminadas ni las opciones
de otros programas. La selección se entrega mediante el componente
`PDFModderShellActions.exe`, fuera del proceso del Explorador; admite hasta 2000
archivos y una solicitud de 4 MiB, sin depender del límite de la línea de comandos.

Las acciones están preparadas para archivos locales accesibles al usuario.
Documentos en la nube deben estar descargados y los recursos enlazados deben estar
disponibles. Los DOC/DOCX se procesan con macros deshabilitadas y LibreOffice usa un
perfil temporal separado. Las verificaciones habituales de integridad de PDF Modder
se mantienen al combinar y editar los resultados.
