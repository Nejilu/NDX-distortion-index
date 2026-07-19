# NDX Weight Distortion Index — MVP

Ce projet mesure séparément l’écart entre les pondérations publiées par des ETF Nasdaq-100 non-UCITS et UCITS, et les poids qu’auraient les mêmes titres selon leur seule capitalisation flottante.

```text
float_market_cap = price × float_shares
float_weight = float_market_cap / Σ(float_market_cap)
weight_delta = actual_weight - float_weight
NDX_WDI = 50 × Σ(abs(weight_delta))
```

Le dashboard permet aussi de basculer vers le contrefactuel en capitalisation cotée totale :

```text
total_market_cap = price × shares_outstanding
total_cap_weight = total_market_cap / Σ(total_market_cap)
weight_delta = actual_weight - total_cap_weight
```

Un `NDX_WDI` de 5 signifie que 5 % du poids total devrait être réalloué pour passer d’une distribution à l’autre.

## Périmètre et choix méthodologiques

- Deux univers indépendants sont enregistrés : `non_ucits` et `ucits`. Ils ne sont jamais fusionnés ou moyennés.
- Deux bases de contrefactuel sont également séparées en SQLite : `float` et `total`. Le toggle du dashboard ne mélange jamais leurs snapshots ni leurs historiques.
- Les pondérations réelles sont toujours lues telles que publiées par le fonds retenu. Le MVP ne reconstruit pas les poids d’un ETF à partir de ses prix ou quantités ; GOOG et GOOGL restent distincts.
- Le cash et les positions explicitement non-actions sont retirés, puis les poids actions sont normalisés à 100 %.
- Prix, `floatShares`, `sharesOutstanding` et `marketCap` viennent de `yfinance`. Les deux derniers champs servent uniquement de contrôles et ne remplacent jamais un flottant manquant ou invalide.
- Le cache SQLite interne de yfinance est stocké dans `data/yfinance_cache` afin que l'application fonctionne même lorsque le cache utilisateur Windows dans `AppData` est inaccessible.
- Un titre sans prix/flottant positif, ou dont le flottant dépasse de façon incohérente les actions en circulation ou la capitalisation totale, est exclu du score et reste visible avec son `data_status`.
- Lorsqu'un même flottant consolidé est publié à l'identique pour plusieurs classes manifestement liées (actuellement GOOG/GOOGL), il est réparti au prorata des actions en circulation par classe et signalé par `valid_shared_float_allocated`.
- Le `coverage_ratio` mesure le poids publié avant exclusion. Les poids réels des titres couverts sont ensuite renormalisés à 100 % afin de comparer deux distributions sur exactement le même univers.
- `complete` signifie une couverture au moins égale à `NDX_COVERAGE_THRESHOLD` (99 % par défaut), `partial_coverage` une couverture inférieure, et `sample_fallback` l’usage des données fictives.

Les ETF demeurent des proxys de l’indice, et les données de marché gratuites ne constituent pas une source officielle ou garantie. L’historique local commence au premier snapshot.

## Sources de pondérations et fallbacks

Chaque source doit contenir entre 90 et 130 actions, des tickers uniques et des poids valides. Les pages limitées au top 10, les exports HTML et les fichiers partiels sont rejetés.

Ordre `non_ucits` :

1. CSV local explicite (`NON_UCITS_HOLDINGS_CSV` ou `--holdings-csv`) ;
2. téléchargement officiel BlackRock/iShares IQQ ;
3. holdings publics Invesco QQQ ;
4. URLs CSV configurées dans `NON_UCITS_FALLBACK_URLS`.

Ordre `ucits` :

1. CSV local explicite (`UCITS_HOLDINGS_CSV` ou `--holdings-csv`) ;
2. CSV officiel iShares CNDX ;
3. holdings publics Invesco EQQQ ;
4. URLs CSV configurées dans `UCITS_FALLBACK_URLS`, prévues notamment pour Xtrackers ou UBS.

La source Nasdaq publique observée ne présentant que les principales positions n’est pas utilisée comme univers complet. Le champ `reference_fund`, la date publiée et les échecs des sources précédentes sont conservés avec chaque snapshot.

## Architecture

```text
qqq_holdings_provider.py  # chaînes QQQ/IQQ et CNDX/EQQQ + CSV configurables
market_data_provider.py   # yfinance + provider CSV local
distortion_engine.py      # calcul pur, couverture et statuts
database.py               # schéma et accès SQLite
snapshot_service.py       # orchestration et fallback explicite
api.py                    # FastAPI
dashboard.py              # Streamlit
run_snapshot.py           # CLI ponctuelle ou quotidienne
data/                     # données fictives versionnées
tests/                    # calcul, parsing, persistance et API
```

Les providers exposent des contrats minimaux, ce qui permet de remplacer Invesco ou yfinance sans toucher au moteur, à l’API ou au dashboard.

## Installation

Python 3.11 ou 3.12 est recommandé.

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

## Premier lancement hors ligne

Le jeu `data/sample_*.csv` est entièrement fictif. Il permet de vérifier l’application sans réseau :

```bash
python run_snapshot.py --mode sample --universe all
python run_snapshot.py --mode sample --universe all --basis total
python -m uvicorn api:app --reload
```

Dans un second terminal :

```bash
python -m streamlit run dashboard.py
```

- API interactive : `http://127.0.0.1:8000/docs`
- Dashboard : `http://localhost:8501`

## Utilisation des sources externes

```bash
# Les deux univers ; échec explicite si aucune chaîne live n'aboutit
python run_snapshot.py --mode live --universe all

# Même univers, contrefactuel prix × actions en circulation
python run_snapshot.py --mode live --universe all --basis total

# Mode recommandé pour le MVP : live, puis fallback fictif clairement marqué
python run_snapshot.py --mode auto --universe all

# Un CSV local doit être rattaché explicitement à un univers
python run_snapshot.py --mode live --universe non_ucits --holdings-csv chemin/holdings_qqq.csv
python run_snapshot.py --mode live --universe ucits --holdings-csv chemin/holdings_cndx.csv
```

Toutes les URLs sont configurables dans `.env`. Un CSV compatible doit contenir au minimum un ticker et un poids, avec idéalement le nom et la classe d’actif.

## API

```text
GET  /api/current
GET  /api/current?universe=ucits
GET  /api/current?universe=ucits&weighting_basis=total
GET  /api/history?limit=365&universe=non_ucits
GET  /api/components?universe=ucits&weighting_basis=total&ranking=contributors&limit=20
POST /api/recompute
```

Exemple de recalcul :

```bash
curl -X POST http://127.0.0.1:8000/api/recompute \
  -H "Content-Type: application/json" \
  -d '{"mode":"auto","universe":"all","weighting_basis":"total"}'
```

`ranking` accepte `all`, `overweights`, `underweights` ou `contributors`.

## Snapshot quotidien

Le processus intégré attend l’heure locale choisie et reste actif :

```bash
python run_snapshot.py --mode auto --universe all --daily --at 18:00
```

En production, il est préférable de faire exécuter la commande ponctuelle par le planificateur du système :

```cron
0 18 * * 1-5 cd /chemin/ndx-wdi && .venv/bin/python run_snapshot.py --mode auto --universe all
```

Sous Windows, créer une tâche dans le Planificateur de tâches qui lance `C:\chemin\.venv\Scripts\python.exe` avec les arguments `run_snapshot.py --mode auto` et le dossier du projet comme répertoire de démarrage.

## Tests

```bash
python -m pytest
```

Le cas de référence vérifie `A=50 %`, `B=30 %`, `C=20 %` contre `60 %`, `25 %`, `15 %`, soit `NDX_WDI = 10`. Les tests couvrent aussi la normalisation, les flottants/prix manquants, la somme des distributions, les contributions, SQLite et les quatre routes API.
