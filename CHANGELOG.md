
## 2026-09-14 - Corrección de cobertura web y próximos partidos

- FutbolArgentino: se prioriza `/primera-division/resultados` sobre la portada parcial del torneo.
- El scraper ya no acepta una página por superar un umbral fijo de 40 partidos: contrasta la cobertura con los PJ de la tabla cuando están disponibles.
- LPF oficial: el parser de agendas preserva líneas separadas por `<br>`, por lo que recupera fecha y hora de las programaciones publicadas en WordPress.
- Próximos partidos: se descartan huecos viejos sin fecha de jornadas anteriores a la última jornada con resultados y partidos programados con fecha claramente vencida.
- Suite: 302 tests OK.
