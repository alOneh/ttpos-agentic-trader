# Agentic Trader — Design Spec

**Date** : 2026-05-05
**Auteur** : Alain Hippolyte (specs) + Claude (rédaction)
**Statut** : draft, en attente de review utilisateur

---

## 1. Objectif

Construire un assistant Python autonome qui, toutes les 5 minutes, scanne une watchlist de marchés, calcule des pivots multi-timeframe, détecte des setups de trading basés sur l'interaction du prix avec ces pivots, et émet des signaux vers un canal Telegram. Pas d'exécution sur les marchés à ce stade — uniquement de la détection et de la notification.

L'agent doit être :
- **Modulable** : chaque stratégie est une unité indépendante, activable par symbole, backtestable de façon isolée.
- **Backtest-ready** : la logique de détection est rejouable sur des données historiques avec simulation PnL (V2 dès le départ).
- **Persistant** : un cache SQLite stocke les pivots calculés et le state inter-cycle (cassures en attente de retest, historique de notifications).
- **Aligné avec le visuel TradingView Vantage** : sessions naturelles par asset (PDH/PDL respectent la session du symbole tel qu'affiché sur le broker).

## 2. Périmètre

### 2.1 Watchlist par défaut

Tous les symboles préfixés par `VANTAGE:` :

| Asset | Symbole TV |
|---|---|
| Or | `VANTAGE:XAUUSD` |
| Bitcoin | `VANTAGE:BTCUSD` |
| Dow Jones 30 | `VANTAGE:DJ30` |
| Nasdaq 100 | `VANTAGE:NAS100` |
| GBP/USD | `VANTAGE:GBPUSD` |
| EUR/USD | `VANTAGE:EURUSD` |

Configurable via `config/watchlist.yaml`.

### 2.2 Timeframes

| TF | Rôle |
|---|---|
| **M5** | Timeframe d'exécution. Les setups sont détectés sur la bougie M5 qui vient de clôturer. |
| **4H** | **Contexte uniquement**. Les pivots 4H sont calculés et présents dans le snapshot ; ils peuvent contribuer aux confluences (S5) et apparaissent dans le message Telegram comme zonage CPR (placement entry/SL/TP). Aucune stratégie ne déclenche un signal sur un trigger 4H seul. |
| **Daily** | Pivots déclenchant les signaux **mode `intraday`**. |
| **Weekly** | Pivots déclenchant les signaux **mode `swing`**. |
| **Monthly** | Pivots déclenchant les signaux **mode `swing`**. |

Sur tous les TF, on calcule : `P, R1, R2, R3, S1, S2, S3, TC, BC, PDH, PDL` (= high/low/close du **bar précédent** de la TF).

### 2.3 Sessions

Sessions naturelles de chaque asset, telles que servies par TradingView pour le symbole `VANTAGE:*`. Pas d'agrégation maison : `tradingview_api.fetch_ohlcv(symbol, timeframe="D")` retourne déjà des bars alignés sur la session du symbole. Conséquence : les frontières de sessions diffèrent entre crypto, FX, indices — c'est voulu, ça garantit l'alignement avec le layout TradingView Vantage de l'utilisateur.

## 3. Stratégies

Les **6 stratégies** sont indépendantes, chacune implémente l'interface `Strategy.detect(snapshot, state) -> list[Signal]`. Elles sont activables par symbole. Chaque stratégie est évaluée pour les modes pertinents (intraday = pivots Daily, swing = pivots Weekly + Monthly).

### 3.1 Pivots cibles par stratégie

| ID | Nom | Pivots utilisés |
|---|---|---|
| **S1** | Bounce / Rejet | PDH, PDL, R1, S1 |
| **S2** | Breakout du Pivot Central | P uniquement |
| **S3** | Break & Retest | tous (P, R1-3, S1-3, PDH, PDL) |
| **S4** | Liquidity Sweep | PDH, PDL, R1, S1, R2, S2 |
| **S5** | Hot Zone (confluence) | toute zone de confluence (≥ 2 pivots empilés) |
| **S6** | Sweet Spot | PDH/R1 (SHORT) ou PDL/S1 (LONG), Daily uniquement |

### 3.2 Règles de détection détaillées

#### S1 — Bounce / Rejet

**Trigger** sur la bougie M5 qui vient de clôturer (la « bougie courante ») :
- Le low (LONG) ou high (SHORT) d'une des **3 dernières bougies M5** (incluant la courante) a touché la **zone dilatée** d'un pivot cible.
- La bougie courante est une **rejection** :
  - `long_wick(side, ratio_min=0.6)` : la mèche du côté testé représente ≥ 60% de la range totale `(high-low)` de la bougie, et la close est dans le tiers opposé ;
  - OR `engulfing(side)` : sa range englobe celle de la bougie précédente, et close dans le sens du rejet ;
  - OR `doji(body_ratio_max=0.1)` AVEC `dominant_wick(side)` : body ≤ 10% de la range, et la mèche du côté testé est ≥ 2× la mèche opposée.

**SL** : `pivot_value - 1.10 × atr_dilation` pour LONG (`+1.10 × atr_dilation` pour SHORT). Soit la borne extérieure de la zone dilatée, augmentée de 10% pour ne pas être stoppé par un tick de bruit qui touche pile la frontière.

**TPs** : ladder du `PivotSet`, dans la direction du signal. Pour un LONG depuis PDL Daily : `[Daily P, Daily R1, Daily PDH]`. Pour un SHORT depuis PDH Daily : `[Daily P, Daily S1, Daily PDL]`.

#### S2 — Breakout du Pivot Central

**Trigger** : la bougie M5 courante clôture au-delà de P (au-dessus pour LONG, en dessous pour SHORT), ET son `body = |close - open|` est `> 0.5 × ATR_M5`. **Une seule fois par session de la TF du pivot** par direction : un signal S2 LONG sur P Daily ne peut se redéclencher avant la prochaine session Daily du symbole. Implémenté via requête sur `signals_log` filtrée sur `(symbol, strategy="S2", direction, trigger_pivot.tf, trigger_pivot.tag, cycle_time >= session_start_of_pivot_tf)`.

**SL** : `P + 0.10 × ATR_M5` pour SHORT (`-0.10 × ATR_M5` pour LONG).

**TPs** : LONG → `[R1, PDH, R2]` ; SHORT → `[S1, PDL, S2]`.

**Note** : S2 ne crée pas explicitement de `PendingBreak`. La détection générique de cassure (§6.5, appelée par le cycle à l'étape 5) en crée un automatiquement à partir de la même bougie M5, accessible ensuite à S3.

#### S3 — Break & Retest

**Pré-requis** : un `PendingBreak` existe en state (cassure détectée ≤ 24 bougies M5 ago, body > 0.5 × ATR_M5 lors de la cassure).

**Trigger** : la bougie M5 courante touche la zone dilatée du pivot cassé **depuis le côté de la cassure** (depuis au-dessus si la cassure était LONG, depuis en dessous si SHORT), ET clôture qui confirme la cassure (close au-dessus du pivot pour LONG, en dessous pour SHORT).

**SL** : `pivot_value - 1.10 × atr_dilation` pour LONG (`+1.10 × atr_dilation` pour SHORT). Pareil que S1, on protège contre un tick de bruit qui repique sous le niveau cassé.

**TPs** : ladder dans le sens du retest, depuis le pivot suivant après celui cassé.

**Expiration** : si la fenêtre de 24 bars passe sans retest, le `PendingBreak` est supprimé du state à la prochaine itération de `state.expire(now)`.

#### S4 — Liquidity Sweep

**Trigger** : sur la bougie M5 courante :
- La mèche traverse **au-delà** de la zone dilatée d'un pivot cible (extension supplémentaire de `0.10 × atr_dilation` — donc le high (SHORT) ou low (LONG) est plus loin que `pivot ± 1.10 × atr_dilation`) ;
- ET la close revient à l'**intérieur** du pivot (en deçà du niveau brut, du côté opposé à la mèche).

C'est volontairement plus profond que S1 : S1 capte un rejet « propre » dans la zone dilatée, S4 capte une chasse de stops vraiment au-delà. Les deux peuvent émettre sur la même bougie (signaux séparés, tags différents).

**SL** : `wick_extreme + 0.10 × atr_dilation` pour SHORT (- pour LONG), où `wick_extreme = bar.high` (SHORT) ou `bar.low` (LONG). On protège contre une nouvelle mèche qui irait chercher 1 tick plus loin.

**TPs** : `[P, pivot opposé du PivotSet]` dans le sens du retour.

#### S5 — Hot Zone (confluence)

**Pré-requis** : `analysis.confluence.detect()` a identifié ≥ 1 `ConfluenceZone` pour ce symbole. Une `ConfluenceZone` = ≥ 2 pivots dont les valeurs sont à `< 0.30 × ATR_D` les uns des autres. Au moins un membre doit être Daily/Weekly/Monthly (4H seul ne suffit pas, mais 4H peut être ajouté à une confluence avec D/W/M).

**Trigger** : exactement les mêmes règles que S1 (long_wick / engulfing / doji), mais le pivot touché doit appartenir à une `ConfluenceZone`.

**SL** : au-delà de la borne extérieure de la `ConfluenceZone` (le `min` de `dilated_low` pour LONG, le `max` de `dilated_high` pour SHORT).

**TPs** : ladder du membre de plus haute TF de la zone (priorité Monthly > Weekly > Daily > 4H).

#### S6 — Sweet Spot

**Pré-requis** :
- Pivot Daily uniquement (PDH/R1 pour SHORT, PDL/S1 pour LONG) ;
- ET la CPR Daily du jour est « narrow » : `cpr_width_D < 0.5 × moyenne(cpr_width_D, last 20 sessions Daily)`.

**Trigger / SL / TPs** : identiques à S1.

**Effet** : tag `sweet_spot` ajouté au signal, priorité maximale dans le formatter Telegram (entête « 💎 SWEET SPOT »).

### 3.3 Tags transversaux

Calculés post-détection et attachés à `Signal.tags` :

| Tag | Condition |
|---|---|
| `confluence` | ≥ 2 pivots empilés (≤ 0.30 × ATR_D) à proximité du pivot trigger |
| `sweet_spot` | S6 trigger OU S1 Daily qui matche les conditions S6 |
| `narrow_cpr_d` | `cpr_width_D < 0.5 × moyenne 20 sessions` |
| `cpr_h4_inside` / `cpr_h4_above` / `cpr_h4_below` | Position de l'entry vs la CPR 4H (TC/BC) |

### 3.3.1 Signaux dupliqués entre stratégies (S1 / S5 / S6)

S5 et S6 sont des **strict supersets** des conditions S1 (avec un filtre additionnel : confluence pour S5, narrow CPR + pivot Daily clé pour S6). Conséquence : sur une même bougie M5, S1 et S5 peuvent émettre tous les deux, ou S1 et S6, ou les trois.

**Règle de design** :
- **Couche détection** : chaque stratégie émet indépendamment dans `signals_log`. Les 3 signaux S1/S5/S6 coexistent → backtest individuel possible (utile pour comparer S1 « tous setups » vs S5 « confluence only » vs S6 « sweet spot only » sur la même période).
- **Couche notif Telegram** : pour le même `(symbol, direction, trigger_pivot, cycle_time)`, on n'envoie qu'**un seul message**, en privilégiant la plus haute priorité : `S6 > S5 > S1`. Le signal envoyé porte alors les tags des stratégies superseded (ex : un message S6 inclura aussi le tag `confluence` si la confluence est présente).
- Cette règle est appliquée par `notif_policy.filter()` avec un `priority_map = {"S6": 3, "S5": 2, "S1": 1, ...}`.

S2, S3, S4 ne sont pas dans cette chaîne — ils ont des triggers distincts, leurs signaux ne se chevauchent pas avec S1/S5/S6 sur la même bougie.

### 3.4 Mode (intraday / swing)

- `intraday` : pivots Daily.
- `swing` : pivots Weekly et Monthly. Un même symbole peut émettre plusieurs signaux dans le même cycle (ex : S1 intraday sur PDL Daily + S1 swing sur PDL Weekly), traités comme indépendants.

S2 est principalement intraday (P Daily) ; sa version swing existe (P Weekly, P Monthly) et est activée par défaut.

## 4. Architecture

### 4.1 Process model

**Option choisie : process async unique** (cf. brainstorming, Option A).

Un seul process Python qui tourne en continu :
- `AsyncIOScheduler` (APScheduler) déclenche `cycle()` toutes les 5 min, aligné UTC au tick `:00:02 / :05:02 / :10:02` (offset de 2s pour laisser TV publier la bougie M5 fraîchement clôturée).
- Une connexion `TradingViewClient` persistante, partagée entre tous les fetch (le wheel est conçu pour ça).
- `asyncio.gather` parallélise les fetch multi-symbole × multi-TF.
- SQLite via `aiosqlite`.
- Telegram via `httpx.AsyncClient` directement sur l'API HTTP (pas de framework bot).
- `max_instances=1, coalesce=True` sur le scheduler : un cycle ne se lance jamais en parallèle d'un autre ; si un cycle traîne, le suivant attend (et les ticks ratés sont coalescés).

### 4.2 Arborescence

```
ttpos-agentic-trader/
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── config/
│   └── watchlist.yaml
├── data/                       # gitignoré (volume Docker)
│   └── agent.db
├── docs/superpowers/specs/
│   └── 2026-05-05-agentic-trader-design.md
├── vendor/
│   └── tradingview_api-0.1.0-py3-none-any.whl
├── src/agentic_trader/
│   ├── config.py               # pydantic-settings (env + yaml merge)
│   ├── domain/                 # types purs, aucune I/O
│   │   ├── pivots.py
│   │   ├── signal.py
│   │   ├── snapshot.py
│   │   └── state.py
│   ├── data/                   # I/O TV + persistence
│   │   ├── fetcher.py          # wraps tradingview_api (WS partagé, fetch parallèle)
│   │   ├── cache.py            # SQLite cache w/ session-aligned expiry
│   │   ├── repository.py       # CRUD signals/pending_breaks/notif_log
│   │   └── schema.sql
│   ├── analysis/               # calculs purs (DataFrame in → values out)
│   │   ├── pivots_calc.py
│   │   ├── atr.py
│   │   ├── candles.py
│   │   ├── breaks.py
│   │   └── confluence.py
│   ├── strategies/
│   │   ├── base.py
│   │   ├── s1_bounce.py
│   │   ├── s2_breakout.py
│   │   ├── s3_break_retest.py
│   │   ├── s4_sweep.py
│   │   ├── s5_hot_zone.py
│   │   ├── s6_sweet_spot.py
│   │   └── registry.py
│   ├── notify/
│   │   ├── telegram.py
│   │   └── formatter.py
│   ├── live/
│   │   ├── scheduler.py
│   │   ├── cycle.py
│   │   └── main.py
│   ├── backtest/
│   │   ├── runner.py
│   │   ├── pnl.py
│   │   ├── metrics.py
│   │   └── cli.py
│   └── observability/
│       ├── logging.py          # structlog config
│       └── healthcheck.py
└── tests/
    ├── unit/
    ├── fixtures/
    └── integration/
```

### 4.3 Data flow d'un cycle

```
                ┌────────────────────────────────────────────────────┐
  scheduler ──► │  cycle() (UTC :00:02 / :05:02 / :10:02 …)         │
                │                                                    │
                │  ① fetch M5 (n_bars=50) + check cache TF↑ pour     │
                │      chaque symbole (asyncio.gather)               │
                │  ② TF↑ en cache miss/expired :                     │
                │     fetch via TV → compute pivots → cache          │
                │  ③ build MarketSnapshot par symbole                │
                │  ④ load state (pending_breaks not expired)         │
                │  ⑤ détection nouvelles cassures sur bougie courante│
                │     → update state                                 │
                │  ⑥ for strategy in registry.enabled():             │
                │       for snap in snapshots:                       │
                │         signals += strategy.detect(snap, state)    │
                │  ⑦ persist signals + state                         │
                │  ⑧ notif Telegram (filtre dedup notif appliqué ici)│
                └────────────────────────────────────────────────────┘
```

## 5. Modèle de domaine

```python
# domain/pivots.py
class PivotLevel(BaseModel):
    tag: Literal["P","R1","R2","R3","S1","S2","S3","TC","BC","PDH","PDL"]
    timeframe: Literal["4H","D","W","M"]
    value: float
    dilated_low: float
    dilated_high: float

class PivotSet(BaseModel):
    timeframe: Literal["4H","D","W","M"]
    symbol: str
    session_end: datetime         # cache expiry
    cpr_width: float              # |TC - BC|
    cpr_width_avg_20: float       # used for narrow_cpr_d / S6
    levels: list[PivotLevel]
    
    def by_tag(self, tag: str) -> PivotLevel: ...
    def ladder(self, direction: Literal["LONG","SHORT"], from_level: str) -> list[PivotLevel]: ...

# domain/snapshot.py
class MarketSnapshot(BaseModel):
    symbol: str
    cycle_time: datetime
    m5_bars: list[Period]         # last ~50 M5 bars
    pivots: dict[Literal["4H","D","W","M"], PivotSet]
    atr_m5: float
    atr_d: float
    market_info: MarketInfo       # for tick size / formatting

# domain/signal.py
class Signal(BaseModel):
    id: str                       # sha1(symbol|strategy|pivot_id|direction|cycle_time)
    symbol: str
    strategy: Literal["S1","S2","S3","S4","S5","S6"]
    direction: Literal["LONG","SHORT"]
    mode: Literal["intraday","swing"]
    trigger_pivot: PivotLevel
    entry: float
    stop_loss: float
    targets: list[tuple[float, str]]  # [(price, "Daily R1"), …]
    tags: list[str]
    context_h4: dict | None       # {"cpr_h4_tc": ..., "cpr_h4_bc": ..., "position": "inside"}
    cycle_time: datetime
    
    @computed_field
    def r_multiples(self) -> list[float]:
        risk = abs(self.entry - self.stop_loss)
        return [abs(t[0] - self.entry) / risk for t in self.targets]

# domain/state.py
class PendingBreak(BaseModel):
    symbol: str
    pivot_tag: str
    pivot_tf: Literal["D","W","M"]
    pivot_value: float
    direction: Literal["LONG","SHORT"]
    break_price: float
    break_time: datetime
    expires_at: datetime          # break_time + 24*5min

class AgentState(BaseModel):
    pending_breaks: list[PendingBreak]
    
    def merge(self, new_breaks: list[PendingBreak]) -> "AgentState": ...
    def expire(self, now: datetime) -> "AgentState": ...
    def find_break(self, symbol: str, pivot_tag: str, pivot_tf: str) -> PendingBreak | None: ...
```

## 6. Calculs

### 6.1 Formules pivots (par TF)

À partir du **bar précédent clôturé** de la TF (PDH = high, PDL = low, PDC = close) :

```
P    = (PDH + PDL + PDC) / 3
BC   = (PDH + PDL) / 2
TC   = 2*P - BC
R1   = 2*P - PDL          S1 = 2*P - PDH
R2   = P + (PDH - PDL)    S2 = P - (PDH - PDL)
R3   = PDH + 2*(P - PDL)  S3 = PDL - 2*(PDH - P)
CPR_width = |TC - BC|
```

`PDH` et `PDL` sont des `PivotLevel` au même titre que les autres (tag = "PDH" / "PDL").

### 6.2 ATR & dilatation

ATR(14) classique (Wilder's smoothing). Le buffer de dilatation appliqué à un pivot :

```python
def dilation(pivot_tf: str, atr_pivot_tf: float, atr_d: float) -> float:
    base = 0.15 * atr_pivot_tf
    if pivot_tf in ("W", "M"):
        cap = 0.50 * atr_d        # plafond pour éviter zones démesurées en W/M
        return min(base, cap)
    return base
```

`PivotLevel.dilated_low = value - dilation`, `dilated_high = value + dilation`.

### 6.3 Confluence

```python
def detect_confluence(
    pivots: list[PivotLevel],   # tous TF mélangés
    threshold: float,            # 0.30 * ATR_D par défaut
) -> list[ConfluenceZone]:
    # Tri par valeur ; agrège tout pivot dont la distance au cluster courant < threshold.
    # Retourne ConfluenceZone(low, high, members) pour chaque cluster de taille ≥ 2.
```

Une `ConfluenceZone` est valide pour S5 si elle contient au moins un pivot D/W/M.

### 6.4 Patterns de bougie

```python
def long_wick_rejection(bar: Period, side: Literal["upper","lower"], min_wick_ratio: float = 0.6) -> bool
def bullish_engulfing(prev: Period, cur: Period) -> bool
def bearish_engulfing(prev: Period, cur: Period) -> bool
def is_doji(bar: Period, body_ratio_max: float = 0.1) -> bool
def has_dominant_wick(bar: Period, side: Literal["upper","lower"]) -> bool  # mèche testée ≥ 2× mèche opposée
```

### 6.5 Détection de cassure

```python
def detect_break(
    bar: Period,                 # bougie M5 fraîchement clôturée
    pivots: list[PivotLevel],
    atr_m5: float,
    body_min_atr_m5: float = 0.50,
) -> list[PendingBreak]:
    # Pour chaque pivot, si |close - open| > body_min_atr_m5 * atr_m5
    # ET close traverse le pivot de l'open au close → PendingBreak
```

## 7. Cache & persistence (SQLite)

### 7.1 Schéma

```sql
CREATE TABLE ohlcv_cache (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,         -- "5","60","240","D","W","M"
    bar_time INTEGER NOT NULL,        -- UNIX seconds
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, timeframe, bar_time)
);

CREATE TABLE pivots_cache (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,          -- "4H","D","W","M"
    session_end INTEGER NOT NULL,     -- UNIX seconds
    pivot_set_json TEXT NOT NULL,     -- serialized PivotSet
    PRIMARY KEY (symbol, timeframe)
);

CREATE TABLE pending_breaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    pivot_tag TEXT NOT NULL,
    pivot_tf TEXT NOT NULL,
    pivot_value REAL NOT NULL,
    direction TEXT NOT NULL,
    break_price REAL NOT NULL,
    break_time INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX idx_pending_breaks_expires ON pending_breaks(expires_at);

CREATE TABLE signals_log (
    id TEXT PRIMARY KEY,              -- Signal.id (sha1)
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    mode TEXT NOT NULL,
    cycle_time INTEGER NOT NULL,
    payload_json TEXT NOT NULL        -- full Signal serialized
);
CREATE INDEX idx_signals_cycle ON signals_log(cycle_time DESC);
CREATE INDEX idx_signals_symbol ON signals_log(symbol, strategy, direction, cycle_time DESC);

CREATE TABLE notif_log (
    signal_id TEXT PRIMARY KEY,
    sent_at INTEGER NOT NULL,
    status TEXT NOT NULL,             -- "sent" | "failed" | "suppressed_by_priority" | "suppressed_by_window"
    error TEXT
);

CREATE TABLE cycle_health (
    cycle_time INTEGER PRIMARY KEY,    -- UNIX seconds, set at end of run_cycle
    duration_ms INTEGER NOT NULL,
    symbols_ok INTEGER NOT NULL,
    symbols_failed INTEGER NOT NULL,
    signals_emitted INTEGER NOT NULL,
    signals_notified INTEGER NOT NULL
);
CREATE INDEX idx_cycle_health_time ON cycle_health(cycle_time DESC);
```

### 7.2 Politique de cache des pivots

`session_end` est calculé à partir du timestamp du **bar courant en cours** de la TF (= last_closed.time + interval). Tant que `now < session_end`, hit. Quand `now >= session_end`, on invalide et on recompute au prochain cycle.

Pour le 4H, c'est `last_4h_bar_open + 4h`. Pour le Daily, dépend de la session du symbole — on lit ça de la 1ère bar reçue (`Period.time + 86400`).

### 7.3 OHLCV cache (pour backtest)

Le cache OHLCV est append-only pour les backtests. En mode live, il n'est pas obligatoire (on peut directement utiliser les bars retournées par TV pour le calcul de pivots). Il devient critique en mode backtest pour ne pas re-fetcher la même période entre runs.

## 8. Cycle live

```python
# live/cycle.py — pseudo-code

async def run_cycle(deps: Deps) -> CycleReport:
    cycle_t = datetime.now(UTC)

    # 1) M5 fetch parallèle (jamais cache)
    m5_fetches = {
        sym: deps.fetcher.fetch_m5(sym, n_bars=50)
        for sym in deps.config.watchlist
    }
    m5_results = await gather_partial(m5_fetches)  # capture exceptions par symbole

    # 2) Pivots cache-aware (1 fetch H1/D/W/M par symbole×TF si miss)
    pivot_jobs = [
        deps.fetcher.get_pivots(sym, tf)            # cache hit OR fetch+compute+store
        for sym in deps.config.watchlist
        for tf in ("4H","D","W","M")
    ]
    pivot_results = await gather_partial(pivot_jobs)

    # 3) MarketSnapshot par symbole (skip si M5 fetch a échoué)
    snapshots = build_snapshots(m5_results, pivot_results, cycle_t, deps.atr_calc)

    # 4) Load state
    state = await deps.repo.load_state(now=cycle_t)

    # 5) Détecte nouvelles cassures sur la bougie M5 fraîche
    new_breaks = []
    for snap in snapshots.values():
        new_breaks.extend(
            analysis.breaks.detect_break(
                snap.m5_bars[-1],
                [p for tf in ("D","W","M") for p in snap.pivots[tf].levels],
                snap.atr_m5,
            )
        )
    state = state.merge(new_breaks).expire(cycle_t)

    # 6) Run strategies
    signals: list[Signal] = []
    for strategy in deps.strategy_registry.enabled():
        for snap in snapshots.values():
            if not strategy.applies_to(snap.symbol, deps.config):
                continue
            try:
                signals.extend(strategy.detect(snap, state))
            except Exception as e:
                logger.exception("strategy.detect failed", strategy=strategy.id, symbol=snap.symbol)

    # 7) Persist
    await deps.repo.save_signals(signals)
    await deps.repo.save_state(state)

    # 8) Notif
    recent_notifs = await deps.repo.recent_notifs(window_min=deps.config.notif.suppress_window_minutes)
    to_notify = deps.notif_policy.filter(signals, recent_notifs)
    await deps.notifier.send_batch(to_notify)
    await deps.repo.record_notifs(to_notify, suppressed=set(signals) - set(to_notify))

    return CycleReport(...)
```

## 9. Notification Telegram

### 9.1 Politiques de dedup (couche notif uniquement)

Deux filtres composés appliqués dans cet ordre par `notif_policy.filter()` :

**Filtre 1 — Priorité entre stratégies superseded** (cf. §3.3.1) :
- Pour un même `(symbol, direction, trigger_pivot.tag, trigger_pivot.tf, cycle_time)`, garder uniquement le signal de plus haute priorité dans la chaîne `S6 > S5 > S1`. Les signaux supprimés sont marqués `notif_log.status="suppressed_by_priority"` ; le signal gagnant hérite des tags des superseded (ex : tag `confluence` ajouté si S5 était présent).

**Filtre 2 — Fenêtre temporelle de répétition** :
Configurable dans `.env` :
```
NOTIF_DEDUP_WINDOW_MIN=30
NOTIF_DEDUP_WITHIN_ATR=0.10
```
Suppression d'un signal si dans la fenêtre `NOTIF_DEDUP_WINDOW_MIN` minutes il existe un signal **déjà notifié** avec :
- Même `(symbol, strategy, trigger_pivot.tag, direction)` ;
- ET `|entry - last_entry| < NOTIF_DEDUP_WITHIN_ATR × atr_d`.

Marqués `notif_log.status="suppressed_by_window"`.

→ La couche détection émet 100% des signaux dans `signals_log` (visibles en backtest, indépendamment de ces 2 filtres). Backtest applique 0 filtre par défaut ; un flag `--apply-notif-filters` peut le réactiver pour étudier l'impact du dedup.

### 9.2 Format du message

```
🟢 LONG — XAUUSD
━━━━━━━━━━━━━━━━━━
📍 Stratégie : S1 Bounce
🎯 Pivot     : PDL Daily @ 4500.00 (zone dilatée 4498.40–4501.60)
💎 Tags      : confluence(Daily PDL + Weekly P), sweet_spot
🪟 Contexte  : CPR H4 [4495.20 / 4502.10] — entry inside CPR H4
─────────────
📊 Entry : 4502.30  (M5 close, 14:35 UTC)
🛑 SL    : 4495.50  (-6.80)
🎯 TP1   : 4520.00  Daily P     (R/R 2.6)
🎯 TP2   : 4540.00  Daily R1    (R/R 5.4)
🎯 TP3   : 4565.00  PDH         (R/R 9.2)
─────────────
🏷  intraday  | id=#a1b2c3
```

Header différencié pour S6 / `sweet_spot` :
```
💎 SWEET SPOT — LONG XAUUSD
```

Header différencié pour SHORT :
```
🔴 SHORT — XAUUSD
```

Le formatting (nombre de décimales) est dérivé de `MarketInfo.pricescale` du symbole (FX → 5 décimales, or → 2, BTC → 1, indices → 1).

### 9.3 Robustesse Telegram

- `httpx.AsyncClient` avec timeout 10s.
- 1 retry à 3s sur 5xx ; sur 429, respecte `retry_after` du body de réponse.
- Sur échec final, `notif_log.status="failed"`. Le signal reste dans `signals_log`.
- Pas de blocage du cycle si Telegram est down.

## 10. Backtest V2 (avec PnL simulation)

### 10.1 CLI

```bash
python -m agentic_trader.backtest \
    --symbol VANTAGE:XAUUSD \
    --from 2025-01-01 --to 2025-12-31 \
    --strategies S1,S2,S3,S4,S5,S6 \
    --partial-take 33,33,34 \
    --output backtest_xauusd_2025.json
```

Options :
- `--symbol` : symbole TV (répétable pour multi-symbole).
- `--from` / `--to` : range de dates inclus (UTC).
- `--strategies` : liste des stratégies à inclure (default = toutes).
- `--partial-take` : pourcentages scalpés à TP1, TP2, TP3 (default `33,33,34` ; alternatives `100,0,0` ou `50,50,0`).
- `--output` : fichier JSON de sortie.
- `--use-cache` : utilise `ohlcv_cache` si dispo, sinon fetch + cache (default true).

### 10.2 Mécanique walk-forward

1. **Fetch + cache** : pour chaque symbole, on fetch M5 + H1 sur la période demandée + un buffer suffisant à gauche pour calculer pivots Monthly (= 60 jours avant `--from`). On stocke dans `ohlcv_cache`.
2. **Reconstruction des TF supérieures** : à chaque tick simulé, on ne donne au snapshot que les bars `bar_time <= tick_time`. Les pivots sont recalculés à chaque frontière de session de la TF.
3. **Boucle bougie par bougie M5** :
   - Build snapshot avec les bars passés.
   - Run strategies → signals.
   - Pour chaque nouveau signal, ouvre un `SimulatedTrade`.
4. **Suivi des trades ouverts** : à chaque bougie suivante, vérifier sur `[bar.high, bar.low]` :
   - Si `SL` est dans la range → SL hit (priorité absolue).
   - Sinon, si `TP1` est dans la range → TP1 hit (`partial_take[0]%` de la position close, le reste continue avec SL trailé au break-even si configuré — V2.0 sans trailing).
   - Pareil pour TP2, TP3.
   - Si tout le volume est sorti → trade fermé.
   - **Hypothèse** : pas de slippage, fill au prix exact du niveau.
   - **Cas ambigu** : si SL et TP1 sont tous deux dans la range d'une même bougie, on assume SL en premier (conservatif).

### 10.3 Output

```json
{
  "config": {...},
  "trades": [
    {
      "signal_id": "...",
      "symbol": "VANTAGE:XAUUSD",
      "strategy": "S1",
      "direction": "LONG",
      "mode": "intraday",
      "tags": ["sweet_spot"],
      "entry_time": "2025-03-15T14:35:00Z",
      "entry": 4502.30,
      "sl": 4495.50,
      "targets": [...],
      "events": [
        {"time": "...", "type": "TP1", "price": 4520.00, "pct_closed": 33},
        {"time": "...", "type": "SL", "price": 4495.50, "pct_closed": 67}
      ],
      "exit_time": "...",
      "r_realized": 0.21,
      "duration_bars": 12,
      "mfe_r": 2.6,
      "mae_r": -1.0
    }
  ],
  "metrics_per_strategy": {
    "S1": {
      "trades": 142,
      "win_rate": 0.46,
      "avg_r": 0.31,
      "expectancy_r": 0.31,
      "sharpe_r": 0.85,
      "max_dd_r": -8.2,
      "duration_p50_bars": 14
    }
  }
}
```

## 11. Configuration

### 11.1 `.env`

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TV_USERNAME=
TV_PASSWORD=
LOG_LEVEL=INFO
DB_PATH=./data/agent.db
NOTIF_DEDUP_WINDOW_MIN=30
NOTIF_DEDUP_WITHIN_ATR=0.10
SCHEDULE_OFFSET_SECONDS=2
```

### 11.2 `config/watchlist.yaml`

```yaml
defaults:
  modes: [intraday, swing]
  strategies: [S1, S2, S3, S4, S5, S6]
  atr_dilation_mult: 0.15
  atr_dilation_cap_d_mult: 0.50      # cap pour W/M
  confluence_threshold_atr_d: 0.30
  narrow_cpr_threshold: 0.50          # 50% de la moyenne 20 sessions
  break_body_min_atr_m5: 0.50
  retest_window_m5_bars: 24
  candle_wick_min_ratio: 0.60
  candle_doji_body_max: 0.10

watchlist:
  - symbol: VANTAGE:XAUUSD
  - symbol: VANTAGE:BTCUSD
  - symbol: VANTAGE:DJ30
    strategies: [S1, S3, S5, S6]      # override possible par symbole
  - symbol: VANTAGE:NAS100
  - symbol: VANTAGE:GBPUSD
  - symbol: VANTAGE:EURUSD
```

## 12. Déploiement

`docker-compose.yml` (résumé) :
```yaml
services:
  agent:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./config:/app/config:ro
    healthcheck:
      test: ["CMD", "python", "-m", "agentic_trader.observability.healthcheck"]
      interval: 5m
      timeout: 30s
      retries: 3
```

Le healthcheck vérifie que `data/agent.db` a été touché par un cycle réussi dans les 10 dernières minutes (table `cycle_health` mise à jour à la fin de chaque `run_cycle`).

## 13. Error handling & resilience

| Erreur | Comportement |
|---|---|
| Timeout fetch un symbole | Skip ce symbole pour le cycle, log warning, autres symboles continuent |
| Exception dans `strategy.detect()` | Log avec contexte (strategy id + symbol), continue les autres stratégies |
| WS TV déconnectée | Le wheel `tradingview_api` est censé reconnecter ; on enveloppera dans un wrapper avec retry exponentiel max 3 si ce n'est pas le cas (à vérifier au moment de l'implémentation) |
| Pivot calc impossible (pas assez de bars) | Skip ce TF pour ce symbole, autres TF du symbole continuent |
| SQLite lock (improbable, single-writer) | Retry exponentiel court max 3 |
| Telegram échec final | `notif_log.status="failed"`, signal préservé dans `signals_log`, cycle non bloqué |
| Crash process | Docker `restart: unless-stopped` ; au boot, `pending_breaks` rechargés depuis SQLite, premier cycle reprend |

## 14. Stratégie de test

| Niveau | Outils | Couverture cible |
|---|---|---|
| **Unit** | pytest (+ hypothesis pour les formulas pivots/ATR) | `analysis/*` à 100% des branches, chaque stratégie avec ≥ 5 scénarios joués bougie par bougie (LONG happy path, SHORT happy path, trigger sans confirmation, hors zone dilatée, expiration de PendingBreak pour S3) |
| **Fixtures** | OHLCV captures JSON committées | 1 fixture par stratégie reproduisant un setup historique observable à l'œil |
| **Integration** | TV mocké via wrapper (httpx mock + faux `TradingViewClient`), Telegram mocké, SQLite tmp | Le cycle complet de bout en bout, multi-cycle (la persistence du state inter-cycle marche) |
| **Smoke réel** | Script optionnel hors CI | Fetch live un symbole, vérifie pas d'exception et qu'un signal de test est correctement formaté |

## 15. Hors-scope V1

Sera ajouté plus tard si nécessaire, **architecture déjà compatible** :
- Exécution réelle d'ordres (le détecteur reste le même, on rajoute un `Executor` plug-and-play après le notifier).
- Slippage / spread / fees dans la simu PnL (`SlippageModel` interface).
- Trailing stop / break-even auto après TP1.
- Multi-canal Telegram (intraday vs swing).
- Stratégies supplémentaires (CPR open, narrow-range day trend, etc.).
- Web dashboard.
- Alertes sur cassures fortes hors setups (info, pas signal).

## 16. Décisions notables (synthèse pour mémoire)

1. **Sessions naturelles par asset** (pas d'agrégation 00:00 UTC) — choix conscient pour rester strictement aligné au layout TradingView Vantage de l'utilisateur.
2. **6 stratégies indépendantes**, pas de modulateur — facilite le backtest individuel.
3. **Détection émet tout, notif filtre** — backtest voit la série complète, prod Telegram dédupe pour le confort.
4. **Architecture single-process async** (Option A) — simplicité, latence faible, le wheel est conçu pour partager une connexion WS.
5. **SQLite pour cache + state + signals_log** — un seul fichier, pas d'infra annexe.
6. **Backtest V2 dès le début** : PnL simulé avec SL/TP, pas de slippage en V2.0 (ajout futur).
7. **4H = contexte uniquement** : pivots calculés et présents dans le snapshot, intégrables aux confluences, mais aucun trigger 4H seul.
