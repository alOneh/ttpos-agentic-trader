# MTZ Scanner — Design Spec

**Date** : 2026-06-03
**Auteur** : Alain Hippolyte (specs) + Claude (rédaction)
**Statut** : draft, en attente de review utilisateur
**Remplace** : le moteur de signaux entry/SL/TP (S1-S6) comme point d'entrée live (cf. `2026-05-05-agentic-trader-design.md`)

---

## 1. Objectif & changement de paradigme

On abandonne la génération d'**ordres** (entry / SL / TP via S1-S6) comme produit live. Le nouveau produit est un **scanner de confluence multi-timeframe** basé sur le **toucher de zones pivots** :

> Quand le prix vient toucher une zone pivot d'une timeframe (ex : Daily P/R/S, ou la zone PDL-S1), on regarde si une zone pivot d'une **timeframe supérieure** (Weekly, Monthly) est *également* touchée / imbriquée au même endroit. Si oui → c'est une **MTZ (Multiple Timeframe Zone)**, on émet une **alerte scorée** avec les zones en jeu et, en best-effort, une **capture 3-TF** TradingView.

Principes conservés du système existant :
- **Sessions naturelles par asset** (alignement layout TradingView Vantage).
- **Pivots multi-TF dilatés en zones** (ATR) — déjà implémenté.
- **Single-process async**, SQLite pour cache + state, Telegram pour la notif.
- **Modularité & testabilité** : chaque unité (détection touche, agrégation MTZ, scoring) est pure et testée isolément.

Les stratégies `S1-S6` et `backtest/` sont **archivées** : code conservé dans le repo mais **décâblé du live**. Le backtest sera **réorienté** plus tard pour rejouer les touches MTZ historiques (Plan 6).

## 2. Décisions de cadrage (verrouillées avec l'utilisateur)

| # | Décision |
|---|---|
| D1 | Le scanner **remplace** S1-S6 dans le chemin live (S1-S6 archivés, décâblés). |
| D2 | Périmètre concepts v1 = **MTZ-first** (toucher multi-TF + scoring). DPZ / GPZ / FVR / Camarilla = phase ultérieure. |
| D3 | Capture 3-TF = **best-effort dès v1** (échec capture ⇒ alerte texte quand même, jamais de plantage). |
| D4 | **3 scanners indépendants** (M5↔Daily, H1↔Weekly, 12H↔Monthly) à cadences distinctes, agrégés en MTZ. |
| D5 | Scoring = **barème intégral du workbook**, RR calculé sur **niveaux indicatifs**. |
| D6 | Niveaux déclencheurs de touche = **P, R1, R2, R3, R4, S1, S2, S3, S4** (ajout R4/S4). |
| D7 | **CPR (TC/BC)** = contexte/scoring **uniquement**, pas déclencheur de touche. **PDH/PDL** = utilisés via les **brackets** (cf. D9). |
| D8 | **Touche** = mèche d'une des **1-3 dernières bougies** de la TF de scan dans la zone dilatée. |
| D9 | **Zones bracket** `[PDL, S1]` (LONG) et `[PDH, R1]` (SHORT) traitées comme une zone unique ; contrôle dédié si un pivot Weekly/Monthly tombe **à l'intérieur** d'un bracket touché (→ tag `bracket_reversal`). |
| D10 | **Alerte dès ≥ 2 TF** en confluence ; le **point MTZ scoring (25)** ne s'applique qu'à **≥ 3 TF** (D+W+M). |
| D11 | **Seuil d'alerte** : score **≥ 55** (bande *monitor* et au-dessus). Configurable, défaut 55. |
| D12 | **Cache pivots D/W/M** réutilisé par les 3 scanners (pas de recalcul intraday). |

## 3. Niveaux, zones et définition d'une touche

### 3.1 Niveaux surveillés (par TF)

- **Niveaux simples** déclencheurs : `P, R1, R2, R3, R4, S1, S2, S3, S4`.
  - **Ajout requis** : `R4 = R3 + (R2 - R1)` et `S4 = S3 - (S1 - S2)` (workbook). Actuellement `pivots_calc.py` ne calcule que R1-3/S1-3.
- **Zones bracket** déclencheuses : `[PDL, S1]` (biais LONG) et `[PDH, R1]` (biais SHORT).
- **Contexte uniquement (non déclencheur)** : `TC, BC` (classe CPR), `P` sert aussi de référence de biais.

### 3.2 Dilatation → zone

Réutilise la dilatation ATR existante (`dilation(pivot_tf, atr_pivot_tf, atr_d)` : `0.15 × ATR_TF`, plafonné à `0.50 × ATR_D` pour W/M). Chaque niveau simple devient `[value − dilation, value + dilation]`. Une **bracket zone** = `[min(level_a, level_b) − dilation, max(level_a, level_b) + dilation]`.

### 3.3 Touche

Une **touche** est détectée si la **mèche** d'au moins une des **1-3 dernières bougies clôturées** de la TF de scan entre dans la zone (simple ou bracket) :

- Zone **support** (S1-S4, P en-dessous du prix, bracket `[PDL,S1]`) : touche si `bar.low ≤ zone.high` et `bar.low ≥ zone.low − marge` (la mèche basse pénètre la zone par le haut). Biais **LONG**.
- Zone **résistance** (R1-R4, P au-dessus du prix, bracket `[PDH,R1]`) : touche si `bar.high ≥ zone.low` et `bar.high ≤ zone.high + marge`. Biais **SHORT**.

Le **type** (support/résistance) du niveau détermine le **biais** du setup. `P` est classé support ou résistance selon la position du prix courant relativement à `P`.

## 4. Architecture des 3 scanners + agrégateur

### 4.1 Scanners indépendants

| Unité | Cadence | Pivots déclencheurs | Bougies de touche |
|---|---|---|---|
| `ScannerUnit("D")` | 5 min (`:00:02/:05:02/…`) | Daily | M5 (`n=50`) |
| `ScannerUnit("W")` | 1 h | Weekly | H1 |
| `ScannerUnit("M")` | 12 h | Monthly | Daily* |

\* **Implémentation** : la cadence Monthly tourne 2×/jour mais détecte les touches sur des **bougies Daily**, pas 12H — TradingView ne sert pas la résolution `"720"` (12H) pour nos symboles (timeout). Daily est le bon analogue d'exécution pour des zones Monthly (Daily/Monthly ≈ 1/30, cohérent avec M5/Daily et H1/Weekly). Le 12H reste la granularité du *layout de capture* (Plan 5).

Chaque `ScannerUnit(tf)` :
1. Récupère le `PivotSet` de **sa** TF depuis le **cache** (calculé une fois/session — cf. §7).
2. Fetch les **bougies** de sa TF (M5/H1/12H) — seule donnée re-fetchée à chaque cadence.
3. Calcule les zones (niveaux simples + brackets) et détecte les **touches** (`TouchEvent`).
4. Écrit/rafraîchit ses touches actives dans le **`TouchStore`** (SQLite).

### 4.2 Agrégateur MTZ

Lancé **après chaque scan** (sur la cadence la plus fine = 5 min, qui voit l'état le plus à jour) :
1. Lit toutes les **touches actives** du `TouchStore` (toutes TF, par symbole).
2. **Cluster inter-TF** : regroupe les zones touchées qui se chevauchent ou sont confluentes (seuil `confluence_threshold_atr_d`, déjà en config). Réutilise la logique de `analysis/confluence.py` étendue aux zones (bornes low/high), pas seulement aux valeurs.
3. **Contrôle bracket-reversal** (D9) : si un pivot W et/ou M tombe à l'intérieur d'un bracket Daily touché → marque le cluster `bracket_reversal`.
4. Émet un `MTZSetup` par cluster de `tf_count ≥ 2` : `{symbol, direction, zone_low, zone_high, members[(tf, tag)], tf_count, tags}`.

### 4.3 Pourquoi 3 scanners et pas un cycle unifié

Choix utilisateur (D4). Le re-scan H1 (toutes les heures) et 12H (toutes les 12h) sont explicites et indépendants : un changement de bougie H1 peut activer/désactiver une touche Weekly sans attendre un cycle M5. L'agrégation reste cohérente car toutes les touches transitent par le `TouchStore` partagé. Alternative écartée : moteur single-cycle 5 min évaluant les 3 TF d'un coup (plus simple mais moins fidèle à la demande et au sens des cadences).

## 5. Scoring (barème workbook intégral)

`scanner/scoring.py` reproduit l'onglet *Scoring* du workbook. Score = somme des points ; bande dérivée du total.

| Facteur | Condition | Points | Source réutilisée |
|---|---|---|---|
| TrendX Strong Alignment | prix au-dessus/en-dessous de Monthly+Weekly+Daily P | **20** | `analysis/bias.py` |
| TrendX Buy/Sell Alignment | macro mixte mais Weekly+Daily alignés | **12** | `analysis/bias.py` |
| Thin CPR | width < rolling P25 | **15** | `analysis/cpr_width.py` |
| Moderate CPR | P25 ≤ width ≤ P75 | **7** | `analysis/cpr_width.py` |
| Wide CPR | width > P75 | **−10** | `analysis/cpr_width.py` |
| DPZ Tier 1 / Tier 2 | (non implémenté v1) | **0** | — |
| GPZ | (non implémenté v1) | **0** | — |
| **MTZ** | **≥ 3 TF** en confluence après dilatation | **25** | `mtz.py` (D10) |
| FVR / Value Sweep | (non implémenté v1) | **0** | — |
| Price Reaction | bougie de rejet / engulfing / close back à travers la zone | **15** | `analysis/candles.py` |
| RR ≥ 3 / ≥ 4 / ≥ 5 | sur niveaux indicatifs | **10 / 15 / 20** (le plus haut, non cumulatif) | §5.1 |

> Note : TrendX Strong et Buy/Sell sont **mutuellement exclusifs** (on prend le plus élevé applicable). Idem pour les 3 classes CPR. Idem pour les paliers RR.

**Bandes** (workbook) : `85-100` *excellent* · `70-84` *high* · `55-69` *monitor* · `<55` *low*.
**Seuil d'alerte** : `score ≥ scan_min_score` (config, défaut **55**) — D11.

### 5.1 Niveaux indicatifs pour le RR

On ne place pas d'ordre, mais on calcule un RR indicatif pour les points RR du barème :
- **Entry indicatif** = valeur du niveau touché (ou centre de la zone bracket).
- **Stop indicatif** = **bord externe** de la zone MTZ combinée (côté opposé au sens du setup), + petit buffer ATR.
- **Cible indicative** = **pivot suivant** dans le sens du setup (sur la TF du membre de plus haute TF de la zone).
- `RR = |cible − entry| / |entry − stop|`.

## 6. Notification

### 6.1 Format du message (alerte MTZ)

```
🔵 MTZ LONG — XAUUSD   (score 85 / excellent)
━━━━━━━━━━━━━━━━━━
🧲 Zone confluente : 2412.0 – 2416.5  (3 TF)
   • Daily   : bracket PDL–S1
   • Weekly  : S1
   • Monthly : P
🏷  tags : bracket_reversal
─────────────
📈 Bias TrendX : strong_buy (M+W+D)
🪟 CPR Daily   : thin (width 0.18%, < P25)
📐 RR indicatif: 3.4  (entry 2414.0 · stop 2410.8 · cible 2425.0 Weekly R1)
─────────────
🧮 Score : align 20 · CPR thin 15 · MTZ 25 · réaction 15 · RR≥3 10 = 85
```
*(Format indicatif, finalisé à l'implémentation. Décimales dérivées de `MarketInfo.pricescale`.)*

### 6.2 Capture 3-TF (best-effort) — D3

Interface `ChartCapturer` (Protocol) :
- `TradingViewCapturer` : pilote le MCP TradingView → `layout_switch(<layout 3-TF>)` → `chart_set_symbol(symbol)` → `capture_screenshot("full")` → renvoie le chemin image. Layout cible : **5m+Daily / H1+Weekly / 12H+Monthly** (layout existant de l'utilisateur, id en config).
- `NullCapturer` : no-op (déploiement headless/Docker sans TV Desktop).

**Best-effort strict** : toute exception du capturer est loguée et avalée ; l'alerte texte+score part quand même. La capture, si dispo, est jointe au message Telegram (`sendPhoto` + caption) sinon `sendMessage`.

### 6.3 Dedup des alertes scan

Pas de ré-alerte sur la même `(symbol, direction, région MTZ arrondie, tf_count)` dans une fenêtre configurable (`scan_dedup_window_min`, défaut p.ex. 60 min). Persisté dans `scan_notif_log`. La détection écrit toujours dans `scan_alerts` (audit complet, indépendant du dedup).

## 7. Cache pivots D/W/M (D12)

`data/cache.py` (`PivotsCache`) existe déjà : **read-through** expirant sur `session_end`. Les pivots Daily/Weekly/Monthly sont donc calculés **une fois par session** et réutilisés tant que `now < session_end`. Les 3 scanners **partagent ce cache** → **aucun recalcul intraday** des pivots HTF ; seules les bougies (M5/H1/12H) sont re-fetchées à chaque cadence.

Vérification à l'implémentation : `session_end` correctement posé pour **Weekly** et **Monthly** par le fetcher (`Period.time + interval` de la TF). Le calcul de `R4/S4` doit être inclus dans le `PivotSet` mis en cache (invalidation naturelle : nouveau champ ⇒ on bump la sérialisation, recompute au prochain cycle).

## 8. Modèle de domaine (nouveau — `domain/scan.py`)

```python
class TouchEvent(BaseModel):          # frozen
    symbol: str
    timeframe: Literal["D","W","M"]
    zone_kind: Literal["level","bracket"]
    tag: str                          # "S1", "R2", "PDL-S1", "PDH-R1", …
    zone_low: float
    zone_high: float
    side: Literal["support","resistance"]
    direction: Literal["LONG","SHORT"]
    bar_time: datetime                # bougie ayant touché
    seen_at: datetime

class MTZSetup(BaseModel):            # frozen
    symbol: str
    direction: Literal["LONG","SHORT"]
    zone_low: float
    zone_high: float
    members: list[tuple[str,str]]     # [(tf, tag), …]
    tf_count: int
    tags: list[str]                   # ["bracket_reversal", …]

class ScanAlert(BaseModel):           # frozen
    id: str                           # sha1(symbol|direction|region|tf_count|window)
    setup: MTZSetup
    score: "Score"
    indicative: dict                  # {entry, stop, target, target_label, rr}
    bias: str
    cpr_class: str
    created_at: datetime

class Score(BaseModel):               # frozen
    total: int
    band: Literal["excellent","high","monitor","low"]
    breakdown: dict[str,int]          # {"align":20, "cpr_thin":15, "mtz":25, …}
```

## 9. Persistence (ajouts `schema.sql`)

```sql
CREATE TABLE touches (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,          -- "D","W","M"
    tag TEXT NOT NULL,                -- "S1","R2","PDL-S1",…
    zone_low REAL NOT NULL,
    zone_high REAL NOT NULL,
    side TEXT NOT NULL,
    direction TEXT NOT NULL,
    bar_time INTEGER NOT NULL,
    seen_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,      -- touche active jusqu'à expiry (ex: fin de N bougies de la TF)
    PRIMARY KEY (symbol, timeframe, tag, bar_time)
);
CREATE INDEX idx_touches_active ON touches(symbol, expires_at);

CREATE TABLE scan_alerts (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    score INTEGER NOT NULL,
    tf_count INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    payload_json TEXT NOT NULL        -- ScanAlert sérialisé
);
CREATE INDEX idx_scan_alerts_time ON scan_alerts(created_at DESC);

CREATE TABLE scan_notif_log (
    alert_id TEXT PRIMARY KEY,
    sent_at INTEGER NOT NULL,
    status TEXT NOT NULL,             -- "sent" | "failed" | "suppressed_by_window"
    error TEXT
);
```

Tables existantes (`pivots_cache`, `ohlcv_cache`, `cycle_health`) conservées. Tables S1-S6 (`signals_log`, `pending_breaks`, `notif_log`) conservées mais **non alimentées** par le scanner (archivées).

## 10. Arborescence (nouveau / modifié)

```
src/agentic_trader/
  scanner/                      # NOUVEAU
    __init__.py
    zones.py        # zones dilatées : niveaux simples + brackets
    touch.py        # TouchDetector → list[TouchEvent]
    mtz.py          # MTZAggregator → list[MTZSetup]
    scoring.py      # barème workbook + niveaux indicatifs RR → Score
    engine.py       # ScannerUnit(tf) + run_scan(tf) + aggregate()
  domain/
    scan.py         # NOUVEAU : TouchEvent, MTZSetup, ScanAlert, Score
    pivots.py       # MODIF : tags R4/S4
  analysis/
    pivots_calc.py  # MODIF : compute R4/S4
    confluence.py   # MODIF (ou helper) : clustering par zones (low/high)
  data/
    repository.py   # MODIF : CRUD touches / scan_alerts / scan_notif_log
    schema.sql      # MODIF : nouvelles tables
    store.py        # NOUVEAU (option) : TouchStore (wrapper repo)
  notify/
    scan_formatter.py  # NOUVEAU
    capture.py         # NOUVEAU : ChartCapturer + TV + Null
    telegram.py        # MODIF : sendPhoto best-effort
  live/
    scan_scheduler.py  # NOUVEAU : 3 jobs APScheduler + aggregate
    main.py            # MODIF : lance le scan scheduler (S1-S6 décâblés)
  strategies/          # ARCHIVÉ (décâblé du live, conservé)
  backtest/            # ARCHIVÉ (réorienté MTZ en Plan 6)
```

## 11. Configuration

### 11.1 `.env` (ajouts)
```
SCAN_MIN_SCORE=55
SCAN_DEDUP_WINDOW_MIN=60
SCAN_TOUCH_LOOKBACK_BARS=3
CAPTURE_ENABLED=false           # true uniquement si TV Desktop + MCP joignables
CAPTURE_TV_LAYOUT_ID=           # id du layout 3-TF
```

### 11.2 `config/watchlist.yaml` (ajouts `defaults`)
```yaml
defaults:
  scan_cadences:                # cadences des 3 scanners
    D: "5m"
    W: "1h"
    M: "12h"
  watched_levels: [P, R1, R2, R3, R4, S1, S2, S3, S4]
  bracket_zones: [[PDL, S1], [PDH, R1]]
  confluence_threshold_atr_d: 0.30   # déjà existant, réutilisé
  mtz_min_tf_for_alert: 2
  mtz_min_tf_for_score: 3
```

## 12. Stratégie de test (TDD)

| Niveau | Couverture |
|---|---|
| **Unit** | `pivots_calc` R4/S4 (+ hypothesis sur invariants pivots) ; `zones` (niveaux + brackets, dilatation W/M plafonnée) ; `touch` (mèche dans/hors zone, 1-3 bougies, support vs résistance, biais) ; `mtz` (clusters 0/2/3 TF, bracket-reversal HTF-dans-bracket, direction cohérente) ; `scoring` (chaque facteur, exclusivités mutuelles, bandes, RR indicatif). |
| **Integration** | un scan complet mocké (TV + Telegram + SQLite tmp) ; **multi-cadence** : une touche Weekly écrite par le scan H1 persiste et s'agrège lors d'un scan M5 ultérieur ; dedup d'alerte sur fenêtre ; capturer mocké (succès + échec best-effort). |
| **Smoke réel** | script hors CI : un symbole live, vérifie pas d'exception et formatage d'alerte. |

## 13. Hors-scope v1 (phases ultérieures)

- **Camarilla** H3/L3/H4/L4, **Money Zone**, **DPZ**, **GPZ**, **FVR** (+ leurs points de scoring) — Plan 5+.
- **Backtest MTZ** réorienté (follow-through des touches) — Plan 6.
- Capture 3-TF en environnement headless (serveur) — dépend d'une instance TV pilotable côté serveur.
- Exécution d'ordres.

## 14. Découpage en plans

1. **Fondations & archivage** : R4/S4 (calc + domaine + tests) ; `domain/scan.py` ; décâblage S1-S6/backtest du live ; ajouts schema.
2. **Détection** : `zones` + `touch` + `TouchStore` (CRUD + expiry).
3. **Agrégation & scoring** : `mtz` (clusters, brackets) + `scoring` (barème + RR indicatif).
4. **Live & notif** : `scan_scheduler` (3 cadences) + `scan_formatter` + dedup + Telegram + `main`.
5. **Capture 3-TF** best-effort (MCP TradingView, `ChartCapturer`).
6. **Backtest MTZ** réorienté.

## 15. Décisions notables (synthèse mémoire)

1. Scanner de **touches MTZ** remplace les ordres S1-S6 en live ; S1-S6 archivés.
2. **3 scanners indépendants** (M5↔D / H1↔W / 12H↔M) + agrégateur via `TouchStore` partagé.
3. Déclencheurs = **P, R1-4, S1-4** + **brackets PDL-S1 / PDH-R1** ; CPR & PDH/PDL en contexte.
4. **Alerte ≥ 2 TF**, **point MTZ scoring ≥ 3 TF** ; seuil d'alerte **score ≥ 55**.
5. Scoring = **barème workbook intégral**, RR sur **niveaux indicatifs**.
6. Capture 3-TF **best-effort** (jamais bloquante).
7. **Cache pivots D/W/M** réutilisé (pas de recalcul intraday).
