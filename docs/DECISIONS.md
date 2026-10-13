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

## D-019 — Navigation par dossier client
Comme dans les logiciels comptables par dossier : on choisit un client en haut de l'écran
(recherche, derniers dossiers, raccourci Ctrl+K) ; il reste actif d'un écran à l'autre et le
menu de gauche présente ses rubriques. Changer de client garde la rubrique ouverte. La
synthèse du dossier commence par les points d'attention (ce qui manque ou demande une
action), chacun menant à la rubrique concernée. Chaque nouveau module ajoute sa rubrique au
dossier (`apps/clients/dossier.py`). La page d'accueil (sans dossier) sera revue ensuite.

## D-020 — Échéances générées à partir de règles en données
Les échéances récurrentes (TVA, listing, AG, comptes annuels, ISOC, IPP) sont décrites dans
`config/taches/regles.yaml` : périodicité, conditions sur la fiche client, calcul de la date
(report au jour ouvrable suivant avec les jours fériés belges), responsable par rôle de
l'équipe, check-list. La génération est idempotente (clé client + règle + période), suit les
changements de fiche via les événements et tourne une fois par jour via `run_jobs`. Une tâche
déjà travaillée n'est jamais modifiée ni supprimée automatiquement. Les délais sont les délais
légaux usuels, à valider par le cabinet ; la date IPP est à renseigner chaque année.

## D-021 — Dossier en onglets stables, sans menu du cabinet
Remplace la partie « menu de gauche » de D-019 (demande de Jeremy : un onglet par fonction
deviendrait illisible). Dans un dossier : en-tête fixe du client, six onglets stables
(Synthèse, Fiche, Travail, Documents, Conformité, Facturation) avec sous-onglets, un onglet
« Accueil » pour revenir, l'historique en lien discret. Aucune nouvelle fonction ne crée
d'onglet : elle devient un sous-onglet (`TABS` dans `apps/clients/dossier.py`). Le menu de
gauche n'existe que sur les écrans du cabinet (accueil, échéancier, clients, paramétrage).

## D-022 — Cinq onglets : Documents et Conformité regroupés
Précise D-021 (demande de Jeremy) : Synthèse, Fiche, Travail, Documents et conformité,
Facturation. Un onglet pas encore construit reste cliquable et décrit ce qu'il contiendra.

## D-023 — Deux clics maximum
Règle d'ergonomie fixée par Jeremy : dans un dossier, toute information est atteignable en deux
clics au plus (onglet puis sous-onglet). Jamais de troisième niveau. Préférer des pages riches
(beaucoup d'informations, présentation aérée) à des pages supplémentaires.

## D-024 — Sites officiels lus pour chaque société, sans rien modifier seul
Pour chaque société active, l'outil consulte la BCE publique (fonctions : gérants,
administrateurs), les annexes du Moniteur belge (publications) et la Banque Nationale (dépôts
des comptes annuels, par son API officielle « Authentic Query », clé gratuite du cabinet). Un
relevé daté est conservé à chaque consultation (10 derniers par source) ; une nouveauté
déclenche l'événement `official.changed` et un point d'attention dans la synthèse. Consultation
automatique une fois par semaine et par société, par petits lots (`run_jobs`), ou à la demande
(bouton « Actualiser »). La BCE et le Moniteur n'ayant pas d'API ouverte, leurs pages sont lues
avec des analyseurs tolérants : si la page devient illisible, l'outil le dit et garde le
dernier relevé ; le lien vers le site officiel reste toujours disponible. Les fonctions lues
sont comparées aux relations ; les reprendre est une décision du cabinet (un clic, fiche
existante réutilisée, sinon fiche « prospect » créée). Les bénéficiaires effectifs ne sont pas
publiés à la BCE : le registre UBO (SPF Finances) se consulte dans MyMinfin, sans accès
automatique, et la loi interdit de s'y fier seul ; l'outil compare le calcul UBO aux
déclarations encodées.

## D-025 — Plus d'onglet Synthèse : un dossier s'ouvre sur la Fiche
Demande de Jeremy : la Synthèse montrait un peu de tout sans rien montrer vraiment. Elle est
supprimée ; ouvrir un client mène à Fiche › Identité et coordonnées (comme FID-Manager), page
qui sera retravaillée. Quatre onglets : Fiche, Travail, Documents et conformité, Facturation.
L'adresse `/clients/<n>/` reste valable et affiche la Fiche. Les points d'attention
(`services/alerts.py`) ne sont plus affichés : leur place est à décider avec Jeremy.

## D-026 — Travail fréquent en haut, paperasse à gauche (comme FID-Manager)
Remplace l'organisation en onglets et sous-onglets de D-021/D-022 (demande de Jeremy). Dans un
dossier : l'en-tête du client reste en haut (nom, badges, relations). Dessous, les onglets du
travail le plus fréquent : Documents, Clôture, Versements anticipés, Déclaration TVA
(seulement si le client est assujetti), Time sheet — mêmes onglets pour une société et un
IPP ; leur contenu sera défini un par un avec Jeremy. À gauche, un panneau groupé comme celui
de FID-Manager : Fiche (identité, BCE et TVA, Moniteur, comptes annuels, équipe), Organisation
(Mandataires, Actionnaires, Bénéficiaires effectifs, Autres relations, avec compteurs), Suivi
(échéances, historique), Conformité, Facturation. Toute page est à un clic. La page
« Relations » est découpée en Mandataires / Actionnaires / Autres relations ; pour une
société on n'y montre plus ses participations dans d'autres sociétés (visibles chez celles-ci).
Ajouter une entrée : dans `TOP` ou `SIDE` (`apps/clients/dossier.py`), jamais ailleurs.

## D-027 — Ordre des onglets du haut
Précise D-026 (demande de Jeremy) : Clôture, Déclaration TVA (si assujetti), Versements
anticipés, Documents. Time sheet retiré pour l'instant ; on en reparlera.

## D-028 — Un dossier s'ouvre toujours sur « Identité et coordonnées »
Remplace la règle de D-019 « changer de client garde la rubrique ouverte » (demande de
Jeremy) : quel que soit le chemin (liste, sélecteur du haut, relation cliquée), ouvrir un
dossier affiche Identité et coordonnées.

## D-029 — Fiche allégée : BCE, Moniteur et équipe sans page propre
Demande de Jeremy. Les sous-onglets « BCE et TVA », « Moniteur belge » et « Équipe du cabinet »
sont supprimés. Les différences avec la BCE (à reprendre en cochant) et les publications
récentes au Moniteur s'affichent sur Identité et coordonnées, seulement quand il y en a ; les
administrateurs publiés à la BCE sont sur la page Mandataires (« Ajouter aux mandataires »).
VIES : un simple lien vers le site officiel, comme FID-Manager (la vérification intégrée est
retirée de l'écran). Pas de fenêtre d'aperçu des sites officiels : les boutons ouvrent le site
sur la bonne société.
