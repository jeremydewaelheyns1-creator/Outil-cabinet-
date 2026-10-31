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

## D-070 — Pas de lettre de mission de base

Demande de Jeremy : la lettre de mission est propre à chaque cabinet, l'outil n'en fait donc
aucune tant que le cabinet n'a pas déposé et activé son modèle (D-069). Le modèle provisoire
est supprimé. Sans modèle : « Pas de modèle du cabinet » dans le dossier (renvoi vers
Réglages du cabinet), on peut toujours ranger une lettre signée ou la demander au client.
Remplace la phrase de D-069 « Sans modèle actif : modèle provisoire de l'outil ».

## D-071 — Déclaration des bénéficiaires effectifs sur le modèle ITAA

Sources : ITAA, « Recueil de modèles de formulaires » anti-blanchiment, modèles 4.2 (société)
et 4.3 (ASBL, fondation). Le document reprend leurs rubriques : A. entités exemptées (néant),
B. bénéficiaires effectifs (nom, date et lieu de naissance, adresse, façon dont ils
contrôlent : directement / via telle société, % du capital et des votes), C. personnes
politiquement exposées, déclaration sur l'honneur (fin de relation si inexact, mise à jour du
registre UBO, art. 1:33 à 1:36 CSA), notes explicatives (seuil « plus de 25 % », définition
PEP, protection des données : 10 ans, art. 60 et 65). Signé par le client seul (comme le
modèle ITAA ; la maquette prévoyait aussi le cabinet).
Signature en ligne : pour chaque bénéficiaire, le client donne le **lieu de naissance** (que
l'outil ne connaît pas) et répond **PEP oui / non**. Réponses obligatoires, imprimées sur le
certificat de signature, gardées avec la preuve (`Signature.answers`), affichées dans
« Bénéficiaires effectifs » et reprises comme réponse proposée dans la fiche de risque (l'humain
valide). Rien n'est écrit automatiquement dans les fiches des personnes.

## D-072 — Mandats SPF : récapitulatif dans la page Documents

Demande de Jeremy : un encadré « Mandats SPF » en haut à droite de la page Documents du
dossier (pas d'onglet du haut, pas de case de document). Une ligne par mandat **utile** :
TVA (Intervat) si assujetti (normal ou mixte), Biztax pour une société ou une association,
Registre UBO si c'est le cabinet qui le dépose (choix « Registre UBO déposé par : le cabinet /
le client », le cabinet par défaut), Tax-on-web pour une personne physique. Pastille verte
quand c'est signé, rouge sinon ; **aucune alerte** ailleurs (ni accueil, ni conformité, ni
pourcentage). Mis à jour à la main (« Noter signé ») : le mandat se crée et se signe dans
« Mes mandats » du SPF, aucun accès connu ne permet à l'outil de le faire ou de le lire.
Chaque changement est journalisé et gardé dans l'historique.
Proposé, en attente de l'accord de Jeremy : bouton « Demander » sur une ligne rouge (ouvrir
« Mes mandats », afficher les infos à encoder, e-mail au client avec la marche à suivre) ;
rappel au client quand c'est lui qui dépose le registre UBO.

## D-073 — Registre UBO : toujours déposé par le cabinet

Jeremy : si le client dépose lui-même, il appelle le cabinet pour le faire ; l'outil part donc
du principe que le cabinet dépose le registre UBO. Le choix « Registre UBO déposé par » (D-072)
est retiré : la ligne « Registre UBO » figure toujours pour une société ou une association.
Vérifié : un mandat SPF par type (TVA, Biztax, Registre UBO…), mais plusieurs types peuvent être
créés en une seule demande dans l'application des mandats.

## D-074 — Mandats SPF : Finprof et Contentieux ajoutés

À la demande de Jeremy (« pour le moment ») : Finprof pour une société ou une association
(consultation de la situation fiscale), Contentieux pour tous les dossiers (réclamations).

## D-075 — Demander les mandats SPF manquants

Maquette 7b validée par Jeremy. Bouton « Demander les N mandats manquants » dans l'encadré
(seulement s'il y a des lignes rouges et le droit de modifier) → page sous l'onglet Documents :
① fiche à recopier sur le site du SPF (numéro d'entreprise du client et du cabinet avec bouton
« copier », cases à cocher = seulement les mandats rouges, bouton vers l'application des
mandats) ; pour une personne physique, le numéro national n'est jamais affiché ici (renvoi à
la fiche, « Afficher » journalisé) ; ② **un seul e-mail** au client avec tous ses mandats, le
lien et 3 étapes. Rien ne part sans clic ; l'e-mail part de la boîte Outlook de l'employé,
copie dans Archives › Courriels ; sans boîte reliée ou sans adresse, rien ne change. Autre
choix : « juste noter demandé ». Les lignes passent en orange (demandé), puis vert à la main.
Réglages du cabinet : numéro d'entreprise du cabinet et lien de l'application des mandats
(par défaut la page officielle du SPF sur les mandats ; adresse exacte de l'application à
vérifier par Jeremy, elle n'a pas pu être confirmée). Contenu de l'e-mail : aucune donnée
sensible (noms des mandats, lien public).

## D-076 — Fiche de risque sur le modèle ITAA (5.1 et 5.2)

Source : recueil de formulaires anti-blanchiment de l'ITAA, modèles 5.1 (grille détaillée)
et 5.2 (synthèse : critères, niveau faible / standard / élevé, motivation, AMLCO). Maquette 6
validée par Jeremy.
- Niveaux : faible / **standard** (terme ITAA, remplace « moyen ») / élevé.
- Les questions (inchangées, D-049) sont rangées dans les 4 critères du modèle 5.2 : client,
  activité / secteur, géographique, nature de la mission. Par critère : élevé si un facteur
  décisif (PEP, pays à haut risque, prête-noms), standard si un autre facteur, faible sinon ;
  motivation = les facteurs relevés. Synthèse = le critère le plus haut, relevée d'un cran si
  les facteurs s'accumulent (≥ 3 points : standard, ≥ 6 : élevé). À valider par l'AMLCO.
- Révision : 3 ans (faible ou standard), 1 an (élevé), et plus tôt en cas de changement.
- PDF : synthèse 5.2 en première page, détail des facteurs en annexe, « Établi le » par
  l'auteur, cadre AMLCO (« Fait le » une fois validé ; le PDF est refait à la validation,
  l'ancien fichier supprimé).

## D-077 — Prospect : lettre de mission avant d'être client

Jeremy : la lettre de mission part souvent après un rendez-vous, avant que la personne soit
cliente (elle peut refuser). On crée alors une fiche « Prospect » (formulaire « Nouveau
client », statut Prospect, préremplie depuis la BCE). Un prospect n'a ni échéances ni
demandes automatiques (les automatismes ne traitent que les clients actifs), mais on peut lui
préparer et envoyer la lettre de mission.
- Lettre signée en ligne → la fiche passe en « Client » (client depuis aujourd'hui), les
  échéances se créent, et l'expert-comptable du dossier (rôle « Responsable » ; à défaut les
  associés, puis les administrateurs) reçoit une notification « Nouveau client » avec ce qu'il
  reste à compléter (statut TVA, clôture, équipe, e-mail), puis anti-blanchiment et mandats.
- Lettre signée sur papier : bouton « Devient client » dans l'en-tête du dossier (journalisé).
- Proposé, pas encore fait : suppression des prospects sans suite après un délai à fixer.

## D-078 — Registre UBO (MyMinfin) : fiche d'encodage et suivi ; prospects sans suite

Jeremy : « fais comme tu le sens ». Registre UBO (maquette 5) :
- Dans « Bénéficiaires effectifs », une **fiche d'encodage** suit l'ordre de MyMinfin :
  entreprise, puis chaque bénéficiaire (nom, naissance, adresse, nature et % du contrôle,
  sociétés intermédiaires avec leur numéro), boutons « copier » ; pièces justificatives prises
  dans Archives › Légal et statuts ; « C'est encodé : ranger l'attestation » (extrait du
  registre UBO).
- L'extrait garde l'empreinte des bénéficiaires : s'ils changent, la ligne passe « à mettre
  à jour » et une échéance « Mettre à jour le registre UBO » (30 jours) est créée pour le
  responsable — la loi demande la mise à jour dans le mois. L'extrait expire après un an
  (confirmation annuelle, D-053). Sources : RSM Tax Insights 2021 (mise à jour dans le mois,
  confirmation annuelle, pièces justificatives : statuts, registre des parts).
- L'outil n'encode rien dans MyMinfin (aucun accès logiciel).
Prospects sans suite (complète D-077) : délai fixé à **1 an** sans modification. Une fois par
mois, les administrateurs voient combien il y en a (notification, lien vers la liste filtrée).
Rien n'est supprimé tout seul. Bouton « Supprimer ce prospect » (administrateurs, prospects
seulement, page de confirmation) : efface la fiche, ses documents et leurs fichiers, ses
demandes, preuves de signature, fiches de risque, coordonnées, liens et l'historique de la
fiche. Le journal des consultations garde la trace des accès ; la suppression y est notée
sans le nom.

## D-079 — Lettre de mission : limites connues du modèle Word

Gérés : trous dans le corps du texte et dans les tableaux, « XXX » découpé en plusieurs
passages de mise en forme, liens hypertextes, paragraphe à option seul dans une case de
tableau (vidé au lieu d'être retiré, pour que Word puisse ouvrir le fichier), fichiers
piégés refusés (taille décompressée > 40 Mo ou > 500 parties). Pas encore gérés : les trous
dans l'en-tête et le pied de page, et dans les modifications suivies (à accepter dans Word
avant de déposer le modèle). À proposer à Jeremy si un vrai modèle en a besoin.

## D-080 — « À mettre à jour » mémorisé pour les tableaux de plusieurs dossiers

Mesure (1 500 dossiers fictifs, chacun avec une déclaration UBO et un extrait du registre) :
« Ma journée » et Conformité prenaient ~30 s, car chaque document recalculait les
bénéficiaires effectifs de son dossier à l'affichage. Désormais `Document.changed_parts`
(parties modifiées depuis le document) est recalculé la nuit (run_jobs) et aussitôt après un
changement de fiche ou de relation (événements client.updated, client.updated_from_bce,
relation.saved, relation.deleted). Les tableaux (conformité, Ma journée, accueil) le lisent ;
la page d'un dossier reste calculée en direct. Résultat : < 1 s (puis cache 15 min).
Limite : un changement chez un actionnaire indirect (holding) se voit dans les tableaux le
lendemain matin ; dans le dossier lui-même, tout de suite.

## D-081 — Mot de passe oublié

Demande de Jeremy. Lien « Mot de passe oublié ? » sur la page de connexion (allauth) :
- l'e-mail part de la boîte Outlook reliée d'un administrateur, **sans copie** dans ses
  éléments envoyés (le lien ne doit rester nulle part) ; à défaut, par le serveur d'envoi du
  cabinet s'il est configuré ;
- lien valable 1 heure, une seule fois ; même réponse à l'écran que l'adresse existe ou non ;
  **aucun e-mail vers une adresse inconnue** (sinon n'importe qui pourrait faire envoyer des
  e-mails depuis la boîte d'un administrateur) ; limite de tentatives d'allauth ;
- la double authentification reste demandée après ; la réinitialisation est tracée dans le
  journal (jamais le mot de passe).
Dépannage sans boîte reliée : `deploy/mot-de-passe.sh` dans Cloud Shell (même principe que le
premier compte : secret temporaire supprimé aussitôt) ; adresse inconnue → rappel des comptes
administrateurs masqués.

## D-082 — Mandats SPF : états en clair, case « signé », envoi jamais perdu

Retour de Jeremy après un vrai envoi : l'e-mail était parti mais les lignes restaient rouges
et l'écran semblait bloqué. Cause probable : une erreur après l'envoi (copie d'archive) qui
annulait tout le reste. Désormais l'état « envoyé » est enregistré dès que l'e-mail est parti ;
la copie d'archive se fait à part et une erreur y est seulement notée dans le journal technique.
Encadré : chaque ligne dit son état en clair — « À demander » (rouge), « Envoyé le … — en
attente de réponse » (orange), « Signé ✓ le … » (vert) — avec une case « signé » à cocher (au
lieu de « Noter signé »). Après l'envoi, « Revoir les infos ou renvoyer l'e-mail » reste
disponible (rappel : objet « Rappel : … »).

## D-083 — Carte d'identité : scan par la caméra du téléphone du client

Maquette 3b validée par Jeremy (itsme écarté pour l'instant). Sur le lien de la demande de
carte, « Ouvrir la caméra » : cadre à la taille d'une carte ; recto pris tout seul quand
l'image est nette, éclairée et stable ; verso pris quand les 3 lignes codées sont lues et que
les chiffres de contrôle tombent juste (une seule confusion de chiffres semblables tolérée dans
les données facultatives). Lecture **dans le téléphone** (Tesseract en WebAssembly,
`static/vendor/tesseract`, servi par l'outil : aucun service extérieur, rien n'est envoyé avant
les deux bonnes photos). Les deux photos partent par le formulaire habituel ; le serveur relit
la carte (il lit désormais les photos contenues dans le PDF avant la page A4) et l'applique
comme avant (D-035). Sans caméra : dépôt de photos comme avant. Lien de la carte : 90 jours
(`REQUEST_CARD_LINK_DAYS`), fermé dès réception, 10 essais. Politique de sécurité des pages :
`'wasm-unsafe-eval'` ajouté (compilation WebAssembly uniquement, pas d'eval de texte).

## D-084 — « Déposer des documents » reconnaît les documents du SPF

Demande de Jeremy. En plus des déclarations TVA d'Intervat et des cartes d'identité (D-041) :
avertissements-extraits de rôle IPP / ISOC / IPM, accusés de réception Biztax et Tax-on-web,
listing clients annuel, compte courant TVA, versements anticipés, avis de rectification et
demandes de renseignements (`apps/documents/spf_docs.py`). Règles de mots sûrs, sans IA ;
aucun type sûr → rien n'est deviné. Dossier retrouvé par le numéro d'entreprise (modulo 97 ;
le numéro du cabinet est ignoré) ou, à défaut, par le numéro national (seulement pour la
recherche, jamais gardé ni affiché), parmi les dossiers visibles de la personne. Un seul
dossier → rangé dans Archives › ISOC / IPP / TVA avec un titre clair (« Avertissement-extrait
de rôle ISOC — exercice 2025 ») ; demande de renseignements et avis de rectification rangés
« à revoir » (réponse à donner). Sinon → « À classer » avec la raison. Courrier scanné sans
texte : 1re page lue sur le serveur (français installé dans l'image : tesseract-ocr-fra).
Reconnu avant la TVA (un avertissement ISOC peut contenir « TVA » et « déclaration »).
À enrichir avec de vrais exemples anonymisés si un document n'est pas reconnu.

## D-085 — Supprimer un document ; champs obligatoires avant une identification

Demandes de Jeremy.
- « Supprimer ce document » (fenêtre du document, page de confirmation) : supprime un document
  validé ou déposé par erreur, et ce qui en a été tiré (carte enregistrée, fiche de risque) ;
  le document qu'il avait remplacé (parti aux archives au même moment) est **remis en place**.
  Refusé pour un document signé par le client (il se remplace) ou en attente de signature.
  Journalisé.
- Identification du client / des mandataires : préparation **et** validation refusées tant
  qu'il manque une donnée obligatoire — personne : nom, prénom, date de naissance, nationalité,
  adresse, numéro national, carte d'identité valable ; société : dénomination, forme, numéro
  d'entreprise, siège, au moins un dirigeant ; et le niveau de risque (fiche de risque).
  Déclaration UBO : au moins un bénéficiaire calculé. L'écran dit ce qui manque, avec des liens.

## D-086 — Identifications : exactement les modèles ITAA 3.1 à 3.4

Jeremy : quand un modèle officiel existe, s'y tenir. Comparaison avec le recueil de
formulaires de l'ITAA, puis réécriture rubrique par rubrique : 3.1 (personne physique –
client : I occasionnel, II risque ☐ Élevé ☐ Standard ☐ Faible, III données personnelles avec
lieu de naissance, IV vérification, V contrôle PPE, VI nature de la relation, VII bénéficiaires
effectifs), 3.2 (personne physique – mandataire : … IV PPE, V pouvoirs, VI bénéficiaires du
mandataire), 3.3 (personne morale – client : siège social et d'exploitation, V gestion), 3.4
(personne morale – mandataire : IV gestion du mandataire, V pouvoirs). Blocs du modèle :
« Fait le … » (responsable de l'acceptation), « Établissement / vérification des données le
… », « La mission a pris fin le … ». Lieu de naissance et réponse PEP repris de la déclaration
UBO signée en ligne (D-071), sinon de la fiche de risque ; à défaut, laissés à compléter.
Remplace la mise en page de D-068 (même contenu, numérotation et rubriques du modèle).


## D-087 — Fiche de risque : exactement les modèles ITAA 5.1 et 5.2

Jeremy : la fiche ne suivait que la synthèse (5.2). Elle est refaite sur le formulaire
officiel 5.1 : 9 blocs (nature de la mission ; client ; nature, réputation et comportement ;
facteurs géographiques ; services et transactions ; client, activité et localisation de
l'annexe III ; varia), 41 critères, chacun noté faible / standard / élevé avec un
commentaire, puis la synthèse ; « Établi le », nom du professionnel, signature. Suit le 5.2
pour l'AMLCO : ses 4 critères sont déduits des blocs (client ← client, comportement, client
annexe III ; activité ← activité annexe III, varia ; géographie ← géographie, localisation ;
mission ← mission, services), motivation = critères relevés et leurs commentaires.
- L'outil propose un niveau quand il sait (BCE, pays, structure de détention, déclaration UBO,
  fiche précédente) et dit pourquoi ; ce qu'il a vérifié est gardé avec la fiche (le PDF refait
  à la validation AMLCO montre les mêmes éléments). Le reste est « à évaluer » ; un bouton met
  « faible » dans les cases vides, sans enregistrer (la personne relit puis enregistre).
- Synthèse proposée = le critère le plus élevé ; abaissable avec une motivation obligatoire,
  jamais si un critère décisif est élevé (PPE, gel des fonds, pays à haut risque, sanctions,
  terrorisme).
- Révisions (3 ans / 1 an) et validation AMLCO inchangées. Les anciennes fiches oui/non restent
  lisibles (correspondance vers les critères du 5.1) ; pas de migration de base.

## D-088 — TVA : acomptes avant l'e-mail, demande de documents sur clic, dates légales à jour

Demandes de Jeremy :
- Colonnes : « Acomptes » passe avant « Com. client » (il faut connaître les acomptes pour
  écrire l'e-mail du montant à payer).
- Case « Doc. reçus » : bouton « Demander les documents au client » (puis « Envoyer un
  rappel »). Même fenêtre que l'e-mail de la déclaration : texte proposé, relu, modifiable,
  envoyé **seulement sur clic** (jamais automatique, au choix du comptable). À l'envoi, la case
  passe « en attente ». `VatMessage.kind` distingue les deux e-mails. Bouton caché une fois les
  documents reçus.
- Dates (corrigé par D-094 : plus de report pour les trimestriels) : trimestriels le 25, mensuels le 20, reportés au jour ouvrable suivant (tolérance de
  la circulaire 2025/C/6, maintenue jusqu'à nouvel ordre par la circulaire du 1er octobre
  2025). La règle existait mais les échéances déjà créées gardaient l'ancienne date (seules les
  tâches futures intactes suivaient) et la ligne TVA en gardait une copie. Désormais : quand la
  règle donne une autre date, chaque échéance suit (même commencée, passée ou terminée : c'est
  un fait légal) ; `task.rescheduled` met la ligne TVA à jour ; et la génération repasse le jour
  même quand le fichier de règles change (`GenerationRun.rules_hash`), donc dès la mise à jour.

## D-089 — Délais prolongés par le SPF : surveillance, encodage, message à l'ouverture

Le SPF ne publie pas de calendrier lisible par une machine ; il annonce ses prolongations dans
des communiqués. Choix (Jeremy : « l'IA plus tard ») :
- **Sources** : deux flux RSS publics et officiels, lus une fois par jour (`run_jobs`) :
  communiqués du gouvernement fédéral (news.belgium.be, où publie le SPF Finances) et
  actualités de l'ITAA (relaie chaque décision du SPF). Liste dans `DEADLINE_SOURCES`. Simple
  lecture : aucune donnée du cabinet ne sort. Source illisible → réessayée le lendemain.
- **Repérage sans IA** : un mot de délai (prolongation, report, délai supplémentaire…) ET un mot
  fiscal (TVA, IPP, ISOC, déclaration…) → « article à vérifier » + cloche des administrateurs.
- **L'humain décide** : Paramètres › Délais du SPF. L'administrateur choisit l'échéance dans une
  liste (même règle, même période, même date actuelle : « Déclaration TVA 3e trimestre 2026 —
  actuellement le 26/10 (11 dossiers) »), la nouvelle date, une précision et le lien. Aussi
  possible sans article (encodage manuel).
- **Effet** : les échéances de tous les dossiers concernés sont déplacées (`task.rescheduled` →
  ligne TVA), la génération quotidienne respecte la prolongation, chacun voit un bandeau en haut
  de l'outil jusqu'à « Compris » (sauf celui qui l'a encodée). « Annuler » remet l'ancienne date.
- Plus tard (si utile) : une IA européenne, sans conservation, pour lire l'article et pré-remplir
  l'encodage ; elle ne recevrait que le texte public de l'article.

## D-090 — Pas d'IA externe pour l'instant (argument de confidentialité)

Jeremy, après avoir étudié la question (Claude via Google Cloud UE, Horus, RGPD) : l'outil
fonctionne bien sans IA, et « aucune donnée de vos clients n'est jamais envoyée à une IA » est
un argument de vente pour des cabinets tenus au secret professionnel. Donc : aucun service
d'IA externe. Formulation exacte à utiliser : « aucune IA externe, aucune donnée envoyée à une
IA » (pas « 100 % sans IA » : la lecture des cartes et des scans utilise Tesseract, un logiciel
local qui repose sur un petit réseau de neurones, sans rien envoyer à l'extérieur).
Si un jour on en ajoute : point par point, avec une IA en Europe, sans conservation ni
entraînement, confirmée par écrit (message préparé pour le support Google Cloud le 28/10/2026),
une seule porte d'entrée dans le code, et un outil qui continue de marcher si elle est en panne.

## D-091 — Grand test de Jeremy : trois défauts corrigés

Un dossier complet de documents fictifs (reprise FID, déclarations et listing Intervat, 10
documents du SPF, extrait UBO, statuts, facture, extrait bancaire) a été déposé dans une base
vierge. Trois défauts trouvés et corrigés :
1. **PDF de déclaration TVA pris pour un listing intracommunautaire** quand il cite une grille
   « intracommunautaire » (44, 46, 86…). C'est le titre (« déclaration périodique ») qui décide.
2. **Déclaration et listing du même trimestre déposés ensemble** : le second PDF effaçait le
   premier (et le compte de paiement). Chaque PDF n'enregistre plus que ses propres champs.
3. **Reprise FID** : la nationalité « Belge » (et « Française »…) n'était pas reconnue ; seuls
   les noms de pays l'étaient.

## D-092 — Un PDF de déclaration TVA vaut un XML

Jeremy : « ne fais pas de différence entre un PDF et un XML : si on dépose un document, c'est
un bon document ». Un PDF Intervat déposé seul, dont le dossier (un seul numéro d'entreprise
reconnu) et la période sont lus, est classé directement : ligne TVA créée si besoin, case
« Déposée » (ou « IC ») cochée, compte et communication de paiement repris, grille 71 / 72
reprise si elle est lisible sans ambiguïté et qu'aucun XML ne l'a déjà donnée. Ne reste « à
confirmer » qu'un PDF dont la période est illisible. Remplace la prudence de D-040 sur le PDF
seul. Un PDF mal rangé se supprime (D-085).

## D-093 — Déposer des documents depuis n'importe quelle page (maquette C)

Jeremy a choisi la piste C (« les infos données sont moins polluantes ») : on glisse des
fichiers sur n'importe quel écran de l'outil, un voile violet dit « Lâchez pour déposer », puis
un petit panneau en haut à droite suit la lecture, fichier par fichier (rond qui tourne → coche
verte, ou « ? » orange pour « à classer »), sans quitter l'écran en cours. Chaque ligne dit en
clair ce qui a été rangé et où, et s'ouvre d'un clic. Le résumé reste affiché jusqu'à ce qu'on
ferme le panneau (fini les bandeaux qui s'effacent seuls). Le bouton « Déposer des documents »
ouvre le même panneau.
- Un fichier = une demande au serveur (`?panneau=1`, même contrôles, mêmes droits, même
  journal) ; les XML partent d'abord. Un champ de fichier d'une page garde son rôle (on peut
  toujours déposer dans une case précise).
- Sans JavaScript, le bouton mène à la page « Déposer des documents », toujours là pour les
  documents « À classer » et « À confirmer ».
- Animations coupées pour qui a demandé moins d'animations à son système.

## D-094 — TVA trimestrielle : le 25, sans report ; calendrier avec les dates légales

Correction de D-088 (Jeremy) : la tolérance « reporté au jour ouvrable suivant » a pris fin
pour les déclarants trimestriels au 30/09/2025 ; elle reste pour les mensuels (le 20). La
règle `tva_trimestrielle` garde le report seulement pour les dates limites jusqu'au
30/09/2025 (`report_jusqu_au`). La génération repasse d'elle-même (empreinte des règles) et
toutes les échéances trimestrielles reviennent au 25, ligne TVA comprise.
Le calendrier de l'accueil montre toujours les dates légales de la TVA du mois (mensuelle,
trimestrielle en janvier, avril, juillet et octobre), même sans dossier concerné.

## D-095 — Supprimer des dossiers : corbeille, jamais d'effacement

Jeremy : sélectionner des clients dans la liste et les supprimer, avec une confirmation, et
pouvoir les retrouver et les réactiver.
- Liste des clients : une case par ligne (et « tout cocher »), bouton « Supprimer la
  sélection… » → page « Êtes-vous sûr ? » qui nomme chaque dossier → « Oui, supprimer ».
- « Supprimer » = mettre à la corbeille (`Client.deleted_at`, `deleted_by`) : rien n'est
  effacé, car les documents anti-blanchiment se gardent 10 ans. Le dossier disparaît partout
  (`visible_to` l'exclut : listes, recherche, tableaux, tâches) ; les échéances futures pas
  commencées partent, les demandes en cours au client sont annulées (plus aucune relance),
  plus de consultation automatique BCE / Moniteur.
- Clients › Corbeille : recherche, « Réactiver » par ligne ou pour la sélection ; tout revient
  tel quel (échéances régénérées).
- Réservé aux administrateurs ; tracé (historique de la fiche, journal, événements
  `client.deleted` / `client.restored`). Un numéro d'entreprise ou national d'un dossier en
  corbeille ne peut pas être recréé ni repris par la reprise FID sans le réactiver d'abord.

## D-096 — Document du SPF qui cite plusieurs dossiers : le premier cité

Deuxième grand test (10 dossiers) : le listing clients annuel d'un indépendant cite aussi les
numéros de TVA de ses clients ; si l'un d'eux est aussi client du cabinet, le document partait
dans « À classer » (« plusieurs dossiers correspondent »). Un document du SPF s'adresse au
contribuable cité en premier (déclarant, destinataire) : c'est désormais lui qui est choisi.

## D-097 — Après le 2e grand test : accueil rempli, aperçu des XML, archives rangées, extrait UBO

Retours de Jeremy sur le dépôt de ses 10 dossiers de test :
- **Accueil vide juste après la reprise** : les échéances des dossiers créés par la reprise FID
  étaient faites en arrière-plan (passage toutes les 5 minutes). Elles sont maintenant créées
  pendant l'import (jusqu'à 300 dossiers ; au-delà, toujours en arrière-plan).
- **Aperçu des XML d'Intervat** : le visualiseur montre la déclaration en clair (grilles par
  partie : sortie, entrée, taxes dues, déductibles, solde ; libellés du formulaire) et, pour un
  listing intracommunautaire, la liste des clients. Rien n'est modifié dans le fichier.
- **Archives par année** (2027, 2026, 2025…), puis **par période pour la TVA** (« T3-26 »,
  « 09-26 », en sous-onglets, le XML et le PDF d'une même déclaration réunis) et **par thème
  pour le reste** (Biztax, avertissements-extraits de rôle, compte courant TVA…). Année : celle
  de la période TVA, sinon celle du titre (« exercice 2025 »), sinon l'année d'ajout. Affichage
  seulement : rien n'est déplacé. Courriels et Moniteur restent en liste simple.
- **Extrait du registre UBO** : reconnu (« registre des bénéficiaires effectifs » + « extrait »)
  et rangé directement dans la case UBO de la société, avec sa date d'expiration.
- **Le rond qui tournait** : un PDF plein de texte passait aussi par la lecture de carte
  d'identité (reconnaissance de texte sur l'image, lente sur le serveur). Elle est réservée aux
  photos et aux PDF quasi sans texte.

## D-098 — Vrais documents officiels : procuration, comptes annuels, IPP, XBRL et Biztax

Jeremy a fourni six vrais documents anonymisés pour « entraîner » le dépôt. Ils ne sont **pas**
dans le dépôt et ont été effacés après usage : seule leur structure a été apprise ; les tests
(`apps/documents/tests/test_official_files.py`) en reprennent la forme avec des données
inventées.
- **Procuration fiscale et administrative** (modèle FID-Manager, « mandant » / « mandataire »)
  → case « Procuration » du dossier (société ou particulier). Reconnue en premier : elle cite
  aussi « TVA », « demandes de renseignements », « versements anticipés », « comptes
  annuels », « UBO », et partait sinon dans l'import TVA ou « à revoir ».
- **Copie de la déclaration IPP** (« copie de votre déclaration » / « document préparatoire »)
  → archives IPP du particulier. Pour les documents d'un particulier (déclaration IPP,
  avertissement-extrait de rôle IPP, Tax-on-web), le **numéro national passe avant** les
  numéros d'entreprise : une déclaration peut citer l'employeur, client lui aussi.
- **Comptes annuels PDF** (modèle BNB) et **comptes annuels XBRL** (`.xbrl`) → nouvel
  emplacement « comptes », affiché sur la page **Comptes annuels (BNB)** sous les dépôts lus à
  la Banque Nationale (par année, comme les archives) ; on peut aussi y déposer et y classer à
  la main. Pas de nouvelle entrée dans le panneau de gauche. Exercice : la fin de la période.
- **Déclaration Biztax** (`.biztax`) → archives ISOC (IPM ou INR selon le type de
  déclaration). Exercice d'imposition lu dans le fichier.
- **Extrait UBO** : la mise en page réelle de MyMinfin (« Informations relatives aux
  bénéficiaires effectifs ») est reconnue.
- **Aperçu** des XBRL dans le visualiseur : période, modèle, date de l'assemblée générale et
  quelques chiffres clés (bilan, capitaux propres, résultat ; résultat fiscal, base imposable,
  versements anticipés), et le nom des annexes jointes à la déclaration Biztax. Aucun nom ni
  adresse n'est repris. Lecture sûre (defusedxml).
- Dossier trouvé par le numéro d'entreprise du fichier, parmi les dossiers visibles de la
  personne qui dépose ; inconnu ou personne physique → « À classer » avec la raison.

Constat de sécurité remonté à Jeremy : dans la procuration, la signature électronique (nom du
signataire et certificat) et la propriété « enregistré par » du PDF gardaient des noms réels,
invisibles à l'écran. Conseil : imprimer en PDF (aplatir) et vider les propriétés avant envoi.

## D-099 — Doublons au dépôt : retenus, comparés, l'utilisateur décide

Demande de Jeremy : « être sûr de son coup » ; ne jamais supprimer soi-même ; montrer les deux
documents avec « Confirmer l'import » et « Supprimer le doublon ».
- **Doublon = contenu strictement identique** (même empreinte SHA-256, octet pour octet), avec
  un document déjà rangé dans un dossier **visible** par la personne qui dépose. Un fichier
  ressemblant (une correction, une autre version) n'est jamais un doublon. Un document d'un
  dossier invisible n'est jamais révélé : le dépôt suit alors son cours normal.
- Le fichier n'est **ni rangé ni supprimé** : il attend dans « Doublons à vérifier » (page
  Déposer des documents ; ligne « Déjà dans … — comparer » dans le panneau de dépôt). Comme
  « À classer », il n'est visible que par son auteur et effacé après le délai de conservation.
- **Comparer** : les deux côte à côte (dossier, emplacement, date et auteur du document rangé ;
  nom et date du nouveau dépôt ; aperçu de la 1re page). L'ouverture est journalisée.
- **Confirmer l'import** : le fichier est traité comme un dépôt normal (rangé une 2e fois) ;
  s'il n'est pas reconnu (une facture rangée à la main, par exemple), il rejoint le document
  identique, au même endroit, plutôt que de repartir dans « À classer ».
  **Supprimer le doublon** : seul le nouveau fichier est effacé ; le document déjà rangé n'est
  jamais touché. Si ce dernier a disparu entre-temps, le fichier redevient un simple « À
  classer ».
- Concerne le dépôt unique (barre du haut / Déposer des documents). L'import TVA de l'onglet
  Déclaration TVA et l'ajout dans une case gardent leur fonctionnement.

## D-100 — Tous les formats lisibles, pas seulement le PDF

Retour de Jeremy sur la page « Doublon à vérifier » : « pas que PDF, on a souvent XBRL, XML ».
Un seul aperçu lisible (`apps/documents/readable.py`), utilisé par le visualiseur ET par la
page des doublons (des deux côtés) :
- PDF et photos : page par page, comme avant ;
- XML d'Intervat : grilles TVA ; XBRL de la BNB et Biztax : chiffres clés (D-097, D-098) ;
- **autre XML** : l'arbre des balises et leurs valeurs, indenté (valeurs longues raccourcies,
  400 lignes au plus) ;
- **Excel** : les 60 premières lignes de 5 feuilles au plus ; **Word** : le texte et les
  tableaux.
Rien n'est exécuté : XML lu avec defusedxml, Word et Excel refusés s'ils dépassent 60 Mo une
fois décompressés ; un fichier abîmé affiche simplement « Pas d'aperçu » avec le bouton de
téléchargement.

## D-101 — Dossier de test 3 (demandes de documents) : trois corrections

En préparant les pièces qu'un client renvoie (carte, lettre de mission, déclaration UBO,
procuration, extrait UBO), trois défauts trouvés et corrigés :
- **Une lettre de mission partait dans la TVA** : il suffisait des mots « TVA » et
  « déclaration » n'importe où. Il faut maintenant le titre d'un document TVA (« déclaration
  périodique », « déclaration TVA », « listing / relevé intracommunautaire », « Intervat »,
  équivalents néerlandais).
- **Lettre de mission et déclaration des bénéficiaires effectifs signées** : reconnues au dépôt
  et rangées dans leur case.
- **Carte d'identité** : sur une photo, la lecture pouvait prendre la 1re ligne machine une 2e
  fois à la place du nom (les contrôles passent, le nom n'en a pas). Une lecture n'est
  acceptée que si le nom ressemble à un nom ; sinon on essaie l'image autrement.

## D-102 — IPP : un calendrier qui suit le SPF tout seul

Jeremy : « ça m'inquiète qu'on n'arrive pas à créer ce calendrier dynamique qui s'adapte tout
seul ». L'IPP n'avait aucune date : aucune échéance, rien au calendrier.
- **Date du cabinet : 16 octobre** (déclarations déposées par le mandataire, revenus
  spécifiques), confirmée par Jeremy. Dates publiées par le SPF encodées : revenus 2024 →
  16/10/2025, revenus 2025 → 16/10/2026.
- **Année pas encore publiée** : le 16 octobre de l'année suivante, marqué « date provisoire »
  au calendrier (`par_defaut` dans `regles.yaml`). Plus jamais de trou.
- **Le SPF annonce une autre date** (report ou date différente) : la veille quotidienne
  (D-089) prévient les administrateurs ; une fois encodée sur « Délais SPF », échéances et
  calendrier suivent (la mention « provisoire » disparaît). Une date peut désormais aussi être
  avancée, pas seulement reculée.
- **Calendrier** : la date IPP apparaît comme la TVA, même sans dossier concerné.
- **Pas de rétroactif** (`premiere_periode: 2026`) : les échéances IPP commencent avec les
  revenus 2026 (16/10/2027) ; celles des revenus 2025, déjà passées, ne sont pas créées.

## D-103 — Test des demandes de documents : 8 retours de Jeremy

- **Carte envoyée par le lien : 30 à 45 s d'attente** → la lecture de la carte se fait après
  la réponse, au passage des travaux automatiques (toutes les 5 minutes) : le client a sa
  page « merci » tout de suite. Le cabinet voit la carte lue quelques minutes plus tard.
- **Document long illisible sans téléchargement** → le visualiseur défile jusqu'à la dernière
  page (page du document : toute la page défile).
- **Doublons dans l'onglet Documents aussi** : un fichier identique ajouté dans une case ou un
  dossier est retenu et comparé (D-099) ; « Confirmer l'import » le range là où il avait été
  déposé. Les photos recto/verso réunies en PDF par le lien gardent leur empreinte : les
  redéposer est reconnu comme doublon.
- **Déclaration UBO signée** : les réponses (lieu de naissance, PPE) et la signature sont
  reportées dans la déclaration elle-même, plus seulement sur le certificat. Seulement si le
  document, refait sans signature, est mot pour mot celui que le client a lu ; sinon il reste
  tel quel. Le document lu reste aux archives avec son empreinte ; le certificat explique
  l'ajout. Valeur juridique : signature électronique simple (eIDAS ; livre 8 du Code civil,
  art. 8.1 et 8.18), recevable, appréciée par le juge ; la loi anti-blanchiment n'impose pas de
  forme pour cette déclaration. À faire confirmer par l'AMLCO / l'expert-comptable.
- **Fiche de risque : signature de l'AMLCO** possible à tout niveau (obligatoire seulement
  pour un risque élevé) : bouton « Signer (AMLCO) » pour qui a la capacité AMLCO.
- **Identifications** : modèles ITAA 3.1 à 3.4 internes au cabinet (signés par le cabinet, pas
  par le client). L'identification d'un mandataire exige maintenant la fiche de risque, comme
  celle du client, et les deux sont signalées « à mettre à jour » quand le niveau de risque
  change (ou si elles ont été faites avant la fiche).
- **UBO « à confirmer »** : après l'extrait du registre, un bouton « Oui, le registre montre
  ces personnes : confirmer » note les bénéficiaires calculés comme déclarés (journalisé).
- **Conformité › envoyer** : n'envoie que ce qui peut partir tout de suite (cartes, et documents
  déjà préparés en attente de signature, D-051) ; un document jamais préparé ne part pas
  d'office.

## D-104 — Calendrier fiscal : flèches mois par mois ; report IPP au 16 novembre

- **Flèches ‹ ›** sur le calendrier de l'Accueil : mois précédent / suivant sans recharger la
  page (et « Aujourd'hui » pour revenir) ; sans JavaScript, l'Accueil s'ouvre au mois demandé
  (`?mois=2026-11`). Le mois affiché montre mes échéances de ce mois et les dates légales.
- **Report du SPF (29/10/2026, cyberattaque)** : les déclarations attendues vers le 31/10
  passent au **16/11/2026**, dont l'IPP avec revenus spécifiques (revenus 2025) — date mise à
  jour dans `regles.yaml` — et l'ISOC des exercices clôturés le 31/03/2026 — à encoder par un
  administrateur sur « Délais SPF » (l'article de l'ITAA est repéré par la veille quotidienne).

## D-105 — Fiche client allégée : Archives en classeur, Factures du cabinet

Jeremy : « le but c'est pas de copier-coller FID-Manager ».
- **Une seule entrée « Archives »** (au lieu de Légal, Moniteur, Comptes annuels, ISOC, IPP, TVA,
  Administratif, Courriels) : un **classeur** — les années (la plus récente ouverte), puis les
  sujets en lignes qui s'ouvrent et se ferment (maquette C2 choisie). Résumé de chaque sujet :
  pour la TVA les 12 mois ou 4 trimestres (en vert : déposés), sinon le dernier document.
  « Tout ouvrir / Tout fermer » ; l'outil se souvient de ce qui était ouvert (navigateur). Les
  anciennes adresses mènent au bon sujet. Le Moniteur belge et les comptes déposés à la BNB
  (données des sites officiels) restent à un clic, en bas du classeur.
- **Suivi retiré du panneau** : Échéances (badge « en retard » de l'en-tête, lien en bas de la
  fiche) et Historique (lien en bas de la fiche) restent à un clic.
- **Facturation** : « Honoraires » retiré (rien n'y était construit) ; « Temps passé » devient
  « Heures prestées » ; **Factures** : les factures et notes de crédit **émises par le cabinet**,
  déposées dans « Déposer des documents », sont reconnues (le mot facture + le nom ou le numéro
  du cabinet) et rangées chez le client (numéro d'entreprise du client, sinon son nom, s'il est
  seul à correspondre). Les montants ne sont pas lus.
- **Nom du cabinet** dans Paramètres › Réglages du cabinet (« Identité du cabinet ») : en tête
  des documents, dans les e-mails, et pour reconnaître les factures. Sans nom ni numéro encodés,
  aucune facture n'est reconnue (jamais le nom par défaut « Cabinet »).
- Les pages cachées existent toujours (`Section.hidden`) : rien n'est perdu.

## D-106 — Mandataires et actionnaires encodés depuis Documents

Jeremy : « il y a déjà ça dans Documents ». Le groupe « Organisation » quitte le panneau de
gauche : on encode les dirigeants depuis Documents › Identification des mandataires (et Cartes
d'identité) — bouton « Ajouter / modifier les mandataires » — et les actionnaires depuis
Documents › UBO — bouton « Encoder les actionnaires ». Les deux pages existent toujours (fil
d'Ariane « Documents › … ») ; les noms de l'en-tête restent cliquables. Panneau : Fiche,
Archives, Facturation.

## D-107 — Heures prestées : vue de l'administrateur

Jeremy : « les employés n'ont pas besoin de savoir combien leurs collègues passent de temps sur
un dossier ». La page « Heures prestées » du dossier (et son entrée à gauche) est réservée au
droit « Voir les heures de tous » (`timesheet.all`) ; chacun encode toujours ses heures dans
« Ma journée ». Les idées du futur module Administrateur sont rassemblées dans
`docs/ADMINISTRATEUR.md`.

## D-108 — Police Inter, texte plus lisible

Jeremy : « c'est un peu fin pour les yeux… change juste la police, rend le truc plus lisible »
(sans toucher à la disposition). Manrope (D-057) est remplacée par **Inter**,
hébergée par l'outil (licence OFL, aucun appel extérieur) ; texte de base 16 px au lieu de 15,
graisse 450 au lieu de 400, gris des libellés plus foncé (#46435f), numéros (BCE, TVA,
montants) dans la même police que le texte, chiffres alignés. Rien d'autre ne bouge.

## D-109 — « Mes déclarations TVA » : un cadre par dossier, vert quand tout est fait

Jeremy (maquette B choisie le 30/10) : pendant le mois TVA, « Ouvrir mes échéances » de
l'Accueil ouvre `echeances/tva/` (`tasks:vat_board`, pas d'entrée de menu : on n'y arrive que
par ce bouton). Un cadre par dossier de MES dossiers (ceux de l'Accueil, `accueil.my_clients`),
rangé en « À commencer / En cours / Terminées », avec filtres. Les cases sont celles de la ligne
de l'onglet « Déclaration TVA » (même gabarit `vat/_cell.html`, même vue `vat_cell` : cocher
ici coche là-bas, journalisé). Le cadre devient vert quand toute la ligne est faite ; la ligne
de l'onglet aussi (vert plus marqué). « + Temps » ajoute une entrée à Ma journée (activité TVA,
dossier prérempli, à la suite de ma dernière entrée du jour) et affiche MON temps TVA sur le
dossier depuis le début de la période — jamais celui des collègues (D-107). Les autres
périodes (comptes annuels…) gardent l'échéancier en attendant leur onglet.

## D-110 — Onglet « Déclaration TVA » : Acomptes avant Solde, colonne « Mon temps »

Jeremy (30/10) : la grille dépassait de son cadre, les colonnes Acomptes et Solde devaient être
échangées, et il manquait l'ajout de temps sur la ligne. Ordre : Période, Doc. reçus, Fini,
Déposée, IC, Acomptes, Solde, Com. client, Resp., Assis., **Mon temps**, Remarque. Les titres et
la période passent à la ligne pour que la grille tienne dans la page (défilement horizontal
sous 1200 px). « + Temps » (même bouton que « Mes déclarations TVA ») crée une entrée de Ma
journée rattachée à la déclaration (`TimeEntry.vat_filing`, activité TVA) ; la colonne montre
MON temps sur cette déclaration, jamais celui des collègues (D-107). Il suffit de voir le
dossier (c'est mon temps, pas une modification de la fiche) ; chevauchement refusé avec la
raison.

## D-111 — Onglet « Clôture » : une ligne par exercice, checklist comptable, clôture comptable

Jeremy (30/10, maquettes « Checklist de clôture ») : l'onglet Clôture remplace la page à
construire. Une ligne par exercice (créée toute seule pour le dernier exercice terminé, d'après
la date de clôture de la fiche), dans son propre cadre : Checklist · Clôture comptable · Resp. · Assis. · Mon temps ·
Remarque (colonne « Fiscal » retirée le 30/10 : la déclaration ISOC aura sa propre case). La ligne devient verte quand
la checklist est complète ET la clôture comptable cochée ; cocher la clôture avec une checklist
incomplète demande confirmation.

- **Checklists communes** (Paramètres › Checklists de clôture, administrateurs) : « Dossiers
  soumis à TVA » (assujetti ou mixte, 16 champs) et « non soumis » (11 champs), listes données
  par Jeremy le 30/10 ; aides proposées par Claude, modifiables. Elles s'appliquent à **tous**
  les dossiers (un champ ajouté arrive partout).
- **Personnalisation par dossier** (Checklist › « Configurer ce dossier ») : renommer, retirer,
  remettre, ajouter, réordonner — gardé pour les années suivantes, même quand la checklist
  commune change (`DossierChange`, `DossierItem`, `DossierSetup.order`).
- **La checklist** s'ouvre dans le cadre du visualiseur : un clic coche (initiales, date),
  « pas concerné », « + Commentaire » lié à une ligne. Tant qu'un commentaire est ouvert, la
  ligne est orange et ne peut pas être cochée ; « Réglé » ferme le commentaire et coche la
  ligne. Remarque générale, onglet Historique, Imprimer.
- **« + Temps »** : entrée de Ma journée rattachée à l'exercice (`TimeEntry.closing_year`,
  activité « Clôture et comptes annuels ») ; on ne voit que SON temps (D-107).
- Modifications journalisées (rubrique « cloture ») ; clôture comptable = événement
  `closing.accounting_closed` / `closing.accounting_reopened`. Commentaires jamais dans un
  journal ni un e-mail.

## D-112 — Checklist gestionnaire et clôture gestionnaire

Jeremy (30/10, maquette « ClotureGestionnaire » validée) : après la clôture comptable, le
gestionnaire (l'expert) a sa propre checklist, qui reste comptable (le fiscal — DNA, etc. —
ira dans une case « Déclaration ISOC » plus tard). Ligne de l'exercice : Checklist comptable ·
Clôture comptable · Checklist gestionnaire · Clôture gestionnaire · Resp. · Assis. · Mon temps
· Remarque. La ligne devient verte quand les deux checklists sont complètes et les deux
clôtures cochées.

- Checklist gestionnaire commune (Paramètres › Checklists de clôture), la même pour tous les
  dossiers, TVA ou non : Vérification générale, Compte courant, ATN, Intérêts fictifs, Dette
  fiscale estimée, Affectation du résultat N-1, Provisions (liste de Jeremy ; aides proposées).
- Même fonctionnement que la checklist comptable (cadre du visualiseur, commentaires liés à
  une ligne, « Configurer ce dossier », historique, remarque générale propre).
- « Clôture gestionnaire » : n'importe qui ayant le droit de modifier les fiches peut la cocher
  (à restreindre au responsable si Jeremy le demande) ; événements
  `closing.manager_closed` / `closing.manager_reopened`.

## D-113 — Cases de dépôt de l'exercice ; un exercice = un cadre, cases de même taille

Jeremy (30/10, maquette « ClotureDepots ») : dans l'onglet Clôture, chaque exercice a aussi ses
dépôts : AG, BNB, ISOC, Fiches 281.50 (celles que le client établit pour les honoraires et
commissions payés) et Annexes 270 (on y dépose toutes les annexes 270 : 270 MLH…). « Veille à ce
que ce soit harmonieux » : un exercice devient un cadre, avec deux lignes de cases toutes de la
même taille (« Clôture » : checklists et clôtures ; « Dépôts ») ; le nombre de fichiers est
écrit dans la case au lieu d'étiquettes qui changeraient sa taille.

- Une case = une échéance = des fichiers : cocher AG / BNB / ISOC termine l'échéance de
  l'exercice (`assemblee_generale`, `comptes_annuels`, `isoc`) et décocher la rouvre ; terminer
  l'échéance dans l'échéancier coche la case (`task.completed`).
- Un fichier déposé dans la case est rangé aux archives (AG : légal ; BNB : comptes ; ISOC,
  281.50, 270 : isoc) et coche la case. Les comptes annuels XBRL et le Biztax XBRL déposés dans
  « Déposer des documents » cochent tout seuls BNB / ISOC du bon exercice.
- Une case peut être retirée pour un dossier (ex. pas de 281.50), et remise.
- Le cadre devient vert quand les checklists, les clôtures et les dépôts sont faits.
- Pas encore : les PDF (accusé Biztax, Belcotax, comptes PDF) ne cochent pas la case tout seuls
  (période pas toujours lisible) ; on les dépose dans la case.

## D-114 — Lecture des documents de clôture et classement dans les cases de dépôt

- « Déposer des documents » reconnaît aussi : procès-verbal d'AG, accusé Belcotax 281.50,
  annexe 270 ; en plus des comptes annuels (PDF/XBRL) et de Biztax (PDF/XBRL) déjà connus.
- Un document reconnu est rangé dans son dossier d'Archives, puis joint à la bonne case de
  dépôt de l'exercice et la case est cochée (l'échéance liée aussi).
- Prudence : seulement des mots clairs, sinon « À classer ». Pas d'année lisible ou pas
  d'exercice correspondant → rangé, mais aucune case cochée. Une case retirée du dossier
  n'est jamais cochée.
- Année : exercice d'imposition − 1 pour Biztax et annexe 270 ; année de l'AG / des revenus
  pour PV et 281.50. Règles écrites sans exemple réel : à ajuster sur des modèles anonymisés.

## D-115 — Dépôts : chaque dossier ne voit que ses cases

- Ajoutés à la ligne « Dépôts » de l'onglet Clôture : Précompte mobilier, Fiches 281 (une
  seule case pour 281.20 dirigeants et 281.50 honoraires), Listing clients. Maquette « 2 »
  choisie par Jeremy le 30/10/2026.
- Listing clients : seulement pour un dossier soumis à TVA (assujetti, mixte, franchise) ;
  relié à l'échéance « Listing annuel des clients » de l'année civile où l'exercice se termine.
- Précompte mobilier : la case AG demande « Dividende décidé ? Oui / Non » ; « Oui » fait
  apparaître la case, date limite = date de l'AG + 15 jours (déclaration 273 S et paiement).
- Fiches 281 : orange « 1 / 2 » tant qu'une des deux manque, verte quand les deux sont faites ;
  chaque morceau se retire pour le dossier (pas de dirigeant rémunéré → 281.50 seule).
- Lecture des documents : accusé Belcotax 281.20 et accusé du listing clients cochent aussi
  leur case. Le précompte mobilier se coche à la main (année du dividende trop incertaine).
- Pas dans l'onglet Clôture : registre UBO (Documents), versements anticipés (leur onglet).

## D-116 — Case « UBO » dans les dépôts de la clôture

- Demande de Jeremy (30/10/2026) : la confirmation annuelle du registre UBO a sa place dans
  la clôture. Nouvelle case « UBO » au bout de la ligne Dépôts, pour toutes les sociétés et
  associations ; fichiers rangés dans Archives › Administratif ; retirable par dossier.
- La case « Déclaration UBO » de l'onglet Documents reste (le document signé) tant que
  Jeremy n'a pas décidé de la retirer.
- Toutes les cases restent sur une seule ligne (8 dépôts) ; libellés un peu plus petits.

## D-117 — Plus de doublon UBO : tout passe par la case « UBO » de la Clôture

- Choix de Jeremy (30/10/2026) : la page « UBO » (bénéficiaires calculés, extrait du
  registre, alerte annuelle) et la case « Déclaration des bénéficiaires effectifs » ne sont
  plus montrées dans l'onglet Documents. Elles s'ouvrent depuis la fenêtre de la case
  « UBO » de l'onglet Clôture (la page UBO s'affiche sous l'onglet Clôture).
- Rien n'est effacé : ce sont toujours des cases où les documents se rangent (dépôt, signature,
  « Déposer des documents »), et elles comptent toujours dans le dossier anti-blanchiment.
- Un extrait du registre UBO rangé coche la case « UBO » du dernier exercice terminé.
- Le mandat SPF « Registre UBO » (accès du cabinet au registre) reste dans Documents › Mandats.

## D-118 — Clôture IPP (personnes physiques)

- Validé par Jeremy le 30/10/2026 (maquette « Clôture IPP par profil »). Une personne
  physique clôture toujours au 31/12 : la ligne de l'année se crée seule, plus de message
  « date de clôture non renseignée ».
- Profil, déduit de la fiche et corrigible dans l'onglet Clôture : indépendant (numéro
  d'entreprise), dirigeant (gérant ou administrateur d'une société cliente), sinon particulier.
- Ligne « Déclaration IPP » pour tous : Pièces reçues (orange tant que des demandes de
  documents attendent), Calcul validé, Déposée (accusé Tax-on-web → cochée, reliée à
  l'échéance IPP), Avertissement-extrait (joint à son arrivée, reste « à vérifier »).
- Indépendant : en plus, checklists IPP (avec TVA : 10 points ; sans TVA : 8, sans clients
  ouverts ni comptes TVA ; gestionnaire IPP : 6 points de départ) et dépôts Fiches 281.50,
  Listing clients (si TVA). Particulier et dirigeant : pas de checklist ni de clôture.
- Dirigeant : la case Pièces montre la fiche 281.20 faite dans la case « Fiches 281 » de sa
  société (même année), pour ne pas la redemander.
- Toutes les cases gardent la même largeur (8 colonnes) d'un dossier à l'autre.

## D-119 — Mode sombre

- Demande de Jeremy (30/10/2026). Paramètres › Affichage : Clair, Sombre ou « Comme
  l'ordinateur » ; choix propre à chaque personne (champ `User.theme`). « Paramètres » est
  donc visible par tous ; les outils d'administration restent réservés.
- `static/css/dark.css` est fabriqué par `python manage.py dark_css` depuis app.css (fonds
  clairs → foncés, textes foncés → clairs, palette sombre pour les variables). Un test vérifie
  qu'il est à jour : relancer la commande après toute modification de app.css.

## D-120 — PV d'assemblée générale préparé depuis la case AG

- Validé par Jeremy le 30/10/2026 (maquettes « PV d'AG »). Le texte est toujours celui d'un
  modèle Word du cabinet (Paramètres › Modèles de PV d'AG) : autant de modèles qu'on veut,
  chacun pour certaines formes (SRL, SA, ASBL… ; rien coché = toutes), plusieurs actifs.
- Même moteur que la lettre de mission (D-069) : trous repérés (« [DATE] », « [MONTANT] »,
  XXX, texte surligné), contenu deviné d'après le mot entre crochets et le texte autour
  (société, adresse, localité, numéro, président, associés, date et heures de l'AG, année,
  date de clôture, cabinet ; montants « à demander » avec une question proposée), réglé une
  fois par un administrateur. Passages à options en plus : « si dividende », « sans dividende ».
- Case AG › « Préparer le PV » : une page — date (proposée : 6 mois après la clôture),
  heures, dividende oui/non, les montants du modèle, résolution libre si le modèle a un trou
  pour cela ; « Déjà rempli » montre ce qui vient de la fiche. Brouillon PDF à relire, puis
  envoi au client pour signature en ligne (comme la lettre). Case AG orange « à signer ».
- Signé : rangé (Archives › Légal), case AG cochée ; « dividende : oui » fait apparaître la
  case Précompte. Le brouillon n'apparaît pas dans les Archives. Aucune IA (voir D-121).

## D-121 — IA : fournie par l'éditeur, en Europe, en appui du code

- Choix de Jeremy (30/10/2026) : l'IA est intégrée au logiciel « clé en main » ; les cabinets
  n'ont rien à brancher. Le code fait le travail ; l'IA propose quand les règles bloquent
  (documents non reconnus, réglage des modèles Word de lettre de mission et de PV d'AG ;
  plus tard les e-mails). L'humain valide toujours.
- Fournisseur retenu : Claude via Amazon Bedrock, région européenne (Francfort), compte de
  la société de Jeremy ; Amazon ne garde ni n'utilise les questions et réponses. Une clé
  d'accès par cabinet, au droit minimal, posée par le script d'installation (jamais dans le
  dépôt ni la conversation). Données minimisées (numéros remplacés par des repères, jamais
  le numéro national), journal de chaque appel sans le contenu, plafond mensuel.
- État : compte AWS en cours de création par Jeremy ; module « Assistant IA » à construire
  (éteint tant qu'il n'y a pas de clé). Avant la commercialisation (D-067) : contrat de
  sous-traitance éditeur–cabinet et mentions RGPD.

## D-122 — Onglet « Versements anticipés » retiré

- Choix de Jeremy (30/10/2026) : l'outil n'est pas un logiciel para-comptable et ne calcule pas
  les versements anticipés (ambition pour plus tard). Sans calcul, l'onglet doublait MyMinfin :
  il est retiré des onglets du haut. Les dates restent dans les échéances et sur l'Accueil.

## D-123 — Assistant IA : Mistral, et ses deux premiers usages

- Fournisseur : Mistral (Jeremy, 31/10/2026), offre payante à l'usage (jamais l'offre
  gratuite, qui peut entraîner sur les requêtes), compte de l'éditeur (pas du cabinet),
  limite de dépense, refus de l'entraînement, zéro conservation demandé. Remplace Amazon dans
  D-121 (inscription bloquée). Clé `MISTRAL_API_KEY` demandée par le script d'installation,
  rangée dans Secret Manager ; jamais dans le dépôt ni la conversation.
- Module `apps/ai` : éteint sans clé ; journal `AiCall` (fonction, dossier, jetons, coût,
  erreur — jamais le contenu) ; plafond mensuel (`AI_MONTHLY_CAP_EUR`, 30 € par défaut) ;
  identifiants masqués avant l'envoi (`privacy.mask`) ; en panne → l'outil continue sans.
- Usage 1 — réglage des modèles Word (lettre de mission, PV d'AG) : « Proposer avec
  l'assistant IA » propose le contenu des trous et les passages à options ; marqué « proposé
  par l'assistant », le modèle est désactivé jusqu'à vérification. Pas de donnée de client.
- Usage 2 — « À classer » : « Demander à l'assistant » lit le document et propose titre et
  endroit ; le dossier est retrouvé par l'outil (numéros imprimés, sinon nom proposé, parmi
  les dossiers visibles) ; « Ranger ainsi » d'un clic. Seulement si le cabinet a coché, dans
  Réglages du cabinet, que Mistral a confirmé le zéro conservation.
- 31/10/2026 : zéro conservation accordé par Mistral pour l'organisation ; l'outil appelle le
  point d'accès européen `api.eu.mistral.ai` (inférence dans l'UE), uniquement l'API sans
  mémoire `/v1/chat/completions` (couverte par le zéro conservation) — ni agents, ni batch,
  ni modèles « Labs ».

## D-124 — Un modèle à partir d'un document déjà rempli

- Demande de Jeremy (31/10/2026) : déposer une lettre de mission ou un PV d'AG réel, fait pour
  un client, et en tirer un modèle pour les autres. Paramètres › Modèles (lettre ou PV d'AG) ›
  « Partir d'un document déjà rempli » : le document + le client pour qui il a été fait.
- L'outil remplace par des repères ce qu'il connaît de la fiche (nom, numéro d'entreprise,
  adresse, code postal et ville, gérants et administrateurs, associés, dates de clôture, nom du
  cabinet) et ce qui se reconnaît à sa forme (dates, heures, montants, e-mails, IBAN) ; noms en
  mots entiers ; mise en forme gardée. Puis, si l'assistant IA peut lire les documents des
  clients (D-123), il signale ce qui reste (valeurs exactes, repères permis seulement).
- Sécurité : le document rempli n'est jamais enregistré ; le rapport ne garde que des sortes et
  des nombres (« montant (2) »), jamais une valeur. Le modèle n'est pas actif : bandeau
  « relisez-le », téléchargement du Word pour vérifier, puis activation par l'administrateur.
- 31/10/2026 (Jeremy) : plus de client à choisir ni de « vide / rempli » à cocher. Tout
  modèle déposé passe par la même conversion : le client est retrouvé tout seul par le numéro
  d'entreprise imprimé (parmi les dossiers visibles) pour remplacer aussi ses gérants,
  associés et adresse ; sinon la forme suffit (société + forme juridique, numéro, code postal
  + ville, dates, heures, montants, e-mails, IBAN), « arrêtés au » → date de clôture ;
  l'assistant IA trouve le reste (noms de personnes…).

## D-125 — Modèle depuis un document rempli : détection renforcée, mise en page gardée

- Constat (essai de Jeremy) : noms et adresses restaient dans le modèle, libellés des questions
  incompréhensibles, PDF qui perdait la mise en page (tableaux, polices).
- Détection sans connaître le client : en-tête « nom » + ligne de forme seule (« S.R.L. »),
  rue avec « boîte », localité avec tiret, « Fait à … », « Monsieur / Mr … » et ses parts,
  année en lettres, date « 23 septembre », heures, montants. Les espaces réservés (« XXX »)
  ne sont pas touchés.
- Libellé d'un montant demandé : le texte de sa ligne de tableau (« ATN Auto »), sinon les
  derniers mots utiles avant le trou. Montants affichés au format belge (100.000,00).
- PDF : LibreOffice sans interface dans l'image (fidèle au Word, polices équivalentes à
  Calibri/Arial/Times), avec repli sur l'ancienne conversion s'il échoue.
- Sécurité : un modèle venu d'un document rempli ne s'active qu'après la case « J'ai relu ce
  modèle » (rien d'un autre client ne doit rester).
- Complément (essai complet avant mise à jour) : les noms sans « Monsieur » sont reconnus par
  leur contexte (« présidence de … », « donnée à … », « …, gérant ») puis remplacés partout ;
  la liste des associés (« 1. Nom — 120 parts ; … », ou une ligne par associé) devient la
  liste de la fiche du client ; « R.P.M. Liège, division … » devient une question (tribunal) ;
  la ligne « S.R.L. » sous le nom disparaît (la forme est dans le nom). Nouveau champ « Tous
  les dirigeants » (« Paul X et Marie Y »).
- Typographie : le modèle Word garde la police, la taille, le gras et la couleur du document
  déposé (seul le texte remplacé change). Pour le PDF, le serveur n'a pas les polices
  Microsoft : il prend un sosie libre (Calibri → Carlito, Arial → Liberation Sans, Garamond →
  EB Garamond, Century Gothic → URW Gothic, Aptos → Open Sans…, `deploy/fonts`).
- Pour que rien ne change par rapport aux PV habituels : (1) le PV préparé se télécharge aussi
  en Word (« PV en Word », refait depuis les réponses gardées : typographie exacte) ; (2) une
  police incorporée dans le Word (Word › Options › Enregistrement) est reprise telle quelle par
  le PDF (testé : police absente du serveur, PDF identique) ; (3) la page du modèle signale
  les polices ni présentes ni incorporées, et comment les incorporer.

## D-126 — PV d'AG : contrôle des montants et « quelque chose de particulier »

- Contrôle des montants (avertissement, pas un blocage) : dans chaque tableau de montants du
  modèle, la dernière ligne est le total des autres (« (-) » dans la ligne = à retrancher) ;
  le bénéfice « reporté en intégralité » doit égaler le bénéfice net. Si ça ne colle pas, le
  PV n'est pas préparé : le comptable corrige, ou coche « Les montants sont justes ».
- « Quelque chose de particulier ? » toujours proposé : le texte devient une résolution de
  plus (« Résolution 7 : »), dans la mise en forme des précédentes, avant « Toutes ces
  résolutions… » / la levée de séance ; dans le PDF et dans le Word. Aucune IA.
- Modèle depuis un document rempli : seul le nom du client (en-tête) devient [SOCIÉTÉ] ; une
  autre société citée (le cabinet « Fiduciaire X & Y SRL ») reste telle quelle.
- Modèles d'autres cabinets (repères propres « [LIEU DE REUNION] », « XXX ») : l'outil ne
  touche jamais à l'intérieur d'un repère existant ; la question reprend les mots du repère
  (« Montant du capital social ») ; un « XXX » de PV est toujours demandé (jamais deviné) ;
  le même repère à deux endroits = une seule question (deux trous au même libellé reçoivent
  la même réponse).
- L'assistant IA règle tout seul, au dépôt, les trous « à demander » (champ de la fiche s'il
  y en a un, question claire) ; c'est une proposition, relue avant activation. Réglages du
  cabinet : bouton « Tester l'assistant » et compteur du mois (appels, coût, dernier appel).
- PV : un mot tapé là où un montant est attendu est refusé ; lien « Modifier les champs du
  modèle » en haut de la page du PV (administrateurs).

## D-127 — L'assistant IA travaille en coulisse

- Demande de Jeremy : aucune case, aucun bouton « IA ». L'assistant agit tout seul, on ne
  voit que le résultat.
- Modèles (lettre de mission, PV d'AG) : au dépôt, les règles de l'outil puis l'assistant
  identifient les champs ; la page du modèle montre en clair « Rempli tout seul (fiche du
  client) » et « Demandé à chaque PV », puis un bouton « C'est bon, activer » (« J'ai relu,
  activer » pour un document rempli). Le détail champ par champ est replié (« Corriger un
  champ »). Plus de bouton « Proposer avec l'assistant », plus de mention de l'assistant.
- « À classer » : un fichier non reconnu est lu par l'assistant dès le dépôt ; la
  proposition s'affiche avec « Ranger ainsi ». Rien n'est rangé sans clic (l'humain décide).
- Réglages : plus de section « Assistant IA ». La lecture des documents des clients est
  active d'office (Mistral a confirmé le « zéro conservation » le 31/10/2026, compte de
  l'éditeur) ; le réglage reste en base (coupure possible par l'éditeur), chaque appel reste
  tracé (AiCall, sans contenu). Sans réponse de l'assistant, l'outil continue avec ses règles.
- Typographie : l'outil ne réécrit pas le document, il remplace le texte des champs dans le
  Word du cabinet ; police, taille, gras, couleurs et mise en page restent ceux du modèle.

## D-128 — PV d'AG : l'assistant comprend « Quelque chose de particulier ? »

- La demande du comptable n'est plus recopiée : l'assistant (Mistral Large, rédaction) lit le
  PV rempli, comprend la décision, trouve où elle se place et modifie les paragraphes
  concernés (ex. un dividende remplace « reporter l'intégralité du bénéfice » par la
  répartition), en style de PV, montants au format 50.000,00 €. Il ne touche à rien d'autre,
  n'invente ni montant ni nom, et signale ce qui ne colle pas (« À vérifier dans le PV : … »).
- Les modifications sont gardées avec le PV : le Word et le PDF sont identiques, sans
  nouvel appel. Sans assistant, la demande devient une résolution de plus (D-126).
- Chaque modification reprend la mise en forme du paragraphe qu'elle touche.
- Au dépôt d'un modèle de PV, les passages « reporter l'intégralité » (sans dividende) et
  « distribuer un dividende » (avec) sont repérés tout seuls ; avec un dividende, la
  question « reporter l'intégralité » n'est plus obligatoire.
- Page du PV : changer de modèle recharge ses questions ; les réponses gardées ne valent que
  pour le modèle qui les a reçues.
- Pourquoi pas un « entraînement » de l'IA chez Mistral : les consignes sont dans le code
  (versionnées, les mêmes pour tous les cabinets) ; un entraînement demanderait d'envoyer de
  vrais PV. Les règles du métier se donnent à Claude, qui les ajoute aux consignes.

## D-129 — Dividende écrit par l'outil ; état de l'assistant visible

- Constat (essai de Jeremy) : dividende « Oui » sur un modèle qui n'a que « reporter
  l'intégralité du bénéfice » → la Résolution 3 restait vide, et la demande libre était
  ajoutée en Résolution 7.
- Désormais, sans passage « dividende » dans le modèle, la page du PV demande le dividende
  brut ; l'outil remplace la phrase de report, à sa place et dans sa mise en forme, par :
  « L'assemblée décide de distribuer un dividende brut de X € et de reporter le solde du
  bénéfice de l'exercice, soit Y € » (Y = bénéfice à affecter − X ; tout distribué : phrase
  dédiée). Dividende > bénéfice à affecter : signalé. Sans IA, sans erreur possible.
- Mistral montrait 0 requête : l'assistant n'a jamais répondu en production. Réglages du
  cabinet : une ligne d'état (pas un réglage) dit s'il est actif, pas branché (clé absente)
  ou en panne, avec la cause sans contenu (« clé refusée (401) », « connexion impossible »…).
- Page d'un modèle : « Passages gardés selon le cas » replié (réglé tout seul).
- Premier essai avec l'IA réellement branchée (clé corrigée) : l'assistant proposait des
  passages « à cocher » (dizaines de « Inclure ce passage ? ») et donnait le même intitulé à
  plusieurs lignes (« Autre composante de rémunération »), fusionnées en une question. Désormais :
  pas de condition « à cocher » venant de l'assistant ni de remplacement d'un réglage déjà
  fait ; un intitulé tiré du document (repère, ligne de tableau) n'est pas réécrit ;
  intitulés distincts, courts, sans « ? » ; une seule question pour deux trous seulement quand
  c'est le même repère (lien explicite « same »), jamais parce que deux intitulés se
  ressemblent.
