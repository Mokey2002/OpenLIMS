# OpenLIMS

**Primeros pasos:** [Instalación paso a paso](#instalación-paso-a-paso) · [Installation guide in English](README.md#installation)

## v0.57.0 — Lenguaje más natural y repetición de consultas

Prueba **“Dame un resumen del proyecto ALPHA”**, **“Muéstrame las muestras de ese proyecto”**, **“Could you please give me a quick overview of project ALPHA?”** o **“Show me my priorities”**. Se reutilizan los mismos servicios con permisos y los adaptadores de proveedores; las respuestas siguen principalmente en inglés.

Para resúmenes/historial/ubicación/secuencias de muestras y resúmenes/listas/calidad de proyectos, **“same for BETA”** o **“what about sample S-102?”** repite la consulta anterior compatible. **“Summarize a project” → “ALPHA”** permite responder con el identificador faltante; usa comillas para nombres con espacios. Se comprueban permisos y ambigüedad en cada lectura. Esta memoria solo selecciona consultas de lectura, nunca repite escrituras. **“What should I do next?”** muestra trabajo personal si no hay muestra seleccionada y orientación de la muestra si la hay. No garantiza comprender cualquier frase.

## v0.56.0 — Respuestas breves y continuidad de conversación

Si el asistente ofrece opciones de muestras, resultados, QC, fallos o inventario, responde con el nombre mostrado, su número o **“the second one”**. Las opciones se reconstruyen con comandos del servidor. **“Thanks”**, **“okay”** y **“got it”** conservan el contexto para seguir consultando, graficando o exportando; **“start over”** borra la elección pendiente. Una solicitud explícita nueva cambia de tema.

Usa **“Summarize this project”**, **“Preview quarantine impact for that lot”** o compara el resultado seleccionado con su rango de referencia. Los IDs inválidos, contradictorios o múltiples requieren aclaración. Las consultas vuelven a comprobar permisos y las escrituras siguen requiriendo confirmación. Son mejoras para conversaciones compatibles, no memoria ilimitada ni respuestas garantizadas a cualquier pregunta.

## v0.55.1 — Seguimiento entre funciones de muestras

Después de **“Summarize sample S-100”**, pregunta **“Show its history”**, **“Where is it stored?”**, **“Who last moved it?”**, **“What's next?”** o **“Show its sequences”**. Estos comandos de lectura usan un ID estable y vuelven a comprobar permisos; varias muestras, IDs inválidos o contexto contradictorio requieren aclaración. Historial/secuencias conservan la muestra y las revisiones de calidad conservan el proyecto. Las búsquedas de secuencias con muestra explícita requieren un ID exacto y accesible; si no se resuelve, no se amplía la búsqueda. El seguimiento está limitado a estas formas compatibles, no es memoria de conversación ilimitada.

## v0.55.0 — Resúmenes y seguimiento de proyectos

Pregunta **“Summarize project ALPHA”** y después **“Show me samples in that project”** o **“Who is assigned work in that project?”**. Estos comandos en inglés funcionan sin modelo y mediante el adaptador compartido de OpenAI/Ollama. El resumen muestra miembros, estados de muestras, trabajo por responsable, vencimientos, trabajo sin asignar, fallos y QC rechazado/repetición. Cada turno vuelve a verificar los permisos. Incluye muestras primarias y vinculadas accesibles (hasta 100 en la lista). Los indicadores excluyen trabajo completado/cancelado; no evalúan todas las dependencias.

## v0.54.0 — Prioridades personales y continuidad de conversación

Pregunta **“What do I need to work on?”**, **“Show my tasks”** o **“¿En qué debo trabajar hoy?”** sin habilitar un proveedor de IA. Se muestran hasta 100 trabajos accesibles, asignados al usuario actual y sin finalizar, ordenados por vencimiento, con alertas y enlaces. Excluye trabajo ajeno, sin asignar, completado o cancelado; incluye fechas futuras y trabajos sin fecha. No es una evaluación completa de dependencias ni de tareas QC. Una lista vacía no significa que todo el laboratorio esté al día. Las respuestas de estas nuevas funciones están principalmente en inglés.

Las nueve funciones directas de lectura/borrador ahora preguntan por un dato faltante a la vez. El relevo acepta `me` como usuario actual, y después pregunta quién recibe el trabajo. Los IDs/nombres de usuario cortos se resuelven sin otra llamada al modelo; usa comillas para títulos con espacios. Con OpenAI/Ollama, respuestas como `same for BETA` reciben los argumentos verificados de la solicitud anterior. Un tema nuevo empieza de cero; `never mind` o `start over` descarta ese contexto.

El estado está firmado, vinculado al usuario y caduca a los 30 minutos. Guarda argumentos, no resultados, y vuelve a comprobar permisos. No autoriza cambios ni permite repetir escrituras; las confirmaciones siguen vigentes. Las dos vistas muestran la interpretación con etiquetas más claras, sin JSON crudo. Las pruebas de proveedores usan respuestas simuladas. No requiere migración.

## v0.53.0 — Conexiones compartidas para OpenAI y Ollama

Cuando las reglas no resuelven una solicitud, cualquiera de los proveedores configurados puede devolver una petición de función validada. OpenLIMS la ejecuta con el usuario autenticado y el contexto existente. Habilita el LLM y su enrutamiento, y configura credenciales/modelo de OpenAI o URL/modelo de Ollama. El modo de solo reglas sigue disponible.

El catálogo compartido cubre 32 entradas: historial de muestras, experimentos relacionados, planificación de reactivos, actualizaciones de proyecto, impacto de cuarentena, calidad de datos, borradores de flujos, relevos y comparación de experimentos; además de adaptadores para análisis, prioridades, códigos de barras, cálculos, gráficos, comparaciones, trabajos confirmados, inventario, investigaciones, notificaciones, QC, informes, muestras/registro, secuencias, SOP, trabajos, asignaciones/resultados guiados, orientación de muestras, consultas de workflows, estado del sistema, identidad, búsqueda de registros y migraciones.

Por ejemplo, “Ayuda a Maria a continuar el trabajo de Peter” puede interpretarse como un relevo entre los usuarios `peter` y `maria`. Se comprueban permisos, funciones habilitadas y ambigüedad. Si faltan datos, se pide repetir la solicitud completa; no se guardan automáticamente respuestas libres de aclaración. Los comandos interpretados deben coincidir con el parser existente. La calidad de interpretación depende del modelo.

Ambas vistas muestran la interpretación del proveedor y sus argumentos. OpenLIMS genera los resultados y puede conservar la etiqueta Rules: el modelo interpreta y OpenLIMS ejecuta. Los cambios requieren la confirmación existente; los flujos requieren guardado explícito. El modelo no confirma acciones, ejecuta SQL/código ni define permisos. La búsqueda global de migraciones mediante esta conexión exige administrador.

Las pruebas usan respuestas simuladas de ambos proveedores; no son una evaluación de precisión con modelos en vivo. Una prueba detecta nuevos routers sin conexión explícita. No requiere migración.

## v0.52.1 — Prueba de privacidad de investigaciones determinista

Corrige un fallo intermitente de CI: los dígitos de un resultado privado (`9999`) podían aparecer en una marca de tiempo ajena. La prueba reproduce esa marca de tiempo y comprueba IDs/valores de resultados, registros comparativos y totales, en lugar de buscar dígitos en toda la respuesta. No cambia el comportamiento ni los permisos de la aplicación; no requiere migración.

## v0.52.0 — Borradores de flujos, relevos y comparación de experimentos

Las tres funciones restantes están disponibles en ambas vistas del chat. Los comandos se escriben en inglés:

- **Borradores de flujos:** un administrador puede pedir `Create a workflow with EXTRACT@1, QC@1, SEQUENCE@2, REVIEW@1`, usando códigos/versiones activos reales (o nombres exactos). Si falta un procedimiento o es ambiguo, se solicita aclaración. Pulsa **Revisar flujo en el diseñador**, ingresa código/nombre, revisa dependencias, controles QC, condiciones y automatización, y guarda explícitamente. El borrador empieza inactivo, con dependencias secuenciales y sin inferir controles QC ni automatizaciones. Se comprueban las versiones al abrirlo. Editar el texto del chat solo cambia la nota copiable. Máximo: 30 pasos.
- **Relevos:** `Prepare peter's handover for maria` requiere nombres de usuario activos exactos. Genera un borrador editable de hasta 100 trabajos asignados sin finalizar, visibles para quien consulta y ambas personas, con vencimientos y alertas de atraso, fallo o QC rechazado/repetición. Excluye trabajos completados/cancelados; las dependencias y bloqueos no registrados requieren revisión manual. No envía mensajes ni reasigna trabajo. Comprueba nuevamente el acceso antes de compartirlo.
- **Comparaciones:** `Compare runs <ID-público-experimento> and <ID-público-experimento>` también acepta títulos exactos únicos. Requiere acceso a ambos experimentos y el cuaderno habilitado. Compara definiciones actuales de pasos, parámetros/estado registrados, lotes vinculados y bloques de resultados estructurados (incluido QC si se registró allí). Alinea por posición: revisa si cambió el orden. Los datos ausentes son desconocidos; un enlace no demuestra consumo ni una diferencia demuestra causalidad. Excluye texto libre, revisiones históricas y QC externo. Límites por experimento: 50 pasos, 100 lotes, 50 bloques; 4.000 caracteres visibles por valor. Indica comparaciones parciales.

No requiere migración de base de datos. Las instrucciones de instalación siguen vigentes.

## v0.51.0 — Vista previa de impacto y revisión de calidad de datos

Dos informes de solo lectura están disponibles en ambas vistas del chat, con tablas de evidencia, enlaces y sugerencias basadas en registros existentes. Los comandos se escriben en inglés:

- **Impacto de cuarentena:** `What would be affected if we quarantine lot LOT-12?` o `Preview quarantine impact for lot LOT-12`. Revisa reservas activas accesibles, consumo registrado y enlaces de la revisión actual del cuaderno. Distingue dependencias previstas de uso anterior y muestra el estado del trabajo/experimento. No pone el lote en cuarentena ni concluye que sus resultados sean inválidos. La evidencia del cuaderno requiere que esté habilitado y que todos los destinos vinculados sean accesibles. Muestra hasta 25 filas por categoría e indica si el informe es parcial; las filas no representan muestras únicas.
- **Calidad de datos del proyecto:** `Check project ALPHA for suspicious records` o `Review data quality for project ALPHA`. Señala IDs similares al ignorar mayúsculas y puntuación, metadatos obligatorios ausentes, formularios de ingreso inválidos (incluidos campos condicionales), unidades diferentes/ausentes para el mismo análisis/tipo de trabajo y campo de resultado, y fechas o vencimientos inusuales. Son indicaciones para revisar, no conclusiones científicas ni correcciones automáticas. Se aceptan unidades conocidas compatibles y valores válidos cero/falso.

La revisión examina hasta 250 muestras del proyecto principal, 1.000 trabajos y 1.000 resultados, ordenados por ID, y muestra hasta 100 hallazgos. Indica los límites y si la revisión es parcial. Repetir la consulta vuelve a comprobar registros y permisos. No requiere migración de base de datos.

## v0.50.2 — Respuestas de registro estables y valores seguros

Las respuestas de registro conservan el ID del proyecto: cambiar o reutilizar un código no redirige la solicitud, y la puntuación del código ya no impide responder. Se comprueban nuevamente el rol y el acceso en cada respuesta. Tras actualizar, reinicia los registros pendientes de v0.50.1 o anteriores: su contexto basado solo en el código ya no se reanuda.

Se rechazan claves JSON duplicadas, caracteres nulos, Unicode inválido y números no finitos antes de proponer; los valores se vuelven a validar al confirmar. Los números demasiado grandes generan un mensaje de validación. Se mantiene el soporte de Unicode válido y puntuación entre comillas. No requiere migración de base de datos.

## v0.50.1 — Registro y cálculo de stock más robustos

El registro rechaza solicitudes negadas, instrucciones adicionales, campos duplicados y listas mal formadas. Usa comillas JSON para conservar comas o puntuación: `Register 2 plasma samples in project ALPHA with source="blood, frozen."`. Puedes corregir los campos con otra respuesta `with ...`; se vuelven a comprobar los permisos. Antes de crear registros se validan los IDs y el tipo de muestra guardados en la propuesta. Los IDs generados demasiado largos se rechazan en la vista previa.

El cálculo de reactivos vuelve a validar cantidades y unidades configuradas, incluso si se importaron sin validación de formularios. Stock inválido, unidades incompatibles o reservas superiores al stock producen un resultado **desconocido**. Las reservas liberadas no se descuentan. Este parche no requiere migración de base de datos.

## v0.50.0 — Cinco ayudas de IA para el laboratorio

Los nuevos comandos se escriben en inglés:

- `What happened to sample S-100?`: últimos 50 eventos de auditoría/custodia, responsables y estado actual del trabajo y QC, con enlace a la muestra. No reconstruye eventos ausentes.
- `Find similar experiments about plasma extraction`: busca todas las palabras en títulos, contenido actual y nombres de plantillas accesibles; muestra hasta 20 experimentos accesibles. Requiere el cuaderno habilitado. Es una búsqueda por palabras, no una evaluación de equivalencia científica.
- `Plan reagents for 30 samples using procedure EXTRACT version 1`: calcula las cantidades configuradas y el stock activo no vencido, descontando reservas y convirtiendo unidades compatibles. No reserva stock ni incluye controles, repeticiones o pérdidas no configuradas.
- `Register 12 plasma samples in project ALPHA`: solicita campos obligatorios; responde `with source=blood` usando los nombres de tus campos y todos los valores obligatorios. Presenta una vista previa y exige confirmación explícita. Vuelve a comprobar permisos y campos al confirmar.
- `Write a short progress update for project ALPHA`: genera un borrador editable en ambas vistas del chat, con enlace al proyecto y botón para copiar. Describe registros actuales del proyecto principal; no envía mensajes. Las ediciones quedan en la vista actual.

**Actualización:** después de reconstruir la API, ejecuta `docker compose -f deploy/docker-compose.yml run --rm api python manage.py migrate`. En Django admin (`/admin/`), abre **Pipelines → Procedure definitions**, selecciona el procedimiento y versión y configura **Procedure reagent requirements**: artículo de inventario, cantidad positiva por muestra y unidad compatible. Guarda antes de pedir el cálculo. Si faltan cantidades, el asistente lo indica; no las deduce de instrucciones de texto.

## v0.49.5 — Vistas previas de asignación de IA más fiables

Al confirmar una asignación se vuelven a comprobar la fecha límite, el tipo de trabajo, la muestra y el proyecto principal, además del estado y responsable. Los elementos modificados se omiten y requieren una vista previa nueva; también deben regenerarse las vistas antiguas que no contienen estos datos. Las solicitudes de más de 100 trabajos piden reducir la selección en vez de tomar solo los primeros 100. Si se indican varios responsables, se solicita uno por acción.

Las solicitudes de operaciones de trabajo con negación, fechas no admitidas o acciones mezcladas piden aclaración en vez de ignorar condiciones. No se generan propuestas para proyectos repetidos ni usuarios inactivos. Las asignaciones entre varios proyectos conservan su alcance al confirmar. Las listas muestran el total de coincidencias e indican el límite de visualización de 100 elementos.

Las listas y propuestas de asignación respetan el proyecto indicado. Los proyectos desconocidos, inaccesibles o ambiguos requieren un código o nombre exacto, sin ampliar la búsqueda. La carga de trabajo muestra solo registros visibles para quien consulta; la confirmación rechaza trabajos que cambiaron de proyecto. También se corrigen los filtros combinados de trabajo vencido y sin asignar, y el regreso a gráficos de estado de muestras.

Los gráficos de trabajo aceptan solicitudes corteses, métricas en distinto orden y una sola métrica. Al quitar el último registro seleccionado, se solicita una nueva selección en vez de ampliar la búsqueda. Un proyecto indicado explícitamente en una solicitud de gráfico reemplaza la selección anterior. Las listas de trabajo sin asignar incluyen elementos vencidos y sin fecha, salvo que se pida **today**. Se mantienen los controles de acceso.

Corrige **Graph overdue and unassigned work** tras revisar bloqueos: conserva el proyecto, grafica conteos actuales y ya no interpreta trabajo sin asignar como una orden de asignación.

Guarda consultas de flujo con nombre en tu cuenta y ábrelas desde ambas vistas del chat. Carga una consulta en el constructor, ajústala y ejecútala con registros actuales. Solo se guardan los ajustes; los permisos se verifican al ejecutar. Incluye límite de 20 consultas y eliminación confirmada. Consulta la [guía](docs/assistant-project-workflows.md#personal-saved-questions).

## v0.48.0 — Crea y reutiliza consultas de IA

Usa el **constructor visual de consultas** en ambas vistas del chat: elige proyecto, filtros, Y/O, responsable y alcance, revisa la pregunta y ejecútala. Los accesos rápidos incluyen tu trabajo vencido, trabajo próximo a vencer sin asignar y problemas de QC. **Usa los mismos filtros en proyecto CODIGO** reutiliza una consulta con permisos actualizados y resultados desde la primera página. Disponible en español e inglés. Consulta la [guía](docs/assistant-project-workflows.md#build-and-reuse-workflow-questions).

## v0.47.0 — Entiende tu consulta de IA

Usa **Explica esta consulta** para ver el significado de los filtros, la lógica Y/O, el alcance, el responsable y las ventanas actuales de vencimiento. La explicación bilingüe verifica permisos, conserva la paginación y no revisa muestras. Disponible en ambas vistas del chat. Consulta la [guía de explicaciones](docs/assistant-project-workflows.md#query-explanations).

**Sistema de gestión de información de laboratorio de código abierto, autohospedado y orientado a flujos de trabajo prácticos.**

OpenLIMS organiza proyectos, muestras, inventario, trabajos, resultados, control de calidad, importaciones de instrumentos, análisis bioinformáticos, migraciones y auditoría en una misma plataforma.

> **Estado actual:** OpenLIMS es un prototipo con arquitectura de producción. Todavía no es un LIMS clínico, diagnóstico o regulado completamente validado.

**Versión de desarrollo actual:** `v0.54.0`

**Demo:** http://35.164.28.250

---

## Instalación paso a paso

### 1. Comprueba los requisitos

Usa una terminal de Linux o macOS, o Ubuntu en WSL2 si utilizas Windows. Necesitas **Git**, **Docker con Compose v2** y **OpenSSL**. Si usas Docker Desktop, ábrelo primero. Comprueba:

```bash
git --version
docker info
docker compose version
openssl version
```

Esta guía es para una **instalación nueva en tu computadora**, disponible en **http://localhost:8080**. Docker ejecuta la interfaz, API, base de datos y trabajador en segundo plano. No necesitas instalar Python, Node.js, PostgreSQL, OpenAI ni Ollama por separado. La primera compilación descarga dependencias y puede tardar varios minutos.

Para un servidor compartido, consulta también [Instalación en un servidor](#instalación-en-un-servidor). No reemplaces la configuración ni las credenciales de una instalación existente.

### 2. Descarga OpenLIMS

```bash
git clone https://github.com/Mokey2002/OpenLIMS.git
cd OpenLIMS
cp deploy/.env.prod.example deploy/.env
chmod 600 deploy/.env
```

Ejecuta los comandos de Docker siguientes desde esta **carpeta OpenLIMS**.

### 3. Configura la instalación local

Ejecuta este comando **tres veces** para generar valores diferentes para el secreto de Django, la contraseña de la base de datos y la clave de instrumentos:

```bash
openssl rand -hex 32
```

Abre `deploy/.env` en un editor de texto. Reemplaza los valores existentes que aparecen abajo y conserva los demás. Sustituye cada `REPLACE_...` por un valor generado. Usa **la misma contraseña de base de datos en las dos líneas** correspondientes.

```env
DJANGO_SECRET_KEY=REPLACE_DJANGO_SECRET
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
OPENLIMS_PUBLIC_URL=http://localhost:8080
OPENLIMS_HTTP_PORT=8080

JWT_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
SESSION_COOKIE_SECURE=false
SECURE_SSL_REDIRECT=false

POSTGRES_PASSWORD=REPLACE_DATABASE_PASSWORD
DATABASE_URL=postgres://openlims:REPLACE_DATABASE_PASSWORD@db:5432/openlims
INSTRUMENT_API_KEY=REPLACE_INSTRUMENT_KEY

OPENLIMS_ASSISTANT_LLM_ENABLED=false
OPENLIMS_EMAIL_ENABLED=false
```

Estas opciones de cookies son **solo para HTTP local**. Conserva `POSTGRES_DB=openlims` y `POSTGRES_USER=openlims` de la plantilla. No compartas este archivo: contiene los secretos de tu instalación.

### 4. Compila e inicia el sistema

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d --build
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml ps
```

Espera a que `db`, `redis` y `api` indiquen `healthy`, y que `web` y `worker` estén ejecutándose. La API aplica las migraciones y recopila los archivos estáticos automáticamente. Para consultar su avance:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml logs --tail=80 api
```

### 5. Crea tu cuenta de administrador

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml exec api python manage.py createsuperuser
```

Introduce el usuario, correo y contraseña cuando se soliciten. La contraseña no se muestra mientras escribes. **No hay una contraseña predeterminada de administrador.**

### 6. Abre OpenLIMS e inicia sesión

Abre **http://localhost:8080** e inicia sesión con la cuenta que acabas de crear. Comprueba la API en **http://localhost:8080/api/health/**.

Ya puedes crear tus proyectos y usuarios. Si prefieres explorar ejemplos en una instalación de evaluación, ejecuta opcionalmente:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml exec api python manage.py seed_demo
```

La demo añade registros de ejemplo y habilita Registry y Notebook. No crea ni cambia contraseñas: usa tu cuenta de administrador. Las identidades nuevas de la demo no permiten iniciar sesión. No añadas la demo a una instalación con datos reales del laboratorio.

### Detener y volver a iniciar

Detén los servicios sin borrar los datos:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml stop
```

Para iniciarlos de nuevo:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d
```

Los registros y archivos se guardan en volúmenes de Docker. Conserva el nombre del proyecto Compose (`openlims`). **No uses `down -v` para reiniciar:** elimina los volúmenes de datos.

### Solución de problemas

| Problema | Qué revisar |
|---|---|
| No se puede conectar a Docker | Abre Docker Desktop o solicita acceso a Docker al administrador del servidor. Comprueba `docker info`. |
| El puerto 8080 está ocupado | Cambia `OPENLIMS_HTTP_PORT`, los dos orígenes locales y `OPENLIMS_PUBLIC_URL` al nuevo puerto; repite el inicio. |
| No carga la página o aparece 502 | Revisa `ps` y los logs de la API. La interfaz espera a que la API esté saludable. |
| Falla el inicio de sesión o aparece CSRF 403 | Usa la dirección configurada. En HTTP local, las tres opciones de cookies seguras deben ser `false`. |
| Falla la autenticación de PostgreSQL | La contraseña de `DATABASE_URL` debe coincidir con `POSTGRES_PASSWORD`. Editar el archivo no cambia la contraseña de una base de datos ya creada. |
| Falla la descarga de una dependencia | Revisa la conexión y repite la compilación. No borres la base de datos ni los volúmenes. |

### Instalación en un servidor

Antes de iniciar el mismo stack para otros usuarios:

- Configura `DJANGO_ALLOWED_HOSTS` con el hostname real, sin esquema ni ruta. Incluye `127.0.0.1` para la comprobación interna de salud.
- Usa la dirección HTTPS exacta en `CSRF_TRUSTED_ORIGINS` y `OPENLIMS_PUBLIC_URL`, incluyendo el puerto si no es el estándar.
- Establece `JWT_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` y `SESSION_COOKIE_SECURE` en `true`. Conserva `DJANGO_DEBUG=0`.
- Configura un proxy HTTPS que conserve `Host`, envíe `X-Forwarded-Proto: https` y reenvíe WebSockets en `/ws/`. Restringe el acceso directo al puerto 8080 al proxy o red de confianza.
- Prepara copias de la base de datos, archivos subidos y configuración privada antes de trabajar con datos reales.

Después sigue los pasos 4–6 usando tu dirección HTTPS. SMTP e IA externa son opcionales. El [instalador guiado](deploy/installer/README.md) es una implementación inicial que requiere imágenes publicadas con sus digests; no es necesario para esta instalación desde código ni sirve para actualizar instalaciones existentes.

Para modificar código con recarga automática, consulta [Local Development](README.md#-local-development): esa alternativa requiere iniciar también el frontend con npm.

---

## 1. Objetivo general

OpenLIMS está pensado para laboratorios de investigación, grupos académicos, pequeñas empresas de biotecnología y unidades de servicio que necesitan más estructura y trazabilidad que una colección de hojas de cálculo, sin adoptar inicialmente la complejidad de un LIMS empresarial.

Sus objetivos principales son:

- Mantener la trazabilidad de una muestra desde su recepción hasta su reporte o archivo.
- Relacionar muestras, proyectos, instrumentos, trabajos y resultados.
- Centralizar la revisión de control de calidad (QC).
- Conservar la procedencia de resultados importados.
- Ejecutar análisis bioinformáticos y trabajos pesados en segundo plano.
- Registrar acciones relevantes en una bitácora de auditoría.
- Facilitar la migración gradual desde bases de datos y hojas de cálculo anteriores.
- Permitir consultas en lenguaje natural mediante un asistente con permisos controlados.

---

## 2. Filosofía de uso

La muestra es el registro central de OpenLIMS. El flujo general es:

```text
Proyecto
   ↓
Muestra o lote de muestras
   ↓
Trabajo, procedimiento o importación de instrumento
   ↓
Resultados estructurados
   ↓
Revisión de QC y análisis
   ↓
Reporte, archivo y auditoría
```

Una muestra normalmente pertenece a un proyecto principal, pero también puede vincularse con otros proyectos para permitir colaboración sin cambiar su propiedad principal.

Los datos pueden ingresar de distintas maneras:

- Creación manual de muestras.
- Creación por lotes.
- Importación CSV desde instrumentos.
- Ingesta directa mediante conectores o API.
- Importación FASTA y otros formatos científicos.
- Migración desde exportaciones de sistemas anteriores.

Por lo tanto, el uso esperado no se limita a crear muestras manualmente y después seleccionar una opción de análisis. OpenLIMS también permite automatizar la entrada de datos, crear trabajos para lotes y conservar la relación entre cada resultado y su origen.

---

## 3. Funcionalidades principales

| Área | Funciones disponibles |
|---|---|
| **Proyectos** | Espacios de trabajo, miembros, notas, muestras, visibilidad y vista unificada desde la muestra hasta el reporte |
| **Muestras** | Alta, alícuotas, linaje de origen y derivación, custodia, estados, responsable, lote, archivos adjuntos, campos personalizados y proyectos vinculados |
| **Pipelines** | Grafos de dependencias, pasos paralelos y condicionales, pasos opcionales, reintentos controlados, asignación por muestra, lote o proyecto y compuertas de QC |
| **Análisis y procedimientos** | Tipos de análisis configurables, resultados obligatorios, procedimientos versionados, vínculo con SOP y duración esperada |
| **Inventario** | Ubicaciones, contenedores y colocación física de muestras |
| **Cola de trabajo** | Creación de trabajos para muestras o lotes, asignación, fechas límite y seguimiento de estado |
| **Resultados** | Valores estructurados de texto, número o booleano, unidades y rangos de referencia |
| **QC** | Reglas, límites, razones de falla, asignación de revisión, aprobación, rechazo y repetición requerida |
| **Instrumentos** | Perfiles de importación, mapeo de columnas, límites numéricos y procedencia por instrumento y corrida |
| **Migración** | Perfiles reutilizables, sugerencias de mapeo, vista previa, confirmación, importación en segundo plano y revisión de filas |
| **Secuencias** | Registros de secuencias, metadatos, características e importaciones FASTA |
| **Alineamientos** | Trabajos de Clustal Omega con salida descargable |
| **BLAST** | Bases BLAST locales y búsquedas `blastn` y `blastp` |
| **Espectrometría de masas** | Revisión de mzML, mzXML, mzData, featureXML, consensusXML y mzIdentML mediante pyOpenMS |
| **Análisis visual** | Tendencias, comparaciones de muestras, proyectos y lotes, valores atípicos y cuellos de botella |
| **Asistente** | Consultas en lenguaje natural, resúmenes, comparaciones, investigación de QC y acciones confirmadas |
| **SOP** | Administración de procedimientos aprobados, versiones, secciones, vigencia y acceso por proyecto o rol |
| **Reportes** | Resúmenes de proyectos, inventario, QC, importaciones, comparaciones, investigaciones y auditoría |
| **Auditoría** | Actor, fecha, entidad, cambios, escaneos de cadena de custodia, razón del cambio y exportaciones |
| **Seguridad** | Autenticación JWT y permisos por rol y proyecto |
| **Idioma** | Interfaz completa en inglés o español, seleccionada por dirección para toda la instancia |

---

## 4. Ciclo de vida de las muestras

OpenLIMS incluye un ciclo de vida controlado:

```text
RECEIVED → IN_PROGRESS → QC → REPORTED → ARCHIVED
```

También permite crear alícuotas, divisiones, muestras derivadas y componentes
de una mezcla sin perder la relación con la muestra de origen. El sistema evita
ciclos de linaje y registra cantidad, unidad, usuario, fecha y motivo.

La pantalla de etiquetas acepta el código de barras o el ID de la muestra para
registrar recepción, retiro, devolución, transferencia de custodia, cambio de
almacenamiento, procesamiento y disposición. Cada escaneo conserva el contenedor
y custodio anterior y nuevo dentro del historial auditable.

Una muestra también puede cancelarse desde las etapas activas y archivarse posteriormente.

Los cambios de estado se validan y pueden exigir una razón para el cambio. Esto contribuye a la trazabilidad y evita saltos no permitidos dentro del ciclo de vida.

Los estados representan el avance general de la muestra. Los trabajos o `work items` representan operaciones específicas, por ejemplo:

- Extracción.
- PCR.
- Secuenciación.
- Análisis.
- Trabajo general definido por el laboratorio.

Cada trabajo puede tener responsable, fecha límite, estado operativo y estado de revisión de QC.

---

## 5. Pipelines y workflows

OpenLIMS permite:

- Mantener un ciclo de estados para cada muestra.
- Crear trabajos para muestras individuales o lotes.
- Clasificar trabajos como extracción, PCR, secuenciación o análisis.
- Asignar y reasignar trabajos.
- Identificar trabajos pendientes, vencidos, sin responsable o bloqueados.
- Relacionar resultados con el trabajo y la muestra correspondientes.
- Ejecutar importaciones y análisis pesados en segundo plano.
- Crear plantillas reutilizables con pasos ordenados desde el **Workflow Designer**.
- Asignar un análisis o pipeline a una muestra, a todas las muestras de un lote o a todas las muestras principales de un proyecto.
- Revisar desde el proyecto la ruta completa: muestras, trabajo, resultados, QC y estado de reporte.
- Relacionar cada paso con un procedimiento y un tipo de análisis configurables.
- Definir un pipeline predeterminado por proyecto, tipo de muestra o ambos.
- Iniciar automáticamente el pipeline correspondiente al dar de alta manualmente una muestra.
- Crear únicamente el trabajo del paso actual y mantener los pasos posteriores bloqueados.
- Validar los resultados obligatorios antes de completar un paso.
- Crear automáticamente el trabajo siguiente cuando el paso actual se completa.
- Esperar la aprobación de QC cuando el paso la requiere.
- Bloquear el pipeline cuando un trabajo falla o la revisión de QC no lo aprueba.
- Conservar una copia estable del nombre, procedimiento, versión y requisitos de cada paso durante la ejecución.

Un pipeline típico puede representarse así:

```text
Recepción
   ↓
Extracción
   ↓
PCR
   ↓
Secuenciación
   ↓
QC ── falla ──→ BLOQUEADO para revisión
   ↓ aprobación
Reporte
```

Las ramas condicionales arbitrarias, ciclos, repeticiones automáticas y rutas alternativas todavía no están incluidas. Una falla o rechazo de QC bloquea la ejecución para que el personal revise el caso de forma explícita.

Para definir un pipeline nuevo se recomienda documentar:

1. Los pasos y su orden.
2. Los datos de entrada y salida de cada paso.
3. Las condiciones para avanzar, repetir o cancelar.
4. Los roles que pueden ejecutar y aprobar cada etapa.
5. Los instrumentos o archivos involucrados.
6. Los límites y reglas de QC.

---

## 6. Procedimientos y análisis nuevos

Un administrador puede configurar sin modificar el código:

- Tipos de análisis con código, nombre, categoría y descripción.
- Campos de resultado obligatorios de texto, número o booleano para cada análisis.
- Procedimientos versionados con instrucciones, duración esperada y documento SOP asociado.
- Plantillas de pipeline con orden, nombre visible y requisito de QC por paso.
- Pipelines predeterminados por proyecto y tipo de muestra.
- Campos personalizados.
- Perfiles de instrumentos.
- Mapeos de columnas.
- Rangos y reglas de QC.
- Perfiles de migración.
- Documentos SOP y sus versiones.
- Trabajos, asignaciones y seguimiento de ejecución.
- Configuración general del laboratorio.

Los documentos SOP pueden incluir código, título, versión, sección, contenido, fecha de vigencia, proyecto, roles permitidos y archivo fuente. El asistente solo utiliza procedimientos aprobados, actuales y accesibles para el usuario.

Un análisis computacional completamente nuevo —por ejemplo un algoritmo, formato científico, instrumento o integración externa no soportados— requiere implementar el módulo o conector correspondiente. La arquitectura separada por aplicaciones permite agregar estas funciones de manera incremental.

El desarrollo está abierto a las necesidades concretas de los laboratorios que adopten OpenLIMS. Una vez definido el alcance, se pueden incorporar procedimientos, conectores y automatizaciones prioritarias en iteraciones cortas, normalmente de un par de semanas.

---

## 7. Importaciones de instrumentos

Los perfiles de instrumentos permiten configurar:

- Código y nombre del instrumento.
- Delimitador del archivo.
- Columna que identifica la muestra.
- Mapeo entre columnas y resultados.
- Tipos de valores.
- Límites numéricos.
- Valores permitidos.
- Ubicación real de la cabecera.
- Detección flexible de encabezados.

OpenLIMS conserva la relación entre:

```text
Instrumento → corrida → trabajo → muestra → resultado
```

Esta procedencia demuestra de dónde se obtuvo un resultado. No implica por sí sola que el instrumento haya causado una falla de QC.

---

## 8. Migración de datos anteriores

El flujo actual de migración es:

```text
SISBI, PostgreSQL, MySQL, SQLite o CSV anterior
   ↓
Perfil de migración
   ↓
Datasets de solo lectura y mapeo de campos
   ↓
Vista previa o dry run
   ↓
Confirmación
   ↓
Importación en segundo plano
   ↓
Revisión de filas importadas, omitidas o con error
```

La herramienta puede crear o relacionar:

- Proyectos.
- Usuarios inactivos sin contraseñas importadas.
- Muestras.
- Identificadores externos y alias.
- Campos personalizados.
- Trabajos.
- Resultados.
- Fechas históricas, unidades, referencias y estado de QC cuando estén mapeados.
- Plantillas de mapeo guardadas que pueden aplicarse a otro perfil compatible.
- Políticas por migración para omitir, combinar, sobrescribir o crear copias con identificadores únicos.
- Informes de conciliación con totales por entidad, acción y estado.
- Reversión controlada por Dirección de las creaciones y modificaciones registradas.

Las columnas no reconocidas pueden conservarse como campos personalizados para reducir la pérdida de información.

### Fuentes de base de datos

Dirección puede configurar conexiones de solo lectura a PostgreSQL,
MySQL/MariaDB o SQLite, inspeccionar tablas y definir un dataset separado para
proyectos, usuarios, muestras y resultados históricos. OpenLIMS no permite SQL
arbitrario desde la interfaz.

La contraseña nunca se guarda en OpenLIMS: se configura en una variable de
entorno y la conexión conserva únicamente el nombre de esa variable. Los hosts
remotos deben incluirse en `MIGRATION_DB_ALLOWED_HOSTS` y la cuenta de origen
debe tener solamente permiso `SELECT`.

La vista previa valida campos obligatorios, tipos, relaciones, estados y fechas.
También genera una huella de los datos y del mapeo. Si SISBI cambia después de
la revisión, la confirmación se bloquea y se debe generar una vista previa nueva.
La política de conflictos forma parte de esa huella. Cada migración confirmada
registra los objetos creados y los valores anteriores de los objetos modificados.
Dirección puede revertir el trabajo; OpenLIMS bloquea la reversión si existen
datos relacionados posteriores que podrían ponerse en riesgo.

### Uso de modelos de lenguaje

La migración no requiere OpenAI, otra API comercial ni una LLM local. Las sugerencias de campos, la validación y la importación utilizan reglas determinísticas. Celery procesa los trabajos grandes en segundo plano.

Ollama u OpenAI son opciones del asistente de lenguaje natural, no dependencias del motor de migración.

---

## 9. Asistente de OpenLIMS

### Consultas de flujo y seguimiento

| Pregunta | Comportamiento |
|---|---|
| `¿Qué muestras en proyecto DEMO-360 están vencidas y sin asignar en el mismo paso?` | Ambas condiciones deben cumplirse en un paso de una ejecución. |
| `¿Qué muestras en proyecto DEMO-360 están asignadas a mí y vencidas en el mismo paso?` | Busca tu trabajo con vencimiento en ese mismo paso. |
| `Solo asignadas a maria` | Reemplaza los filtros por un usuario activo exacto del proyecto. |
| `También asignadas a mí` | Añade tu asignación a una consulta Y conservando el alcance. |
| `¿Qué muestras en proyecto DEMO-360 están asignadas a mí y vencen mañana en el mismo paso?` | Busca tu trabajo disponible con vencimiento mañana en ese paso. |
| `También vencen hoy` | Añade la ventana de hoy a una consulta Y. |
| `Solo vencen en los próximos 7 días` | Reemplaza los filtros por vencimientos en las próximas 168 horas. |
| `Cumplir cualquier condición` | Cambia Y por O conservando proyecto y alcance. |
| `Quitar el filtro de vencidas` | Quita ese requisito; no excluye las muestras vencidas. |
| `En toda la muestra` | Permite coincidencias entre distintos pasos o ejecuciones de una muestra. |
| `Actualizar resultados` | Consulta registros y permisos actuales desde la primera página. |

Sin coincidencias, la respuesta muestra conteos individuales entre las muestras
revisadas en esa consulta. Pueden solaparse y no deben sumarse. Una revisión
parcial, incluso la última página de una búsqueda paginada, no equivale al total
del proyecto. Si quedan muestras, utiliza `Siguiente página`. La ausencia de un
pipeline activo no demuestra que el trabajo esté completo.

Un seguimiento poco claro conserva la consulta anterior solo si sus filtros,
alcance y acceso al proyecto siguen siendo válidos. Las opciones de recuperación
se aplican a esa consulta anterior, no al cambio rechazado. Las mezclas de Y/O,
negaciones, fechas arbitrarias y condiciones anidadas no están admitidas.
Se admite un responsable por consulta: un nombre de usuario exacto, sensible a
mayúsculas, de un miembro activo del proyecto; `mí` identifica al usuario
autenticado. El trabajo asignado corresponde a pasos pendientes de ejecuciones
activas/bloqueadas, incluso pasos que esperan QC. No identifica al revisor de QC.
Usa el mismo paso si el vencimiento o QC debe corresponder al trabajo de esa persona. Estas rutas son de solo lectura y funcionan sin OpenAI ni Ollama.


Los filtros de vencimiento solo incluyen trabajo activo disponible, con pasos
listos/en curso y dependencias satisfechas. Hoy y mañana son días naturales de la
zona activa del servidor (UTC por defecto), con inicio y fin explícitos en cada
respuesta. Hoy puede incluir trabajo ya vencido durante el día; los próximos siete
días empiezan ahora y abarcan 168 horas. Se incluye el inicio y se excluye el fin.
No coinciden trabajos sin fecha, completados/cancelados ni bloqueados por
dependencias. Actualizar y paginar usan fechas y registros actuales.

El asistente combina rutas determinísticas, herramientas seguras y, opcionalmente, un modelo de lenguaje.

```text
Pregunta del usuario
   ↓
Clasificación y reglas de OpenLIMS
   ↓
Consulta con permisos a la base de datos o herramienta
   ↓
Resultado estructurado
   ↓
Resumen opcional con OpenAI u Ollama
```

Puede ayudar a:

- Encontrar y resumir muestras o proyectos.
- Mostrar trabajos que necesitan atención.
- Identificar muestras con resultados fallidos o pendientes de QC.
- Investigar una falla mostrando la evidencia registrada.
- Comparar muestras, proyectos o lotes.
- Mostrar tablas y gráficas solicitadas explícitamente.
- Detectar valores atípicos y tendencias.
- Revisar importaciones y migraciones fallidas.
- Consultar procedimientos SOP aprobados.
- Proponer ciertas operaciones y ejecutarlas solo después de una confirmación explícita.

Los resultados de las herramientas internas son la fuente de verdad. El modelo de lenguaje no obtiene acceso directo e ilimitado a la base de datos.

### Modos disponibles

| Modo | Uso |
|---|---|
| **OpenLIMS Rules** | Rutas y respuestas integradas sin utilizar una LLM externa |
| **Ollama** | Modelo local y autohospedado |
| **OpenAI** | Resúmenes opcionales mediante configuración del servidor |

Si el modelo no está disponible o su clasificación tiene baja confianza, el asistente utiliza las reglas integradas o indica claramente que la solicitud no está soportada.

---

## 10. Secuencias y análisis científicos

### Secuencias y FASTA

Las secuencias pueden relacionarse con muestras y proyectos, conservar metadatos y alimentar trabajos posteriores.

```text
Muestra → importación FASTA → espacio de secuencias → alineamiento o BLAST
```

### Clustal Omega

Los alineamientos se ejecutan como trabajos asíncronos y conservan las secuencias de entrada, la salida alineada, el número de secuencias, el estado y un resumen.

### BLAST local

OpenLIMS puede construir bases BLAST locales y ejecutar búsquedas `blastn` y `blastp`. Los resultados incluyen identidad, e-value, posición, accession y regiones alineadas.

### Espectrometría de masas

Mediante pyOpenMS se pueden revisar archivos y resúmenes de:

- mzML, mzXML y mzData.
- featureXML y consensusXML.
- mzID y mzIdentML.
- TIC, espectros MS1/MS2, tiempo de retención y rangos m/z.
- Características detectadas, péptidos y proteínas.
- Comparaciones por proyecto, muestra o selección manual.

---

## 11. Permisos y trazabilidad

Los permisos se aplican por rol y proyecto.

| Rol | Alcance general |
|---|---|
| **Director / administrador** | Acceso completo al sistema y configuración |
| **Técnico** | Operación de laboratorio en los proyectos asignados |
| **Observador** | Acceso de solo lectura a los registros permitidos |

La bitácora de auditoría puede registrar, entre otros eventos:

- Creación y cambio de estado de muestras.
- Asignaciones y movimientos de inventario.
- Importaciones y migraciones.
- Revisiones de QC.
- Ejecución de alineamientos y BLAST.
- Procesamiento de espectrometría de masas.
- Cambios administrativos.
- Acciones propuestas y confirmadas mediante el asistente.

---

## 12. Arquitectura técnica

| Capa | Tecnología |
|---|---|
| Frontend | React y Vite |
| API | Django REST Framework |
| Base de datos | PostgreSQL |
| Trabajos en segundo plano | Celery |
| Broker y caché | Redis |
| Actualizaciones en tiempo real | Django Channels y Daphne |
| Alineamientos | Clustal Omega |
| Búsquedas | NCBI BLAST+ |
| Espectrometría de masas | pyOpenMS |
| Asistente | Reglas de OpenLIMS, Ollama u OpenAI opcional |
| Despliegue | Docker Compose y Caddy |

La plataforma está diseñada para ser autohospedada y mantener los componentes de laboratorio dentro de la infraestructura elegida por la organización.

---

## 13. Recorrido recomendado de la demo

Para conocer las funciones generales:

1. Abrir el panel principal para revisar proyectos, muestras, trabajos y actividad reciente.
2. Abrir un proyecto y revisar sus miembros, muestras y actividad.
3. Abrir una muestra y revisar estado, resultados, trabajos, procedencia y auditoría.
4. Revisar las importaciones de instrumentos y su relación con las muestras.
5. Utilizar **Analyze** para explorar métricas numéricas.
6. Revisar secuencias, alineamientos y BLAST.
7. Revisar corridas y comparaciones de espectrometría de masas.
8. Consultar trabajos pendientes y revisiones de QC.
9. Revisar la herramienta de migración y su vista previa.
10. Utilizar el asistente para consultar, comparar e investigar registros.
11. Revisar los eventos de auditoría y la configuración administrativa.

La aplicación también incluye una página **Getting Started** con un recorrido guiado y datos de demostración que se adaptan a los registros disponibles.

---

## 14. Limitaciones actuales y colaboración

Las principales funciones que todavía requieren ampliación son:

- Diseñador visual de pipelines configurables.
- Dependencias automáticas entre trabajos.
- Ramas condicionales y repetición automática según QC.
- Creación de nuevos algoritmos ejecutables completamente desde la interfaz administrativa.
- Conectores específicos para APIs de sistemas externos.
- Validación formal para entornos clínicos o regulados.

OpenLIMS se encuentra en desarrollo activo. El autor está abierto a trabajar con laboratorios que utilicen el sistema para priorizar los pipelines, conectores, procedimientos, automatizaciones y reportes que necesiten.

---

## 15. Licencia y código fuente

OpenLIMS es software de código abierto y se distribuye bajo la Licencia Apache 2.0. El código fuente puede utilizarse, modificarse y distribuirse de acuerdo con los términos de esa licencia.

Las dependencias y los componentes de terceros conservan sus respectivas licencias.

---

## Autor

**Eduardo Lemus**

OpenLIMS se desarrolla como una plataforma extensible para laboratorios que necesitan trazabilidad, automatización y control sobre su propia infraestructura.
