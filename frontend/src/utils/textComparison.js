const MAX_TEXT = 12000;
const MAX_CELLS = 250000;

export function comparisonText(value) {
  if (value === undefined) return "Not recorded";
  if (value === null) return "Not set";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(comparisonText).join("\n") : "Empty list";
  if (typeof value === "object") return Object.entries(value).map(([key, entry]) =>
    `${key.replaceAll("_", " ")}: ${comparisonText(entry)}`).join("\n") || "Empty object";
  return String(value);
}

function clip(value) {
  let text = value.slice(0, MAX_TEXT);
  const last = text.charCodeAt(text.length - 1);
  if (value.length > MAX_TEXT && last >= 0xd800 && last <= 0xdbff) text = text.slice(0, -1);
  return text;
}

export function compareText(before, after) {
  const originalBefore = String(before), originalAfter = String(after);
  const oldText = clip(originalBefore), newText = clip(originalAfter);
  const left = oldText.match(/\s+|[^\s]+/gu) || [], right = newText.match(/\s+|[^\s]+/gu) || [];
  const parts = [];
  const add = (type, text) => {
    if (!text) return;
    if (parts.at(-1)?.type === type) parts.at(-1).text += text;
    else parts.push({ type, text });
  };
  let prefix = 0;
  while (prefix < left.length && prefix < right.length && left[prefix] === right[prefix]) prefix++;
  let suffix = 0;
  while (suffix < left.length - prefix && suffix < right.length - prefix && left[left.length - 1 - suffix] === right[right.length - 1 - suffix]) suffix++;
  add("equal", left.slice(0, prefix).join(""));
  const a = left.slice(prefix, left.length - suffix), b = right.slice(prefix, right.length - suffix);
  const bounded = (a.length + 1) * (b.length + 1) > MAX_CELLS;
  if (bounded) {
    add("removed", a.join("")); add("added", b.join(""));
  } else {
    const width = b.length + 1, cells = new Uint32Array((a.length + 1) * width);
    for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) {
      cells[i * width + j] = a[i] === b[j] ? cells[(i + 1) * width + j + 1] + 1
        : Math.max(cells[(i + 1) * width + j], cells[i * width + j + 1]);
    }
    let i = 0, j = 0;
    while (i < a.length || j < b.length) {
      if (i < a.length && j < b.length && a[i] === b[j]) { add("equal", a[i]); i++; j++; }
      else if (j < b.length && (i === a.length || cells[i * width + j + 1] > cells[(i + 1) * width + j])) { add("added", b[j]); j++; }
      else { add("removed", a[i]); i++; }
    }
  }
  add("equal", suffix ? left.slice(left.length - suffix).join("") : "");
  return { before: parts.filter(part => part.type !== "added"), after: parts.filter(part => part.type !== "removed"),
    truncated: originalBefore.length !== oldText.length || originalAfter.length !== newText.length, coarse: bounded };
}
