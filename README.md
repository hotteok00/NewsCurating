# NewsCurating

Weekly news curation pipeline that crawls configured sources, preprocesses articles, and renders Markdown/HTML/PDF reports.

## Fresh Clone Dependency Restore

Use a project-local virtual environment. The repository does not rely on globally installed Python packages.

```bash
cd ~/NewsCurating
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Run the pipeline through the wrapper, which automatically prefers `.venv/bin/python` when the virtual environment exists:

```bash
./run_curate.sh
```

Run tests:

```bash
.venv/bin/pytest tests
```

## Delete Safety

- `.venv`, generated reports, logs, crawled data, pytest cache, Python bytecode, and Claude local settings are ignored by git.
- Deleting the project directory removes project-local caches and generated outputs.
- Re-cloning plus the restore commands above is enough to recover dependencies.
- Generated reports/logs are intentionally not preserved unless copied elsewhere before deletion.
