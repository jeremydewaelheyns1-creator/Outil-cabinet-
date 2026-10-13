# Décisions

Une décision ne se réécrit pas : on en ajoute une nouvelle qui la remplace.

## D-001 — Un outil pour un seul cabinet
Pas de multi-cabinet, pas de SaaS. Simplifie tout (pas d'isolation entre locataires) et
garde le coût d'hébergement autour de 20–40 €/mois.

## D-002 — Django + HTMX, rendu côté serveur
Django 6.1 (puis 6.2 LTS en avril 2027), Python 3.13. Pages HTML rendues par le serveur,
HTMX pour la recherche en direct et les fragments. Pas de framework JavaScript ni d'étape de
compilation : moins de pièces qui cassent, maintenance simple sur dix ans.

## D-003 — Hébergement Google Cloud, région Belgique
Cloud Run + Cloud SQL + Cloud Storage dans le projet du cabinet. Données en Belgique ; le
cabinet reste propriétaire de son infrastructure.

## D-004 — PostgreSQL, seule source de vérité
Une seule base : données, historique, journaux, file de travaux (procrastinate). Pas de Redis
ni de file externe. Fonctions PostgreSQL utilisées : `unaccent`, `pg_trgm`, déclencheurs.

## D-005 — Double authentification obligatoire
allauth + MFA (application TOTP, codes de récupération, clés d'accès WebAuthn). Imposée par
middleware à tous les comptes, administration comprise.

## D-006 — Droits par capacités et portefeuilles
Profils de sécurité = listes de capacités nommées. Visibilité des clients par portefeuille
(privé = membres seulement). Plus simple et plus lisible que les permissions Django par modèle.

## D-007 — Journal des consultations inaltérable
Exigence AML/RGPD : traçabilité de qui a vu quoi. Protégé par déclencheur PostgreSQL.
Comptes jamais supprimés, seulement désactivés.

## D-008 — Journal d'événements avec exécution unique par traitement
Les automatismes réagissent à des faits enregistrés, rejouables, chaque traitement n'étant
exécuté qu'une fois. Permet d'ajouter des automatismes sans toucher au code existant.

## D-009 — Numéros stockés en forme compacte
Numéro d'entreprise (10 chiffres) et numéro national (11 chiffres) validés par python-stdnum,
stockés sans ponctuation, uniques, NULL si absents. Le numéro de TVA belge se déduit
(« BE » + numéro d'entreprise).

## D-010 — Une personne = une fiche, reliée aux sociétés
Dirigeants, actionnaires, conjoints sont des fiches clients reliées par `Relation`
(rôle, pourcentages, dates). Permet le calcul UBO et évite les doublons.

## D-011 — Seuil UBO paramétrable
« Plus de 25 % » aujourd'hui ; la réforme européenne (10 juillet 2027) passe à « au moins
25 % » : `UBO_THRESHOLD_INCLUSIVE=True`. Le calcul propose, le cabinet décide.

## D-012 — Copie locale BCE Open Data
Recherche et préremplissage sans dépendre d'un service en ligne ni d'un scraping. Seules les
données utiles sont gardées (quelques centaines de Mo). Les champs publics se synchronisent
seuls ; nom et adresse restent des propositions à valider.

## D-013 — Reprise FID-Manager pilotée par un fichier de correspondance
Les intitulés de colonnes de l'export varient : un fichier YAML les associe aux champs, sans
code. Analyse à blanc obligatoire avant import ; jamais d'écrasement de l'existant.

## D-014 — Données fictives uniquement pendant le développement
Aucune donnée réelle dans le dépôt, les tests ou la conversation avec l'IA de développement.
Les vraies données vont directement dans l'outil hébergé par le cabinet.

## D-015 — Travaux de fond sans processus permanent
Cloud Run ne facture que le temps d'exécution : pas de worker permanent. Les traitements
courts s'exécutent juste après la requête (`JOBS_MODE=eager`) ; `run_jobs`, lancé toutes les
5 minutes par Cloud Scheduler, retraite les échecs et vide la file.

## D-016 — Recherche par numéro national séparée et journalisée
La recherche générale ne cherche jamais dans les numéros nationaux (sinon, la date de
naissance étant visible, on pourrait deviner un numéro en une centaine d'essais). Une
recherche dédiée, réservée au droit « données sensibles », passe par POST (le numéro
n'apparaît ni dans l'adresse ni dans les journaux du serveur) et chaque essai est journalisé.

## D-017 — Aucun écran de connexion sans second facteur
L'écran de connexion propre à l'administration Django est remplacé par une redirection vers
la connexion de l'application. L'historique de l'administration n'est pas activé sur les
fiches clients (il montrerait le numéro national en clair) : l'historique se consulte dans
l'application, masqué.

## D-018 — Fiches d'un portefeuille privé masquées partout
Les calculs (UBO) tiennent compte de toutes les fiches, mais celles que l'utilisateur ne peut
pas voir sont affichées sans nom ni lien ; recherche BCE, relations et administration
appliquent la même règle.
