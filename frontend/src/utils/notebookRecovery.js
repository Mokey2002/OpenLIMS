const PREFIX = "openlims:notebook-draft:v1:";
const MAX_AGE = 7 * 24 * 60 * 60 * 1000;
const MAX_SIZE = 2 * 1024 * 1024;

export function notebookDraftKey(userId, experimentId) {
  return /^[1-9]\d*$/.test(String(userId)) && /^[a-zA-Z0-9-]{1,80}$/.test(String(experimentId)) ? `${PREFIX}${userId}:${experimentId}` : null;
}

export function draftContent(blocks, links) {
  return {
    blocks: blocks.map(({ block_type, data }) => ({ block_type, data })),
    links: links.map(({ entity_type, public_id, relation_type, label, version }) => ({ entity_type, public_id, relation_type, label, version })),
  };
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]));
  return value;
}

export function sameDraftContent(left, right) {
  const canonical = content => ({ blocks: content.blocks, links: content.links.map(({ entity_type, public_id, relation_type }) => ({ entity_type, public_id, relation_type })).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))) });
  return JSON.stringify(stable(canonical(left))) === JSON.stringify(stable(canonical(right)));
}

export function storeNotebookDraft(storage, key, content, baseRevision, now = Date.now()) {
  if (!key) return false;
  try {
    const value = JSON.stringify({ version: 1, savedAt: now, baseRevision, ...draftContent(content.blocks, content.links) });
    if (value.length > MAX_SIZE) return false;
    storage.setItem(key, value);
    return true;
  } catch { return false; }
}

export function readNotebookDraft(storage, key, now = Date.now()) {
  if (!key) return null;
  try {
    const text = storage.getItem(key);
    if (!text) return null;
    if (text.length > MAX_SIZE) { storage.removeItem(key); return null; }
    const draft = JSON.parse(text);
    if (draft?.version !== 1 || !Number.isFinite(draft.savedAt) || draft.savedAt > now + 60000 || now - draft.savedAt > MAX_AGE
      || typeof draft.baseRevision !== "string" || !Array.isArray(draft.blocks) || !Array.isArray(draft.links)
      || draft.blocks.some(block => !block || typeof block.block_type !== "string" || !block.data || typeof block.data !== "object" || Array.isArray(block.data))
      || draft.links.some(link => !link || typeof link.entity_type !== "string" || typeof link.public_id !== "string" || typeof link.relation_type !== "string")) {
      storage.removeItem(key); return null;
    }
    return draft;
  } catch { return null; }
}

export function removeNotebookDraft(storage, key) {
  try { if (key) storage.removeItem(key); } catch { /* Saving still works without browser storage. */ }
}

export function recoveryStorage() {
  try { return window.sessionStorage; } catch { return null; }
}
