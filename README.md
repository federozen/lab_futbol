# Laboratorio de fútbol argentino

Aplicación en **Python + Streamlit** para analizar el fútbol argentino a partir de la lógica y los datos de la Calculadora LPF.

La versión actual está preparada para funcionar **sin Opta y sin APIs pagas**. Por defecto intenta actualizar resultados y programación mediante scraping de fuentes públicas y conserva una base local como respaldo.

## Fuentes web actuales

La actualización sin APIs usa varias fuentes HTML en paralelo para no depender de un solo sitio:

- **TyC Sports**: columna vertebral alternativa para fixture/resultados y fechas.
- **FutbolArgentino.com**: resultados y estado actual, especialmente útil para refresco de la jornada.
- **Liga Profesional de Fútbol**: programación oficial cuando la agenda está publicada en su web.

Todos los cruces se validan contra el fixture canónico incluido. Una fuente parcial nunca borra un resultado ya conocido. En **Calidad de datos** se ve cuántos registros, finales y fechas aportó cada fuente.

## Qué incluye hoy

- actualización web por scraping público;
- fixture canónico del Clausura 2026 como lista blanca de partidos;
- base offline de respaldo;
- carga alternativa por CSV;
- forma reciente 3/5/10;
- rendimiento local/visitante;
- Elo, Colley y PageRank;
- comparación entre equipos y partidos;
- descanso/congestión cuando hay fechas reales disponibles;
- narrativas determinísticas;
- controles contra data leakage;
- página de calidad de datos;
- arquitectura preparada para xG, eventos, jugadores y Opta cuando exista una fuente adecuada.

Las métricas que necesitan información inexistente en la fuente actual se muestran como **“No disponible con la fuente actual”**. No se completan con datos inventados.

## Ejecutar localmente

Recomendado: **Python 3.12**.

```bash
python -m venv .venv
```

Activar el entorno:

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Instalar y ejecutar:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

## Fuente de datos

La barra lateral ofrece:

1. **Web · scraping público**: modo recomendado. Intenta recuperar resultados y programación desde fuentes públicas.
2. **Base incluida · offline**: respaldo local.
3. **CSV propio**: reemplaza temporalmente la fuente para la sesión.

El proveedor web está en:

```text
football_lab/data/scraping_provider.py
```

La adaptación de la Calculadora LPF está en:

```text
football_lab/data/calculator_adapter.py
```

El futuro adaptador de Opta está reservado en:

```text
football_lab/data/opta_adapter.py
```

## Controles editoriales

El sistema no considera automáticamente válida una tabla sólo porque pudo leerla. Compara cobertura, cantidad de resultados y, cuando hay datos suficientes, consistencia con posiciones publicadas.

Para evitar data leakage, un análisis de un partido sólo utiliza información anterior al partido. Cuando la fuente no aporta fecha exacta, el corte se hace por jornadas anteriores y no por resultados de la misma jornada.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

La entrega fue validada con **300 tests**.

## GitHub

El repositorio incluye `.gitignore` y GitHub Actions en:

```text
.github/workflows/ci.yml
```

Cada `push` o `pull request` instala dependencias, compila y corre los tests.

## Streamlit Community Cloud

El entrypoint es:

```text
app.py
```

No hay secretos obligatorios en esta versión. Ver `DEPLOY_STREAMLIT.md` para el procedimiento exacto.

## Estructura principal

```text
app.py
football_lab/
  data/
  feature_engineering/
  narratives/
  rankings/
  services/
  ui/
data/
  sample/
  live/
tests/
requirements.txt
.streamlit/config.toml
.github/workflows/ci.yml
```

## Importante sobre scraping

Las páginas web pueden cambiar HTML, bloquear solicitudes o devolver información parcial. Por eso el proyecto conserva fallbacks y controles de calidad. Un scraper que no encuentra datos no debe interpretarse como “no hubo partidos”.
