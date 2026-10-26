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
- Mise à jour (même jour, demande de Jeremy) : seuls quatre états sont proposés au clic —
  Fini, Travail en cours, Avertissement, Pas nécessaire pour cette période. Recliquer sur
  l'état en cours vide la case. Dans la démo en ligne, on peut cocher pour essayer (rien
  n'est enregistré).

## D-041 — Un seul endroit pour déposer les documents, l'outil les classe
Demande de Jeremy : le dépôt ne se fait pas dans un dossier client mais à un seul endroit
pour tout l'outil (« Déposer des documents », barre du haut). L'outil trouve seul le dossier
et la place (`apps/documents/inbox.py`) :
- XML/PDF d'Intervat → grille TVA du dossier (D-040) ; un PDF n'est pris pour une déclaration
  que si son texte parle de TVA et de déclaration/listing ;
- carte d'identité (photo du dos ou PDF) → lignes codées lues sur le serveur, personne
  retrouvée par son numéro national parmi les fiches visibles → case « Cartes d'identité »
  de son dossier (le sien s'il est client, sinon une société liée), vérifiée aussitôt (D-035) ;
- sinon → « À classer » (`InboxItem`) : visible seulement par la personne qui l'a déposé,
  effacé après 30 jours (`INBOX_RETENTION_DAYS`, `run_jobs`), classé à la main en deux étapes
  (dossier, puis endroit).
- La liste « À confirmer » (PDF TVA sans période sûre, cartes à vérifier) est sur la même page.
  La zone d'import de l'onglet TVA est retirée.

## D-042 — E-mail au client après le dépôt TVA, acomptes déduits
Demande de Jeremy (option 1 proposée : comme FID, montants dans l'e-mail et PDF joint, avec
une case pour ne pas le joindre).
- Colonne « Acomptes » : acomptes **déjà payés** par le client (1er et 2e mois). Reste à payer
  = grille 71 − grille 72 − acomptes (négatif : en sa faveur), affiché sous le solde.
- Case « Com. client » → « Préparer l'e-mail au client » : fenêtre comme le visualiseur.
  L'outil propose l'objet et le texte (montant de la déclaration, acomptes déjà payés, reste à
  payer, date limite), modifiables ; « Refaire le texte » reprend les montants actuels.
  En bas à droite : Enregistrer, Envoyer au client. Rien ne part sans ce clic.
- Sécurité : destinataire choisi parmi les adresses e-mail de la fiche du client uniquement
  (jamais une adresse tapée à la main) ; ouverture et envoi journalisés ; ouvrir la fenêtre
  n'enregistre rien.
- Envoyer coche « Com. client ». Tant que la messagerie du cabinet n'est pas branchée
  (`OUTGOING_EMAIL_ENABLED` faux), l'e-mail est enregistré mais ne part pas, et la fenêtre
  le dit.

## D-043 — E-mails personnalisés : personne de contact, paiement prêt à copier
Demande de Jeremy.
- Fiche client, page Identité : « Personne de contact » = civilité (Monsieur, Madame, Madame
  et Monsieur, Docteur, Maître) + nom. Les e-mails commencent par « Bonjour Docteur Leroy, »
  (sinon « Bonjour, »).
- Le compte et la communication structurée de paiement sont lus sur le PDF de la déclaration
  quand ils y sont, et repris dans l'e-mail en bloc à copier-coller. Repris seulement s'ils
  sont sûrs : communication aux chiffres de contrôle corrects, compte valide sur une ligne qui
  parle de paiement (jamais une ligne de restitution, pour ne pas prendre le compte du client),
  un seul candidat. Sinon : la phrase générale.
- Emplacement exact de ces données sur le PDF d'Intervat à vérifier sur un vrai fichier.

## D-044 — Les e-mails partent de la boîte Outlook de chaque employé
Idée de Jeremy (le cabinet est sur Outlook / Microsoft 365). Application `apps/outlook`.
- « Ma boîte mail » (barre du haut) : « Se connecter avec Microsoft » (OAuth 2.0, code +
  PKCE, état vérifié). Droits délégués : `Mail.Send`, `User.Read`, `offline_access`, rien
  d'autre (pas de lecture des boîtes). Refus si `Mail.Send` n'est pas accordé.
- En base : adresse + jeton de renouvellement **chiffré** (Fernet, `MAILBOX_TOKEN_KEY`).
  Jamais de mot de passe. Jeton renouvelé à chaque envoi ; jeton refusé → boîte « à relier
  à nouveau ».
- Envoi par Microsoft Graph `/me/sendMail` (copie dans « Éléments envoyés »), pièce jointe
  jusqu'à 3 Mo. Si Microsoft refuse, l'e-mail n'est pas marqué envoyé et la case reste
  inchangée. Journaux : code d'erreur seulement.
- Branché d'abord sur l'e-mail TVA (D-042). Sans boîte reliée : e-mail enregistré seulement.
- Mise en route (inscription de l'application dans Microsoft Entra, secret placé directement
  dans le gestionnaire de secrets de l'hébergement) : `docs/OUTLOOK.md`. Nécessite l'outil
  en ligne chez le cabinet.
- Mise à jour (même jour) : format confirmé sur un PDF de l'administration (ligne « Pour tout
  paiement à "TVA-BTW" - compte (BIC : …) … communication structurée … »). L'outil reprend
  aussi le bénéficiaire et le BIC. Vérifié sans afficher ni conserver aucune valeur réelle.

## D-045 — Demandes de documents envoyées depuis Outlook, copies dans « Courriels »
Demande de Jeremy après son essai.
- Les demandes (carte d'identité d'abord) et leurs relances partent réellement de la boîte
  Outlook reliée : celle de l'employé qui demande, sinon du responsable du dossier, sinon de
  son assistant (pour les demandes et relances automatiques). Sans boîte reliée : préparées
  seulement, et l'outil le dit.
- Texte réécrit : « Bonjour Madame X, », raison (loi anti-blanchiment), consigne claire
  (photo recto verso en réponse), signature de l'employé, référence de la demande.
- Chaque e-mail réellement envoyé (demande, relance, e-mail TVA) est gardé en PDF dans
  « Archives › Courriels » du dossier.
- E-mail TVA : « Pour le paiement : » (sans « à copier-coller dans votre banque »).
- **Pas encore fait, en attente de l'accord de Jeremy** : lire les réponses pour ranger la
  carte jointe toute seule (demande le droit de lire la boîte, voir la question posée).

## D-046 — Lien sécurisé pour que le client dépose la pièce demandée
Choix de Jeremy (plutôt que la réponse par e-mail, qui demanderait de lire les boîtes et
laisserait la carte dans les messageries).
- Chaque demande (sauf signature) contient un **lien personnel** : page publique sans compte
  où le client dépose sa photo recto + verso (réunies en un PDF) ou un PDF. La pièce est
  rangée et, pour une carte, lue et vérifiée comme d'habitude (D-035).
- Lien de 256 bits au hasard ; seule son empreinte sert à le retrouver, le lien est gardé
  chiffré pour les relances (même lien, validité prolongée). Valable 14 jours
  (`REQUEST_LINK_DAYS`), inutilisable après réception ou annulation, bloqué après 10 essais.
  Il ne permet que de déposer : la page ne montre que l'objet de la demande ; lien inconnu ou
  expiré → même message neutre. Pas de cache, pas d'indexation, `Referrer-Policy: no-referrer`.
  Chaque dépôt est journalisé.
- L'e-mail demande de ne pas envoyer la carte par e-mail. `SITE_URL` (adresse des liens)
  réglée par l'installateur.

## D-047 — Archives « Courriels » : demandes annulées retirées, réponse sous l'e-mail
Demande de Jeremy.
- Annuler une demande supprime les copies de ses e-mails (demande, relances) des archives
  « Courriels ». L'annulation reste dans l'historique du dossier.
- Sous chaque e-mail de demande archivé, la pièce renvoyée par le client (par le lien
  sécurisé) s'affiche avec sa date de réception et s'ouvre dans le visualiseur.

## D-048 — Signature en ligne des documents par le client
Mandat de Jeremy (« fais-le pour tout le reste »).
- Un document à signer (lettre de mission, déclaration UBO, procuration) part avec le lien
  personnel de D-046. Le client lit les pages (images, rien à télécharger), dessine sa
  signature, coche « J'ai lu et j'approuve ».
- L'outil vérifie la signature (vraie image, assez d'encre, taille limitée) et la redessine,
  ajoute au document **inchangé** une page « certificat de signature » (qui, quand, adresse IP,
  empreinte SHA-256 du document lu), range le document signé (l'envoyé reste aux archives),
  garde la preuve (`Signature`) et envoie une copie au client depuis la boîte Outlook.
- Valeur : signature électronique simple (Code civil, livre 8 ; eIDAS), appréciée par le juge,
  renforcée par la piste d'audit. Une signature qualifiée (itsme, eID) pourra venir plus tard
  par un prestataire agréé (coût par signature) — à décider par Jeremy.

## D-049 — Fiche de risque guidée
- 11 questions tirées de la loi du 18/09/2017 (annexes I à III) et de la norme ITAA. L'outil
  propose une réponse quand il sait (activité BCE dans un secteur sensible, pays, structure de
  détention, ancienneté, fiche précédente) et dit pourquoi ; le reste est « à répondre ».
- Points → faible (0-2), moyen (3-5), élevé (6+). PPE, pays à haut risque, prête-noms :
  élevé d'office. Révision : faible 5 ans, moyen 3 ans, élevé 1 an (`RISK_REVIEW_YEARS`),
  alignées sur le futur règlement européen (AMLR 2027).
- Le PDF est rangé dans la case « Fiche de risque » avec sa date d'expiration = prochaine
  révision. Risque élevé : en attente de la validation de l'AMLCO (droit « aml.decide »),
  bouton « Valider » ; un AMLCO qui remplit la fiche la valide d'office.
- Barème, secteurs et pays sont des points de départ **à valider par l'AMLCO du cabinet**.

## D-050 — Documents obsolètes et suivi de ce qui expire
- Un document produit par l'outil garde une empreinte (HMAC, sans numéro national) de chaque
  partie du dossier utilisée. Si l'adresse, les mandataires, les bénéficiaires… changent, la
  ligne passe en orange « À mettre à jour : adresse modifiée depuis ».
- Chaque jour : une échéance « Anti-blanchiment » est créée pour le gestionnaire quand une
  fiche de risque ou un extrait UBO expire dans les 60 jours, ou qu'un document est obsolète.
  Elle se ferme seule quand le document est remplacé. Les cartes d'identité restent demandées
  directement au client (D-035).

## D-051 — Tableau « Conformité » et demande groupée
- Nouvelle entrée du menu principal « Conformité » (pas un onglet du dossier) : tous les
  dossiers visibles, ce qui manque (rouge), ce qui expire (orange), et ce que l'outil peut
  demander tout de suite. Filtre « Mes dossiers / Tout le cabinet ».
- « Demander » : **un seul e-mail et un seul lien par client** pour toutes les pièces
  (cartes d'identité + documents préparés à signer). La page du lien liste les documents ;
  le client dépose et signe en une ou plusieurs fois. Une seule relance pour le tout, qui ne
  cite que ce qui manque encore. La demande se clôture quand tout est reçu.
- Un document jamais préparé n'est jamais envoyé d'office : il faut le générer et le relire.
- Le même bouton existe dans la case « À recevoir » du dossier.

## D-052 — Automatismes : e-mails au client, résumé mensuel aux employés
Choix de Jeremy (24/10/2026).
- **E-mails automatiques : au client seulement.** Ce que le client doit fournir et qui expire
  (carte d'identité) lui est demandé tout seul, avant l'expiration (`IDENTITY_RENEWAL_DAYS`)
  ou dès qu'elle a expiré. Plusieurs cartes pour le même client : **un seul e-mail et un seul
  lien** (demande groupée, D-051). Relances : 2, à 7 jours d'intervalle.
- **Employés : pas d'e-mail.** Une fois par mois (premier passage du mois), deux
  notifications dans l'outil (cloche en haut) pour les dossiers de son équipe :
  « N dossiers à mettre en ordre » et « Ce que l'outil a fait en <mois> » (demandes
  envoyées, rappels, documents reçus, demandes sans réponse après les rappels). Seulement des
  nombres et un lien vers « Conformité » : aucun nom, aucune donnée sensible.
- Ce que le cabinet doit faire lui-même (fiche de risque, extrait UBO, document à mettre à
  jour) reste une échéance du gestionnaire (D-050) et apparaît dans le résumé.

## D-053 — Réglages de délais et accueil
Mandat de Jeremy (« fais tout ce qui améliore »), propositions annoncées le 24/10.
- Carte d'identité : demande au client **60 jours** avant l'expiration (avant : 30), en même
  temps que la ligne passe en orange (`IDENTITY_RENEWAL_DAYS`).
- Extrait du registre UBO rangé sans date : valable **un an** (`UBO_EXTRACT_VALID_DAYS`), car
  on le reconsulte au moins une fois par an.
- Accueil : trois chiffres « de mes dossiers incomplets / à revoir bientôt / demandes en un
  clic », vers l'écran Conformité. Calcul gardé 15 minutes en mémoire (des nombres seulement).
- Tableau de conformité : toutes les cases d'un dossier lues en une fois (environ 6 fois plus
  rapide).

## D-054 — Carte d'identité : 15 jours avant l'expiration
Choix de Jeremy (24/10) : 60 jours, c'est trop tôt, personne ne renouvelle sa carte deux mois
avant. La ligne passe en orange **et** la demande part au client **15 jours** avant
l'expiration (`IDENTITY_RENEWAL_DAYS`, `identity.WARN_DAYS`). Remplace ce point de D-053.

## D-055 — Rappels de la carte après l'expiration, puis avertissement du gestionnaire
Choix de Jeremy (24/10).
- Carte d'identité : demande au client 15 jours **avant** l'expiration (D-054), rappels
  automatiques 15 jours et 30 jours **après** l'expiration (`CARD_REMINDERS_AFTER_EXPIRY`).
  Carte déjà expirée au moment de la demande : rappels 15 et 30 jours après la demande.
  Les autres demandes gardent un rappel tous les 7 jours (2 au plus).
- Le lien sécurisé reste valable jusqu'au rappel suivant + 14 jours (il ne doit pas expirer
  entre deux rappels) ; il sert toujours une seule fois.
- **Sans réponse 15 jours après le dernier rappel** (`REQUEST_ESCALATION_DAYS`) : plus d'e-mail
  au client ; le gestionnaire est averti dans l'outil — pastille rouge « N sans réponse » en
  haut de l'écran (seulement pour les dossiers de son équipe), page « Clients sans réponse »,
  badge « ⚠ sans réponse » dans l'en-tête du dossier, ligne dans le résumé mensuel.

## D-056 — Nouveau look « style Apple »
Choix de Jeremy (24/10) parmi 5 maquettes : la 5 (« moderne doux »), poussée vers un style
Apple. Seule l'apparence change (aucune page, aucun lien, aucun droit modifié) : une couche
de style ajoutée à la fin de `static/css/app.css`.
- Fond gris très clair, cartes blanches très arrondies sans contour, ombres douces.
- Barre du haut translucide, menu de gauche façon Finder, onglets du dossier en « segmented
  control », grand titre du dossier, boutons en pilule bleue, états par pastille de couleur.
- Police Inter **hébergée par l'outil** (`static/fonts`, licence OFL) : aucun appel à Google
  Fonts ni à un autre site (confidentialité). Sur Mac, la police du système (San Francisco).

## D-057 — Look « moderne doux » (maquette 5), à la place de D-056
Choix de Jeremy (24/10) : rester exactement sur la maquette 5. Remplace l'essai « style
Apple » de D-056 (même principe : une couche de style en fin de `static/css/app.css`, aucune
fonction changée).
- Fond lavande clair, cartes blanches très arrondies et à plat, police Manrope **hébergée
  par l'outil** (licence OFL, aucun appel extérieur), violet indigo pour les actions.
- Barre du haut blanche, onglets du dossier en pilules (l'onglet ouvert en bleu nuit),
  en-tête du dossier dans un bloc blanc avec pictogramme, bandeau « tout demander » foncé.
- Nouveau dans l'en-tête du dossier : barre **« Dossier anti-blanchiment : NN % »**
  (documents en ordre / documents exigés, cartes d'identité comprises), lien vers Documents.

## D-058 — Feuille de temps reliée aux dossiers
Demande de Jeremy (25/10) : un calendrier où chacun note ce qu'il a fait, avec les heures,
relié (ou non) à un dossier.
- `TimeEntry` : jour, début, fin, dossier facultatif (seulement parmi les dossiers visibles),
  activité (TVA, compta, clôture, impôts, juridique, conseil, social, administratif, interne,
  formation, autre), description courte. Pas de chevauchement, 14 h maximum par entrée.
  Interne, formation ou sans dossier = non facturable.
- Vues : la journée (Ma journée › Mon agenda, clic à l'heure voulue pour ajouter), la semaine
  (lien « Voir la semaine »), et dans le dossier la rubrique **Temps passé** (panneau de gauche,
  groupe Facturation) : totaux, par activité, par mois, ajout rapide.
- Vie privée des employés : chacun voit et modifie seulement ses heures. Voir celles d'un
  collègue demande le nouveau droit « timesheet.all » et chaque consultation est journalisée.
  Dans un dossier, tout le monde voit les totaux ; le détail des lignes des collègues demande
  ce même droit. Historique des modifications conservé.

## D-059 — « Ma journée » remplace l'accueil
Idée retenue par Jeremy (maquette A). Deux sous-onglets :
- **À traiter** : « Prêt à valider » (e-mail TVA prêt, PDF TVA à confirmer, carte reçue à
  confirmer, risque élevé à valider pour l'AMLCO, fichiers à classer, pièces à demander en un
  clic), « À faire vous-même » (échéances du jour ou en retard, clients sans réponse), « Fait
  tout seul depuis hier » (rappels, demandes automatiques, pièces reçues, cartes classées).
  Sur le côté : la semaine, le temps encodé aujourd'hui, l'état de mes dossiers, signaux BCE.
- **Mon agenda** : la feuille de temps du jour, façon agenda (D-058).
- « Mes dossiers » = ceux de mon équipe ; tous les dossiers visibles si je n'en ai aucun.
  Tout passe par `visible_to`. L'entrée « Ma journée » remplace « Accueil » dans le menu.

## D-060 — « Ma boîte mail » : les e-mails de l'employé rangés par dossier, sans IA
Idée de Jeremy (25/10), version 1 validée sur maquette. But : ne plus devoir ouvrir Outlook.
- **Qui voit quoi.** Chaque employé active lui-même la lecture de *sa* boîte (« Activer avec
  Microsoft », droit délégué `Mail.Read` en plus de `Mail.Send`). Seul lui voit ses e-mails
  dans l'outil : pas de partage entre collègues, pas d'accès par l'administrateur de l'outil.
  Outlook reste la boîte d'origine. Rien n'est lu avant la date d'activation.
- **Où va la donnée.** Copie dans la base du cabinet (Belgique) : texte simple du corps
  (jamais de HTML affiché, donc ni image espion ni script), pièces jointes dans le stockage
  des documents, servies avec les en-têtes de sécurité habituels. Aucun service externe en
  dehors de Microsoft ; **aucune IA**, ni pour classer, ni pour répondre (choix de Jeremy).
- **Classement par règles vérifiables**, dans l'ordre : référence d'une de nos demandes dans
  l'objet ; adresse connue (adresse d'une société → la société ; adresse privée d'un
  dirigeant → petit choix « société » ou « personne physique », sous-dossier de la
  société) ; numéro d'entreprise connu dans le texte (courriers du SPF…) ; sinon « à classer
  vous-même ». Seuls les dossiers visibles de l'employé (`visible_to`) sont proposés.
- **L'humain décide.** L'e-mail reste dans la boîte de réception avec l'endroit proposé ; il
  n'est rangé que quand l'employé clique « Traité : classer ». Après une réponse, il reste
  aussi en réception jusqu'au clic. Les e-mails envoyés sont rangés d'office quand il n'y a
  pas de choix à faire.
- **Clic droit / « ⋯ »** : Ajouter une échéance (D-061), Reclasser dans…, Ajouter à la
  timesheet (agenda pré-rempli), Privé : retirer (copie effacée et jamais recopiée).
- **Pièces jointes** : rangées dans un sous-dossier « Pièces jointes » personnel. L'outil
  reconnaît (sans IA) déclaration TVA, carte d'identité, extrait UBO, avertissement-extrait
  de rôle, facture et propose « Ranger dans le dossier » (le vrai dossier, via le dépôt
  unique D-041 pour TVA et cartes). Le numéro national lu sur une carte ne sert qu'à trouver
  la personne : ni gardé, ni affiché, ni journalisé.
- **Répondre / écrire** depuis l'outil : texte écrit par l'employé, envoyé par sa boîte
  Outlook. Case « J'attends une réponse » → liste « En attente de réponse », fermée seule
  quand la réponse arrive.
- **Recherche** : un dossier + des mots ; recherche plein texte PostgreSQL (accents ignorés,
  pluriels compris), résultats classés et mots surlignés.
- **Traçabilité** : ouverture d'un e-mail, activation, désactivation journalisées.
- **Durée de conservation** : copie non rangée effacée après 1 an ; rangée, 10 ans après la
  fin de la relation client. Désactiver la lecture efface toutes les copies.
- Relève toutes les 5 minutes (`run_jobs`), 200 e-mails au plus par passage.
- **À faire avant l'usage réel** : analyse d'impact (AIPD) et note d'information aux
  employés (lecture de leur boîte professionnelle) ; ajout de `Mail.Read` dans Entra
  (docs/OUTLOOK.md).
- Pas retenu pour l'instant : partage d'une boîte entre collègues, modèles de réponse, toute
  IA. Plus tard : adresse « support » distincte pour les demandes automatiques.

## D-061 — Échéances personnelles et rappel le jour J
- Une échéance (`Task` manuelle) peut avoir une heure de début et de fin et l'option « me
  rappeler le jour J ». Créée depuis un e-mail (clic droit) ou depuis Ma journée › Mon agenda
  (« Une échéance »). Elle est attribuée à l'employé qui la crée, dans un dossier visible.
- Dans l'agenda : en pointillés avec une cloche, à l'heure prévue ; sans heure, en haut
  (« Toute la journée »).
- Le jour J : bandeau « Rappel d'aujourd'hui » dans l'agenda et notification dans la cloche
  (une seule fois, `run_jobs`). Aucun e-mail.

## D-062 — Lecture des cartes sur de vraies photos de téléphone
Retour de Jeremy (25/10) : une photo nette de carte n'était pas lue. Mesure sur des photos
FICTIVES « de téléphone » (carte de travers, perspective, flou, reflet, table, photo couchée
avec l'orientation dans les métadonnées) : 1 sur 40 lue avant, 40 sur 40 après, et 54 sur 60
sur une seconde série jamais vue.
- `apps/documents/card_reader.py` : photo remise à l'endroit, recherche de la bande des lignes
  « machine » par traitement d'image classique (OpenCV, local, sans IA), redressement,
  agrandissement, quelques versions (contraste, noir et blanc), photo retournée ou couchée.
  Arrêt dès qu'une lecture passe tous les contrôles ; 40 secondes au plus ; une lecture
  bloquée est abandonnée sans planter.
- Lecture plus tolérante (`mrz.py`) : « < » perdus ou lus K/L dans le remplissage, caractère
  parasite, forme de chaque ligne vérifiée.
- Garde-fou en plus : sur une carte belge, le numéro national lu doit passer son propre
  contrôle (modulo 97). Un cas réel l'a montré utile : une lettre parasite décalait le numéro
  et le contrôle global tombait juste par hasard.
- Nom : une seule lettre mal lue est tolérée, et seulement si le numéro national lu est celui
  de la fiche (c'est lui qui prouve l'identité). Sinon, « à confirmer » comme avant.
- Toujours rien n'est conservé : ni la photo de travail, ni le texte lu, ni le numéro.
- Nouvelles dépendances : `opencv-python-headless`, `numpy`.

## D-063 — Accueil personnel selon la période, et gestion hybride des dossiers
Validé par Jeremy sur maquettes (25/10).
- **Accueil** (menu « Accueil », l'adresse d'arrivée `/`) ; « Ma journée » passe à
  `/ma-journee/`. Chacun ne voit que **ses** dossiers : ceux où il est affecté (expert-comptable,
  comptable…) et les dossiers hybrides qu'il a pris. Jamais de nom de collègue ; le total du
  cabinet ira dans l'onglet Administrateur.
- **L'écran suit la période** (`apps/core/accueil.py`), calculée à partir des échéances déjà
  générées : une campagne = mes échéances d'une famille (TVA, listing, comptes annuels, ISOC,
  IPP, AG) tombant le même mois. Elle est « en cours » du 1er du mois de sa date limite (IPP :
  165 jours avant) jusqu'à la date limite. Au centre la grande campagne en cours ; **la TVA
  passe toujours en premier** (« en mois TVA, c'est LE mois TVA », mensuels compris) ; un mois
  avec seulement des mensuels n'est pas une grande période. Autres campagnes non terminées :
  « Aussi en cours ». Sinon : **période calme** (mes échéances des 30 jours, la prochaine
  grande période et la date où l'Accueil changera).
- Calendrier fiscal du mois (mes dates limites fiscales seulement), compte à rebours, barre
  « Mes déclarations déposées X / Y » et détail (trimestriels / mensuels), liste de mes dossiers
  restants (pas commencé, en cours, en attente du client, **en retard**).
- Sélecteur du haut : au clic, les **5** derniers dossiers ouverts.
- **Gestion hybride** : option des réglages du cabinet (`CabinetSettings`, administrateurs,
  coupée par défaut, historisée). Activée, le comptable (rôle « Assistant ») d'un dossier peut
  être « Hybride » : pas de comptable fixe. L'expert-comptable (« Responsable ») reste attitré.
  « Je le prends » (un seul à la fois, contrainte en base) : ses échéances ouvertes sans
  responsable lui sont attribuées, rendues à « personne » quand il le rend. Tableau « Dossiers
  hybrides » sous la période, sur l'Accueil : les dossiers libres et ceux que **j'ai** pris ;
  ceux des collègues ne sont pas listés (seulement leur nombre). Dans le dossier : badge
  « Hybride · libre / pris par X », pour ne pas travailler à deux dessus. Sans temps encodé
  pendant N jours (14 par défaut, réglable), le dossier redevient libre et la personne est
  prévenue dans la cloche. Événements `hybrid.taken`, `hybrid.released`,
  `client.hybrid_changed`.
- Pas construit : l'état des sites de l'administration (maquette F) — aucune source publique
  fiable vérifiée ; ne rien afficher plutôt qu'un faux « vert ». À étudier.


## D-064 — Reprise FID : dossiers complets (contact, « Hybride », feuille Relations)

- L'import de l'export clients (D-013) reprend aussi la **personne de contact**
  (civilité + nom) et accepte « Expert-comptable » / « Comptable » comme intitulés de colonnes.
- Dans la colonne du comptable, la valeur **« Hybride »** met le dossier en gestion hybride
  (D-063) au lieu de chercher un collaborateur. Une fiche existante n'est passée en hybride
  que si elle n'a pas de comptable fixe (jamais d'écrasement).
- **Feuille « Relations »** facultative dans le même classeur (n'importe quelle feuille après
  la première, reconnue par ses en-têtes, config/reprise/clients.yaml) : une ligne par lien
  (dossier, personne, rôle, part %, depuis, jusqu'au). Chaque fiche est désignée par son code
  client, son numéro d'entreprise ou national, ou son nom exact s'il est unique. Un lien déjà
  présent (même dossier, même personne, même rôle) n'est jamais doublé : réimporter le fichier
  ne change rien. Une part « 0,6 » (cellule Excel en %) vaut 60 %. Lignes non comprises :
  signalées dans le rapport, jamais devinées. Source des liens : « reprise ».
- Comme le reste de la reprise : analyse d'abord (rien n'est modifié), puis confirmation ;
  le rapport ne contient jamais de numéro national.
- Fichier de test : 30 dossiers fictifs (numéros d'entreprise dans la plage 0020.9xx.xxx,
  jamais attribuée par la BCE ; numéros nationaux fictifs valides).

## D-065 — Recette de nuit : tenue de charge, politique de sécurité du contenu

- **Tenue de charge** : essai avec 1 500 dossiers fictifs et 3 300 échéances. Le tableau de
  conformité calculait chaque dossier séparément (une dizaine de requêtes par dossier :
  22 secondes pour « Conformité » et « Ma journée »). Il charge désormais tout en une dizaine
  de requêtes pour l'ensemble (`compliance.load`, `identity.preload`) : 0,2 à 0,4 seconde.
  Résultat identique vérifié par un test (calcul dossier par dossier = calcul groupé).
  « Conformité » est découpée en pages de 50 dossiers ; le tableau hybride de l'Accueil liste
  les 15 dossiers libres les plus urgents (le total reste affiché).
- **Politique de sécurité du contenu** (en-tête `Content-Security-Policy`, intégré à Django) :
  le navigateur n'exécute que les scripts servis par l'outil (aucun script en ligne, aucun site
  tiers) et l'outil ne peut pas être affiché dans un autre site. Les trois listes déroulantes
  qui utilisaient un script en ligne passent par `data-autosubmit`. Vérifié : 103 pages sans
  erreur, connexion et ajout d'une clé d'accès (clé virtuelle) fonctionnent.
- Parcours automatiques gardés pour les prochaines recettes (hors dépôt, données fictives) :
  toutes les pages avec trois profils, formulaires remplis de valeurs absurdes (aucune erreur
  500, aucun script renvoyé), formulaires de l'administrateur envoyés par un stagiaire sans
  droits (aucune écriture, sauf l'actualisation des données publiques BCE / Moniteur / BNB),
  fiches d'un portefeuille privé demandées par adresse (aucune fuite), numéro national
  recherché dans les pages, journaux et tables techniques (jamais en clair).

## D-066 — « Ma boîte mail » : mise en forme et envoi programmé

- **Mise en forme** (gras, italique, souligné, listes à puces ou numérotées) dans « Répondre »
  et « Nouveau message ». Éditeur du navigateur, sans bibliothèque externe (script de l'outil,
  compatible avec la politique de sécurité du contenu). Avant l'envoi, le serveur ne garde
  que ces balises, **sans aucun attribut** (ni lien, ni image, ni script : bibliothèque `nh3`).
  Sans JavaScript : la zone de texte simple d'avant. Le corps gardé dans l'outil reste du
  texte simple (D-060).
- **Envoi programmé** (`ScheduledMail`) : « Programmer le » + jour et heure (heure belge), au
  plus un an à l'avance. Parti par le passage périodique (`run_jobs`, toutes les 5 minutes),
  donc à quelques minutes près. Rubrique « Programmés » : envoyer maintenant ou annuler ;
  seul l'auteur les voit. Une fois parti, annulé ou abandonné, **le contenu est effacé** de
  l'outil (l'original est dans les Éléments envoyés d'Outlook). Trois refus de Microsoft :
  abandon et notification dans la cloche (titre = objet, jamais le contenu).
- Si l'envoi est refusé (boîte déliée, heure passée…), le message tapé est remis dans la
  fenêtre (brouillon gardé le temps de l'envoi dans l'onglet du navigateur, effacé dès que
  l'envoi a réussi) et le motif s'affiche dans la fenêtre elle-même.
- Correction : le filtre `date_fr` affiche les dates et heures **à l'heure belge** (il les
  affichait à l'heure universelle, une heure de moins en hiver).
- Les e-mails envoyés étaient déjà visibles dans « Envoyés » (copie relevée dans Outlook).
- **Signature personnelle** (`Signature`, une par employé, « Ma boîte mail › Ma signature »,
  aussi depuis « Liaison Outlook ») : même éditeur, mêmes balises autorisées, 5 000 caractères
  au plus ; ajoutée en bas des messages et réponses écrits dans l'outil (case cochée par
  défaut, décochable pour un message). Pas de logo ni de lien. Les e-mails automatiques aux
  clients (demandes de pièces, TVA) gardent leur formule actuelle.
- **Logo du cabinet dans les signatures** : déposé une fois par un administrateur (Réglages du
  cabinet), commun à tous. L'image est refaite par l'outil (PNG, 600 × 200 au plus, 200 Ko au
  plus : seuls les pixels sont gardés). Elle part **jointe** à l'e-mail (« image dans le
  texte », `cid:`) : rien n'est chargé depuis Internet, donc pas d'image bloquée ni de
  « mouchard » d'ouverture. Chacun peut l'ôter de sa signature. Une réponse avec logo passe par
  un brouillon de réponse Outlook (créer, compléter, joindre, envoyer). Logo retiré avant un
  envoi programmé : la balise est enlevée (pas d'image cassée). Le logo n'est pas copié dans
  l'historique des réglages (seuls les autres réglages le sont).

## D-067 — Cap sur la commercialisation (26 octobre 2026)

Décision de Jeremy : l'outil n'est plus seulement un outil interne ; le but, **à terme**, est
de le vendre à d'autres cabinets. Information de cap seulement : on n'en est pas à préparer la
vente (précision de Jeremy, même jour) ; les questions ci-dessous attendront qu'il le décide. Remplace l'intention « un seul cabinet, pas un SaaS » des débuts (D-001 et
suivantes restent valables pour l'existant).

Ce qui ne change pas : la sécurité des données reste la priorité ; aucune donnée réelle de
client ne passe par Claude ; l'IA propose, l'humain décide.

À décider avec Jeremy avant de construire (rien n'est lancé) :
- **Modèle de mise à disposition** : une installation séparée par cabinet (données jamais
  mélangées, comme aujourd'hui ; recommandé au départ) ou une installation commune.
- **Paramétrage par cabinet** : nom, logo, règles d'échéances, droits — sans toucher au code.
- **Exigences avant la vente** : relecture du code par un développeur indépendant, test
  d'intrusion par une société spécialisée, contrat de sous-traitance RGPD avec chaque cabinet,
  conditions générales, assurance, support et engagement de disponibilité.
- **Exploitation** : mises à jour de toutes les installations, sauvegardes, supervision,
  facturation des clients.
- Les envois d'e-mails doivent partir d'une vraie boîte professionnelle (Microsoft 365 avec le
  domaine du cabinet, SPF/DKIM/DMARC) : un compte Outlook personnel relié à une adresse Gmail
  arrive en indésirables (constaté le 26/10/2026).
- **Brouillons** (`MailDraft`) : ce qu'on écrit dans « Nouveau message » ou « Répondre » est
  enregistré tout seul (2 secondes après la dernière frappe, et en quittant un champ).
  Rubrique « Brouillons » : reprendre ou supprimer. Seul l'auteur les voit. Effacé dès que le
  message part ou est programmé, quand l'auteur le supprime, ou après 30 jours sans
  modification (`run_jobs`). Un enregistrement arrivé après l'envoi ne recrée pas le
  brouillon. Le brouillon d'une réponse disparaît si l'e-mail d'origine est retiré (« Privé »).

## D-068 — Documents anti-blanchiment calqués sur les modèles de l'ITAA

Validé avec Jeremy, document par document (maquettes « Documents, un par un »).
- **Identification du client** (personne physique pour l'IPP, personne morale pour l'ISOC) et
  **identification mandataire** (personne physique ou morale, choisie selon la fiche) : mêmes
  rubriques que les modèles de l'ITAA et que FID-Manager (client occasionnel, risque,
  identité, vérification, gestion, nature de la relation, bénéficiaires effectifs, date de
  vérification, fin de mission, conservation 10 ans). Document interne : une seule signature,
  celle de la personne responsable de l'acceptation du client (l'employé qui valide). Créé,
  signé, rangé par le parcours existant (générer → valider).
- **Lettre de mission** (décidé, pas encore construit) : chaque cabinet dépose son modèle
  Word tel quel ; l'outil repère les trous (XXX, ……, [à compléter], surlignage), propose leur
  contenu, l'utilisateur confirme ou désigne à la souris ; passages à options choisis de même.
  Contrôle des éléments obligatoires de l'ITAA avant d'accepter le modèle (bloquant), éléments
  recommandés en avertissement. Le modèle d'un cabinet n'entre jamais dans le dépôt.
- Ensuite (à valider) : déclaration UBO pour le cabinet, registre UBO (MyMinfin), fiche de
  risque (modèle ITAA 5.1/5.2, révision 3 ans / 1 an), mandats SPF électroniques.

## D-069 — Lettre de mission sur le modèle Word du cabinet

Construit selon D-068. Un administrateur dépose le .docx du cabinet (Paramètres › Réglages du
cabinet › Modèle de lettre de mission), **sans rien y changer** :
- trous repérés : « XXX », « …… », « ____ », « [texte] », texte surligné ; contenu proposé
  d'après les mots qui précèdent (siège, numéro, représenté par, honoraires, fait à…) ;
  l'administrateur corrige par une liste. « À demander » = le comptable le donne à chaque
  lettre (honoraires, lieu, début…) ;
- passages à options, par paragraphe : toujours / assujetti TVA / société / personne
  physique / coché par le comptable ;
- éléments obligatoires (parties, début, fin, honoraires, documents, litiges, représentant,
  signature) retrouvés par mots-clés et confirmés à la main : un absent ou non confirmé
  bloque l'activation. Blanchiment, RGPD, secret professionnel : conseillés, signalés ;
- un seul modèle actif. Un modèle modifié qui n'est plus complet est désactivé.
Génération : seuls les trous sont remplacés (la mise en forme du reste est gardée), les
passages non retenus sont retirés, puis Word → HTML (mammoth) → PDF (WeasyPrint, aucune
ressource extérieure chargée). Brouillon puis signature en ligne par le parcours existant.
Sans modèle actif : modèle provisoire de l'outil. Aucune IA. Le modèle est gardé dans la base
du cabinet (jamais dans le dépôt) ; dépôt, réglage, suppression et génération sont journalisés.

