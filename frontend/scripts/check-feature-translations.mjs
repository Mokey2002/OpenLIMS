import {
  featureDefinitions,
  featureFlagCopy,
  v026ModuleCopy,
} from "../src/featureFlags.js";

const requiredLanguages = ["en", "es"];
const requiredFields = ["labels", "descriptions"];
const errors = [];

for (const feature of featureDefinitions) {
  if (!feature.key || !feature.setting) {
    errors.push("Every feature requires a key and backend setting name.");
  }
  for (const field of requiredFields) {
    for (const language of requiredLanguages) {
      if (!String(feature[field]?.[language] || "").trim()) {
        errors.push(`${feature.key || "unknown"}.${field}.${language} is required.`);
      }
    }
  }
}

if (new Set(featureDefinitions.map((item) => item.key)).size !== featureDefinitions.length) {
  errors.push("Feature keys must be unique.");
}

for (const [key, translations] of Object.entries(featureFlagCopy)) {
  for (const language of requiredLanguages) {
    if (!String(translations?.[language] || "").trim()) {
      errors.push(`featureFlagCopy.${key}.${language} is required.`);
    }
  }
}

for (const [key, translations] of Object.entries(v026ModuleCopy)) {
  for (const language of requiredLanguages) {
    if (!String(translations?.[language] || "").trim()) {
      errors.push(`v026ModuleCopy.${key}.${language} is required.`);
    }
  }
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log(`Validated bilingual metadata for ${featureDefinitions.length} features.`);
