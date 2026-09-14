from __future__ import annotations


def match_narrative(home: str, away: str, features: dict) -> dict:
    diffs = features.get("differences", {})
    home_adv, away_adv = [], []
    rules = [
        ("points_last_5_diff", "forma reciente", True, 1.0),
        ("goals_for_avg_5_diff", "producción ofensiva reciente", True, 0.15),
        ("goals_against_avg_5_diff", "goles recibidos recientes", False, 0.15),
        ("elo_diff", "Elo", True, 20.0),
        ("rest_diff", "descanso", True, 1.0),
        ("xg_diff", "xG", True, 0.15),
    ]
    for key, label, higher_better, threshold in rules:
        value = diffs.get(key)
        if value is None or abs(value) < threshold:
            continue
        home_better = value > 0 if higher_better else value < 0
        (home_adv if home_better else away_adv).append(label)
    if len(home_adv) > len(away_adv):
        conclusion = f"Con los indicadores disponibles antes del partido, {home} reúne más ventajas relativas. No es una probabilidad de resultado."
    elif len(away_adv) > len(home_adv):
        conclusion = f"Con los indicadores disponibles antes del partido, {away} reúne más ventajas relativas. No es una probabilidad de resultado."
    else:
        conclusion = "Los indicadores disponibles quedan repartidos. No se fuerza un favorito ni se inventan probabilidades."
    return {"home_advantages": home_adv, "away_advantages": away_adv, "conclusion": conclusion}
