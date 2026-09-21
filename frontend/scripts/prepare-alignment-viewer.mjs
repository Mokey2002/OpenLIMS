import { mkdir, copyFile } from 'node:fs/promises';
const source = new URL('../node_modules/@teselagen/ove/', import.meta.url);
const destination = new URL('../public/vendor/ove/', import.meta.url);
await mkdir(destination, { recursive: true });
for (const file of ['index.umd.js', 'ove.css']) {
  await copyFile(new URL(file, source), new URL(file, destination));
}
await copyFile(new URL('../public/vendor/TESELAGEN-LICENSE.txt', import.meta.url), new URL('LICENSE.txt', destination));
