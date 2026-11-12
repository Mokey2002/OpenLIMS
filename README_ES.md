# OpenLIMS

**Primeros pasos:** [Instalación paso a paso](#instalación-paso-a-paso) · [Installation guide in English](README.md#installation)

**Versión actual: v0.78.1.** El pie de página usa `OPENLIMS_VERSION` del archivo
generado `frontend/src/version.js`. Antes de iniciar o compilar el frontend,
`frontend/scripts/write-version.mjs` toma `VITE_OPENLIMS_VERSION`, el archivo raíz
`VERSION`, la etiqueta Git alcanzable más reciente, la versión generada existente
o `development`, en ese orden. Una variable `VITE_OPENLIMS_VERSION` explícita
prevalece sobre la versión normal. Al cambiar de versión, actualiza `VERSION`,
regenera `frontend/src/version.js` y mantén sincronizadas ambas guías.

## Probar la demostración local

Requiere Docker Engine/Desktop con Compose v2, Python 3.10+ y curl en Linux, macOS o WSL2. **Las descargas estarán disponibles cuando termine el flujo de publicación de v0.78.1.** No hay que compilar la aplicación.

```bash
curl -fsSL https://github.com/Mokey2002/OpenLIMS/releases/download/v0.78.1/openlims-demo.sh -o openlims-demo.sh && sh openlims-demo.sh
```

Crea `./openlims-demo`, muestra la URL y contraseña generada y solo escucha en `127.0.0.1:8080`. Puedes elegir directorio o puerto con `OPENLIMS_DEMO_DIRECTORY` y `OPENLIMS_DEMO_PORT`.

```bash
./openlims-demo/openlims doctor
./openlims-demo/openlims stop
./openlims-demo/openlims start
./openlims-demo/openlims update --version v0.78.1
```

Para actualizar, elige una versión **publicada** más reciente. Si ya está instalada, solo verifica la salud. Consulta la [guía de demo, producción y actualización](docs/prebuilt-releases-demo-updates-v0780.md). La instalación desde código sigue disponible abajo.

## Tres versiones recientes

| Versión | Mejoras | Detalles |
| --- | --- | --- |
| **v0.78.1** | Espera al servidor PostgreSQL definitivo y conserva diagnósticos de CI con secretos ocultos. | [Guía de disponibilidad y diagnóstico](docs/release-smoke-readiness-v0781.md) |
| **v0.78.0** | Imágenes para ambas arquitecturas, demostración local y actualizaciones con respaldo y reanudación. | [Guía de versiones, demo y actualizaciones](docs/prebuilt-releases-demo-updates-v0780.md) |
| **v0.77.1** | Corrección de cuatro pruebas de CI con expectativas antiguas de errores y paginación; comprobación de recuperación tras fallos. | [Guía de regresiones de CI](docs/frontend-ci-regressions-v0771.md) |

## v0.78.1 — Disponibilidad de PostgreSQL y diagnósticos de publicación

Las comprobaciones de PostgreSQL esperan conexiones TCP. El servidor temporal de inicialización acepta conexiones por socket Unix antes de que esté disponible el servidor definitivo; las migraciones o restauraciones podían empezar demasiado pronto. Se corrigen las plantillas de demo/producción, el despliegue de producción desde código y las pruebas nativas. La prueba de restauración retrasa la inicialización deliberadamente y verifica que termine antes de restaurar los registros.

Los fallos de las pruebas nativas muestran y conservan diagnósticos limitados durante siete días, incluidas operaciones del instalador y estado/logs de contenedores. Se ocultan credenciales generadas y contraseñas de conexión antes de publicarlos. No se suben configuración privada, respaldos ni archivos de muestras. El control de publicación se omite deliberadamente en los pull requests.

Versión/pie **v0.78.1**. Ambos README conservan solo **v0.78.1, v0.78.0 y v0.77.1**. Sin migración de aplicación ni dependencia nueva. Consulta la [guía de disponibilidad y diagnóstico](docs/release-smoke-readiness-v0781.md).

## v0.78.0 — Imágenes precompiladas, demo y actualizaciones reanudables

La publicación construye y prueba imágenes de backend/frontend en ejecutores nativos **linux/amd64** y **linux/arm64**. Requiere CI de la aplicación aprobada, pruebas nativas de instalación/actualización/restauración y acceso anónimo a GHCR. Las imágenes versionadas y el manifiesto con hashes fijan versiones compatibles de API, worker, monitor del asistente y frontend. Los archivos publicados se comprueban antes de reutilizarlos y no se sobrescriben.

El lanzador descarga un instalador pequeño y crea una demostración aislada en localhost con datos de ejemplo y credenciales generadas. El comando instalado permite iniciar, detener, verificar, respaldar y actualizar a una versión elegida. Antes de migrar detiene los procesos que escriben y respalda PostgreSQL, archivos y configuración. Una migración interrumpida conserva su punto de progreso para reanudar explícitamente. Las actualizaciones conservan los datos y no vuelven a cargar ejemplos ni restablecen contraseñas.

Versión/pie **v0.78.0**. Ambos README conservan solo las tres actualizaciones indicadas arriba. Sin migración de aplicación ni dependencia Python nueva. La publicación se ejecuta después de crear la versión revisada en GitHub; configurar el flujo no significa que las imágenes ya estén publicadas. Consulta la [guía de versiones, demo y actualizaciones](docs/prebuilt-releases-demo-updates-v0780.md).

## v0.77.1 — Correcciones de regresiones de CI del frontend

Cuatro pruebas del navegador esperaban mensajes HTTP técnicos o el nombre antiguo del botón de paginación después de las mejoras de UX. Ahora comprueban mensajes legibles y el control accesible **Next sample page**. Se mantiene la comprobación de que un cambio de cuaderno fallido conserva el cuaderno/experimento actual y que un acceso inicial denegado permite seguir navegando. Las pruebas de historial siguen rechazando estados vacíos engañosos y ahora comprueban la recuperación cuando vuelve el servicio. No cambia el comportamiento de la aplicación, los permisos ni el esquema de datos.

Versión/pie **v0.77.1**. Ambos README conservan solo las tres actualizaciones indicadas arriba. Consulta la [guía de regresiones de CI](docs/frontend-ci-regressions-v0771.md) para causas y validación.

**Sistema de gestión de información de laboratorio de código abierto, autohospedado y orientado a flujos de trabajo prácticos.**

OpenLIMS organiza proyectos, muestras, inventario, trabajos, resultados, control de calidad, importaciones de instrumentos, análisis bioinformáticos, migraciones y auditoría en una misma plataforma.

> **Estado actual:** OpenLIMS es un prototipo con arquitectura de producción. Todavía no es un LIMS clínico, diagnóstico o regulado completamente validado.

**Versión de desarrollo actual:** `v0.78.1`

**Demo:** http://35.164.28.250

---

## Favoritos personales

Abre **Favorites** y selecciona **Pin current page** o **Unpin current page**. Los pines pertenecen a tu cuenta en ese navegador; no se sincronizan entre computadoras o navegadores. La lista compartida de versiones anteriores ya no se utiliza: vuelve a fijar tus páginas una vez después de actualizar.

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

La cuenta creada por `createsuperuser` recibe acceso efectivo **admin** en OpenLIMS sin asignar grupos manualmente. El nombre de usuario puede ser `root` u otro: el acceso depende de los permisos de Django. Si una instalación anterior muestra «No assigned role» para un superusuario, actualiza/reconstruye la API y la web con este parche y vuelve a iniciar sesión. Una cuenta normal llamada `root` necesita que un administrador le conceda el rol adecuado.

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

### Explicaciones de muestras y seguimiento

Funcionan con OpenLIMS Rules en ambas vistas del chat, sin proveedor de IA.
Sustituye `S-100` por un ID exacto y accesible; usa comillas si contiene espacios.

| Consulta directa | Seguimiento de una muestra seleccionada | Respuesta |
|---|---|---|
| `Explica la muestra S-100` | `Explícalo más simple` | Explicación breve de las alertas registradas y la primera comprobación sugerida. |
| `Muestra la evidencia de la muestra S-100` | `¿Por qué necesita atención?` / `Muestra la evidencia` | Recuentos actuales y registros prioritarios con responsables, fechas, valores, rangos y notas de QC. |
| `¿Qué debo revisar primero para la muestra S-100?` | `¿Qué debo revisar primero?` | Sugerencias ordenadas por fallos/QC, revisiones pendientes, vencimientos y falta de responsable. |
| `¿Qué no sabemos de la muestra S-100?` | `¿Qué no sabemos?` | Valores, controles, notas y límites ausentes o inválidos, y limitaciones de la evidencia. |

`In Spanish` / `In English` conserva el tipo de explicación. `Thanks` mantiene la
muestra; `same for S-102` repite la explicación para otra muestra accesible y
`Back to the previous sample` recupera una consulta reciente compatible.
`Forget this conversation` borra el contexto. Si falta la selección o hay varios
IDs contradictorios, se solicita una sola muestra. Se usan IDs estables y se
verifican permisos en cada consulta, incluso para miembros de proyectos vinculados.

Los recuentos pueden solaparse. Las alertas excluyen trabajos completados o
cancelados; los resultados pueden ser históricos. La evidencia muestra hasta
tres trabajos y tres resultados señalados; si no hay resultados señalados,
muestra hasta tres recientes. Los datos desconocidos se revisan solo en los
cinco resultados recientes y hasta tres prioritarios, sin duplicados, no en todos
los resultados de la muestra. Las notas se limitan a 240 caracteres y se marcan
como extractos. Se conservan valores cero/falso y se indican valores o límites
inválidos. Estar fuera del rango configurado no inventa un fallo registrado de
QC ni establece su causa científica. Un control de QC y una decisión de revisión
son evidencias distintas.

Las sugerencias no evalúan todas las dependencias ni autorizan liberar la muestra
o modificar registros. Usa `What next for sample S-100?` para la guía de pipelines
y consulta a un revisor autorizado para decisiones de QC. Estas explicaciones no
guardan transcripciones ni copias de registros: la memoria de temas guarda solo
IDs y operaciones de lectura permitidas. OpenAI/Ollama pueden usar la misma
herramienta `sample_explanations`, con permisos comprobados y evidencia sin
reescritura del modelo. No requiere migraciones ni nueva configuración del modelo.

### Resúmenes de muestras con evidencia

Usa `Summarize sample S-100` para ver prioridades de trabajo, conteos de QC y los
cinco resultados más recientes, con valores, unidades y fechas. Una lista separada
muestra hasta tres trabajos y tres resultados que necesitan atención, para que los
fallos antiguos puedan aparecer aunque no estén entre los resultados recientes.
Los conteos totales indican cuántos registros quedan fuera de las listas.

El resumen distingue comprobaciones de QC, decisiones del revisor y comparación
con límites de referencia. Muestra responsables, fechas límite, motivos y notas
registrados; indica valores o límites inválidos y marca los textos largos como
extractos. Los resultados pueden ser históricos; el trabajo completado o cancelado
no entra en las prioridades de trabajo. Funciona sin un modelo externo y no
determina si una muestra está lista para liberarse. Las preguntas sugeridas sobre
resultados, flujo e historial vuelven a comprobar los registros y permisos actuales.

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
| **Ollama** | Resúmenes y conversación general con un modelo local y autohospedado |
| **OpenAI** | Resúmenes y conversación general mediante configuración del servidor |

Si el modelo no está disponible o su clasificación tiene baja confianza, el asistente utiliza las reglas integradas o indica claramente que la solicitud no está soportada.

### Conversación general y seguimiento

Configura OpenAI u Ollama y activa `OPENLIMS_ASSISTANT_LLM_ENABLED=true` y
`OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=true`. En cualquiera de las dos vistas del
chat, prueba `Explain photosynthesis`, seguido de `Explain that more simply`,
`Give me an example`, `Explain that in Spanish` o `What were we talking about?`.
Estas formas comunes reutilizan el historial general verificado sin otra llamada
al clasificador; otras preguntas no reconocidas proporcionan ese historial al
clasificador para interpretar referencias. El modelo recibe roles separados y
guías para responder directamente, adaptar idioma y detalle, usar ejemplos y
distinguir hechos de incertidumbre. La calidad depende del modelo configurado;
las pruebas simulan proveedores y no demuestran equivalencia con ChatGPT ni una
puntuación de calidad con modelos reales.

La memoria general conserva hasta cuatro pares de pregunta/respuesta y 12.000
caracteres. Los mensajes de más de 4.000 caracteres se recortan con una indicación.
Caduca 30 minutos después de la última respuesta general correcta. `Thanks` y
`Okay` conservan el contexto sin añadir mensajes de cortesía al historial; los
fallos o respuestas vacías conservan el último historial correcto para reintentar.
`Start over`, `Reset conversation` y `Forget this conversation` borran el contexto
del chat. Una consulta a herramientas del laboratorio descarta la transcripción
general activa; las referencias anteriores de muestras/proyectos siguen sus
propias reglas de memoria.

El historial viaja en el contexto del chat como un token firmado, vinculado al
usuario y **legible, sin cifrar**. No se añade almacenamiento de transcripciones
en la base de datos ni se requieren migraciones. Los mensajes generales retenidos
se envían al proveedor configurado cuando se necesitan. Las respuestas de
herramientas y los datos de registros no se incorporan automáticamente a esta
memoria ni a su prompt de respuesta. El modo general no accede a registros ni
ejecuta herramientas. Las consultas del laboratorio mantienen sus permisos y
las modificaciones compatibles requieren confirmación explícita. Sigue
disponible el modo de solo reglas sin un modelo.

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
| **Director / administrador** | Administración y configuración; muestras según membresía de proyecto |
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

### Pruebas de descarga de imágenes en CI

Desde la raíz del repositorio, con Python 3 y sin necesidad de Docker:

```bash
python3 -m unittest discover -s scripts -p 'test_ci_pull_images.py'
```

Las descargas en CI realizan hasta tres intentos ante errores transitorios de red
o del registro, incluido `context deadline exceeded` del daemon de Docker, con
esperas de 15 y 30 segundos entre intentos. Si se agotan, un registro alternativo
configurado explícitamente utiliza los mismos límites de reintentos. Los errores
permanentes fallan de inmediato; una descarga fallida del registro alternativo
nunca se etiqueta como una imagen descargada correctamente.

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
