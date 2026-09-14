# Bootstrap de resultados

`lpf_clausura_2026_20260914.json` es una red de seguridad para que el laboratorio no vuelva a la base histórica de 49 partidos cuando una web responde parcialmente o bloquea a Streamlit Cloud.

- Fuente de origen: nota viva de fixture/resultados de TyC Sports.
- Foto: 14/09/2026 antes de los tres partidos del lunes.
- Incluye: 132 resultados terminados (Fechas 1 a 8 completas + 12 partidos de Fecha 9) y programación con fecha/hora para el cierre de la Fecha 9 y las Fechas 10 y 11.
- Cada cruce fue validado contra `LPF_FIXTURE` antes de generar el JSON.
- Los resultados históricos sin hora publicada se guardan a las 23:59 del día para mantener una política conservadora contra data leakage en partidos del mismo día.

El bootstrap no sustituye al scraping. En cada ejecución, TyC Sports, FutbolArgentino y LPF oficial pueden reemplazar/completar estos registros con información más nueva. Si el bootstrap envejece y no hay una fuente web reciente, Calidad de datos vuelve a advertir/bloquear la foto actual.
