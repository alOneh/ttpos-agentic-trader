# Scanner v2 — Single Execution-TF + Refined Evaluation — Design Spec

**Date** : 2026-06-04
**Auteur** : Alain Hippolyte (specs) + Claude (rédaction)
**Statut** : approuvé (design), en cours d'implémentation
**Remplace** : le modèle 3-cadences (M5↔D / H1↔W / 12H↔M) de `2026-06-03-mtz-scanner-design.md` §4.

---

## 1. Objectif

Deux évolutions issues du test 3 mois :
1. **TF d'exécution unique** : le scanner tourne sur **une** timeframe d'exécution (défaut **5 min**, configurable) qui balaie les zones pivots **Daily + Weekly + Monthly d'un coup**. Le pairing 5m/H1/12H ne sert plus qu'à la **capture visuelle**.
2. **Évaluation affinée** : **dedup par épisode**, **niveaux indicatifs « risque serré »**, et **double cible** (pivot HTF suivant + 2R) pour rendre le backtest exploitable.

## 2. Décisions verrouillées

| # | Décision |
|---|---|
| V1 | TF d'exécution unique `scan_exec_tf` (défaut `"5"`, configurable : `15`, `60`…). À chaque bougie d'exéc, scan des zones D/W/M ensemble. |
| V2 | Le scheduler live passe de 3 jobs à **1 job** à la cadence d'exéc. `run_scan(deps, now)` (plus de `trigger_tf`). |
| V3 | Le replay perd le gating de cadence : chaque tick scanne D/W/M. Live et replay **convergent**. |
| V4 | Pairing 5m+Daily / H1+Weekly / 12H+Monthly = **capture visuelle uniquement** (Plan 5 inchangé). |
| V5 | Récence de touche = **mémoire courte, TTL unique** `scan_touch_ttl_min` (défaut 60). |
| V6 | **Dedup par épisode** : 1 alerte quand une région devient confluente ; ré-arme quand la confluence disparaît puis revient. |
| V7 | Niveaux indicatifs **risque serré** : LONG `entry=zone_low, stop=entry−risk` ; SHORT `entry=zone_high, stop=entry+risk`. **Itération** : `risk = scan_risk_atr_mult × ATR(exec)` (basé ATR, **découplé de la largeur de zone** — le `buffer×largeur` initial rendait les cibles triviales sur des zones larges). Dilatation ATR par défaut resserrée **0.15 → 0.07**. |
| V8 | **Double cible** : (A) pivot de TF la plus haute suivant dans le sens ; (B) 2R = `entry ± 2×risk`. Follow-through mesuré vers les deux. |

## 3. Scanner unifié

### 3.1 Live (`scanner/engine.py`, `live/scan_scheduler.py`)
- `Settings.scan_exec_tf` (défaut `"5"`).
- `build_snapshot(..., exec_tf="5")` : généralisé pour fetcher la **série d'exécution** sur `exec_tf` (= `m5_bars` du snapshot, `atr_m5`, bias). Pivots D/W/M et `atr_d` inchangés.
- `run_scan(deps, *, now)` (sans `trigger_tf`) :
  ```
  pour chaque symbole :
      snapshot = build_snapshot(exec_tf=settings.scan_exec_tf)
      exec_bars = snapshot.m5_bars
      touches = []
      pour tf in ("D","W","M") si tf in snapshot.pivots :
          zones = build_zones(snapshot.pivots[tf], current_price=exec_bars[-1].close)
          touches += detect_touches(symbol, tf, zones, exec_bars, now, lookback)
      upsert_touches(touches, expires_at = now + scan_touch_ttl_min·60)
      active = load_active_touches(symbol, now)
      alerts = build_alerts(active, snapshot, min_tf=2, min_score, buffer_frac)
      episode-dedup + notify (best-effort capture inchangé)
  ```
- `setup_scan_scheduler` : **1 job** `scan` à la cadence d'exéc (cron dérivé de `scan_exec_tf` : `"5"`→`*/5 min`, `"15"`→`*/15`, `"60"`→`hour *`). Digests inchangés.

### 3.2 Replay (`backtest/scan_replay.py`)
- `replay_scan(..., base_key=...)` : **sans gating**. À chaque bougie de `base_key`, scan D/W/M avec les bougies `base_key`, TTL unique, episode-dedup, double-cible follow-through.
- `build_snapshot_at(..., base_key=...)` déjà généralisé (fait au plan précédent).

## 4. Dedup par épisode (V6)

État = ensemble des **ids de confluence actifs** (`scan_alert_id(setup)`).
- À chaque scan : `current = {ids confluents maintenant}`. **Émettre** `current − active`. Puis `active = current` (les ids absents sont retirés → ré-armables).
- **Live** : table `scan_active_episodes(alert_id TEXT PK, symbol TEXT, last_seen INTEGER)`. Chaque scan : émettre les `current` absents de la table ; `DELETE` les rows dont l'id ∉ `current` ; upsert `current`. (Remplace la fenêtre `recent_scan_notif_ids` pour le déclenchement ; `scan_notif_log` reste pour l'audit d'envoi.)
- **Replay** : set en mémoire, même logique.

## 5. Niveaux indicatifs « risque serré » + double cible (V7/V8)

`compute_indicative(setup, *, targets, buffer_frac) -> dict` :
```
width  = zone_high - zone_low
buffer = buffer_frac * width
LONG :  entry = zone_low ; stop = zone_low - buffer
SHORT:  entry = zone_high; stop = zone_high + buffer
risk   = |entry - stop| = buffer
target_2r  = entry + 2*risk (LONG) | entry - 2*risk (SHORT)
target_htf = next_target(pivot_set[highest_tf], direction, beyond=entry)  # (price, label) | None
```
`indicative` dict : `{entry, stop, risk, target_htf, target_htf_label, rr_htf, target_2r, rr_2r}` (rr_2r=2.0 par construction ; rr_htf=(|tgt−entry|/risk)).

**Hypothèse de fill** : entrée supposée remplie au niveau de réaction au début de l'épisode (idéalisation documentée ; affinable plus tard avec une logique de fill).

## 6. Follow-through multi-cible (`backtest/followthrough.py`)

```
simulate_followthrough(*, direction, entry, stop, targets: dict[str,float],
                       future_bars, horizon_bars) -> FollowThrough
```
- Parcourt les bougies ; pour **chaque** cible, déduit `TARGET` (atteinte avant stop), `STOP`, ou `OPEN`. Le stop est commun ; cas ambigu (stop & cible même bougie) → **STOP**.
- `FollowThrough` (frozen) : `outcomes: dict[str, "TARGET"|"STOP"|"OPEN"]`, `mfe_r`, `mae_r` (R = risk), `bars`.
- Résumé (`_summarize`) : **win-rate par cible** (`htf`, `2r`), MFE/MAE moyens, répartition bande/direction/mois.

## 7. Config

`Settings` (+ `.env.example`) :
```
SCAN_EXEC_TF=5          # 5 | 15 | 60 …
SCAN_TOUCH_TTL_MIN=60
SCAN_BUFFER_FRAC=0.25   # (existe) — buffer = frac × largeur de zone
```
CLI replay : `--timeframe {m5,h1}` pilote `base_key` (= TF d'exéc du replay) ; `--min-score`, `--horizon-bars`, `--output` inchangés.

## 8. Fichiers touchés

| Fichier | Changement |
|---|---|
| `config.py` | `scan_exec_tf`, `scan_touch_ttl_min` |
| `live/snapshot_builder.py` | `build_snapshot(exec_tf=...)` |
| `scanner/engine.py` | `run_scan(deps, now)` unifié (scan D/W/M), épisode-dedup côté live |
| `live/scan_scheduler.py` | 1 job à la cadence d'exéc |
| `data/repository.py` | table `scan_active_episodes` CRUD (+ schema.sql) |
| `data/schema.sql` | `scan_active_episodes` |
| `scanner/scoring.py` | `compute_indicative` risque serré + double cible |
| `backtest/followthrough.py` | multi-cible |
| `backtest/scan_replay.py` | sans gating, exec-bars pour D/W/M, épisode-dedup mémoire, double cible |
| `backtest/scan_cli.py` | inchangé (déjà `--timeframe`) |
| `notify/scan_formatter.py` | afficher 2 cibles |
| `live/main.py` | wiring scheduler unifié |

## 9. Tests (TDD)

- `compute_indicative` risque serré : entry/stop/risk LONG & SHORT, rr_htf, rr_2r=2, buffer.
- `simulate_followthrough` multi-cible : htf TARGET / 2r STOP / OPEN, cas ambigu, MFE/MAE.
- `run_scan` unifié (intégration mock) : un exec bar touchant une zone D + une touche W active → 1 alerte ; episode-dedup (2 scans confluents consécutifs → 1 alerte ; sortie puis retour → 2 alertes).
- `replay_scan` sans gating : D/W/M scannés chaque tick ; double cible présente ; episode-dedup.
- `scan_active_episodes` repo CRUD.
- Cadence scheduler : 1 job `scan` enregistré.

## 10. Hors-scope / différé

- Logique de fill réaliste de l'entrée (idéalisation pour l'instant).
- Resserrement de la dilatation Weekly/Monthly (séparé ; le risque serré atténue déjà le souci de zones larges).
- Optimisation paramétrique (grid de seuils/TTL/buffer).
