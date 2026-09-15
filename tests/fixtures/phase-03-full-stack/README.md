# Phase 3 full-stack acceptance project

This disposable fixture is the runnable real-profile target: a browser frontend,
a Python API, validated item creation, SQLite persistence, and a Playwright user
journey. Version 1.1 is the follow-on change: an item can be completed without
regressing creation, validation, persistence, or reload behavior.

```text
npm ci --ignore-scripts
npm run build
npm test
npm run test:browser
```

Dependency preparation is intentionally separate from all three verification
commands. Runtime state stays under `.tmp/` and is never source evidence.
