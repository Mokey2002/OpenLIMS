const alphabets = {
  DNA: /^[ACGTRYSWKMBDHVN]+$/,
  RNA: /^[ACGURYSWKMBDHVN]+$/,
  PROTEIN: /^[ACDEFGHIKLMNPQRSTVWYBXZJUO*]+$/,
};

export function parseSingleSequence(text, type) {
  const lines = String(text).replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  const headers = lines.filter((line) => line.trim().startsWith(">"));
  if (headers.length > 1) throw new Error("Import one sequence at a time. Use Imports for multi-record FASTA files.");
  if (headers.length && !lines[0].trim().startsWith(">")) throw new Error("The FASTA header must be the first line.");
  const name = headers.length ? lines.shift().trim().slice(1).trim() : "";
  const sequence = lines.join("").replace(/\s/g, "").toUpperCase();
  if (!sequence) throw new Error("The sequence file is empty.");
  if (!alphabets[type]?.test(sequence)) throw new Error("The file contains symbols that do not match the selected sequence type.");
  return { name, sequence };
}

export function selectedSequence(sequence, selection) {
  const start = Number(selection?.start);
  const end = Number(selection?.end);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > sequence.length || start >= end) return "";
  return sequence.slice(start, end);
}
