export const featureDefinitions = [
  {
    key: "notebook",
    setting: "notebook_enabled",
    labels: { en: "Notebook", es: "Cuaderno de laboratorio" },
    descriptions: {
      en: "Collaborative experiment records, templates, revisions, and review.",
      es: "Registros colaborativos de experimentos, plantillas, revisiones y aprobación.",
    },
  },
  {
    key: "registry",
    setting: "registry_enabled",
    labels: { en: "Registry", es: "Registro biológico" },
    descriptions: {
      en: "Versioned biological entities, aliases, schemas, and relationships.",
      es: "Entidades biológicas versionadas, alias, esquemas y relaciones.",
    },
  },
  {
    key: "studies",
    setting: "studies_enabled",
    labels: { en: "Studies", es: "Estudios" },
    descriptions: {
      en: "Preclinical study design, schedules, execution, and data capture.",
      es: "Diseño, programación, ejecución y captura de datos de estudios preclínicos.",
    },
  },
  {
    key: "insight",
    setting: "insight_enabled",
    labels: { en: "Insight", es: "Analítica" },
    descriptions: {
      en: "Saved dashboards, reusable metrics, analytics, and shared reports.",
      es: "Paneles guardados, métricas reutilizables, analítica e informes compartidos.",
    },
  },
];

export const featureFlagCopy = {
  heading: { en: "Feature Flags", es: "Indicadores de funciones" },
  developmentNotice: {
    en: "Disabled by default while new modules are developed and validated.",
    es: "Desactivadas de forma predeterminada mientras se desarrollan y validan los módulos nuevos.",
  },
};

export const v026ModuleCopy = {
  registry: {
    en: "Configurable biological registry with immutable versions, duplicate detection, review, and physical links.",
    es: "Registro biológico configurable con versiones inmutables, detección de duplicados, revisión y vínculos físicos.",
  },
  sequenceRevisions: {
    en: "Immutable DNA, RNA, and protein sequence revisions with visual comparison and restore.",
    es: "Revisiones inmutables de secuencias de ADN, ARN y proteínas con comparación visual y restauración.",
  },
  molecularTools: {
    en: "Molecular calculations, ORFs, primer properties, restriction analysis, and virtual digests.",
    es: "Cálculos moleculares, ORF, propiedades de cebadores, análisis de restricción y digestiones virtuales.",
  },
  interchange: {
    en: "FASTA and GenBank import and export with preserved annotations.",
    es: "Importación y exportación FASTA y GenBank con anotaciones conservadas.",
  },
  assembly: {
    en: "Registered-part construct assembly and reusable feature libraries.",
    es: "Ensamblaje de constructos con partes registradas y bibliotecas reutilizables de características.",
  },
};

export function featureIsEnabled(flags, key) {
  return Boolean(flags?.[key]);
}
