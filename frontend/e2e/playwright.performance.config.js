const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./performance",
  workers: 1,
  retries: 0,
  timeout: 600000,
  reporter: [["list"], ["json", { outputFile: "performance-results/results.json" }]],
  outputDir: "performance-results/artifacts",
  use: { baseURL: process.env.OPENLIMS_E2E_BASE_URL || "http://127.0.0.1:5173", trace: "retain-on-failure" },
});
