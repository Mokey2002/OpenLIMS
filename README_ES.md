# OpenLIMS

**Sistema de gestión de información de laboratorio de código abierto, autohospedado y orientado a flujos de trabajo prácticos.**

OpenLIMS organiza proyectos, muestras, inventario, trabajos, resultados, control de calidad, importaciones de instrumentos, análisis bioinformáticos, migraciones y auditoría en una misma plataforma.

> **Estado actual:** OpenLIMS es un prototipo con arquitectura de producción. Todavía no es un LIMS clínico, diagnóstico o regulado completamente validado.

**Versión descrita:** `v0.25.0`

**Demo:** http://35.164.28.250

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
| **Muestras** | Alta, estados, responsable, lote, archivos adjuntos, campos personalizados y proyectos vinculados |
| **Pipelines** | Plantillas ordenadas, asignación por muestra, lote o proyecto, valores predeterminados, avance automático, bloqueo por fallas y compuertas de QC |
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
| **Auditoría** | Actor, fecha, entidad, cambios, razón del cambio y exportaciones |
| **Seguridad** | Autenticación JWT y permisos por rol y proyecto |
| **Idioma** | Interfaz completa en inglés o español, seleccionada por dirección para toda la instancia |

---

## 4. Ciclo de vida de las muestras

OpenLIMS incluye un ciclo de vida controlado:

```text
RECEIVED → IN_PROGRESS → QC → REPORTED → ARCHIVED
```

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
Exportación del sistema anterior
   ↓
Archivo CSV
   ↓
Perfil de migración
   ↓
Mapeo de campos
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
- Muestras.
- Identificadores externos y alias.
- Campos personalizados.
- Trabajos.
- Resultados.

Las columnas no reconocidas pueden conservarse como campos personalizados para reducir la pérdida de información.

### Alcance actual

El tipo de fuente soportado directamente es CSV. OpenLIMS no se conecta automáticamente a cualquier base de datos de laboratorio. Para otro sistema se puede:

1. Exportar sus datos a CSV y configurar un perfil reutilizable.
2. Crear un conector específico para su base de datos o API.

### Uso de modelos de lenguaje

La migración no requiere OpenAI, otra API comercial ni una LLM local. Las sugerencias de campos, la validación y la importación utilizan reglas determinísticas. Celery procesa los trabajos grandes en segundo plano.

Ollama u OpenAI son opciones del asistente de lenguaje natural, no dependencias del motor de migración.

---

## 9. Asistente de OpenLIMS

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
- Conectores universales para bases de datos externas.
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
