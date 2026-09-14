from __future__ import annotations
from datetime import datetime, time
import json
from pathlib import Path
from lpf_clubs import canon_club
from lpf_data_2026 import LPF_FIXTURE
from lpf_fixture_sources import ARG_TZ, official_fixture_index, resolve_team_token
from football_lab.utils import slug

raw = [
# Fecha 1
(1,'2026-07-23','Belgrano',2,1,'Rosario Central'),
(1,'2026-07-23','Sarmiento',2,3,'Argentinos'),
(1,'2026-07-23','Defensa y Justicia',1,1,'Aldosivi'),
(1,'2026-07-24','Gimnasia (Mza.)',1,0,'Central Córdoba'),
(1,'2026-07-24','Racing',2,1,'Gimnasia'),
(1,'2026-07-24','Vélez',1,0,'Instituto'),
(1,'2026-07-24','Huracán',1,0,'Banfield'),
(1,'2026-07-24','Platense',2,2,'Unión'),
(1,'2026-07-25','Estudiantes (Río Cuarto)',1,0,'Tigre'),
(1,'2026-07-25',"Newell's",1,0,'Talleres'),
(1,'2026-07-25','River',0,1,'Barracas Central'),
(1,'2026-07-25','Lanús',1,0,'San Lorenzo'),
(1,'2026-07-26','Atlético Tucumán',0,0,'Ind. Rivadavia Mza.'),
(1,'2026-07-26','Estudiantes',0,2,'Independiente'),
(1,'2026-07-26','Deportivo Riestra',3,0,'Boca'),
# Fecha 2
(2,'2026-07-28','San Lorenzo',1,0,'Gimnasia (Mza.)'),
(2,'2026-07-28','Banfield',3,2,'Sarmiento'),
(2,'2026-07-28','Argentinos',3,0,'Estudiantes (Río Cuarto)'),
(2,'2026-07-28','Rosario Central',0,0,'Racing'),
(2,'2026-07-29','Barracas Central',1,0,'Aldosivi'),
(2,'2026-07-29','Defensa y Justicia',2,1,'Deportivo Riestra'),
(2,'2026-07-29','Gimnasia',1,0,'River'),
(2,'2026-07-29','Instituto',2,1,'Platense'),
(2,'2026-07-30','Ind. Rivadavia Mza.',2,1,'Huracán'),
(2,'2026-07-30','Talleres',1,3,'Vélez'),
(2,'2026-07-30','Independiente',1,0,"Newell's"),
(2,'2026-07-30','Central Córdoba',0,2,'Atlético Tucumán'),
(2,'2026-08-05','Boca',1,0,'Estudiantes'),
(2,'2026-08-05','Tigre',0,0,'Belgrano'),
(2,'2026-08-06','Unión',2,1,'Lanús'),
# Fecha 3
(3,'2026-08-01','Gimnasia (Mza.)',2,0,'Unión'),
(3,'2026-08-01','Estudiantes (Río Cuarto)',0,0,'Banfield'),
(3,'2026-08-01','Belgrano',0,1,'Argentinos'),
(3,'2026-08-01','Estudiantes',3,0,'Defensa y Justicia'),
(3,'2026-08-01','Racing',1,3,'Tigre'),
(3,'2026-08-02','Deportivo Riestra',0,1,'Barracas Central'),
(3,'2026-08-02','Aldosivi',1,2,'Gimnasia'),
(3,'2026-08-02',"Newell's",2,2,'Boca'),
(3,'2026-08-02','River',0,1,'Rosario Central'),
(3,'2026-08-02','Lanús',0,1,'Instituto'),
(3,'2026-08-03','Sarmiento',2,1,'Ind. Rivadavia Mza.'),
(3,'2026-08-03','Platense',0,4,'Talleres'),
(3,'2026-08-03','Vélez',1,0,'Independiente'),
(3,'2026-08-03','Central Córdoba',1,0,'San Lorenzo'),
(3,'2026-08-03','Huracán',0,0,'Atlético Tucumán'),
# Fecha 4
(4,'2026-08-07','Rosario Central',2,1,'Aldosivi'),
(4,'2026-08-07','Ind. Rivadavia Mza.',2,1,'Estudiantes (Río Cuarto)'),
(4,'2026-08-08','Deportivo Riestra',2,0,'Estudiantes'),
(4,'2026-08-08','Atlético Tucumán',1,2,'Sarmiento'),
(4,'2026-08-08','Tigre',1,0,'River'),
(4,'2026-08-08','Boca',1,1,'Vélez'),
(4,'2026-08-08','Independiente',0,1,'Platense'),
(4,'2026-08-08','Instituto',1,0,'Gimnasia (Mza.)'),
(4,'2026-08-09','San Lorenzo',0,2,'Huracán'),
(4,'2026-08-09','Defensa y Justicia',2,1,"Newell's"),
(4,'2026-08-09','Gimnasia',2,0,'Barracas Central'),
(4,'2026-08-09','Argentinos',2,1,'Racing'),
(4,'2026-08-10','Banfield',0,2,'Belgrano'),
(4,'2026-08-10','Unión',1,2,'Central Córdoba'),
(4,'2026-08-11','Talleres',0,3,'Lanús'),
# Fecha 5
(5,'2026-08-14','Racing',0,1,'Banfield'),
(5,'2026-08-15','Aldosivi',0,0,'Tigre'),
(5,'2026-08-15','San Lorenzo',1,0,'Unión'),
(5,'2026-08-15','Estudiantes',4,0,'Gimnasia'),
(5,'2026-08-15',"Newell's",2,0,'Deportivo Riestra'),
(5,'2026-08-15','Belgrano',2,0,'Ind. Rivadavia Mza.'),
(5,'2026-08-15','Platense',1,1,'Boca'),
(5,'2026-08-16','Sarmiento',2,0,'Huracán'),
(5,'2026-08-16','River',2,0,'Argentinos'),
(5,'2026-08-16','Barracas Central',0,1,'Rosario Central'),
(5,'2026-08-16','Central Córdoba',0,1,'Instituto'),
(5,'2026-08-17','Estudiantes (Río Cuarto)',0,1,'Atlético Tucumán'),
(5,'2026-08-17','Lanús',1,3,'Independiente'),
(5,'2026-08-17','Vélez',1,1,'Defensa y Justicia'),
(5,'2026-08-17','Gimnasia (Mza.)',3,1,'Talleres'),
# Fecha 6
(6,'2026-08-21','Aldosivi',1,3,'Unión'),
(6,'2026-08-21','Estudiantes (Río Cuarto)',0,0,'San Lorenzo'),
(6,'2026-08-22','Gimnasia',2,3,'Gimnasia (Mza.)'),
(6,'2026-08-22','Atlético Tucumán',0,0,'Instituto'),
(6,'2026-08-22','Independiente',0,0,'Ind. Rivadavia Mza.'),
(6,'2026-08-22',"Newell's",2,1,'Banfield'),
(6,'2026-08-22','Huracán',0,0,'Deportivo Riestra'),
(6,'2026-08-23','Sarmiento',2,0,'Estudiantes'),
(6,'2026-08-23','Barracas Central',1,2,'Platense'),
(6,'2026-08-23','Belgrano',1,2,'Defensa y Justicia'),
(6,'2026-08-23','River',2,2,'Vélez'),
(6,'2026-08-23','Racing',1,1,'Boca'),
(6,'2026-08-24','Tigre',2,1,'Central Córdoba'),
(6,'2026-08-24','Lanús',1,1,'Argentinos'),
(6,'2026-08-24','Talleres',2,2,'Rosario Central'),
# Fecha 7
(7,'2026-08-28','Unión',4,1,'Sarmiento'),
(7,'2026-08-28','Boca',1,0,'Lanús'),
(7,'2026-08-29','Deportivo Riestra',1,1,'Vélez'),
(7,'2026-08-29','Rosario Central',1,2,'Gimnasia'),
(7,'2026-08-29','Huracán',1,1,'Estudiantes (Río Cuarto)'),
(7,'2026-08-29','Talleres',0,0,'Central Córdoba'),
(7,'2026-08-29','Atlético Tucumán',0,0,'Belgrano'),
(7,'2026-08-30','Banfield',2,3,'River'),
(7,'2026-08-30','Argentinos',2,1,'Aldosivi'),
(7,'2026-08-30','Independiente',0,3,'Gimnasia (Mza.)'),
(7,'2026-08-30','Ind. Rivadavia Mza.',3,1,'Racing'),
(7,'2026-08-31','Defensa y Justicia',1,0,'Platense'),
(7,'2026-08-31','Estudiantes',0,0,"Newell's"),
(7,'2026-08-31','Tigre',0,0,'Barracas Central'),
(7,'2026-08-31','Instituto',1,0,'San Lorenzo'),
# Fecha 8
(8,'2026-09-04','Estudiantes (Río Cuarto)',0,2,'Sarmiento'),
(8,'2026-09-04','Belgrano',1,1,'Huracán'),
(8,'2026-09-04','Platense',1,1,'Deportivo Riestra'),
(8,'2026-09-05','Aldosivi',3,1,'Banfield'),
(8,'2026-09-05','Gimnasia',2,1,'Tigre'),
(8,'2026-09-05','Gimnasia (Mza.)',2,2,'Boca'),
(8,'2026-09-05','San Lorenzo',1,0,'Talleres'),
(8,'2026-09-05','Vélez',1,0,'Estudiantes'),
(8,'2026-09-06','Rosario Central',1,1,"Newell's"),
(8,'2026-09-06','Lanús',1,0,'Defensa y Justicia'),
(8,'2026-09-06','Central Córdoba',0,1,'Independiente'),
(8,'2026-09-06','River',3,1,'Ind. Rivadavia Mza.'),
(8,'2026-09-06','Racing',1,2,'Atlético Tucumán'),
(8,'2026-09-07','Barracas Central',0,0,'Argentinos'),
(8,'2026-09-07','Unión',3,2,'Instituto'),
# Fecha 9 jugados hasta el 13/09
(9,'2026-09-11',"Newell's",1,1,'Vélez'),
(9,'2026-09-11','Defensa y Justicia',2,0,'Gimnasia (Mza.)'),
(9,'2026-09-11','Boca',3,1,'Central Córdoba'),
(9,'2026-09-12','Ind. Rivadavia Mza.',4,3,'Aldosivi'),
(9,'2026-09-12','Estudiantes',2,1,'Platense'),
(9,'2026-09-12','Atlético Tucumán',1,2,'River'),
(9,'2026-09-12','Talleres',2,1,'Unión'),
(9,'2026-09-13','Sarmiento',1,1,'Belgrano'),
(9,'2026-09-13','Tigre',0,1,'Rosario Central'),
(9,'2026-09-13','Argentinos',1,1,'Gimnasia'),
(9,'2026-09-13','Independiente',1,1,'San Lorenzo'),
(9,'2026-09-13','Huracán',2,1,'Racing'),
]

fixture = official_fixture_index(LPF_FIXTURE)
expected_teams = {t for pair in fixture for t in pair}
records=[]
errors=[]
for rnd, d, home_raw, hg, ag, away_raw in raw:
    home=resolve_team_token(home_raw, canon_club=canon_club, expected_teams=expected_teams)
    away=resolve_team_token(away_raw, canon_club=canon_club, expected_teams=expected_teams)
    if not home or not away:
        errors.append((rnd,home_raw,away_raw,'resolve',home,away)); continue
    meta=fixture.get((home,away))
    if not meta or int(meta['round']) != rnd:
        errors.append((rnd,home,away,'fixture',meta)); continue
    dt=datetime.fromisoformat(d).date()
    stamp=datetime.combine(dt,time(23,59),tzinfo=ARG_TZ).isoformat()
    records.append({
        'match_id': f'SEED-F{rnd:02d}-{slug(home)}-{slug(away)}',
        'round': rnd,
        'home': home,'away':away,'scheduled_at':stamp,'status':'played',
        'home_score':hg,'away_score':ag,'source':'Seed TyC Sports 14/09/2026',
    })


# Programación publicada en la misma fuente para completar la jornada actual y las dos siguientes.
scheduled_raw = [
    (9, '2026-09-14', '19:00', 'Deportivo Riestra', 'Lanús'),
    (9, '2026-09-14', '19:00', 'Banfield', 'Barracas Central'),
    (9, '2026-09-14', '21:15', 'Instituto', 'Estudiantes (Río Cuarto)'),
    (10, '2026-09-18', '19:00', 'Central Córdoba', 'Defensa y Justicia'),
    (10, '2026-09-18', '21:15', 'Racing', 'Sarmiento'),
    (10, '2026-09-19', '14:30', 'Gimnasia', 'Banfield'),
    (10, '2026-09-19', '14:30', 'Gimnasia (Mza.)', 'Deportivo Riestra'),
    (10, '2026-09-19', '16:45', 'Unión', 'Independiente'),
    (10, '2026-09-19', '19:00', 'River', 'Huracán'),
    (10, '2026-09-19', '21:15', 'Instituto', 'Talleres'),
    (10, '2026-09-20', '14:45', 'San Lorenzo', 'Boca'),
    (10, '2026-09-20', '17:00', 'Rosario Central', 'Argentinos'),
    (10, '2026-09-20', '17:00', 'Platense', "Newell's"),
    (10, '2026-09-20', '19:15', 'Belgrano', 'Estudiantes (Río Cuarto)'),
    (10, '2026-09-20', '21:30', 'Vélez', 'Tigre'),
    (10, '2026-09-21', '14:30', 'Aldosivi', 'Atlético Tucumán'),
    (10, '2026-09-21', '19:00', 'Barracas Central', 'Ind. Rivadavia Mza.'),
    (10, '2026-09-21', '21:15', 'Lanús', 'Estudiantes'),
    (11, '2026-10-02', '19:15', 'Independiente', 'Instituto'),
    (11, '2026-10-02', '21:30', 'Ind. Rivadavia Mza.', 'Gimnasia'),
    (11, '2026-10-03', '14:45', 'Defensa y Justicia', 'San Lorenzo'),
    (11, '2026-10-03', '17:00', 'Atlético Tucumán', 'Barracas Central'),
    (11, '2026-10-03', '17:00', "Newell's", 'Lanús'),
    (11, '2026-10-03', '19:15', 'Argentinos', 'Tigre'),
    (11, '2026-10-03', '21:30', 'Huracán', 'Aldosivi'),
    (11, '2026-10-04', '14:45', 'Sarmiento', 'River'),
    (11, '2026-10-04', '17:00', 'Talleres', 'Belgrano'),
    (11, '2026-10-04', '19:15', 'Boca', 'Unión'),
    (11, '2026-10-04', '21:30', 'Estudiantes (Río Cuarto)', 'Racing'),
    (11, '2026-10-05', '16:45', 'Deportivo Riestra', 'Central Córdoba'),
    (11, '2026-10-05', '19:00', 'Estudiantes', 'Gimnasia (Mza.)'),
    (11, '2026-10-05', '19:00', 'Vélez', 'Platense'),
    (11, '2026-10-05', '21:15', 'Banfield', 'Rosario Central'),
]
for rnd, d, clock, home_raw, away_raw in scheduled_raw:
    home=resolve_team_token(home_raw, canon_club=canon_club, expected_teams=expected_teams)
    away=resolve_team_token(away_raw, canon_club=canon_club, expected_teams=expected_teams)
    meta=fixture.get((home,away)) if home and away else None
    if not meta or int(meta['round']) != rnd:
        errors.append((rnd,home_raw,away_raw,'scheduled_fixture',home,away,meta)); continue
    dt=datetime.fromisoformat(f'{d}T{clock}:00').replace(tzinfo=ARG_TZ)
    records.append({
        'match_id': f'SEED-SCHED-F{rnd:02d}-{slug(home)}-{slug(away)}',
        'round': rnd, 'home': home, 'away': away, 'scheduled_at': dt.isoformat(),
        'status': 'scheduled', 'home_score': None, 'away_score': None,
        'source':'Seed TyC Sports 14/09/2026',
    })

from collections import Counter
counts=Counter(r['round'] for r in records if r['status']=='played')
print('records',len(records),'played_counts',dict(sorted(counts.items())))
print('errors',errors)
assert not errors
assert sum(r['status']=='played' for r in records)==132
assert len(records)==165
for r in range(1,9): assert counts[r]==15,(r,counts[r])
assert counts[9]==12
assert len({(r['home'],r['away']) for r in records})==165
payload={
    'schema':1,
    'saved_at':'2026-09-14T15:59:00-03:00',
    'source_url':'https://www.tycsports.com/liga-profesional-de-futbol/fixture-del-clausura-2026-calendario-de-partidos-y-resultados-id750943.html',
    'note':'Bootstrap editorial derivado del fixture/resultados publicado por TyC Sports. Resultados hasta el 13/09; los tres partidos del 14/09 quedaban pendientes al momento de la foto.',
    'records':records,
}
out=Path('/mnt/data/lab_futbol_fix2/data/bootstrap/lpf_clausura_2026_20260914.json')
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print(out, out.stat().st_size)
