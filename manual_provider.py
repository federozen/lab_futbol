from __future__ import annotations

import pandas as pd

from football_lab.data.csv_provider import dataframe_to_dataset
from football_lab.models import ProviderDataset


class ManualProvider:
    provider_name = "manual"

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def load(self) -> ProviderDataset:
        return dataframe_to_dataset(pd.DataFrame(self.rows), provider_name=self.provider_name)
