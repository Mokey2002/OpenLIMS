const MAX_MESSAGES = 100;

export function flattenValidationErrors(data) {
  const fields = Object.create(null), general = [];
  let count = 0;
  function walk(value, path = "", depth = 0) {
    if (count >= MAX_MESSAGES || depth > 8) return;
    if (typeof value === "string") {
      if (!value.trim()) return;
      const message = value.slice(0, 1500);
      if (!path || /(^|\.)(non_field_errors|detail|message|error)$/.test(path)) general.push(message);
      else (fields[path] ||= []).push(message);
      count++;
    } else if (Array.isArray(value)) {
      value.forEach((item, index) => walk(item, item && typeof item === "object" ? `${path}.${index}`.replace(/^\./, "") : path, depth + 1));
    } else if (value && typeof value === "object") {
      for (const [key, item] of Object.entries(value)) {
        if (["__proto__", "constructor", "prototype"].includes(key)) continue;
        walk(item, path ? `${path}.${key}` : key, depth + 1);
      }
    }
  }
  walk(data);
  return { fields, general };
}

export class ApiError extends Error {
  constructor(status, data) {
    const parsed = status >= 400 && status < 500 ? flattenValidationErrors(data) : { fields: {}, general: [] };
    const messages = {
      0: "Could not confirm the request. Check your connection and whether the record was saved before trying again.",
      400: "Check the submitted values and try again.",
      401: "Session expired. Please log in again.",
      403: "This action is not permitted with your current access. Check your profile or ask an administrator.",
      404: "This record is unavailable or you no longer have access.",
      409: "This record changed. Review its latest version before trying again.",
      413: "This upload is too large. Choose a smaller file.",
      422: "Check the submitted values and try again.",
      429: "Too many requests. Wait before trying again.",
    };
    const fieldSummary = Object.entries(parsed.fields).slice(0, 3).map(([key, errors]) => `${fieldLabel(key)}: ${errors.join(" ")}`).join(" ");
    super(parsed.general[0] || fieldSummary || messages[status] || "OpenLIMS could not complete the request. Please try again later.");
    this.name = "ApiError";
    this.status = status;
    this.fieldErrors = parsed.fields;
    this.generalErrors = parsed.general;
  }
}

export async function responseError(response) {
  let data;
  try { data = JSON.parse(await response.text()); } catch { data = null; }
  return new ApiError(response.status, data);
}

export function fieldLabel(path) {
  const key = path.split(".").at(-1).replace(/_/g, " ");
  return key.replace(/^./, letter => letter.toUpperCase()).replace(/\bid\b/gi, "ID");
}

export function controlValidationMessage(control, t = value => value) {
  if (!control.willValidate) return "";
  const value = control.value || "", validity = control.validity;
  if (validity.valueMissing || (control.required && !value.trim())) return t("Enter or select a value.");
  if (validity.typeMismatch && control.type === "email") return t("Enter a valid email address, such as name@example.org.");
  if (validity.typeMismatch && control.type === "url") return t("Enter a complete URL, such as https://example.org.");
  if (validity.badInput) return t("Enter a valid number.");
  if (value && control.minLength > 0 && value.trim().length < control.minLength) return t("Use at least {count} characters.").replace("{count}", control.minLength);
  if (validity.rangeUnderflow) return t("Enter a value of at least {value}.").replace("{value}", control.min);
  if (validity.rangeOverflow) return t("Enter a value no greater than {value}.").replace("{value}", control.max);
  if (validity.stepMismatch) return t("Use the required increment for this value.");
  if (validity.patternMismatch) return t("Use the format described below this field.");
  if (validity.tooLong) return t("Shorten this value to the stated limit.");
  return validity.valid ? "" : t("Check this value and try again.");
}
