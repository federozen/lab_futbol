# Validación del paquete GitHub + Streamlit

Fecha: 14/09/2026.

## Estado

- Suite completa: **302 tests OK**.
- El repositorio compila y la capa de servicios funciona sin Opta.
- El modo web usa scraping HTML público con validación contra el fixture canónico.

## Corrección aplicada tras el primer deploy

La primera ejecución en Streamlit mostró 91 resultados finales, 0 resultados fechados y partidos de Fecha 4 como próximos. Se detectaron dos causas:

1. El proveedor consultaba primero la portada del Clausura y podía detenerse al superar 40 partidos, aunque esa portada fuera una ventana parcial del historial.
2. Las agendas de LPF pueden venir en un único párrafo de WordPress con saltos `<br>`; el parser anterior aplastaba esas líneas y perdía fecha/hora.

La versión actual:

- consulta primero la página dedicada de resultados de FutbolArgentino;
- usa la tabla pública como control de cantidad de partidos jugados cuando está disponible;
- sigue buscando otras variantes si la cobertura no explica esa tabla;
- parsea agendas LPF conservando los saltos de línea;
- evita mostrar como próximos huecos viejos sin fecha de jornadas ya superadas.

## Limitaciones que siguen siendo deliberadas

- xG, PPDA, eventos y jugadores no se inventan: quedan no disponibles hasta contar con una fuente que los entregue.
- Si las fuentes web quedan parciales o contradictorias, Calidad de datos bloquea la interpretación como foto actual.
- La snapshot local de Streamlit es un respaldo operativo, no una base persistente garantizada entre redeploys.
