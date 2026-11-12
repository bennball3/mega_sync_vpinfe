# CLAUDE.md

A VPinFE 3 extension (`mega_sync_vpinfe`) that installs table zips from MEGA via MEGAcmd. The
folder name must equal `name` in `extension.json`. Modules import only `common.extensions.contract`
from VPinFE, so they can't run standalone.

## Working rules

- **The repo is public.** Keep personal paths, account emails, MEGA folder contents, config and
  logs out of it. `cache/` is gitignored; downloads go there.
- **Always ask before committing or pushing**, every time.
- No test suite. Check with `python -m py_compile *.py`, parse `i18n/en.json`, and run
  `vpinfe.exe --check-extension .`.
- Put user-facing text in `i18n/en.json`. Keep README style like `vpc_vpinfe` (second person,
  active voice, no em dashes).

## Architecture

- `mega.py`: stateless MEGAclient wrapper (no console window, timeouts).
- `sync.py`: the job. The MEGA folder is the record of what is waiting; `history.py`
  (`cache/history.json`) is the lasting list of imported/rejected zips, shown even after the
  user deletes them from MEGA.
- `screens.py`: Sync Now action, MEGA Sync list, Needs You rows.
- `settings.py`: fields and the `check` that refuses a non-MEGAcmd exe.
- `__init__.py`: wiring and the startup timer (skipped under `--check-extension`).
