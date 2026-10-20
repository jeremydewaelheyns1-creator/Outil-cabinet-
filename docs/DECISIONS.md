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

## D-030 — Pas de page « Autres relations »
Demande de Jeremy : la page est supprimée. Les liens existants (conjoint, autres) restent
enregistrés et visibles sous le nom du client. Les bénéficiaires effectifs déclarés se gèrent
depuis la page Bénéficiaires effectifs.

## D-031 — Archives à gauche, Documents en haut pour ce qui est en cours
Demande de Jeremy. À gauche, un groupe « Archives » comme celui de FID-Manager : dossiers du
passé rangés (Légal et statuts, Moniteur belge, Comptes annuels (BNB), ISOC ou IPP, TVA,
Administratif, Courriels). L'onglet Documents (en haut) ne montrera que ce qui est en cours ;
un document traité y sera rangé automatiquement dans le bon dossier d'archives. Le contenu de
Documents est à définir avec Jeremy ; Anti-blanchiment et Pièces d'identité quittent la
gauche pour y aller, les Bénéficiaires effectifs y iront aussi (encore à gauche en attendant).

## D-032 — Automatique sans confirmation quand toutes les vérifications sont vertes
Demande de Jeremy (option B). Précise la règle « l'IA propose, l'humain décide » : un
automatisme peut ranger un document ET mettre à jour la fiche sans confirmation si toutes les
vérifications concrètes sont vertes (réponse à une demande de l'outil, type de document
attendu, données lues identiques au dossier — numéro d'entreprise ou national, nom —, document
lisible et complet, contrôles de lecture réussis). Au moindre doute, le document va dans
« À confirmer ». Garde-fous obligatoires : liste « Classé automatiquement », bouton « Annuler »
pendant quelques jours, tout est tracé. On commence par des cas précis (date d'expiration
d'une carte d'identité) et on élargit cas par cas.

## D-033 — Onglet Documents : des cases avec un état en couleur
Demande de Jeremy. L'onglet Documents montre une case par sujet en cours : À recevoir, Pièces
d'identité, Bénéficiaires effectifs (UBO), Anti-blanchiment, Lettre de mission. Chaque case a
une icône : vert (tout va bien), orange (à confirmer : document reçu lu sans certitude,
expiration proche…), rouge (problème : expiré, manquant, relance sans réponse), gris (pas
encore en place). Pas de case « À confirmer » séparée : une réponse à une demande va toujours
dans la case de son sujet (on sait ce qu'on a demandé) ; en cas de doute, la case passe en
orange. « À recevoir » liste les demandes envoyées au client jusqu'à leur réception. Les
documents signés sont des pièces « à recevoir » comme les autres. Les Bénéficiaires effectifs
quittent le panneau de gauche pour leur case.

## D-034 — Documents : stockage privé, lecture contrôlée, demandes et relances
Base commune de l'onglet Documents (application `apps/documents`). Les fichiers sont stockés
dans un espace privé dédié (`STORAGES["documents"]` : seau Cloud Storage privé en Belgique en
production, dossier local non publié ailleurs), sous un nom aléatoire, avec leur empreinte
SHA-256. Seuls PDF, JPG, PNG, Word et Excel sont acceptés, reconnus par leur contenu ; 20 Mo
maximum. Un fichier ne se lit que par une vue qui vérifie que le client est visible, journalise
la consultation et interdit au navigateur d'exécuter quoi que ce soit (sandbox, nosniff, pas de
cache). Les demandes « À recevoir » préparent un e-mail neutre (objet de la demande + référence,
aucune donnée sensible ni pièce jointe) ; tant que la messagerie du cabinet n'est pas branchée,
l'e-mail est seulement affiché. Relances automatiques (7 jours, 2 fois par défaut) par
`run_jobs` ; ensuite la case passe en rouge. À la réception, la pièce va dans sa case (carte
d'identité → Pièces d'identité, en archivant l'ancienne carte de la même personne) ou dans les
archives (document signé → Légal, autre → Administratif).

## D-035 — Pièces d'identité : lecture locale des lignes « machine », application automatique
Les cartes des personnes (mandataires, actionnaires, client IPP) sont suivies avec leur date
de validité : rouge si absente ou expirée, orange si elle expire dans les 60 jours ou si une
carte reçue est à confirmer, vert sinon. La carte reçue est lue sur le serveur du cabinet par
Tesseract (OCR local, aucun service extérieur) : on cherche les 3 lignes MRZ au dos et on
recalcule tous les chiffres de contrôle (norme OACI 9303). Elle est appliquée sans confirmation
(D-032) seulement si : contrôles exacts, carte d'identité, nom identique à la fiche, numéro
national identique (ou, à défaut, date de naissance identique), carte non expirée. Sinon :
« à confirmer » avec la raison, et le gestionnaire encode la date de validité. Un classement
automatique est annulable 7 jours. Le numéro national lu n'est ni conservé, ni journalisé, ni
affiché ; le numéro de carte est affiché masqué. Chaque jour, `run_jobs` demande la nouvelle
carte 30 jours avant expiration (une seule demande en cours par personne). Plus tard, une
lecture par IA (cloud du cabinet, Europe) pourra remplacer ou compléter l'OCR local
(`identity.READER`).

## D-036 — Visualiseur de documents au-dessus de la page
Demande de Jeremy (comme FID-Manager). Un clic sur un document ouvre une fenêtre au-dessus de
la page (sans la quitter) : titre, date, classement, personne ; boutons Imprimer et
Télécharger ; onglets Aperçu, Informations (fichier, origine, empreinte) et, pour une carte
d'identité, Données lues (numéro masqué, validité). L'aperçu montre les pages en images
fabriquées sur le serveur (pdftoppm) : le navigateur n'affiche jamais le PDF lui-même, aucun
contenu actif ne peut s'exécuter, et le rendu est le même partout. Word et Excel : pas
d'aperçu, téléchargement. L'ouverture est journalisée. Sans JavaScript, le même visualiseur
s'ouvre en page entière.

## D-037 — Documents exigés par la loi anti-blanchiment : un catalogue de types
Inspiré de la rubrique « Loi anti-blanchiment » de FID-Manager. Un catalogue
(`apps/documents/types.py`) décrit chaque document exigé : sa case (Lettre de mission ;
Anti-blanchiment : identification du client, identification de chaque mandataire, fiche de
détermination du niveau de risque, procuration ; UBO : déclaration des bénéficiaires effectifs,
extrait du registre UBO ; les cartes d'identité gardent leur suivi D-035), s'il est
obligatoire, s'il expire, qui le fournit et où l'ancien part aux archives quand un nouveau le
remplace. Chaque case affiche une ligne par type (et par mandataire) : document, date,
expiration, surligné orange (expire dans 60 jours, date indéfinie) ou rouge (manquant,
expiré) ; l'état de la case suit la pire ligne et nomme le premier problème. Les documents
fournis par le client se demandent en un clic depuis leur ligne (demande « À recevoir »
typée : à la réception, le document va dans la bonne case avec son type). Ce qui reste à
automatiser (fiches d'identification et fiche de risque produites par l'outil à partir des
données du dossier, lettre de mission pré-remplie, rappels de revue) sera proposé à Jeremy.

## D-038 — Un rectangle par ligne de FID dans l'onglet Documents
Demande de Jeremy (« 90 % des documents iront dans l'onglet Documents »). Précise D-033 et
D-037 : une case par type de document, dans l'ordre de la rubrique anti-blanchiment de
FID-Manager : À recevoir, Lettre de mission, Cartes d'identité, Déclaration des bénéficiaires
effectifs, Identification du client, Identification des mandataires (une ligne par mandataire),
Procuration, Fiche de détermination du niveau de risque, UBO (calcul + extrait du registre).
La case « Anti-blanchiment » disparaît (ses documents sont répartis, migration 0004).

## D-039 — Générer ou mettre à jour un document, puis l'envoyer pour signature
Demande de Jeremy. La plupart des documents viendront de FID-Manager ; l'outil sait aussi les
produire lui-même à partir des données du dossier (`apps/documents/generation.py`, modèles
HTML dans `templates/documents/modeles/`, PDF fait sur le serveur par WeasyPrint, aucun
service externe).
- Bouton « Générer » si le document n'a jamais existé, « Mettre à jour » s'il existe (même
  document, données et dates du jour).
- Le résultat est d'abord un **brouillon** affiché dans le visualiseur : déjà signé par le
  cabinet (mention « Signé électroniquement le … » au nom du gestionnaire), case du client
  vide. En bas à droite : « Envoyer au client » (documents à signer) ou « Valider et ranger »
  (documents du cabinet), et « Supprimer le brouillon ».
- « Envoyer au client » crée une demande « À recevoir » (relances comprises) ; le document
  signé reçu remplace l'ancien, qui part aux archives. Rien ne remplace le document en place
  avant d'être définitif.
- Générables : identification du client, identification des mandataires (sans signature du
  client), déclaration des bénéficiaires effectifs, lettre de mission et procuration (modèles
  provisoires, à remplacer par ceux du cabinet). La fiche de risque attend le questionnaire
  guidé. Numéro national toujours masqué dans les documents produits.
- Limites actuelles : la signature du cabinet est une mention, pas une signature électronique
  qualifiée ; l'e-mail est préparé mais pas envoyé tant que la messagerie et la signature en
  ligne ne sont pas branchées.

## D-040 — Onglet « Déclaration TVA » : la grille de FID et l'import Intervat
Demande de Jeremy, sur le modèle de FID-Manager (application `apps/vat`).
- Une ligne par période (trimestre ou mois), créée d'elle-même à partir des échéances TVA
  (`config/taches/regles.yaml`) ou à l'import d'une déclaration.
- Cinq cases cliquables : documents reçus, travail fini, déclaration déposée, listing
  intracommunautaire, communication au client. Sept états comme FID (jamais nécessaire pour ce
  client, non commencé, en cours, fait, pas nécessaire pour cette période, en attente,
  avertissement), avec date, auteur et remarque. « Jamais nécessaire » vaut pour toute la
  colonne du client. Puis solde (grille 71 à payer ou 72 à récupérer, décision de Jeremy),
  acomptes (trimestriels), responsable, assistant, remarque.
- L'échéance suit la grille : case « Déposée » faite → échéance terminée.
- Import : on dépose le XML et le PDF sortis d'Intervat, de n'importe quel dossier. Le XML est
  lu sans IA (numéro de TVA, période, grilles) : classement direct (règle D-032), case cochée,
  solde repris. Le PDF rejoint son XML (même envoi, ou XML déjà importé pour la même période) ;
  seul, il est rangé dans le dossier reconnu mais la période est « à confirmer » ; dossier non
  reconnu → rien n'est rangé. Un XML groupant plusieurs clients n'est rangé dans aucun dossier
  (montants repris seulement). Lecture XML par `defusedxml` ; tout reste sur le serveur ;
  seuls les dossiers visibles par l'utilisateur sont cherchés ; chaque import est journalisé.
- Format XML repris du format publié par le SPF Finances (VATConsignment / IntraConsignment),
  à vérifier sur un vrai fichier du cabinet.
