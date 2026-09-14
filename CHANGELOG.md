
## 2026-09-14 - Corrección de cobertura web y próximos partidos

- FutbolArgentino: se prioriza `/primera-division/resultados` sobre la portada parcial del torneo.
- El scraper ya no acepta una página por superar un umbral fijo de 40 partidos: contrasta la cobertura con los PJ de la tabla cuando están disponibles.
- LPF oficial: el parser de agendas preserva líneas separadas por `<br>`, por lo que recupera fecha y hora de las programaciones publicadas en WordPress.
- Próximos partidos: se descartan huecos viejos sin fecha de jornadas anteriores a la última jornada con resultados y partidos programados con fecha claramente vencida.
- Suite: 302 tests OK.

## 2026-09-14 · Hotfix cobertura Fecha 9

- TyC Sports pasa a ser segunda fuente troncal de fixture/resultados, independiente de FutbolArgentino.
- FutbolArgentino queda como refresco complementario/live y LPF oficial como fuente de agenda/contraste.
- Nuevo parser para la nota viva de TyC: resultados históricos con fecha y programación actual/futura con hora.
- Alias ampliados para River, Racing, Gimnasia (Mza.) e Independiente Rivadavia Mza.
- Inicio muestra Fecha actual, cobertura esperada, resultados fechados y una guía de uso.
- Calidad de datos muestra el aporte de cada fuente por separado.
- Mensajes de bloqueo ahora explican exactamente cuántos resultados faltan.
