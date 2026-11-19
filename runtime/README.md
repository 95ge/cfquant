# Runtime Files

This directory is reserved for local runtime files and is not part of the source package.

- `config/`: local runtime configuration and encrypted credentials.
- `audit/`: isolated API Key operation audit database; not removed by ordinary log cleanup.
- `cache/`: local generated caches moved out of the project root.
- `db/`: local SQLite settings databases.
- `lttx/`: LTtx file transfer and DataFrame cache files.
- `media/`: local generated media, article assets, and video synthesis workspaces.
- `reports/`: generated latency reports and diagnostic outputs.
- `status/`: generated runtime status snapshots.
- `screenshots/`: temporary validation screenshots.

Only this README and `.gitkeep` placeholders should be committed.
