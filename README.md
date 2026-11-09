# Foulée

Assistant de course à pied pour Windows. Foulée récupère tes données Garmin (activités, VFC, sommeil,
FC de repos, Body Battery, disponibilité Garmin), calcule des indicateurs inspirés de Runalyze et
te propose chaque matin une séance : **repos**, **fractionné**, **renforcement** ou **endurance Z2**
(dont sorties longues), en fonction de ta forme du jour et de tes prochaines courses.

## Installation

**Avec l'installateur** : lance `Foulee-Setup-x.y.z.exe` (installation par utilisateur, sans droits
administrateur). Les mises à jour peuvent être suivies par Vedware en ajoutant l'URL du dépôt GitHub.

**Construire l'installateur** : double-clique sur `build.bat`. Le script installe au besoin Python 3.12
et Inno Setup via winget, crée un environnement virtuel, lance les tests, construit l'application avec
PyInstaller puis produit `dist\Foulee-Setup-x.y.z.exe`.

**Depuis les sources** : `pip install -r requirements.txt` (Python 3.12 ou plus), puis `python main.py`.

**Publier sur GitHub** : double-clique sur `publish.bat`. Il installe au besoin Git et GitHub CLI,
te connecte à GitHub dans le navigateur, crée le dépôt public `foulee` sur ton compte, pousse le code
puis le tag `vX.Y.Z`. Le workflow `.github/workflows/release.yml` construit alors l'installateur sur un
runner Windows et le publie dans une release, avec son empreinte SHA-256 ; le script suit la
construction et affiche l'URL à ajouter dans Vedware.

**Nouvelle version** : mets à jour `__version__` dans `foulee/__init__.py`, puis relance `publish.bat`.

## Premier lancement

1. Clique sur **Connecter Garmin** et saisis l'e-mail et le mot de passe de ton compte Garmin Connect.
   Si la validation en deux étapes est active, une fenêtre te demande le code reçu.
2. La première synchronisation récupère un an d'activités et 120 jours de données santé (réglable).
   Elle prend quelques minutes ; les données déjà reçues sont conservées si elle est interrompue.
3. Ajoute tes courses dans **Courses** : la suggestion du jour s'organise autour de ta prochaine course A.
   La fiche propose une recherche : courses de ton calendrier Garmin et parcours Garmin enregistrés
   (récupérés à la synchronisation), catalogue UTMB World Series (en ligne), ou import du GPX du
   parcours (distance et dénivelé calculés). Un clic sur un résultat remplit la fiche.
4. Vérifie **Réglages** : disponibilités par jour, nombre de sorties de course par semaine (automatique
   par défaut), nombre de séances de renfo, FC max si la valeur déduite de tes activités ne te convient pas.

Tu peux aussi essayer l'application avec des données fictives (bouton sur l'écran d'accueil ou case
« Mode démo » dans Réglages).

Synchronise ta montre après ton réveil puis lance Foulée (ou clique sur **Synchroniser**) : la VFC et
le sommeil de la nuit sont alors disponibles pour la suggestion du jour.

## Ce que calcule Foulée

| Indicateur | Méthode |
|---|---|
| Charge (TRIMP) | Banister, à partir de la FC moyenne ; repli sur la charge Garmin puis sur la durée |
| Fatigue (ATL), forme (CTL), équilibre (TSB) | Moyennes exponentielles sur 7 et 42 jours ; TSB = CTL − ATL |
| Ratio aigu / chronique | ATL / CTL ; zone sûre 0,8 à 1,3 |
| Monotonie, contrainte | Foster : moyenne / écart-type de la charge sur 7 jours |
| VO2max effective | Par sortie : VO2 à l'allure (Daniels) corrigée du dénivelé, divisée par le %VO2max déduit du %FCmax ; moyenne pondérée sur 30 jours, sorties atypiques écartées |
| Endurance pour une course | Inspirée de la « forme marathon » de Runalyze, en km-effort : volume hebdomadaire (26 semaines) et sorties longues (70 jours) comparés aux exigences de la course |
| Pronostics | Tables de Daniels ; au-delà du marathon, exposant de fatigue 1,15 ; trail en km-effort × technicité, calibré par tes résultats passés |
| Disponibilité du jour | VFC vs ta normale sur 60 jours, FC de repos vs médiane 30 jours, sommeil, Body Battery au réveil, disponibilité Garmin, stress de la veille |
| Efficacité (progression) | Vitesse ajustée à la pente (Garmin) divisée par la FC moyenne : mètres parcourus par battement. Comparée entre sorties du même type (footing, tempo, seuil, VO2max, sortie longue, d'après l'effet d'entraînement principal de la montre) |
| Forme du jour | Message en clair (plein d'énergie, en forme, fatigue d'entraînement, fatigué, organisme en alerte…) tiré de la disponibilité, de la charge (TSB, ratio aigu/chronique, jours d'affilée) et de l'évolution sur 3 jours vs la semaine passée, avec points forts et points à surveiller |

**Progression.** La page du même nom compare tes 6 dernières semaines aux 18 précédentes pour chaque
type de séance (efficacité, FC moyenne, allure ajustée), trace leur évolution et liste tes meilleurs temps
sur 1 km, 5 km, 10 km, semi et marathon (meilleurs passages mesurés par la montre, y compris au sein d'une
sortie plus longue). La fiche d'une activité, et la page du jour quand tu as couru, la comparent à tes
10 sorties précédentes du même type sur 4 mois : FC moyenne, allure ajustée, efficacité et rang.
Les sorties de moins de 15 min, les courses et les FC moyennes sous 100 bpm (capteur décroché) sont écartées.

Le **km-effort** vaut la distance en km plus le dénivelé positif divisé par 100.

## Comment le coach décide

Les règles sont appliquées dans cet ordre ; la première qui s'applique fixe la séance, et l'écran
affiche toujours les raisons :

1. Séance déjà faite aujourd'hui, ou jour de course.
2. Signaux de récupération dans le rouge (disponibilité < 35, ou VFC effondrée avec FC de repos en hausse) : repos.
3. Aucune disponibilité ce jour-là : repos.
4. Récupération après une course A ou B (durée proportionnelle au km-effort) : repos puis footings.
5. Six jours d'affilée (quatre si la forme est moyenne) : repos.
6. Surcharge (TSB < −30 ou ratio > 1,5) : repos ou footing de récupération.
7. Affûtage avant la course A : volume réduit, un rappel d'allure, repos à J-2, activation à J-1.
8. Veille de course B ou C : activation.
8 bis. Jour sans sortie si le nombre de sorties de la semaine est déjà réparti sur d'autres jours :
   renfo si le quota n'est pas atteint, sinon repos (voir ci-dessous).
9. Sortie longue sur ton jour le plus disponible si la dernière date d'au moins 5 jours ;
   dos-à-dos le lendemain en phase spécifique ultra.
10. Fractionné si la forme est bonne (≥ 62), la dernière séance dure date d'au moins 48 h et le quota
    de la phase n'est pas atteint (1 par semaine en foncier, 2 en développement et en spécifique).
11. Renforcement si le quota hebdomadaire n'est pas atteint.
12. Repos si aucun jour off sur 7 jours, footing très facile si la forme est moyenne, sinon endurance Z2.

Phases selon la course A : foncier (plus de 16 semaines), développement, spécifique (4 à 6 semaines),
affûtage (7 à 21 jours selon la distance). Les séances de qualité alternent VO2max, seuil et côtes
(trail) ou allure course (route), et sont choisies pour tenir dans ton créneau du jour.

**Sorties par semaine.** Réglage fixe (2 à 7) ou automatique : 3 sans course objectif, plafond de 4
(foncier, affûtage) ou 5 (développement, spécifique) avant une course A, 3 en récupération, sans
dépasser ton habitude des 6 dernières semaines de plus d'une sortie. Le coach choisit les jours de la
semaine : courses et sortie longue d'abord, puis les autres sorties espacées au maximum (pas plus de
deux jours d'affilée quand c'est possible, pas la veille de la sortie longue). Les jours disponibles
restants accueillent le renfo ou du repos.

## Confidentialité

Tout reste sur ton ordinateur, dans `%APPDATA%\Foulee` : base SQLite, réglages et jetons de session
Garmin. Le mot de passe n'est jamais enregistré. Foulée ne fait que lire ton compte Garmin.
Seule exception : le bouton **Rechercher** de la fiche course envoie le nom saisi au catalogue public
UTMB World Series (`api.utmb.world`), sans aucune autre donnée.
La désinstallation laisse ce dossier en place.

## Limites

- La connexion utilise `garminconnect`, une bibliothèque non officielle : un changement côté Garmin peut
  casser la synchronisation jusqu'à sa mise à jour (`pip install -U garminconnect`, puis reconstruire).
- Les seuils du coach sont des règles d'entraînement classiques, pas un modèle validé sur toi.
  Ils ne remplacent ni un entraîneur ni un avis médical.
- La VO2max effective est bruitée en trail technique, par forte chaleur ou avec un capteur poignet
  imprécis ; le facteur de correction (Réglages) permet de l'aligner sur la VO2max Garmin.
- La projection sur 7 jours suppose que les séances sont faites et une récupération moyenne.

## Développement

```
python -m unittest discover -s tests     # tests hors ligne (métriques, coach, parsing Garmin)
```

```
foulee/
  metrics.py      indicateurs (TRIMP, charge, VO2max, endurance, pronostics, zones, allures)
  readiness.py    disponibilité du jour
  form.py         bilan de forme du jour (message en clair)
  progress.py     progression : types de séance, efficacité, comparaisons, meilleurs temps
  coach.py        phases, règles et séances, sorties par semaine, projection 7 jours
  race_search.py  recherche de courses (Garmin, UTMB World Series, GPX)
  analysis.py     assemble données stockées et indicateurs
  garmin_sync.py  connexion et synchronisation incrémentale
  db.py           stockage SQLite
  demo.py         données fictives
  ui/             interface PySide6
```

Polices : Barlow et Barlow Semi Condensed (licence SIL OFL, voir `assets/OFL.txt`).
