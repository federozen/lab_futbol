"""Contrato común de entrada de datos para la calculadora LPF.

Los motores y ``lpf_services`` no deben conocer si la información vino de la UI
actual, de archivos CSV o de un futuro proveedor como Opta. Esta capa normaliza
todas esas fuentes a un único ``ProviderData`` JSON-safe, compatible con
``lpf_services.prepare_competition_snapshot``. Desde el contrato v2, la fuente
puede adjuntar ``provenance`` (timestamps, nombres de fuente y advertencias) sin
mezclar esos metadatos con la matemática del torneo.

La frontera queda así::

    fuente -> DataProvider -> ProviderData -> snapshot -> servicios/motores

Un proveedor futuro sólo tiene que implementar ``load() -> ProviderData``. No debe
importar Streamlit ni modificar reglas de competencia.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21
DATA_PROVIDER_CONTRACT_VERSION = "2"
SUPPORTED_DATA_PROVIDER_CONTRACT_VERSIONS = ("1", "2")

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
import csv
import io
import re
import unicodedata

from lpf_averages import previous_averages_json
from lpf_clubs import canon_base, canon_club


class ProviderError(ValueError):
    """Error estable de normalización de una fuente de datos."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = str(code)
        self.field = field

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.field:
            out["field"] = self.field
        return out


def _normalize_timestamp(value: object, *, field: str) -> str | None:
    """Normaliza timestamps de proveedor a ISO-8601 UTC sin inventar una hora."""
    if value in (None, ""):
        return None
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderError(
            "invalid_timestamp",
            f"'{field}' debe ser una fecha/hora ISO-8601.",
            field=field,
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _string_list(value: object, *, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProviderError("invalid_provenance", f"'{field}' debe ser una lista.", field=field)
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _normalize_provenance(raw: object) -> dict[str, object]:
    """Metadatos estáticos de la fuente; la edad se calcula al consultar el snapshot."""
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, Mapping):
        raise ProviderError("invalid_provenance", "'provenance' debe ser un objeto.", field="provenance")
    return {
        "source_name": str(raw.get("source_name") or "").strip(),
        "source_updated_at": _normalize_timestamp(
            raw.get("source_updated_at"), field="provenance.source_updated_at"
        ),
        "data_as_of": _normalize_timestamp(raw.get("data_as_of"), field="provenance.data_as_of"),
        "sources": _string_list(raw.get("sources"), field="provenance.sources"),
        "warnings": _string_list(raw.get("warnings"), field="provenance.warnings"),
    }


def _norm_label(value: object) -> str:
    text = str(value or "").strip().lower()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _simple_row(row: Mapping[str, object] | None) -> dict[str, int]:
    row = row or {}
    out = {
        "pts": int(row.get("pts", 0) or 0),
        "pj": int(row.get("pj", 0) or 0),
        "dg": int(row.get("dg", 0) or 0),
        "gf": int(row.get("gf", 0) or 0),
        "ga": int(row.get("ga", 0) or 0),
    }
    if row.get("source_pos") is not None:
        out["source_pos"] = int(row.get("source_pos") or 0)
    return out


def _normalize_table(raw: Mapping[str, object] | None) -> dict[str, dict[str, int]]:
    base = canon_base(raw or {})
    return {str(team): _simple_row(row) for team, row in base.items()}


def _normalize_zones(raw: Mapping[str, object] | None) -> dict[str, dict[str, dict[str, int]]]:
    if not isinstance(raw, Mapping) or not raw:
        raise ProviderError("missing_zones", "El proveedor debe entregar al menos una zona.", field="zones")
    out: dict[str, dict[str, dict[str, int]]] = {}
    for label, table in raw.items():
        if not isinstance(table, Mapping):
            raise ProviderError("invalid_zone", f"La zona '{label}' no es una tabla válida.", field="zones")
        normalized = _normalize_table(table)
        if not normalized:
            raise ProviderError("empty_zone", f"La zona '{label}' está vacía.", field="zones")
        out[str(label).strip() or str(label)] = normalized
    return out


def _normalize_played(raw: object) -> list[tuple[str, str, int, int]]:
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ProviderError("invalid_played", "'played' debe ser una lista de partidos.", field="played")
    out: list[tuple[str, str, int, int]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw):
        try:
            if isinstance(item, Mapping):
                home = item.get("home", item.get("l", item.get("local")))
                away = item.get("away", item.get("v", item.get("visitante")))
                hg = item.get("home_goals", item.get("gl", item.get("goles_local")))
                ag = item.get("away_goals", item.get("gv", item.get("goles_visitante")))
            else:
                home, away, hg, ag = item  # type: ignore[misc]
            home_name, away_name = canon_club(str(home)), canon_club(str(away))
            key = (home_name, away_name)
            if not home_name or not away_name or home_name == away_name:
                raise ValueError
            row = (home_name, away_name, int(hg), int(ag))
        except (TypeError, ValueError) as exc:
            raise ProviderError(
                "invalid_result",
                f"Resultado inválido en played[{index}].",
                field="played",
            ) from exc
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _normalize_fixture(raw: object, zones: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ProviderError("invalid_fixture", "'fixture' debe ser una lista.", field="fixture")
    membership = {
        str(team): str(label)
        for label, table in zones.items()
        for team in table
    }
    out: list[dict[str, object]] = []
    seen: set[tuple[int, str, str]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ProviderError("invalid_fixture_row", f"Fixture inválido en fila {index}.", field="fixture")
        try:
            round_no = int(item.get("f", item.get("round", item.get("fecha"))))
            home = canon_club(str(item.get("l", item.get("home", item.get("local", "")))))
            away = canon_club(str(item.get("v", item.get("away", item.get("visitante", "")))))
        except (TypeError, ValueError) as exc:
            raise ProviderError("invalid_fixture_row", f"Fixture inválido en fila {index}.", field="fixture") from exc
        if not home or not away or home == away or round_no <= 0:
            raise ProviderError("invalid_fixture_row", f"Fixture inválido en fila {index}.", field="fixture")
        key = (round_no, home, away)
        if key in seen:
            continue
        seen.add(key)
        inferred_zone = membership.get(home) if membership.get(home) == membership.get(away) else None
        game: dict[str, object] = {
            "f": round_no,
            "l": home,
            "v": away,
            "tipo": str(item.get("tipo") or ("zona" if inferred_zone else "inter")),
            "zona": item.get("zona") if item.get("zona") not in (None, "") else inferred_zone,
        }
        for key_name in ("date", "datetime", "fecha_hora", "kickoff", "status"):
            if item.get(key_name) not in (None, ""):
                game[key_name] = str(item.get(key_name))
        out.append(game)
    return out


def _normalize_qualification(raw: object) -> dict[str, object]:
    raw = raw if isinstance(raw, Mapping) else {}
    champions = raw.get("champions") if isinstance(raw.get("champions"), Mapping) else {}
    international = raw.get("international_champions") if isinstance(raw.get("international_champions"), Mapping) else {}

    def _club(value: object) -> str:
        text = str(value or "").strip()
        return canon_club(text) if text else ""

    return {
        "champions": {
            "apertura": _club(champions.get("apertura")),
            "clausura": _club(champions.get("clausura")),
            "copa_argentina": _club(champions.get("copa_argentina")),
        },
        "international_champions": {
            "libertadores": _club(international.get("libertadores")),
            "sudamericana": _club(international.get("sudamericana")),
        },
        "copa_argentina_replacement": _club(raw.get("copa_argentina_replacement")),
    }


def _normalize_rules(raw: object) -> dict[str, int]:
    raw = raw if isinstance(raw, Mapping) else {}
    defaults = {
        "annual_relegations": 1,
        "average_relegations": 1,
        "opening_rounds": 16,
        "playoff_cutoff": 8,
        "sudamericana_slots": 6,
    }
    out: dict[str, int] = {}
    for key, default in defaults.items():
        try:
            out[key] = int(raw.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ProviderError("invalid_rule", f"La regla '{key}' debe ser entera.", field=f"rules.{key}") from exc
    if out["opening_rounds"] <= 0 or min(
        out["annual_relegations"], out["average_relegations"], out["playoff_cutoff"], out["sudamericana_slots"]
    ) < 0:
        raise ProviderError("invalid_rule", "Las reglas tienen valores fuera de rango.", field="rules")
    return out


@dataclass(frozen=True)
class ProviderData:
    """Entrada canónica compartida por cualquier fuente de datos."""

    zones: dict[str, dict[str, dict[str, int]]]
    played: list[tuple[str, str, int, int]] = field(default_factory=list)
    annual: dict[str, dict[str, int]] = field(default_factory=dict)
    opening: dict[str, dict[str, int]] = field(default_factory=dict)
    previous_averages: dict[str, dict[str, int]] = field(default_factory=dict)
    fixture: list[dict[str, object]] = field(default_factory=list)
    qualification: dict[str, object] = field(default_factory=dict)
    rules: dict[str, int] = field(default_factory=dict)
    provenance: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "ProviderData":
        zones = _normalize_zones(payload.get("zones") if isinstance(payload, Mapping) else None)
        return cls(
            zones=zones,
            played=_normalize_played(payload.get("played")),
            annual=_normalize_table(payload.get("annual") if isinstance(payload.get("annual"), Mapping) else {}),
            opening=_normalize_table(payload.get("opening") if isinstance(payload.get("opening"), Mapping) else {}),
            previous_averages=previous_averages_json(
                payload.get("previous_averages") if isinstance(payload.get("previous_averages"), Mapping) else {}
            ),
            fixture=_normalize_fixture(payload.get("fixture"), zones),
            qualification=_normalize_qualification(payload.get("qualification")),
            rules=_normalize_rules(payload.get("rules")),
            provenance=_normalize_provenance(payload.get("provenance")),
        )

    def to_payload(self) -> dict[str, object]:
        """Payload JSON-safe aceptado por ``prepare_competition_snapshot``."""
        return {
            "data_provider_contract_version": DATA_PROVIDER_CONTRACT_VERSION,
            "zones": self.zones,
            "played": [list(row) for row in self.played],
            "annual": self.annual,
            "opening": self.opening,
            "previous_averages": self.previous_averages,
            "fixture": self.fixture,
            "qualification": self.qualification,
            "rules": self.rules,
            "provenance": self.provenance,
        }


@runtime_checkable
class DataProvider(Protocol):
    """Interfaz mínima que debe implementar cualquier proveedor futuro."""

    provider_name: str

    def load(self) -> ProviderData:
        ...


@dataclass(frozen=True)
class CurrentProvider:
    """Adaptador de la fuente/estado que usa hoy la aplicación Streamlit."""

    payload: Mapping[str, object]
    provider_name: str = "current"

    def load(self) -> ProviderData:
        return ProviderData.from_mapping(self.payload)


_STANDINGS_ALIASES = {
    "team": {"team", "equipo", "club"},
    "pts": {"pts", "puntos", "points"},
    "pj": {"pj", "jugados", "played", "partidos_jugados"},
    "dg": {"dg", "dif", "diferencia", "goal_difference"},
    "gf": {"gf", "goles_favor", "goals_for"},
    "ga": {"ga", "gc", "goles_contra", "goals_against"},
    "source_pos": {"source_pos", "pos", "posicion", "position"},
}


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    file_path = Path(path)
    if not file_path.is_file():
        raise ProviderError("missing_csv", f"No existe el CSV: {file_path}", field=str(file_path))
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="latin-1")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ProviderError("invalid_csv", f"El CSV {file_path.name} no tiene encabezados.", field=str(file_path))
    return [{str(key): str(value or "").strip() for key, value in row.items()} for row in reader]


def _column_map(rows: Sequence[Mapping[str, object]], aliases: Mapping[str, set[str]]) -> dict[str, str]:
    if not rows:
        return {}
    normalized = {_norm_label(name): str(name) for name in rows[0].keys()}
    out: dict[str, str] = {}
    for target, candidates in aliases.items():
        for candidate in candidates:
            if candidate in normalized:
                out[target] = normalized[candidate]
                break
    return out


def _csv_standings(path: str | Path) -> dict[str, dict[str, int]]:
    rows = _read_csv(path)
    columns = _column_map(rows, _STANDINGS_ALIASES)
    if not {"team", "pts", "pj"}.issubset(columns):
        raise ProviderError(
            "invalid_standings_csv",
            f"{Path(path).name} necesita columnas equipo/team, pts y pj.",
            field=str(path),
        )
    out: dict[str, dict[str, int]] = {}
    for index, row in enumerate(rows, start=2):
        team = canon_club(str(row.get(columns["team"], "")))
        if not team:
            continue
        try:
            pts = int(row.get(columns["pts"], 0) or 0)
            pj = int(row.get(columns["pj"], 0) or 0)
            gf = int(row.get(columns.get("gf", ""), 0) or 0) if columns.get("gf") else 0
            ga = int(row.get(columns.get("ga", ""), 0) or 0) if columns.get("ga") else 0
            dg = int(row.get(columns.get("dg", ""), gf - ga) or (gf - ga)) if columns.get("dg") else gf - ga
            source_pos = int(row.get(columns.get("source_pos", ""), 0) or 0) if columns.get("source_pos") else 0
        except ValueError as exc:
            raise ProviderError("invalid_standings_value", f"Valor inválido en {Path(path).name}:{index}.", field=str(path)) from exc
        data = {"pts": pts, "pj": pj, "dg": dg, "gf": gf, "ga": ga}
        if source_pos > 0:
            data["source_pos"] = source_pos
        out[team] = data
    return out


_RESULT_ALIASES = {
    "home": {"home", "local", "l"},
    "away": {"away", "visitante", "v"},
    "home_goals": {"home_goals", "goles_local", "gl"},
    "away_goals": {"away_goals", "goles_visitante", "gv"},
}


def _csv_played(path: str | Path) -> list[tuple[str, str, int, int]]:
    rows = _read_csv(path)
    columns = _column_map(rows, _RESULT_ALIASES)
    if not set(_RESULT_ALIASES).issubset(columns):
        raise ProviderError("invalid_results_csv", f"{Path(path).name} no tiene las columnas de resultados requeridas.", field=str(path))
    return _normalize_played([
        {
            "home": row[columns["home"]],
            "away": row[columns["away"]],
            "home_goals": row[columns["home_goals"]],
            "away_goals": row[columns["away_goals"]],
        }
        for row in rows
    ])


_FIXTURE_ALIASES = {
    "round": {"round", "fecha", "f"},
    "home": {"home", "local", "l"},
    "away": {"away", "visitante", "v"},
    "type": {"type", "tipo"},
    "zone": {"zone", "zona"},
}


def _csv_fixture(path: str | Path, zones: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    rows = _read_csv(path)
    columns = _column_map(rows, _FIXTURE_ALIASES)
    if not {"round", "home", "away"}.issubset(columns):
        raise ProviderError("invalid_fixture_csv", f"{Path(path).name} necesita fecha/round, local/home y visitante/away.", field=str(path))
    raw: list[dict[str, object]] = []
    for row in rows:
        game: dict[str, object] = {
            "f": row[columns["round"]],
            "l": row[columns["home"]],
            "v": row[columns["away"]],
        }
        if columns.get("type"):
            game["tipo"] = row[columns["type"]]
        if columns.get("zone"):
            game["zona"] = row[columns["zone"]]
        raw.append(game)
    return _normalize_fixture(raw, zones)


_AVERAGE_ALIASES = {
    "team": {"team", "equipo", "club"},
    "points": {"points", "pts", "puntos"},
    "played": {"played", "pj", "jugados", "partidos_jugados"},
}


def _csv_previous_averages(path: str | Path) -> dict[str, dict[str, int]]:
    rows = _read_csv(path)
    columns = _column_map(rows, _AVERAGE_ALIASES)
    if not set(_AVERAGE_ALIASES).issubset(columns):
        raise ProviderError("invalid_averages_csv", f"{Path(path).name} necesita equipo, points/pts y played/pj.", field=str(path))
    raw = {
        canon_club(row[columns["team"]]): {
            "points": int(row[columns["points"]]),
            "played": int(row[columns["played"]]),
        }
        for row in rows
        if row.get(columns["team"])
    }
    return previous_averages_json(raw)


@dataclass(frozen=True)
class CsvProvider:
    """Proveedor reproducible para archivos CSV con encabezados estables.

    ``files`` requiere ``zone_a`` y ``zone_b``. El resto es opcional:
    ``annual``, ``opening``, ``previous_averages``, ``played`` y ``fixture``.
    Reglas y vías de clasificación se inyectan como objetos simples para no mezclar
    reglamento con el formato tabular.
    """

    files: Mapping[str, str | Path]
    qualification: Mapping[str, object] | None = None
    rules: Mapping[str, object] | None = None
    provenance: Mapping[str, object] | None = None
    provider_name: str = "csv"

    def load(self) -> ProviderData:
        if "zone_a" not in self.files or "zone_b" not in self.files:
            raise ProviderError("missing_csv_zone", "CsvProvider requiere 'zone_a' y 'zone_b'.", field="files")
        zones = {
            "A": _csv_standings(self.files["zone_a"]),
            "B": _csv_standings(self.files["zone_b"]),
        }
        source_paths = [Path(path) for path in self.files.values()]
        existing = [path for path in source_paths if path.is_file()]
        default_updated = (
            datetime.fromtimestamp(max(path.stat().st_mtime for path in existing), tz=timezone.utc)
            .isoformat(timespec="seconds")
            if existing else None
        )
        default_provenance: dict[str, object] = {
            "source_name": "CSV",
            "source_updated_at": default_updated,
            "data_as_of": default_updated,
            "sources": [path.name for path in source_paths],
            "warnings": [],
        }
        if self.provenance:
            default_provenance.update(dict(self.provenance))

        payload: dict[str, object] = {
            "zones": zones,
            "annual": _csv_standings(self.files["annual"]) if self.files.get("annual") else {},
            "opening": _csv_standings(self.files["opening"]) if self.files.get("opening") else {},
            "previous_averages": _csv_previous_averages(self.files["previous_averages"])
            if self.files.get("previous_averages") else {},
            "played": _csv_played(self.files["played"]) if self.files.get("played") else [],
            "fixture": _csv_fixture(self.files["fixture"], zones) if self.files.get("fixture") else [],
            "qualification": dict(self.qualification or {}),
            "rules": dict(self.rules or {}),
            "provenance": default_provenance,
        }
        return ProviderData.from_mapping(payload)


def provider_payload(provider: DataProvider) -> dict[str, object]:
    """Obtiene el payload canónico JSON-safe de cualquier ``DataProvider``."""
    data = provider.load()
    if not isinstance(data, ProviderData):
        raise ProviderError("invalid_provider_data", "DataProvider.load() debe devolver ProviderData.")
    payload = data.to_payload()
    payload["data_provider"] = str(provider.provider_name)
    return payload
