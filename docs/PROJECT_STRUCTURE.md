# Project Structure

Root directory is reserved for stable entry points and project metadata.

## Root Entries

- `cfquant_web_server.py`: local Web dashboard entry.
- `cfquant_pipe_hub.py`: named-pipe hub entry.
- `start_cfquant.bat`, `stop_cfquant.bat`, `restart_cfquant.bat`: Windows service scripts.
- `启动cfquant.bat`, `停止cfquant.bat`, `重启cfquant.bat`: Chinese aliases for the Windows service scripts.
- `README.md`, `requirements.txt`, `pyproject.toml`, `.gitignore`, `AGENTS.md`: project metadata.

## Source Directories

- `cfquant/`: external Python compatibility layer and bridge client code.
- `LTtx/`: LTtx server and compatibility files.
- `qmt_scripts/`: QMT-side entry scripts.
- `web_dashboard/`: local Web dashboard frontend assets.
- `scripts/`: development and diagnostic scripts.
- `docs/`: project documentation and documentation assets.

## Local Runtime Directories

Local runtime files should be kept out of Git and placed under `runtime/` or `log/`.

- `runtime/config/`: local JSON runtime configuration.
- `runtime/db/`: local SQLite databases.
- `runtime/status/`: generated status snapshots.
- `runtime/lttx/`: LTtx file transfer and DataFrame caches.
- `runtime/reports/`: generated diagnostic reports.
- `runtime/media/`: local generated media and article/video assets.
- `runtime/cache/`: generated caches moved out of the root.
- `log/`: local service logs.

Legacy root directories such as `file_data/`, `dataframe_data/`, `reports/`, `pic/`, `log_data/`, and `tx_log/` are ignored by Git in case old tools recreate them.
