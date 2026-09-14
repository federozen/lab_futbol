from __future__ import annotations

from typing import Protocol, runtime_checkable

from football_lab.models import ProviderDataset


@runtime_checkable
class DataProvider(Protocol):
    provider_name: str

    def load(self) -> ProviderDataset:
        ...
