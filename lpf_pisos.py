"""Puntos por objetivo — cuánto necesita cada equipo para cada meta.

Este módulo unifica un cálculo que hasta ahora estaba disperso: para cada objetivo
(playoffs, Libertadores, Sudamericana, no descender) responde tres números con
significado distinto y sin mezclarlos:

- **Mínimo posible:** el menor puntaje final con el que *todavía existe* una
  combinación de resultados que logra el objetivo. No es una garantía.
- **Mínimo que asegura:** el menor puntaje que asegura el objetivo sin depender de
  otros resultados ni de desempates. Sale del optimizador exacto.
- **Total seguro:** un total que sabemos que alcanza cuando la ventana todavía es
  demasiado grande para buscar el mínimo exacto. Puede pedir puntos de más: es
  seguro, pero todavía no sabemos si es el menor que asegura.

Todos los objetivos de tipo "quedar por encima de un corte" (playoffs y las dos
copas) comparten la misma estructura: un conjunto de equipos y un corte. Por eso
se resuelven con la misma función; sólo cambian la tabla base y el corte.

El módulo es Python puro (sin Streamlit) y reutiliza los motores ya validados
por fuerza bruta en ``lpf_scenarios`` y ``lpf_exact``.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


from dataclasses import dataclass
from typing import Mapping, Sequence

from lpf_scenarios import point_ladder
from lpf_averages import combine_average_totals
from lpf_exact import safe_average_guarantee_points, safe_guarantee_line

# El motor exacto se reserva para el tramo final: es un problema de optimización
# entera y se encarece con ventanas grandes. Medido sobre zonas de 16 equipos, el
# costo por equipo se mantiene por debajo de ~2 s hasta ocho fechas, así que ese es
# el umbral. Es por equipo: cada club usa el motor exacto apenas entra en sus
# últimas ocho fechas, sin importar los postergados de otras canchas.
VENTANA_EXACTA = 8
MAX_MATCHES = 140


def promedio_totales(
    anual: Mapping[str, object],
    zonas: Mapping[str, Mapping[str, object]],
    previas: Mapping[str, object] | None,
) -> dict[str, tuple[int, int]] | None:
    """Compatibilidad: devuelve totales acumulados para el cálculo de promedios.

    ``previas`` contiene únicamente temporadas anteriores. La temporada 2026 se
    agrega desde la Tabla Anual; ``zonas`` se usa sólo como respaldo si una foto
    legacy de la Anual no trae PJ. La normalización vive en ``lpf_averages``.
    """
    return combine_average_totals(anual, previas, zones=zonas)


@dataclass
class PisoObjetivo:
    """Resultado de puntos necesarios para un equipo y un objetivo puntual."""

    clave: str
    nombre: str
    aplica: bool = True
    estado: str = "pelea"          # "in" | "out" | "pelea"
    puntos_hoy: int = 0
    techo: int = 0
    minimo_posible: int | None = None
    piso_exacto: int | None = None
    piso_conservador: int | None = None
    exacto: bool = False
    detalle: str = ""
    caminos: list = None  # escalera exacta: [(puntos, estado, ejemplo)]

    def __post_init__(self):
        if self.caminos is None:
            self.caminos = []

    @property
    def garantia_exacta(self) -> int | None:
        """Alias interno histórico del mínimo que asegura, si el cálculo global es exacto."""
        return self.piso_exacto if self.exacto else None

    @property
    def minimo_que_asegura(self) -> int | None:
        """Menor total comprobado que asegura el objetivo."""
        return self.garantia_exacta

    @property
    def referencia_conservadora(self) -> int | None:
        """Alias interno histórico del total seguro disponible antes del mínimo exacto."""
        if self.exacto:
            return None
        if self.piso_conservador is not None:
            return self.piso_conservador
        return self.piso_exacto

    @property
    def piso(self) -> int | None:
        """Valor seguro vigente; se conserva por compatibilidad interna/API."""
        if self.exacto:
            return self.piso_exacto
        if self.piso_conservador is not None:
            return self.piso_conservador
        return self.piso_exacto

    def lectura(self) -> str:
        """Frase corta lista para publicar."""
        if not self.aplica:
            return self.detalle or "No aplica para este equipo."
        if self.estado == "in":
            return self.detalle or f"Ya lo tiene asegurado con {self.puntos_hoy} puntos; no depende de nadie."
        if self.estado == "out":
            return f"Sin chances: aun ganando todo llega a {self.techo} y no alcanza."
        piso = self.piso
        if piso is None:
            return f"En carrera; el mínimo que asegura se calcula con {VENTANA_EXACTA} partidos restantes o menos."
        faltan = max(0, piso - self.puntos_hoy)
        cola = "" if faltan == 0 else f" (le faltan {faltan})"
        if self.exacto:
            return f"Mínimo que asegura: con {piso} puntos asegura {self.nombre}{cola}."
        return (
            f"Total seguro: {piso} puntos{cola}. Si llega a ese total, asegura {self.nombre}. "
            "Todavía no sabemos si ése es el menor total que asegura; puede alcanzar con menos."
        )


def _pts(base: Mapping[str, object], team: str) -> int:
    value = base.get(team, 0)
    if isinstance(value, Mapping):
        return int(value.get("pts", 0))
    return int(value)


def _techo(base: Mapping[str, object], rest: Mapping[str, int], team: str) -> int:
    return _pts(base, team) + 3 * int(rest.get(team, 0))


def _estado_corte(base: Mapping[str, object], rest: Mapping[str, int], team: str, corte: int) -> str:
    """in = ya adentro del top ``corte``; out = ya afuera; pelea = indefinido."""
    pts = {e: _pts(base, e) for e in base}
    techo = {e: pts[e] + 3 * int(rest.get(e, 0)) for e in base}
    arriba = sum(1 for x in base if x != team and techo[x] >= pts[team])
    inalcanzable = sum(1 for x in base if x != team and pts[x] > techo[team])
    if arriba < corte:
        return "in"
    if inalcanzable >= corte:
        return "out"
    return "pelea"


def _matches_del_pool(pend: Sequence[tuple[str, str]], pool: set[str]) -> list[tuple[str, str]]:
    """Sólo los partidos que tocan a un equipo del pool.

    Un equipo del pool también suma puntos contra rivales de afuera; esos partidos
    quedan incluidos (el motor los usa como puntos "libres"). Los cruces internos
    reparten como máximo tres puntos entre ambos.
    """
    return [(a, b) for a, b in pend if a in pool or b in pool]


def piso_por_corte(
    base: Mapping[str, object],
    rest: Mapping[str, int],
    pend: Sequence[tuple[str, str]],
    team: str,
    corte: int,
    *,
    clave: str,
    nombre: str,
) -> PisoObjetivo:
    """Piso para "quedar entre los primeros ``corte`` de ``base``".

    Sirve igual para playoffs (zona, corte 8), Libertadores (tabla reducida, corte
    de plazas directas) y Sudamericana (tabla reducida, corte ampliado).
    """
    if team not in base:
        return PisoObjetivo(clave, nombre, aplica=False, detalle="El equipo no está en esta tabla.")

    pts_hoy = _pts(base, team)
    techo = _techo(base, rest, team)
    estado = _estado_corte(base, rest, team, corte)
    resultado = PisoObjetivo(
        clave=clave, nombre=nombre, estado=estado,
        puntos_hoy=pts_hoy, techo=techo,
    )
    if estado == "in":
        resultado.minimo_posible = pts_hoy
        resultado.piso_exacto = pts_hoy
        resultado.exacto = True
        return resultado
    if estado == "out":
        return resultado

    pool = set(base)
    matches = _matches_del_pool(pend, pool)
    games_left = int(rest.get(team, 0))

    # Total seguro: siempre disponible. safe_guarantee_line devuelve el mayor
    # puntaje con el que `corte` rivales todavía pueden igualar al equipo; sumar uno
    # garantiza terminar por encima de ese grupo.
    try:
        linea = safe_guarantee_line(base, rest, matches, team, corte)
        if linea is not None and linea >= pts_hoy - 1:
            resultado.piso_conservador = min(techo, max(pts_hoy, linea + 1))
    except Exception:
        resultado.piso_conservador = None

    # Motor exacto en el tramo final.
    if matches and 0 < games_left <= VENTANA_EXACTA and len(matches) <= MAX_MATCHES:
        try:
            ladder = point_ladder(base, matches, team, corte, max_rows=6, max_matches=MAX_MATCHES)
            if ladder.get("available"):
                resultado.minimo_posible = ladder.get("minimum_possible")
                if ladder.get("guarantee") is not None:
                    resultado.piso_exacto = int(ladder["guarantee"])
                    resultado.exacto = True
                # Guardar la escalera (puntos → estado → camino de ejemplo).
                for row in ladder.get("rows", []) or []:
                    ejemplo = ""
                    ej_list = getattr(row, "example", None)
                    if ej_list:
                        ejemplo = "; ".join(ej_list[:2])
                    resultado.caminos.append((
                        int(getattr(row, "final_points", 0)),
                        str(getattr(row, "status", "")),
                        ejemplo,
                    ))
        except Exception:
            pass

    return resultado


def piso_no_descenso(
    anual: Mapping[str, object],
    rest: Mapping[str, int],
    pend: Sequence[tuple[str, str]],
    team: str,
    *,
    n_anual: int = 1,
    prom_totales: Mapping[str, tuple[int, int]] | None = None,
    n_prom: int = 1,
) -> PisoObjetivo:
    """Puntos necesarios para NO descender.

    En la LPF se baja por dos vías: el último de la Tabla Anual y el peor promedio.
    Para estar salvado hay que estarlo en **las dos** tablas, así que manda la
    exigencia más alta. La parte anual se resuelve con el motor exacto (en el tramo
    final) y la de promedios con un total seguro por cocientes.
    """
    nombre = "no descender"
    if team not in anual:
        return PisoObjetivo("descenso", nombre, aplica=False, detalle="El equipo no está en la Anual.")

    total = len(anual)
    corte_salvacion = max(1, total - int(n_anual))  # quedar dentro del top (N - descensos)
    parte_anual = piso_por_corte(
        anual, rest, pend, team, corte_salvacion, clave="descenso", nombre=nombre,
    )

    piso_prom = None
    detalle_prom = ""
    if prom_totales and team in prom_totales:
        totales = {e: int(v[0]) for e, v in prom_totales.items()}
        jugados = {e: int(v[1]) for e, v in prom_totales.items()}
        restantes = {e: int(rest.get(e, 0)) for e in prom_totales}
        pool = set(prom_totales)
        matches = _matches_del_pool(pend, pool)
        try:
            extra = safe_average_guarantee_points(
                totales, jugados, restantes, matches, team, int(n_prom),
            )
            if extra is not None:
                piso_prom = _pts(anual, team) + int(extra)
                detalle_prom = "Incluye la exigencia por promedios (total seguro por cocientes)."
        except Exception:
            piso_prom = None

    # Combinar: para no descender hay que quedar a salvo en las dos tablas.
    # La Anual puede tener un mínimo exacto; promedios aporta un total
    # seguro. Si esa referencia exige más que la garantía anual, el objetivo
    # global deja de ser exacto y manda el mayor total seguro.
    prom_disponible = bool(prom_totales and team in prom_totales)
    annual_safe = parte_anual.piso
    safe_values = [value for value in (annual_safe, piso_prom) if value is not None]

    if parte_anual.estado == "out":
        estado_global = "out"
    elif prom_disponible:
        promedio_ya_seguro = piso_prom is not None and piso_prom <= parte_anual.puntos_hoy
        estado_global = "in" if parte_anual.estado == "in" and promedio_ya_seguro else "pelea"
    else:
        # Sin promedios no se inventa una conclusión sobre esa vía; se conserva la
        # lectura anual y la interfaz avisa que falta cargar los antecedentes.
        estado_global = parte_anual.estado

    resultado = PisoObjetivo(
        clave="descenso", nombre=nombre,
        estado=estado_global,
        puntos_hoy=parte_anual.puntos_hoy, techo=parte_anual.techo,
        minimo_posible=parte_anual.minimo_posible,
    )

    if not prom_disponible:
        resultado.piso_exacto = parte_anual.piso_exacto
        resultado.piso_conservador = parte_anual.piso_conservador
        resultado.exacto = parte_anual.exacto
    elif (
        parte_anual.exacto
        and parte_anual.piso_exacto is not None
        and piso_prom is not None
        and piso_prom <= parte_anual.piso_exacto
    ):
        # El mínimo exacto de la Anual ya supera la exigencia segura de
        # promedios. Como cualquier total menor falla la Anual en algún escenario,
        # ese mismo número es también el mínimo exacto del objetivo combinado.
        resultado.piso_exacto = parte_anual.piso_exacto
        resultado.exacto = True
    else:
        resultado.piso_exacto = parte_anual.piso_exacto
        resultado.piso_conservador = max(safe_values) if safe_values else None
        resultado.exacto = False

    resultado.detalle = detalle_prom
    if resultado.estado == "in":
        resultado.exacto = True
        resultado.piso_exacto = resultado.puntos_hoy
        resultado.piso_conservador = None
    return resultado


def objetivos_de_equipo(
    zonas: Mapping[str, Mapping[str, object]],
    anual: Mapping[str, object],
    reducida: Sequence[str],
    n_lib: int,
    team: str,
) -> list[dict]:
    """Objetivos aplicables a un equipo, con su tabla base y su corte.

    Devuelve especificaciones ``{clave, nombre, base, corte}`` para los objetivos
    de corte; el descenso se calcula aparte porque combina dos tablas.
    """
    specs: list[dict] = []
    zona = next((lab for lab, b in zonas.items() if team in b), None)
    if zona is not None:
        specs.append({
            "clave": "playoffs", "nombre": "los playoffs (top 8 de zona)",
            "base": dict(zonas[zona]), "corte": 8,
        })
    reducida = list(reducida)
    if team in reducida and anual:
        base_red = {e: anual[e] for e in reducida if e in anual}
        specs.append({
            "clave": "libertadores", "nombre": "la Libertadores por Tabla Anual",
            "base": base_red, "corte": int(n_lib),
        })
        specs.append({
            "clave": "sudamericana", "nombre": "al menos la Sudamericana por Tabla Anual",
            "base": base_red, "corte": int(n_lib) + 6,
        })
    return specs


def pisos_de_equipo(
    zonas: Mapping[str, Mapping[str, object]],
    anual: Mapping[str, object],
    reducida: Sequence[str],
    n_lib: int,
    rest: Mapping[str, int],
    pend: Sequence[tuple[str, str]],
    team: str,
    *,
    n_anual: int = 1,
    prom_totales: Mapping[str, tuple[int, int]] | None = None,
    n_prom: int = 1,
) -> list[PisoObjetivo]:
    """Todos los objetivos aplicables a un equipo, en orden editorial."""
    salida: list[PisoObjetivo] = []
    for spec in objetivos_de_equipo(zonas, anual, reducida, n_lib, team):
        salida.append(piso_por_corte(
            spec["base"], rest, pend, team, spec["corte"],
            clave=spec["clave"], nombre=spec["nombre"],
        ))

    # Los equipos que ya tienen una plaza directa (por campeón o por una plaza
    # internacional adicional) quedan fuera de ``reducida``. Antes desaparecían de
    # las filas de copas y la interfaz podía sugerir que no tenían ese objetivo.
    # Se muestran como ya clasificados, sin atribuir esa plaza a una cantidad de
    # puntos de la Tabla Anual.
    if anual and team in anual and team not in set(reducida):
        pts_hoy = _pts(anual, team)
        techo = _techo(anual, rest, team)
        salida.append(PisoObjetivo(
            clave="libertadores", nombre="la Libertadores", estado="in",
            puntos_hoy=pts_hoy, techo=techo,
            detalle=(
                "Ya está clasificado a la Libertadores por una vía directa; "
                "la Tabla Anual ya no define esa plaza."
            ),
        ))
        salida.append(PisoObjetivo(
            clave="sudamericana", nombre="al menos la Sudamericana", estado="in",
            puntos_hoy=pts_hoy, techo=techo,
            detalle=(
                "Ya tiene asegurada una plaza internacional superior (Libertadores); "
                "la vía de Sudamericana por Tabla Anual ya no aplica."
            ),
        ))

    if anual and team in anual:
        salida.append(piso_no_descenso(
            anual, rest, pend, team,
            n_anual=n_anual, prom_totales=prom_totales, n_prom=n_prom,
        ))
    return salida


def tabla_pisos_objetivo(
    base: Mapping[str, object],
    rest: Mapping[str, int],
    pend: Sequence[tuple[str, str]],
    corte: int,
    *,
    clave: str,
    nombre: str,
    orden: Sequence[str] | None = None,
) -> list[dict]:
    """Filas listas para tabla: los puntos de *cada* equipo para un mismo objetivo."""
    equipos = list(orden) if orden else list(base)
    filas: list[dict] = []
    for e in equipos:
        if e not in base:
            continue
        p = piso_por_corte(base, rest, pend, e, corte, clave=clave, nombre=nombre)
        filas.append({
            "Equipo": e,
            "PTS": p.puntos_hoy,
            "Restan": int(rest.get(e, 0)),
            "Techo": p.techo,
            "Mínimo posible": p.minimo_posible,
            "Mínimo que asegura": p.minimo_que_asegura,
            "Total seguro": p.referencia_conservadora,
            "Tipo de dato": (
                "Mínimo exacto" if p.minimo_que_asegura is not None
                else ("Total seguro" if p.referencia_conservadora is not None else "—")
            ),
            "Estado": {"in": "Adentro", "out": "Afuera", "pelea": "En carrera"}.get(p.estado, p.estado),
        })
    return filas
