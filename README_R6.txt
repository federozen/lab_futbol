HOTFIX R6 - UN SOLO ARCHIVO

Reemplazar UNICAMENTE app.py en la raiz del repositorio.
No hace falta tocar football_lab/config.py.

El app.py define e inyecta antes de cargar pages.py:
- APP_BUILD_ID
- APP_BUILD_LABEL
- MIN_VERIFIED_FINISHED

Build esperado en la barra lateral:
2026.09.14-f9-r6

Comandos:
git add app.py
git commit -m "Hotfix R6 arranque Streamlit"
git push origin main
