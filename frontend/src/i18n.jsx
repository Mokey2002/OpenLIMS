/* eslint-disable react-refresh/only-export-components */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { apiGet } from "./api";

const LANGUAGE_STORAGE_KEY = "openlims-ui-language";
const SUPPORTED_LANGUAGES = new Set(["en", "es"]);
const TRANSLATABLE_ATTRIBUTES = ["placeholder", "title", "aria-label"];

const spanishText = {
  // Application shell and navigation
  Demo: "Demostración",
  Dashboard: "Panel",
  "Getting Started": "Primeros pasos",
  Assistant: "Asistente",
  Core: "Principal",
  Projects: "Proyectos",
  Samples: "Muestras",
  Inventory: "Inventario",
  Analysis: "Análisis",
  Analyze: "Analizar",
  "Investigation Workbench": "Área de investigación",
  "Comparisons & Charts": "Comparaciones y gráficas",
  Sequences: "Secuencias",
  Alignments: "Alineamientos",
  "Mass Spec": "Espectrometría de masas",
  "Compare Mass Spec": "Comparar espectrometría",
  Operations: "Operaciones",
  Imports: "Importaciones",
  "Sample Batches": "Lotes de muestras",
  "Result QC": "QC de resultados",
  "Work Queue": "Cola de trabajo",
  "Barcode Labels": "Etiquetas de código de barras",
  "Audit Events": "Eventos de auditoría",
  Reports: "Reportes",
  Notifications: "Notificaciones",
  Admin: "Administración",
  Users: "Usuarios",
  Settings: "Configuración",
  "SOP Management": "Gestión de SOP",
  "Workflow Designer": "Diseñador de workflows",
  "System Status": "Estado del sistema",
  Logout: "Cerrar sesión",
  Unknown: "Desconocido",
  "No role": "Sin rol",
  "Search samples, projects...": "Buscar muestras, proyectos...",
  "Guided demo": "Demostración guiada",
  Previous: "Anterior",
  Next: "Siguiente",
  Done: "Listo",
  Guide: "Guía",
  Exit: "Salir",

  // Common actions
  Refresh: "Actualizar",
  Save: "Guardar",
  Saving: "Guardando",
  "Saving...": "Guardando...",
  Cancel: "Cancelar",
  Close: "Cerrar",
  Create: "Crear",
  Update: "Actualizar",
  Edit: "Editar",
  Delete: "Eliminar",
  Remove: "Quitar",
  Add: "Agregar",
  Archive: "Archivar",
  Open: "Abrir",
  View: "Ver",
  Search: "Buscar",
  Filter: "Filtrar",
  Filters: "Filtros",
  Clear: "Limpiar",
  Reset: "Restablecer",
  Submit: "Enviar",
  Continue: "Continuar",
  Back: "Volver",
  Upload: "Subir",
  Download: "Descargar",
  Preview: "Vista previa",
  Confirm: "Confirmar",
  Approve: "Aprobar",
  Reject: "Rechazar",
  Reopen: "Reabrir",
  Assign: "Asignar",
  Unassign: "Desasignar",
  Start: "Iniciar",
  Stop: "Detener",
  Run: "Ejecutar",
  Reprint: "Reimprimir",
  "View details": "Ver detalles",
  "View alignment": "Ver alineamiento",
  "View import": "Ver importación",
  "Reset Defaults": "Restablecer valores predeterminados",
  "Resetting...": "Restableciendo...",
  "Save Settings": "Guardar configuración",

  // Common fields and table headings
  ID: "ID",
  Name: "Nombre",
  Code: "Código",
  Description: "Descripción",
  Type: "Tipo",
  Kind: "Clase",
  Status: "Estado",
  Project: "Proyecto",
  Sample: "Muestra",
  Batch: "Lote",
  Container: "Contenedor",
  Location: "Ubicación",
  Created: "Creado",
  Updated: "Actualizado",
  Uploaded: "Subido",
  Processed: "Procesado",
  Completed: "Completado",
  Failed: "Fallido",
  Error: "Error",
  Warning: "Advertencia",
  Warnings: "Advertencias",
  Time: "Hora",
  Date: "Fecha",
  Actor: "Usuario",
  Action: "Acción",
  Entity: "Entidad",
  Reason: "Motivo",
  Value: "Valor",
  Key: "Clave",
  Field: "Campo",
  Before: "Antes",
  After: "Después",
  Results: "Resultados",
  Result: "Resultado",
  Work: "Trabajo",
  "Work Item": "Trabajo",
  "Work Items": "Trabajos",
  Pipeline: "Pipeline",
  Procedure: "Procedimiento",
  Step: "Paso",
  Requirements: "Requisitos",
  Report: "Reporte",
  QC: "QC",
  "QC Pending": "QC pendiente",
  Approved: "Aprobado",
  Rejected: "Rechazado",
  Pending: "Pendiente",
  Active: "Activo",
  Inactive: "Inactivo",
  Available: "Disponible",
  Quantity: "Cantidad",
  Unit: "Unidad",
  Category: "Categoría",
  Length: "Longitud",
  File: "Archivo",
  Row: "Fila",
  Column: "Columna",
  Progress: "Progreso",
  Summary: "Resumen",
  Details: "Detalles",
  Overview: "Resumen",
  Members: "Miembros",
  Owner: "Responsable",
  Assignee: "Asignado a",
  Instrument: "Instrumento",
  Database: "Base de datos",
  Query: "Consulta",
  Program: "Programa",
  Metric: "Métrica",
  Scope: "Alcance",
  Target: "Destino",
  Assignment: "Asignación",
  Version: "Versión",
  Role: "Rol",
  Username: "Usuario",
  Email: "Correo electrónico",
  Password: "Contraseña",
  Notes: "Notas",
  Message: "Mensaje",
  Events: "Eventos",
  Activity: "Actividad",
  Attachments: "Archivos adjuntos",
  Source: "Fuente",
  Rank: "Posición",
  Hit: "Coincidencia",
  Hits: "Coincidencias",
  Identity: "Identidad",
  Alignment: "Alineamiento",
  Reorder: "Reordenar",
  Expires: "Caduca",
  Reservation: "Reserva",
  Reservations: "Reservas",
  Containers: "Contenedores",
  Locations: "Ubicaciones",
  Lots: "Lotes",
  Profile: "Perfil",
  Errors: "Errores",
  Imported: "Importado",
  Skipped: "Omitido",
  Spectra: "Espectros",

  // Status values returned by the API
  RECEIVED: "RECIBIDA",
  PROCESSING: "EN PROCESO",
  COMPLETED: "COMPLETADO",
  FAILED: "FALLIDO",
  CANCELLED: "CANCELADO",
  ARCHIVED: "ARCHIVADO",
  PENDING: "PENDIENTE",
  ACTIVE: "ACTIVO",
  INACTIVE: "INACTIVO",
  READY: "LISTO",
  BLOCKED: "BLOQUEADO",
  IN_PROGRESS: "EN PROGRESO",
  AWAITING_QC: "ESPERANDO QC",
  APPROVED: "APROBADO",
  REJECTED: "RECHAZADO",
  UNREVIEWED: "SIN REVISAR",
  IMPORTED: "IMPORTADO",
  SKIPPED: "OMITIDO",
  ERROR: "ERROR",
  RESERVED: "RESERVADO",
  CONSUMED: "CONSUMIDO",
  EXPIRED: "CADUCADO",
  STRING: "TEXTO",
  NUMBER: "NÚMERO",
  BOOLEAN: "BOOLEANO",

  // Empty, loading and state messages
  "Loading...": "Cargando...",
  "Searching...": "Buscando...",
  "Loading settings...": "Cargando configuración...",
  "Loading project...": "Cargando proyecto...",
  "Loading sample...": "Cargando muestra...",
  "Loading import job...": "Cargando importación...",
  "Loading migration job...": "Cargando migración...",
  "Loading mass spec runs...": "Cargando corridas de espectrometría...",
  "Loading workflow configuration...": "Cargando configuración del workflow...",
  "Unable to load system settings.": "No se pudo cargar la configuración del sistema.",
  "No results found.": "No se encontraron resultados.",
  "No projects found.": "No se encontraron proyectos.",
  "No projects available yet.": "Todavía no hay proyectos disponibles.",
  "No samples yet.": "Todavía no hay muestras.",
  "No samples found.": "No se encontraron muestras.",
  "No work items yet.": "Todavía no hay trabajos.",
  "No results yet.": "Todavía no hay resultados.",
  "No result values yet.": "Todavía no hay valores de resultados.",
  "No attachments yet.": "Todavía no hay archivos adjuntos.",
  "No posts yet.": "Todavía no hay publicaciones.",
  "No recent events yet.": "Todavía no hay eventos recientes.",
  "No matching users.": "No se encontraron usuarios.",
  "No linked projects": "Sin proyectos vinculados",
  "No project": "Sin proyecto",
  "No sample": "Sin muestra",
  "No container": "Sin contenedor",
  "No instrument": "Sin instrumento",
  "No numeric metrics found": "No se encontraron métricas numéricas",
  "No open QC review items.": "No hay revisiones de QC abiertas.",
  "No import jobs for this project.": "No hay importaciones para este proyecto.",
  "No alignments for this project.": "No hay alineamientos para este proyecto.",
  "No project activity found.": "No se encontró actividad del proyecto.",
  "No samples in this project yet.": "Todavía no hay muestras en este proyecto.",
  "No samples are associated with this project.": "No hay muestras asociadas con este proyecto.",
  "No pipeline has been started for this sample.": "No se ha iniciado un pipeline para esta muestra.",
  "No further transitions.": "No hay más transiciones.",
  "No skipped rows for this import.": "No hay filas omitidas en esta importación.",
  "No BLAST jobs yet.": "Todavía no hay trabajos BLAST.",
  "No BLAST job selected.": "No se seleccionó un trabajo BLAST.",
  "No hits found.": "No se encontraron coincidencias.",
  "No inventory items yet.": "Todavía no hay artículos de inventario.",
  "No inventory lots yet.": "Todavía no hay lotes de inventario.",
  "No accessible reservations.": "No hay reservas disponibles.",
  "No locations yet.": "Todavía no hay ubicaciones.",
  "No containers yet.": "Todavía no hay contenedores.",
  "No mass spec runs yet.": "Todavía no hay corridas de espectrometría.",

  // Settings page
  "Admin Settings": "Configuración administrativa",
  "General Settings": "Configuración general",
  "Import Settings": "Configuración de importación",
  "Sequence & Alignment Settings": "Configuración de secuencias y alineamientos",
  "Security Settings": "Configuración de seguridad",
  "Lab Name": "Nombre del laboratorio",
  "Organization Name": "Nombre de la organización",
  "UI Language": "Idioma de la interfaz",
  English: "Inglés",
  Spanish: "Español",
  "Default Timezone": "Zona horaria predeterminada",
  "Default Sample Status": "Estado predeterminado de muestras",
  "Max Upload Size MB": "Tamaño máximo de carga (MB)",
  "Allowed FASTA Extensions": "Extensiones FASTA permitidas",
  "Max Sequences Per Alignment": "Máximo de secuencias por alineamiento",
  "Max Sequence Length": "Longitud máxima de secuencia",
  "Last Updated": "Última actualización",
  "Updated By": "Actualizado por",
  "Admin editable": "Editable por dirección",
  "Read only": "Solo lectura",
  "Require import preview before confirm": "Requerir vista previa antes de confirmar una importación",
  "Enable alignment jobs": "Habilitar trabajos de alineamiento",
  "Viewer role is read-only": "El rol de consulta es de solo lectura",
  "Require audit reason for critical changes": "Requerir motivo de auditoría para cambios críticos",
  "Enforce QC separation of duties": "Aplicar separación de funciones de QC",
  "System settings updated.": "Configuración del sistema actualizada.",
  "System settings reset to defaults.": "La configuración se restableció a los valores predeterminados.",
  "Only admin/director users can update system settings.": "Solo dirección/administración puede actualizar la configuración del sistema.",
  "Only admin/director users can reset system settings.": "Solo dirección/administración puede restablecer la configuración del sistema.",
  "Display name for the lab using this OpenLIMS instance.": "Nombre del laboratorio que utiliza esta instancia de OpenLIMS.",
  "Comma-separated. Example: .fasta, .fa, .fna, .txt": "Separadas por comas. Ejemplo: .fasta, .fa, .fna, .txt",
  "Changes are logged to the Events page as SETTINGS_UPDATED.": "Los cambios se registran en Eventos como SETTINGS_UPDATED.",
  "Configure OpenLIMS defaults, import limits, sequence alignment behavior, and security settings.": "Configura los valores predeterminados de OpenLIMS, límites de importación, alineamientos y seguridad.",
  "Choose the language shown to every signed-in OpenLIMS user.": "Elige el idioma que verán todos los usuarios de OpenLIMS.",

  // Projects, samples and workflow
  "Project Workflow": "Workflow del proyecto",
  "Project Overview": "Resumen del proyecto",
  "Project Feed": "Actividad del proyecto",
  "Project Samples": "Muestras del proyecto",
  "Recent Project Activity": "Actividad reciente del proyecto",
  "Recent Imports": "Importaciones recientes",
  "Recent Alignments": "Alineamientos recientes",
  "Samples by Status": "Muestras por estado",
  "QC Review Queue": "Cola de revisión de QC",
  "Team Members": "Miembros del equipo",
  "Manage Team": "Administrar equipo",
  "Create Project": "Crear proyecto",
  "Existing Projects": "Proyectos existentes",
  "Create Sample": "Crear muestra",
  "Bulk Actions": "Acciones masivas",
  "Sample ID": "ID de muestra",
  "Sample Type": "Tipo de muestra",
  "Primary Project": "Proyecto principal",
  "Linked Projects": "Proyectos vinculados",
  "Created By": "Creado por",
  "Created At": "Creado el",
  "Sample Overview": "Resumen de la muestra",
  "Sample Classification": "Clasificación de la muestra",
  "Change Status": "Cambiar estado",
  "New Status": "Nuevo estado",
  "Reason for change": "Motivo del cambio",
  "Reason for status change": "Motivo del cambio de estado",
  "Pipeline Execution": "Ejecución del pipeline",
  "Pipeline template": "Plantilla de pipeline",
  "Storage Assignment": "Asignación de almacenamiento",
  "Result Values": "Valores de resultados",
  "Import History": "Historial de importaciones",
  "Sample Attachments": "Archivos adjuntos de la muestra",
  "Assign analysis or pipeline": "Asignar análisis o pipeline",
  "Entire project": "Proyecto completo",
  "Sample batch": "Lote de muestras",
  "One sample": "Una muestra",
  "Select batch": "Seleccionar lote",
  "Select sample": "Seleccionar muestra",
  "Select pipeline": "Seleccionar pipeline",
  "Select analysis": "Seleccionar análisis",
  "Pipeline / Analysis": "Pipeline / Análisis",
  "Linked to this project": "Vinculadas a este proyecto",
  "Import Jobs": "Importaciones",
  "Assign analysis or pipeline to samples without breaking their project association.": "Asigna análisis o pipelines sin separar las muestras de su proyecto.",
  "Use project/sample-type default": "Usar valor predeterminado del proyecto/tipo de muestra",
  "QC approval required": "Se requiere aprobación de QC",
  "Set status...": "Establecer estado...",
  "Assign project...": "Asignar proyecto...",
  "Assign container...": "Asignar contenedor...",
  "Link project...": "Vincular proyecto...",
  Unassigned: "Sin asignar",

  // Imports, analysis and lab operations
  "Job Overview": "Resumen del trabajo",
  "Run ID": "ID de corrida",
  "Uploaded By": "Subido por",
  "Progress Count": "Conteo de progreso",
  "Rows Processed": "Filas procesadas",
  "Samples Matched": "Muestras encontradas",
  "Samples Created": "Muestras creadas",
  "Results Created": "Resultados creados",
  "Linked Provenance": "Procedencia vinculada",
  "Skipped Rows": "Filas omitidas",
  "Import Action": "Acción de importación",
  "Linked Samples": "Muestras vinculadas",
  "Raw Summary": "Resumen sin procesar",
  "QC Review": "Revisión de QC",
  "Create BLAST Database": "Crear base de datos BLAST",
  "Database Type": "Tipo de base de datos",
  "Source FASTA": "FASTA de origen",
  "BLAST Databases": "Bases de datos BLAST",
  "Run BLAST Search": "Ejecutar búsqueda BLAST",
  "Query Sequence": "Secuencia de consulta",
  "BLAST Database": "Base de datos BLAST",
  "Job Name": "Nombre del trabajo",
  "Max Hits": "Máximo de coincidencias",
  "BLAST Jobs": "Trabajos BLAST",
  "BLAST Results": "Resultados BLAST",
  "Bit Score": "Puntuación de bits",
  Protein: "Proteína",
  "Auto / none": "Automático / ninguno",
  "Select sequence...": "Seleccionar secuencia...",
  "Select ready database...": "Seleccionar base de datos lista...",
  "Reagents and supplies": "Reactivos y suministros",
  "Reserve reagent": "Reservar reactivo",
  "Consume from lot": "Consumir del lote",
  "Mark lot expired": "Marcar lote como caducado",
  "Preview operation": "Vista previa de la operación",
  "Created by": "Creado por",
  "Storage path": "Ruta de almacenamiento",
  "Create Analysis": "Crear análisis",
  "Analysis definitions": "Definiciones de análisis",
  "Procedure definitions": "Definiciones de procedimientos",
  "Pipeline templates": "Plantillas de pipeline",
  "Required result fields": "Campos de resultado obligatorios",
  "Expected duration (minutes)": "Duración esperada (minutos)",
  "Linked SOP": "SOP vinculado",
  "Ordered steps": "Pasos ordenados",
  "Add field": "Agregar campo",
  "Add step": "Agregar paso",
  "Create analysis": "Crear análisis",
  "Create procedure": "Crear procedimiento",
  "Create pipeline": "Crear pipeline",
  "Director only": "Solo dirección",
  "Director/Admin": "Dirección/Administración",

  // Sign in
  Director: "Director",
  Viewer: "Consulta",
  "Tech Peter": "Técnico Peter",
  "Tech Maria": "Técnica Maria",
  "Tech Michael": "Técnico Michael",
  "Admin Access": "Acceso administrativo",
  "Lab Tech": "Técnico de laboratorio",
  "Read Only": "Solo lectura",
  "Sign in": "Iniciar sesión",
  "Signing in...": "Iniciando sesión...",
  "Demo Accounts": "Cuentas de demostración",
  "Recommended demo login": "Acceso de demostración recomendado",
  "Role differences:": "Diferencias entre roles:",
  "Enter username": "Ingresa el usuario",
  "Enter password": "Ingresa la contraseña",
  "Use your OpenLIMS account or try one of the demo roles.": "Usa tu cuenta de OpenLIMS o prueba uno de los roles de demostración.",
  "For the best demo experience, start with the Director account first.": "Para una mejor demostración, comienza con la cuenta de Director.",
  "Start with Director for the full demo, then compare with Tech and Viewer permissions.": "Comienza con Director para ver la demostración completa y después compara los permisos de Técnico y Consulta.",
  "Lab director access. Can manage users, project teams, admin settings, imports, samples, sequences, alignments, and audit workflows.": "Acceso de dirección. Puede administrar usuarios, equipos, configuración, importaciones, muestras, secuencias, alineamientos y auditoría.",
  "Lab workflow access. Can run imports, update samples, add results, upload attachments, and manage sequence workspaces.": "Acceso a workflows del laboratorio. Puede importar, actualizar muestras, agregar resultados, subir archivos y administrar secuencias.",
  "Lab workflow access focused on sequencing QC, FASTA imports, sequence workspaces, and alignment review.": "Acceso a workflows enfocados en QC de secuenciación, importaciones FASTA, secuencias y revisión de alineamientos.",
  "Lab workflow access focused on endotoxin review, instrument results, sample QC, and project updates.": "Acceso a workflows enfocados en endotoxinas, resultados de instrumentos, QC de muestras y proyectos.",
  "Read-only demo access. Can view dashboards, samples, projects, events, analysis, sequences, and alignments but cannot make changes.": "Acceso de demostración de solo lectura. Puede consultar paneles, muestras, proyectos, eventos, análisis, secuencias y alineamientos sin realizar cambios.",
};

function normalizeLanguage(language) {
  return SUPPORTED_LANGUAGES.has(language) ? language : "en";
}

function translatePattern(value) {
  let match = value.match(/^Step (\d+)$/);
  if (match) return `Paso ${match[1]}`;

  match = value.match(/^Page (\d+) of (\d+)$/);
  if (match) return `Página ${match[1]} de ${match[2]}`;

  match = value.match(/^(\d+) samples?$/);
  if (match) return `${match[1]} ${match[1] === "1" ? "muestra" : "muestras"}`;

  match = value.match(/^(\d+) selected$/);
  if (match) return `${match[1]} seleccionados`;

  match = value.match(/^Next: (.+)$/);
  if (match) return `Siguiente: ${translateText(match[1], "es")}`;

  match = value.match(/^Guided demo step (\d+) of (\d+)$/);
  if (match) return `Paso ${match[1]} de ${match[2]} de la demostración`;

  match = value.match(/^Login as (.+)$/);
  if (match) return `Entrar como ${translateText(match[1], "es")}`;

  match = value.match(/^Loading (.+)\.\.\.$/);
  if (match) return `Cargando ${translateText(match[1], "es").toLowerCase()}...`;

  return value;
}

export function translateText(value, language) {
  const text = String(value ?? "");
  if (normalizeLanguage(language) !== "es" || !text) return text;
  return spanishText[text] || translatePattern(text);
}

const originalText = new WeakMap();
const originalAttributes = new WeakMap();

function translateTextNode(node, language) {
  const current = node.nodeValue || "";
  const saved = originalText.get(node);

  if (language === "en") {
    if (saved !== undefined && current !== saved) node.nodeValue = saved;
    return;
  }

  const savedTranslated = saved === undefined ? null : translatePreservingSpace(saved);
  const original = saved === undefined || current !== savedTranslated ? current : saved;
  if (saved === undefined || original !== saved) originalText.set(node, original);

  const translated = translatePreservingSpace(original);
  if (translated !== current) node.nodeValue = translated;
}

function translatePreservingSpace(value) {
  const leading = value.match(/^\s*/)?.[0] || "";
  const trailing = value.match(/\s*$/)?.[0] || "";
  const content = value.slice(leading.length, value.length - trailing.length);
  if (!content) return value;
  return `${leading}${translateText(content, "es")}${trailing}`;
}

function translateAttributes(element, language) {
  let saved = originalAttributes.get(element);
  if (!saved) {
    saved = new Map();
    originalAttributes.set(element, saved);
  }

  for (const attribute of TRANSLATABLE_ATTRIBUTES) {
    if (!element.hasAttribute(attribute)) continue;
    const current = element.getAttribute(attribute) || "";
    const original = saved.get(attribute);

    if (language === "en") {
      if (original !== undefined && current !== original) {
        element.setAttribute(attribute, original);
      }
      continue;
    }

    const expected = original === undefined ? null : translateText(original, "es");
    const nextOriginal = original === undefined || current !== expected ? current : original;
    if (original === undefined || nextOriginal !== original) saved.set(attribute, nextOriginal);

    const translated = translateText(nextOriginal, "es");
    if (translated !== current) element.setAttribute(attribute, translated);
  }
}

function translateSubtree(root, language) {
  if (!root) return;

  if (root.nodeType === Node.TEXT_NODE) {
    translateTextNode(root, language);
    return;
  }

  if (root.nodeType !== Node.ELEMENT_NODE) return;
  translateAttributes(root, language);

  const walker = document.createTreeWalker(
    root,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
  );
  let node = walker.nextNode();
  while (node) {
    if (node.nodeType === Node.TEXT_NODE) translateTextNode(node, language);
    else translateAttributes(node, language);
    node = walker.nextNode();
  }
}

const LanguageContext = createContext({
  language: "en",
  locale: "en-US",
  setLanguage: () => {},
  t: (value) => value,
});

export function LanguageProvider({ children }) {
  const [language, setLanguageState] = useState(() =>
    normalizeLanguage(window.localStorage.getItem(LANGUAGE_STORAGE_KEY))
  );

  const setLanguage = useCallback((nextLanguage) => {
    const normalized = normalizeLanguage(nextLanguage);
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized);
    setLanguageState(normalized);
  }, []);

  useEffect(() => {
    let active = true;
    apiGet("/api/ui-settings/")
      .then((settings) => {
        if (active) setLanguage(settings.ui_language);
      })
      .catch(() => {
        // Keep the last known language when settings are temporarily unavailable.
      });
    return () => {
      active = false;
    };
  }, [setLanguage]);

  useEffect(() => {
    document.documentElement.lang = language;
    translateSubtree(document.body, language);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") {
          translateTextNode(mutation.target, language);
        } else if (mutation.type === "attributes") {
          translateAttributes(mutation.target, language);
        } else {
          mutation.addedNodes.forEach((node) => translateSubtree(node, language));
        }
      }
    });

    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: TRANSLATABLE_ATTRIBUTES,
    });

    return () => observer.disconnect();
  }, [language]);

  const value = useMemo(
    () => ({
      language,
      locale: language === "es" ? "es-MX" : "en-US",
      setLanguage,
      t: (text) => translateText(text, language),
    }),
    [language, setLanguage]
  );

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  return useContext(LanguageContext);
}
