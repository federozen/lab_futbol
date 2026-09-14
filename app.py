from __future__ import annotations

import pandas as pd
import streamlit as st

from football_lab.data.calculator_adapter import ExistingCalculatorProvider
from football_lab.data.csv_provider import DataFrameProvider
from football_lab.data.scraping_provider import PublicScrapingProvider
from football_lab.services.lab_service import LabService
from football_lab.ui.pages import PAGES, render_page


st.set_page_config(page_title="Laboratorio de fútbol argentino", page_icon="⚽", layout="wide")


@st.cache_resource(show_spinner=False)
def offline_service():
    return LabService(ExistingCalculatorProvider())


@st.cache_resource(ttl=900, show_spinner="Actualizando resultados y programación desde fuentes públicas...")
def web_service(refresh_token: int):
    # refresh_token forma parte de la clave de caché: el botón permite forzar un
    # nuevo scraping sin acoplar la capa de datos a Streamlit.
    _ = refresh_token
    return LabService(PublicScrapingProvider())


st.sidebar.title("Laboratorio")
st.sidebar.caption("Datos públicos · sin leakage · sin Opta obligatorio")

if "web_refresh_token" not in st.session_state:
    st.session_state.web_refresh_token = 0

source_mode = st.sidebar.radio(
    "Fuente de partidos",
    ["Web · scraping público", "Base incluida · offline"],
    index=0,
    help="El modo web usa HTML público de FutbolArgentino y LPF. Si falla, conserva la última snapshot válida y luego la base incluida.",
)

if source_mode.startswith("Web"):
    if st.sidebar.button("Actualizar ahora", use_container_width=True):
        st.session_state.web_refresh_token += 1
    try:
        service = web_service(st.session_state.web_refresh_token)
    except Exception as exc:
        st.sidebar.error(f"Falló el proveedor web: {exc}")
        service = offline_service()
else:
    service = offline_service()

st.sidebar.divider()
uploaded = st.sidebar.file_uploader(
    "Usar CSV propio en esta sesión",
    type=["csv"],
    help="Si cargás un CSV, reemplaza temporalmente al proveedor elegido. No modifica archivos del proyecto.",
)
if uploaded is not None:
    try:
        dataframe = pd.read_csv(uploaded)
        service = LabService(DataFrameProvider(dataframe, uploaded.name))
        st.sidebar.success("Usando el CSV cargado")
    except Exception as exc:
        st.sidebar.error(f"No pude usar el CSV: {exc}")

quality = service.data_quality()
if source_mode.startswith("Web") and uploaded is None:
    if quality.get("live_results_ok"):
        st.sidebar.success(f"Resultados web actualizados · {quality['finished_matches']} finales cargados")
    elif quality.get("snapshot_used"):
        st.sidebar.warning("Sin respuesta web: usando snapshot reciente")
    else:
        st.sidebar.error("Sin actualización web: usando respaldo local")
    if quality.get("updated_at"):
        stamp = pd.to_datetime(quality["updated_at"], errors="coerce", utc=True)
        if not pd.isna(stamp):
            stamp = stamp.tz_convert("America/Argentina/Buenos_Aires")
            st.sidebar.caption(f"Intento de actualización: {stamp.strftime('%d/%m/%Y %H:%M')} ARG")
        else:
            st.sidebar.caption(f"Intento de actualización: {quality['updated_at']}")

page = st.sidebar.radio("Sección", list(PAGES))
if quality["status"] == "blocked":
    st.error(
        "La foto actual tiene un bloqueo de calidad. Revisá 'Calidad de datos': la app conserva los datos, "
        "pero no conviene tratarlos como una actualización completa."
    )
render_page(page, service)
