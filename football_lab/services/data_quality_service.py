from __future__ import annotations

from football_lab.models import ProviderDataset


def data_quality_report(dataset: ProviderDataset) -> dict:
    matches = list(dataset.matches)
    finished = [m for m in matches if m.finished]
    scheduled = [m for m in matches if not m.finished]
    dated = [m for m in matches if m.match_date is not None]
    dated_finished = [m for m in finished if m.match_date is not None]
    score_complete = [m for m in finished if m.home_score is not None and m.away_score is not None]
    duplicate_ids = len(matches) - len({m.match_id for m in matches})
    meta = dataset.metadata or {}
    issues = []

    if duplicate_ids:
        issues.append({"level": "blocked", "message": f"Hay {duplicate_ids} IDs de partido duplicados."})
    if len(score_complete) != len(finished):
        issues.append({"level": "blocked", "message": "Hay partidos marcados como terminados sin marcador completo."})

    expected = meta.get("expected_played_matches")
    if isinstance(expected, (int, float)):
        expected = int(expected)
        if len(finished) < expected:
            issues.append({
                "level": "blocked",
                "message": (
                    f"La tabla pública implica {expected} partidos jugados, pero la base de resultados explica "
                    f"{len(finished)}. No conviene usar ratings/forma como foto actual hasta completar los faltantes."
                ),
            })
        elif len(finished) > expected:
            issues.append({
                "level": "info",
                "message": (
                    f"Los resultados ya contienen {len(finished)} finales y la tabla de contraste implica {expected}. "
                    "Puede ser una actualización de resultados anterior a la tabla de posiciones."
                ),
            })

    if meta.get("standings_reconciled") is False:
        detail = " | ".join((meta.get("standings_mismatches") or [])[:4])
        issues.append({
            "level": "blocked",
            "message": "Los resultados no reconstruyen exactamente PJ, puntos y goles de la tabla pública." + (f" {detail}" if detail else ""),
        })
    elif meta.get("standings_reconciled") is True:
        issues.append({
            "level": "info",
            "message": "Los resultados reconstruyen exactamente PJ, puntos, GF, GC y DG de la tabla pública de contraste.",
        })

    if meta.get("provider") == "scraping_publico" and not meta.get("live_results_ok", False):
        if meta.get("snapshot_used"):
            age = meta.get("snapshot_age_hours")
            suffix = f" ({float(age):.1f} h de antigüedad)" if isinstance(age, (int, float)) else ""
            issues.append({"level": "warning", "message": f"No pude actualizar marcadores en esta ejecución; se usan resultados de la última snapshot válida{suffix}."})
        else:
            issues.append({
                "level": "blocked",
                "message": "No pude actualizar marcadores desde la web ni recuperar una snapshot reciente. Los resultados provienen de la base incluida y no deben tratarse como una foto de hoy.",
            })
    elif not meta.get("live_fetch_ok", True):
        issues.append({"level": "warning", "message": "No hubo datos web nuevos en esta ejecución."})

    if len(dated_finished) < len(finished):
        issues.append({
            "level": "warning",
            "message": (
                f"{len(dated_finished)} de {len(finished)} resultados tienen fecha exacta. "
                "Cuando falta timestamp, forma y ratings mantienen la jornada como eje conservador; descanso sólo se calcula con fechas reales."
            ),
        })
    if len(dated) < len(matches):
        issues.append({
            "level": "info",
            "message": f"Hay fecha/hora exacta para {len(dated)} de {len(matches)} partidos del fixture.",
        })
    if not dataset.events:
        issues.append({"level": "info", "message": "La fuente actual no incluye eventos: xG, PPDA, pases y pelota parada no se muestran."})

    for warning in meta.get("warnings") or []:
        if warning and not any(i["message"] == str(warning) for i in issues):
            issues.append({"level": "warning", "message": str(warning)})

    return {
        "expected_matches": len(matches),
        "expected_played_matches": expected,
        "loaded_matches": len(matches),
        "finished_matches": len(finished),
        "pending_matches": len(scheduled),
        "complete_results": len(score_complete),
        "dated_matches": len(dated),
        "dated_finished_matches": len(dated_finished),
        "teams": len({m.home_team for m in matches} | {m.away_team for m in matches}),
        "events": len(dataset.events),
        "players": len(dataset.players),
        "availability": {
            "xg": bool(meta.get("xg_available") or any(e.xg is not None for e in dataset.events)),
            "events": bool(dataset.events),
            "players": bool(dataset.players),
            "dates": bool(dated),
            "all_finished_dated": len(dated_finished) == len(finished) and bool(finished),
        },
        "sources": meta.get("sources", []),
        "chronology_basis": meta.get("chronology_basis", "unknown"),
        "updated_at": meta.get("updated_at"),
        "live_fetch_ok": meta.get("live_fetch_ok"),
        "live_results_ok": meta.get("live_results_ok"),
        "live_schedule_ok": meta.get("live_schedule_ok"),
        "snapshot_used": bool(meta.get("snapshot_used")),
        "snapshot_age_hours": meta.get("snapshot_age_hours"),
        "issues": issues,
        "status": "blocked" if any(i["level"] == "blocked" for i in issues) else "warning" if any(i["level"] == "warning" for i in issues) else "ok",
    }
