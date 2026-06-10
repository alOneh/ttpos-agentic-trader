# MTZ Scan Replay (Backtest) — Design Spec

**Date** : 2026-06-04
**Auteur** : Alain Hippolyte (specs) + Claude (rédaction)
**Statut** : approuvé (design), en cours d'implémentation
**Contexte** : "Plan 6" du scanner MTZ — rejouer le scanner sur l'historique pour évaluer les setups. Réoriente le backtest legacy (qui simulait des ordres S1-S6) vers un replay des alertes MTZ + suivi.

---

## 1. Objectif

Rejouer le **scanner MTZ** sur des données historiques (ex. XAUUSD, 3 derniers mois) **sans look-ahead**, en reproduisant fidèlement les 3 cadences live, et produire :
1. La liste des **alertes MTZ** qui auraient été émises (date, zone, score, direction, membres, tags, niveaux indicatifs).
2. Le **follow-through** de chaque alerte (la cible indicative a-t-elle été atteinte avant le stop ? MFE/MAE en R).
3. Un **résumé** agrégé (alertes/mois, répartition par bande/direction, win-rate, MFE/MAE moyens).

## 2. Décisions verrouillées

| # | Décision |
|---|---|
| R1 | Sortie = **alertes + follow-through** + résumé agrégé. |
| R2 | Simulation **fidèle** : 3 cadences (D toutes les 5min, W toutes les heures via H1, M 2×/jour via Daily) + TouchStore (TTL) + dedup id (fenêtre 60min). |
| R3 | **`min_score` configurable, défaut 0** : émettre toute confluence ≥ 2 TF avec son score. |
| R4 | Réutiliser `backtest/history.py` + `backtest/snapshot_builder.build_snapshot_at` et les fonctions pures du scanner (`scan_symbol_tf`, `aggregate_mtz`, `build_alerts`). Pas de réutilisation du `runner.py` legacy. |
| R5 | TouchStore **en mémoire** (mêmes sémantiques que le live : upsert clé `(tf,tag,bar_time)` + expiry) pour la vitesse ; pas de SQLite dans la boucle. |
| R6 | Pas d'appel réseau en test (fetch injecté). |

## 3. Données

`fetch_history(symbol, to)` pré-charge une batch par TV timeframe finissant à `to`. **Ajout de la clé `"60"` (H1)** à `TV_KEYS` (nécessaire à la cadence Weekly). La fenêtre = `[start, end]` ; on fetch assez de buffer à gauche (les défauts `DEFAULT_N_BARS` couvrent déjà 1.5 an de Daily / 5 ans de Monthly, donc 3 mois + buffer Monthly est largement couvert).

`build_snapshot_at(history, t)` reconstruit le `MarketSnapshot` à `t` (bars filtrées `time ≤ t`, zéro look-ahead) : pivots D/W/M, `cpr_widths`, `atr`, `m5_bars`. Déjà implémenté et testé.

## 4. Boucle de replay

```
pour chaque bougie M5 close à t dans [start, end] :
    snapshot = build_snapshot_at(history, t)

    # cadence D : toujours (toutes les 5 min)
    scan_and_store(snapshot, tf="D", scan_bars=snapshot.m5_bars, ttl=15min)

    # cadence W : si t est une heure pleine
    si t.minute == 0 :
        scan_and_store(snapshot, tf="W", scan_bars=H1_up_to(t), ttl=90min)

    # cadence M : si t ∈ {00:00, 12:00}
    si t.minute == 0 et t.hour ∈ {0, 12} :
        scan_and_store(snapshot, tf="M", scan_bars=Daily_up_to(t), ttl=13h)

    # agrégation + alertes (après chaque scan effectué à t)
    active = touchstore.load_active(t)
    alerts = build_alerts(symbol, active, snapshot, min_tf=2, min_score, buffer_frac)
    pour chaque alerte non dédupliquée (id absent de la fenêtre 60min) :
        enregistrer ; lancer follow-through ; marquer id notifié à t
```

`scan_and_store` = `scan_symbol_tf(...)` puis `touchstore.upsert(events, expires_at=t+ttl)`.
`scan_bars` par cadence : D → `snapshot.m5_bars` ; W → dernières ~50 H1 ≤ t ; M → dernières ~50 Daily ≤ t. Lookback de touche = `scan_touch_lookback_bars` (3).

Note : comme en live, l'agrégation tourne après chaque scan ; sur un tick M5 sans frontière horaire, seules les touches D sont rafraîchies mais les touches W/M encore actives participent (c'est tout l'intérêt de la confluence cross-cadence).

## 5. TouchStore mémoire

```python
class MemTouchStore:
    # clé (timeframe, tag, bar_time) → (TouchEvent, expires_at)
    def upsert(events, *, expires_at): ...          # remplace par clé
    def load_active(now) -> list[TouchEvent]: ...    # expires_at > now
```
Sémantique identique à `Repository.upsert_touches`/`load_active_touches` (mono-symbole dans le replay).

## 6. Follow-through

```python
def simulate_followthrough(
    *, direction, entry, stop, target, future_bars: list[Period], horizon_bars: int,
) -> FollowThrough
```
Parcourt jusqu'à `horizon_bars` bougies M5 après l'entrée :
- LONG : `STOP` si `bar.low ≤ stop` ; `TARGET` si `bar.high ≥ target`. SHORT : inverse.
- **Cas ambigu** (stop et cible dans la même bougie) → **STOP d'abord** (conservateur).
- `OPEN` si ni l'un ni l'autre dans l'horizon.
- `mfe_r` / `mae_r` = excursion favorable/défavorable max / `risk`, `risk = |entry − stop|` (0 si risk=0).
- `bars_to_resolution`.

`horizon_bars` configurable (défaut **1440** = ~5 jours de trading M5).

## 7. Sortie

`ReplayResult` (pydantic frozen) sérialisé en JSON :
```json
{
  "config": {"symbol":"VANTAGE:XAUUSD","start":"...","end":"...","min_score":0,"horizon_bars":1440},
  "alerts": [
    {"time":"...","direction":"LONG","zone_low":..., "zone_high":..., "score":..., "band":"...",
     "tf_count":..., "members":[["D","S1"],["W","S1"]], "tags":["bracket_reversal"],
     "indicative":{"entry":...,"stop":...,"target":...,"target_label":"W R1","rr":...},
     "followthrough":{"outcome":"TARGET","mfe_r":...,"mae_r":...,"bars":...}}
  ],
  "summary": {"n_alerts":..., "by_month":{...}, "by_band":{...}, "by_direction":{...},
              "win_rate":..., "avg_mfe_r":..., "avg_mae_r":..., "n_open":...}
}
```
+ résumé imprimé en console (table lisible).

## 8. CLI

```bash
python -m agentic_trader.backtest.scan_cli \
    --symbol VANTAGE:XAUUSD --months 3 \
    --min-score 0 --horizon-bars 1440 \
    --output scan_xauusd_3m.json
```
Options : `--from/--to` (alternative à `--months`), `--min-score`, `--horizon-bars`, `--output`. `--months N` ⇒ `end = now`, `start = now − N×30j`.

## 9. Fichiers

| Fichier | Rôle | Action |
|---|---|---|
| `backtest/history.py` | +clé `"60"` (H1) dans `TV_KEYS`/`DEFAULT_N_BARS` | Modifier |
| `backtest/followthrough.py` | `FollowThrough` + `simulate_followthrough` (pur) | Créer |
| `backtest/scan_replay.py` | `MemTouchStore` + `ReplayAlert`/`ReplayResult` + `replay_scan(...)` | Créer |
| `backtest/scan_cli.py` | CLI argparse → `fetch_history` → `replay_scan` → JSON + résumé | Créer |
| tests | unit + replay synthétique | Créer |

## 10. Tests

- **Unit** `simulate_followthrough` : TARGET, STOP, OPEN, cas ambigu (stop+cible même bougie → STOP), MFE/MAE en R, risk=0.
- **Unit** `MemTouchStore` : upsert/replace par clé, expiry (`load_active` filtre).
- **Integration** `replay_scan` sur historique **synthétique** (fetch injecté) construisant une confluence D+W connue → exactement 1 alerte avec la direction/zone attendues + un follow-through déterministe. Multi-cadence : une touche W posée à une heure pleine persiste et s'agrège aux ticks M5 suivants.
- Aucun réseau en test.

## 11. Performance

~25 000 ticks M5 sur 3 mois ; chaque tick reconstruit un snapshot (ATR via pandas). Estimé quelques minutes. Mitigations v1 : log de progression. Optimisation différée si nécessaire : cache des pivots/cpr/atr des TF supérieures par frontière de session (ne recomputer que sur rollover).

## 12. Hors-scope

- PnL monétaire / position sizing (on reste en R-multiples).
- Slippage / spread / frais.
- Multi-symbole simultané (le CLI tourne 1 symbole ; répétable).
- Optimisation paramétrique (grid search de seuils) — possible plus tard sur cette base.
