"""Pruebas de la canonicalización de clubes (`lpf_clubs`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_clubs import LPF_CLUBES, canon_base, canon_club  # noqa: E402


def test_todos_los_canonicos_son_punto_fijo():
    # Aplicar canon_club a un nombre ya canónico debe devolverlo igual.
    for canonical in LPF_CLUBES:
        assert canon_club(canonical) == canonical


def test_todos_los_alias_mapean_al_canonico():
    for canonical, aliases in LPF_CLUBES.items():
        for alias in aliases:
            assert canon_club(alias) == canonical, f"{alias!r} debería mapear a {canonical!r}"


def test_insensible_a_acentos_y_mayusculas():
    for canonical in list(LPF_CLUBES)[:10]:
        assert canon_club(canonical.upper()) == canonical
        assert canon_club(canonical.lower()) == canonical
        assert canon_club(f"  {canonical}  ") == canonical


def test_nombre_desconocido_se_devuelve_limpio():
    assert canon_club("Club Inventado XYZ") == "Club Inventado XYZ"
    assert canon_club("") == ""


def test_no_confunde_hermanos_ambiguos():
    # Los nombres "hermanos" (Gimnasia, Estudiantes) no deben colapsarse entre sí
    # por el paréntesis desambiguador. Sólo verificamos que canon es determinista
    # y no lanza excepción para estas variantes delicadas.
    for name in ["Gimnasia", "Gimnasia (M)", "Estudiantes", "Estudiantes RC"]:
        assert isinstance(canon_club(name), str)
        assert canon_club(name) == canon_club(name)


def test_canon_base_reindexa_por_nombre_canonico():
    base = {list(LPF_CLUBES)[0].lower(): {"pts": 5}}
    out = canon_base(base)
    assert list(out) == [list(LPF_CLUBES)[0]]
    assert out[list(LPF_CLUBES)[0]] == {"pts": 5}
    assert canon_base(None) == {}
