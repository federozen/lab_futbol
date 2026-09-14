from __future__ import annotations


class OptaProvider:
    """Punto de extension futuro. La V1 no requiere ni simula acceso a Opta."""

    provider_name = "opta"

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def load(self):
        raise RuntimeError(
            "Opta no esta configurado. La aplicacion funciona sin Opta; "
            "cuando exista acceso, este adaptador debe traducir la fuente a los modelos internos."
        )
