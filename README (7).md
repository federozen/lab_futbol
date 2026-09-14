# Pruebas

Validación por **fuerza bruta** de los motores exactos: en ligas chicas se
enumeran todos los desenlaces posibles y se comparan, resultado por resultado,
contra lo que dicen los solucionadores. Es la evidencia de que "los números
siempre salen de Python y están validados".

La suite actual contiene **274 pruebas**.

| Archivo | Qué cubre |
| --- | --- |
| `test_lpf_scenarios.py` | Motor MILP: `can_qualify` / `can_fail`, rangos de puesto, puesto exacto por puntos sin desempate, escalera de puntos (`point_ladder`) y escenarios gana/empata/pierde. |
| `test_rank_points_simulation.py` | Escenarios por puesto: la simulación refactorizada conserva exactamente las posiciones históricas y devuelve los puntos de las mismas corridas para calcular distribuciones condicionadas. |
| `test_lpf_exact.py` | Garantías conservadoras: la línea de garantía y el piso por promedios **nunca declaran una garantía falsa** y nunca piden menos que la garantía exacta real. |
| `test_lpf_text.py` | Utilidades de texto: normalización sin acentos y detección de equipos. |
| `test_lpf_intents.py` | Ruteo de intención del chat: consultas → `{"intent": ...}`. |
| `test_lpf_clubs.py` | Canonicalización de clubes: alias y variantes → nombre canónico. |
| `test_lpf_parsers.py` | Parsers de tablas pegadas: listas, promedios, fixture y Anual. |
| `test_lpf_averages.py` | Promedios: formatos legacy/JSON, aliases, separación previas→totales y uso de PJ de la Tabla Anual en vez de PJ sólo del Clausura. |
| `test_lpf_preview.py` | Previa por equipo: módulo puro, normalización de objetivo, tabla exportable, descenso explícito y wrapper Streamlit reducido a adaptador. |
| `test_lpf_state.py` | Estado canónico: constructor/revalidador puros sin Streamlit, prioridad de Apertura, migración de sesiones, derivación y alertas de procedencia. |
| `test_lpf_loading.py` | Preparación de carga sin I/O: canonicalización de resultados, carga offline, actualización automática, avance de standings, reconstrucción anual y rechazo de fotos insuficientes. |
| `test_lpf_provider_adapters.py` | Fixtures locales de ESPN/FutbolArgentino.com: standings, zonas, scoreboards, estados, deduplicación y metadatos sin red. |
| `test_lpf_http.py` | Transporte HTTP con `requests` simulado; incluye la ventana multi-request de scoreboards ESPN y la secuencia de páginas de resultados de FutbolArgentino.com (cache-busters y fallos parciales) y verifica que no mezcle parsing ni Streamlit. |
| `test_competition_html_adapters.py` | Fixtures HTML genéricos: tabla, una rueda e ida/vuelta; parsers sin red y wrappers finos en Streamlit. |
| `test_lpf_services.py` | Contrato JSON-safe: cálculos individuales, foto canónica, batch de consultas, descenso combinado, serialización, errores y versión compartida. |
| `test_lpf_standings.py` | Motor puro de tabla: estadísticas, desempates configurables, mano a mano, fair play/ranking, posiciones y clasificador in/out/pelea. |
| `test_lpf_derive.py` | Derivación: reconstrucción del Apertura e inferencia determinista. |
| `test_lpf_reconcile.py` | Reconciliación: nóminas conocidas, estadísticas, merge sin duplicar, encaje en zonas. |
| `test_data_pipeline.py` | Integridad del flujo: fixture ↔ nóminas, 16 partidos por equipo, datos → tabla y pisos. |
| `test_lpf_pisos.py` | Puntos por objetivo: mínimo posible y garantía por objetivo, invariantes y combinación de tablas en el descenso. |
| `test_lpf_table_backup.py` | Respaldo de tablas: payload JSON, escritura atómica, prioridad sesión→disco, vencimiento, formato legacy y recuperación sin Streamlit. |
| `test_lpf_runtime.py` | Compatibilidad de deploy: nivel requerido por el archivo principal, módulos sincronizados, detección de un archivo viejo y chequeo antes de los imports sensibles. |
| `test_release_tools.py` | Guard de release: versión/runtime/metadata sincronizados y paquetes incremental/sync que incluyen siempre el núcleo crítico completo. |
| `test_ci_workflow.py` | CI de GitHub: push/PR, permisos mínimos y ejecución obligatoria de pytest, Ruff y release guard. |
| `test_lpf_schedule.py` | Agenda/Previa: prioridad de fuentes horarias, compatibilidad legacy, jornada vs. postergados, orden por calendario real, agrupación por día y hora argentina. |
| `test_lpf_result_updates.py` | Aplicación manual de resultados: no muta la entrada, ignora duplicados/no pendientes, calcula cambios de posiciones y conserva equivalencia con 3.8.21. |
| `test_lpf_form.py` | Forma, rachas y fuerza regularizada: casos dirigidos, equivalencia aleatoria con 3.8.25 y ausencia de dependencias de Streamlit/red. |
| `test_lpf_simulation.py` | Contexto y Monte Carlo puros: Anual/cupos explícitos, posición/puntos por zona, suma de puntos, objetivos, reproducibilidad y ausencia de Streamlit/red. |
| `test_lpf_probability_audit.py` | Auditoría probabilística con foto real de Fecha 4: kernel único, sensibilidad, backtest, interzonales, 8 cupos por zona, muestra condicionada y consistencia entre proyecciones. |
| `test_lpf_qualification.py` | Tabla Anual, plazas y contexto de copas: prioridad Apertura/Anual directa, reordenamientos, clasificados fijos, vivos de Copa Argentina, etiqueta de actualización y equivalencia histórica. |

Convenio de desempates (verificado en las pruebas):

- Mínimo posible / mejor puesto / `can_qualify`: desempate **a favor** (sólo
  cuentan los rivales estrictamente por encima).
- Garantía / peor puesto / `can_fail`: desempate **en contra** (cuentan los
  rivales iguales o por encima).

## Ejecutar

```bash
pip install -r requirements.txt
pip install pytest
python -m pytest -q
```

- `test_lpf_table_selection.py`: prioridad/fallback puro de zonas y Tabla Anual entre proveedores y respaldos.

La extracción de `lpf_simulation.py` se verificó además contra 3.8.26 en 500 casos de zona + 500 wrappers, 800 matrices globales y 900 máscaras de objetivos. En 3.8.28, el constructor de contexto se comparó además contra `_lpf_ctx` de 3.8.27 en 500 estados con fallbacks de Apertura/Anual/Copa Argentina.

En 3.8.29 se congeló una foto real del Clausura 2026 al 11/08 20:28 ART para auditar 59 partidos completados, comparar el modelo canónico contra el camino editorial legado y verificar interzonales/muestras condicionadas. No se recalibraron parámetros con esa muestra.

En 3.8.35 se agregaron regresiones de navegación/UI que fijan que **Chat libre** no vuelva a aparecer como workspace independiente y que el tablero de **Últimas fechas** reutilice Previa, escalera exacta y motor de la otra cancha en vez de duplicar fórmulas.

En 3.8.36 se agregaron regresiones para que `point_ladder` ignore partidos totalmente ajenos a la tabla sin perder interzonales; así Puntos por objetivo, Escenarios y Radar usan el mismo conjunto matemáticamente relevante en el tramo final.
