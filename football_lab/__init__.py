"""Laboratorio de analisis del futbol argentino, sin dependencia de Opta."""

from .config import LabConfig
from .services.lab_service import LabService

__all__ = ["LabConfig", "LabService"]
