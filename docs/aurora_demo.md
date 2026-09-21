# Aurora demo / Demostración Aurora

An optional, compact fictional project for a 15–20 minute walkthrough. Every
measurement, sequence and MS curve is synthetic. These are not customer results,
real strains, validated compound identifications or evidence of production yield.

## Load the project

Use an isolated demonstration database with migrations already applied. The command
requires an **existing active username**, preserves its password and roles, and
sends no email. It creates a published `DEMO_PIGMENT` sample form but does not
change existing forms or global feature flags.

From the repository root, with the development Compose API already running:

```bash
docker compose -f deploy/docker-compose.yml exec api python manage.py seed_demo --showcase-only --owner director
```

Replace `director` with the account you will use during the demonstration. If
using the production Compose layout on a **demo instance**, run from `deploy/`:

```bash
docker compose -p openlims -f docker-compose.prod.yml exec api python manage.py seed_demo --showcase-only --owner director
```

Rebuild the API image after obtaining this code, before running the command.
`python manage.py seed_showcase --owner director` is an equivalent direct entry point.
Do not run the broad `seed_demo` command without `--showcase-only` for this task.

Enable Notebook in the demo instance's feature settings if it is hidden. Sign in
as the specified owner and search Projects for `DEMO-AURORA`. The seed makes this
account a project member and notebook owner, without elevating its global role.
Use an existing demo director/technician account for the full application tour.

The operation is transactional. A rerun skips an existing Aurora project and
preserves edits made during a demo. It does not repair partial manual deletions.
Conflicting fixture IDs cause an error rather than overwriting other records.

## Fictional scenario

Aurora compares a reference with two pigment-screening candidates. The six samples
have synthetic intake fields, one completed experiment with six linked samples,
12 result values, six completed measurements and one open QC repeat task.

| Sample | Group | Replicate | Signal (a.u.) | Recovery (%) | Outcome |
| --- | --- | --- | --- | --- | --- |
| AUR-001 | Reference | 1 | 100 | 98 | Reported |
| AUR-002 | Reference | 2 | 104 | 101 | Reported |
| AUR-003 | Candidate A | 1 | 148 | 99 | Reported |
| AUR-004 | Candidate A | 2 | 152 | 103 | Reported |
| AUR-005 | Candidate B | 1 | 176 | 97 | Reported |
| AUR-006 | Candidate B | 2 | 181 | 63 | QC repeat |

Reference mean: 102. Candidate A mean: 150, a 47.1% relative increase in the
**fictional signal**, not yield. Candidate B requires a QC repeat. The illustrative
recovery range is 80–120%. Two synthetic replicates do not demonstrate significance.

Three short DNA fragments have one variable position and a prepared alignment.
They have no assigned biological function or causal connection to signal changes.
Three MS summaries contain simulated curves and features, with no raw mzML files.
Show viewing/comparison, not raw-file download or reprocessing. No analysis tools,
external services or background jobs need to run to prepare these records.

## Guion de demostración

1. **Pregunta inicial (1 minuto).** ¿Qué les cuesta más organizar: muestras,
   experimentos o resultados? Aclarar que Aurora usa datos totalmente ficticios.
2. **Proyectos y muestras (3 minutos).** Buscar `DEMO-AURORA`. Abrir `AUR-003`,
   mostrar candidato, réplica y relación con el proyecto.
3. **Bitácora (3 minutos).** Abrir `Aurora | Bitácora de evaluación` y
   `Aurora E01 | Comparación inicial (simulada)`. Mostrar tabla, conclusión y
   enlaces a las seis muestras. El experimento está completado, no firmado.
4. **Resultados y QC (3 minutos).** Abrir los resultados de `AUR-006`. Su señal
   alta no resuelve la recuperación de 63%. Mostrar la tarea pendiente de repetir
   QC. No ejecutarla durante la explicación inicial.
5. **Secuencias (3 minutos).** Buscar `AUR-`, abrir una anotación y el alineamiento
   `Aurora | alineamiento simulado`. Mostrar la posición variable 21.
6. **Espectrometría de masas (3 minutos).** Buscar `Aurora` y comparar los tres
   resúmenes de `AUR-001`, `AUR-003` y `AUR-005`. Aclarar que las curvas son
   ilustrativas y no identifican compuestos.
7. **Cierre (2 minutos).** ¿Qué flujo real les gustaría probar? Acordar un ejemplo
   pequeño y quién daría retroalimentación.

Antes de la llamada: probar el acceso con la cuenta elegida, abrir la bitácora y
los análisis, y dejar las pestañas listas. La presentación permite explicar el
mismo caso si la conexión falla. No cargar datos reales de la empresa en la demo.
