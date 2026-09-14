# Subir a GitHub y desplegar en Streamlit Community Cloud

## 1. Crear el repositorio en GitHub

Crear un repositorio vacío, por ejemplo:

```text
laboratorio-futbol-argentino
```

No hace falta agregar README, `.gitignore` ni licencia desde GitHub porque este paquete ya contiene los archivos necesarios.

## 2. Subir este paquete desde la terminal

Ubicarse dentro de la carpeta del proyecto y ejecutar:

```bash
git init
git add .
git commit -m "Primera version del laboratorio"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/laboratorio-futbol-argentino.git
git push -u origin main
```

Si GitHub pide autenticación, usar el método de autenticación configurado en la cuenta (navegador, GitHub CLI o token personal).

## 3. Verificar GitHub Actions

En GitHub abrir **Actions**. El workflow `CI` debe terminar en verde.

## 4. Crear la app en Streamlit Community Cloud

1. Ingresar a Streamlit Community Cloud con GitHub.
2. Elegir **Create app**.
3. Seleccionar el repositorio.
4. Branch: `main`.
5. Main file path: `app.py`.
6. En **Advanced settings**, seleccionar **Python 3.12**.
7. No cargar secrets: esta versión no necesita ninguno.
8. Presionar **Deploy**.

## 5. Actualizaciones posteriores

Cada vez que se modifica código:

```bash
git add .
git commit -m "Descripcion del cambio"
git push
```

Streamlit Community Cloud detecta el nuevo commit y actualiza la aplicación.

## Archivos que no deben subirse

El `.gitignore` ya excluye:

- `.env`;
- `.streamlit/secrets.toml`;
- entornos virtuales;
- caches de Python y pytest;
- snapshots temporales de scraping en `data/live/*.json`.

## Si falla el scraping

La app intenta conservar datos conocidos y usar fallbacks. Revisar **Calidad de datos** antes de utilizar una actualización editorialmente.

El parser principal está en:

```text
football_lab/data/scraping_provider.py
```
