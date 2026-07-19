# Anomalie ASML dans les snapshots IQQ et CNDX

## Résumé technique

Le poids flottant d'ASML à 49,13 % ne provient pas des holdings IQQ ou CNDX. Les deux calculs ont réutilisé une valeur `floatShares` yfinance incohérente de 21 331 633 667 titres. Le contrôle ajouté exclut désormais cette observation sans lui substituer `sharesOutstanding`.

## Une même observation erronée contamine les deux univers

Les snapshots 10 (IQQ) et 11 (CNDX) enregistrent le même prix ASML de 1 747,58 USD, le même flottant de 21 331 633 667 titres et le même poids flottant de 49,13 %. Le poids publié d'ASML reste pourtant proche de 0,74 % dans les deux ETF. Cette symétrie localise le défaut dans la donnée de marché commune, et non dans les deux sources de holdings indépendantes.

## Les contrôles de cohérence invalident le flottant ASML

La lecture live yfinance du 18 juillet 2026 fournit simultanément :

- `floatShares` : 21 331 633 667 ;
- `sharesOutstanding` : 384 100 000 ;
- `marketCap` : 671 245 467 648 USD ;
- prix : 1 747,58 USD.

Le flottant est 55,5 fois supérieur aux actions en circulation. Le produit prix × flottant implique environ 37,28 billions USD, également 55,5 fois la capitalisation totale publiée. Ces deux tests sont descriptifs : ils identifient une incohérence d'unité ou de fournisseur, sans déterminer la bonne valeur de flottant.

## Méthode de rejet ajoutée

Une observation est maintenant marquée `invalid_float_inconsistent` et exclue si le flottant dépasse les actions en circulation de plus de 10 %, ou si sa capitalisation implicite dépasse la capitalisation totale de plus de 25 %. Les marges tolèrent les décalages de date entre champs. Aucun fallback vers 100 % des actions en circulation n'est effectué.

Le même contrôle a révélé que yfinance publie un flottant Alphabet consolidé identique pour GOOG et GOOGL. Lorsque plusieurs classes présentent exactement le même flottant, des prix et capitalisations proches, et que ce flottant est cohérent avec la somme des actions en circulation des classes, le total est réparti au prorata des actions par classe. Les lignes restent distinctes et portent le statut `valid_shared_float_allocated`.

## Limites et robustesse

Les contrôles dépendent encore de champs yfinance pouvant être absents ou datés. En leur absence, un flottant positif ne peut pas être validé par ces deux règles. Le `coverage_ratio`, le statut du snapshot et le nombre de flottants invalides doivent donc rester visibles.

## Validation de bout en bout

Les snapshots live finaux 14 (IQQ) et 15 (CNDX) ont respectivement une couverture de 98,7870 % et 98,7877 %. ASML porte le statut `invalid_float_inconsistent` et aucun `float_weight`. GOOG et GOOGL portent `valid_shared_float_allocated`, restent deux lignes distinctes, et les poids réels comme flottants des 100 lignes valides somment chacun à 1. Le poids flottant maximal est AAPL à 14,04 %.

Les snapshots antérieurs contaminés ou produits pendant le diagnostic sont conservés dans SQLite avec le statut `invalidated_data_quality`, mais exclus du graphe historique du dashboard.

## Suite recommandée

Conserver ASML comme ligne exclue tant qu'une source de flottant plus fiable n'est pas branchée, puis remplacer le provider de données de marché sans modifier le moteur de calcul.

## Question ouverte

Une source gratuite stable fournissant le flottant ajusté des ADR et titres étrangers permettrait-elle de couvrir ASML sans introduire un remplacement automatique non auditable ?
