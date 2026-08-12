import { execSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(here, "..");
const repoRoot = resolve(frontendRoot, "..");
const versionOutput = resolve(frontendRoot, "src", "version.js");
const rootVersionFile = resolve(repoRoot, "VERSION");

function run(command) {
  try {
    return execSync(command, {
      cwd: repoRoot,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
  } catch {
    return "";
  }
}

function readCurrentFrontendVersion() {
  if (!existsSync(versionOutput)) return "";

  const current = readFileSync(versionOutput, "utf8");
  const match = current.match(/OPENLIMS_VERSION\s*=\s*["']([^"']+)["']/);

  return match ? match[1] : "";
}

let version =
  process.env.VITE_OPENLIMS_VERSION ||
  (existsSync(rootVersionFile) ? readFileSync(rootVersionFile, "utf8").trim() : "") ||
  run("git describe --tags --abbrev=0") ||
  readCurrentFrontendVersion() ||
  "development";

mkdirSync(dirname(versionOutput), { recursive: true });

writeFileSync(
  versionOutput,
  `export const OPENLIMS_VERSION = ${JSON.stringify(version)};\n`,
);

if (existsSync(resolve(repoRoot, ".git"))) {
  writeFileSync(rootVersionFile, `${version}\n`);
}

console.log(`OpenLIMS version: ${version}`);
