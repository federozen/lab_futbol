# Hotfix Streamlit · Fecha 9

Build esperado: `2026.09.14-f9-r4`.

## Qué corrige

- Evita que la app vuelva a `91 terminados / 0 fechados` si el JSON auxiliar del bootstrap no fue copiado al repositorio.
- El historial verificado hasta antes de los tres partidos del lunes 14/09 queda embebido también en Python: 132 resultados, todos con fecha.
- Una fuente web parcial nunca puede reducir ese piso verificado.
- Agrega TyC Sports Estadísticas como fuente adicional para fecha/hora/estado de la jornada actual y la siguiente.
- Un resultado en vivo no se toma como final hasta que la fuente indique `Finalizado`.
- Muestra el identificador de build en la barra lateral y en Inicio para comprobar que Streamlit ejecuta el código correcto.
- Actualiza `use_container_width` al parámetro `width` de Streamlit 1.63.
- Fija `pyarrow==24.0.0` para evitar que Community Cloud lo reemplace durante el deploy.

## Cómo comprobar que subiste todos los archivos

Después del deploy, la barra lateral debe mostrar exactamente:

`Build 2026.09.14-f9-r4 · Fecha 9 · hotfix de cobertura`

En Inicio deben aparecer cinco métricas:

- Fecha actual
- Terminados
- Control esperado
- Resultados fechados
- Equipos

Si todavía aparece `Partidos cargados`, Streamlit está ejecutando la versión anterior de `football_lab/ui/pages.py`.

## Actualización recomendada del repositorio

No subas el ZIP como un archivo dentro de GitHub. Descomprimilo localmente y reemplazá el contenido del repositorio, incluidos todos los subdirectorios.

```bash
git clone URL_DE_TU_REPO lab_futbol
cd lab_futbol
# copiar aquí TODO el contenido descomprimido del hotfix, reemplazando archivos existentes
git status
git add -A
git commit -m "Hotfix cobertura Fecha 9"
git push origin main
```

Antes de hacer `git push`, `git status` debería mostrar, entre otros, cambios en:

- `app.py`
- `football_lab/ui/pages.py`
- `football_lab/data/scraping_provider.py`
- `football_lab/data/bootstrap_seed_20260914.py`
- `football_lab/release.py`
- `requirements.txt`

El archivo `data/bootstrap/lpf_clausura_2026_20260914.json` sigue incluido, pero ya no es un punto único de falla porque la misma base verificada está embebida en el paquete Python.
