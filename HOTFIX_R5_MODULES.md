# Hotfix R5 - Streamlit Cloud

Este hotfix corrige el error:

```text
ModuleNotFoundError: No module named 'football_lab.release'
```

## Qué cambia

R5 no depende de archivos nuevos para arrancar:

- `APP_BUILD_ID`, `APP_BUILD_LABEL` y `MIN_VERIFIED_FINISHED` viven en `football_lab/config.py`.
- El respaldo editorial de 132 resultados terminados está embebido en `football_lab/data/scraping_provider.py`.
- `app.py` y `football_lab/ui/pages.py` importan el build desde `football_lab.config`.
- No se necesita `football_lab/release.py`.
- No se necesita `football_lab/data/bootstrap_seed_20260914.py`.

## Archivos que hay que reemplazar

Reemplazá exactamente estos cuatro archivos en el repositorio:

```text
app.py
football_lab/config.py
football_lab/data/scraping_provider.py
football_lab/ui/pages.py
```

Después:

```bash
git add -A
git commit -m "Hotfix R5 Streamlit autocontenido"
git push origin main
```

Al iniciar la app debe verse en la barra lateral:

```text
Build 2026.09.14-f9-r5 · Fecha 9 · hotfix autocontenido
```

## Validación

La suite fue ejecutada sin `football_lab/release.py` ni `football_lab/data/bootstrap_seed_20260914.py`:

```text
308 passed
```
