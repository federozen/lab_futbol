# Validación de la entrega con scraping público

## Tests

Comando ejecutado:

```bash
pytest -q
```

Resultado:

```text
300 passed
```

Incluye la suite heredada de la Calculadora LPF y tests nuevos de:

- data leakage por fecha y por jornada;
- Elo con cronología mixta protegida;
- Colley y PageRank;
- proveedor offline;
- proveedor de scraping público;
- parser de fechas/horas de la agenda oficial LPF (`18.00`, `18 de septiembre`);
- descubrimiento de notas de programación LPF;
- reconciliación entre scraping, snapshot y base incluida;
- calidad de datos y servicios JSON-safe.

## Flujo operativo validado

El proveedor `PublicScrapingProvider`:

1. intenta resultados/horarios públicos de FutbolArgentino.com;
2. intenta tabla de posiciones como control de cobertura;
3. descubre agendas recientes en la portada de Primera de la LPF y parsea fecha/hora;
4. consulta marcadores oficiales adicionales cuando la cobertura principal no alcanza;
5. reconcilia sin hacer retroceder resultados ya conocidos;
6. guarda una snapshot válida;
7. cae a snapshot/base incluida si la red falla.

Los tests usan HTML controlado e inyección del transporte para probar este flujo sin depender de Internet durante CI.

## Validación de fuentes actuales

El 14/09/2026 se verificó mediante búsqueda web que FutbolArgentino.com mantiene una página de resultados del Torneo Clausura 2026 con fechas, horarios, marcadores y estados, y que la LPF oficial publica la programación de las fechas 8 a 11. El código no depende de esos textos exactos: filtra los partidos contra el fixture canónico.

## Streamlit

Este runtime de construcción no tiene `streamlit` instalado y no puede descargar paquetes por `pip`, por lo que no fue posible levantar literalmente `streamlit run app.py` aquí.

Se verificaron:

```text
python -m compileall -q football_lab app.py lpf_fixture_sources.py lpf_reconcile.py
pytest -q
```

`requirements.txt` declara `streamlit>=1.36`; Streamlit Community Cloud instalará la dependencia al desplegar el repositorio.
