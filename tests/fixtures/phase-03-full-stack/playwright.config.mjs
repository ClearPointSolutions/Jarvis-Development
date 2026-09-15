import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:8765" },
  webServer: {
    command: "python api/app.py",
    url: "http://127.0.0.1:8765",
    reuseExistingServer: false,
    env: {
      ACCEPTANCE_DATABASE: ".tmp/browser.sqlite3",
      ACCEPTANCE_RESET: "1",
    },
  },
});
