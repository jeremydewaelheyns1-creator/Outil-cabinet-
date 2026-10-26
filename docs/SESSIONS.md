# Journal des sessions

## Session — 25 octobre 2026 : Ma journée, feuille de temps, Ma boîte mail

**Fait** (D-056 à D-061)
- Nouveau look « moderne doux » sur tout l'outil ; barre « Dossier anti-blanchiment NN % ».
- Feuille de temps reliée aux dossiers ; « Ma journée » (À traiter / Mon agenda) remplace
  l'accueil.
- **Ma boîte mail** (V1 validée sur maquette) : lecture de la boîte de chaque employé (sur
  activation), réception avec dossier proposé, « Traité : classer », arborescence société ›
  personne physique › pièces jointes, clic droit (échéance, reclasser, timesheet, privé),
  pièces reconnues et rangées dans le vrai dossier, réponse écrite par l'employé, « en
  attente de réponse », recherche surlignée. Aucune IA.
- Échéances avec heure et rappel le jour J dans Mon agenda.

**À faire par Jeremy / le cabinet**
- Ajouter `Mail.Read` (déléguée) dans Entra et accorder le consentement (docs/OUTLOOK.md).
- AIPD + note d'information aux employés avant d'activer la lecture sur de vraies boîtes.

**Idées gardées pour plus tard (pas commencées)** : fil du dossier (frise + échéances
faites, sans documents), tableau de bord du cabinet, espace client (mis de côté : trop
ambitieux pour l'instant), adresse « support » pour les demandes automatiques,
**module Administrateur** (onglet réservé, vue générale de ce qui se passe ; Conformité et
le journal des consultations pourraient y aller — à décider avec Jeremy).

**26/10/2026 — Cap sur la commercialisation (D-067)** : annoncé par Jeremy. Questions à
trancher listées dans D-067 (modèle d'installation, audit, RGPD, support). Rien de construit.

**Ma boîte mail — mise en forme et envoi programmé (D-066)** : fait le 26 octobre au soir.
Reste des idées boîte mail : rien (la vue « Envoyés » existait déjà).

**Recette de nuit du 25 au 26 octobre (D-065)** — faite seule, à la demande de Jeremy
(« teste tout, améliore »). Corrigé : heures vides (erreur 500), lenteur à 1 500 dossiers
(Conformité / Ma journée), téléphone (menus, tableaux, recherche boîte mail), visualiseur
ouvert seul, « 1er », libellés accessibles, portefeuille par défaut, politique de sécurité du
contenu, icône. Propositions NON faites (à décider par Jeremy) :
- base de données : `db-f1-micro` (partagée, 0,6 Go) suffit pour la démo ; pour ~1 000
  dossiers réels, passer au moins à `db-g1-small` (coût mensuel plus élevé) ;
- échéancier : quelqu'un sans le droit « modifier les fiches » peut quand même cocher une
  échéance « terminée » (voulu ? sinon réserver au droit clients.edit) ;
- rôles accordés au féminin (« gérante ») : il faudrait connaître le sexe (lu sur la carte
  d'identité) ;
- « Tous les clients » : filtre « hybrides libres » pour parcourir les dossiers à prendre
  au-delà des 15 de l'Accueil ;
- l'adresse de la page « Liaison Outlook » est /ma-boite-mail/ (historique, liée au retour
  Microsoft enregistré dans Azure) : ne pas la renommer sans mettre Azure à jour.

**Reprise FID — dossiers complets (D-064)** : personne de contact, « Hybride » dans la
colonne Comptable, feuille « Relations ». Fichier de test de 30 dossiers fictifs envoyé à
Jeremy (script : à refaire depuis D-064 si besoin). Les tâches IPP n'apparaissent pas tant
que la date limite IPP de l'année n'est pas indiquée dans config/taches/regles.yaml (voir
l'idée « dates du SPF »). À faire plus tard : connaître la vraie structure de l'export FID
(intitulés exacts) pour compléter clients.yaml.

**Accueil — CONSTRUIT (D-063)**, d'après la maquette validée :
- Personnel : chacun voit SA période et SES dossiers, jamais de nom de collègue. « Ses
  dossiers » = ceux où il est affecté (expert-comptable ou comptable, `Assignment`) : deux
  personnes n'ont donc pas le même Accueil.
- Période calme : la 1re maquette ne plaisait pas ; 3 propositions à choisir (prendre de
  l'avance / mettre mes dossiers en ordre / mes 30 prochains jours).
- L'écran suit la saison : au centre, la grande échéance la plus proche (en octobre : LE mois
  TVA, mensuels et trimestriels) ; les autres dans « Aussi en cours » ; bascule 10 jours avant.
  Maquettes : mois TVA, listing clients (mars), saison IPP, comptes annuels BNB, période calme.
- Campagne : barre « mes déclarations déposées X / Y » + liste de mes dossiers restants (état).
- Calendrier fiscal du mois ; état des sites de l'administration (Intervat, MyMinfin, Biztax,
  dépôt BNB) — à tester (vérifier que l'info publique est exploitable).
- Dates IPP/ISOC : à vérifier chaque année auprès du SPF.
- Barre de recherche du haut (existante) : au clic, les 5 derniers dossiers ouverts.

**Module / onglet Administrateur (à construire)** : total du cabinet et détail par personne
des campagnes, Conformité, journal des consultations, tableau de bord. Case « Administrateur »
sur la fiche utilisateur (plusieurs comptes possibles), changement tracé.

**Administrateur › « Gestion des dossiers » (idée validée par Jeremy, 25/10)** :
- Grand tableau de tous les clients (avec l'expert-comptable et le comptable affectés).
- Bouton « Affecter temporairement des dossiers » : tableau avec recherche, on coche les
  dossiers, « Affecter à » une personne, date « jusqu'au » facultative. Sans date : définitif.
  Avec date : à la date, les dossiers reviennent seuls à la personne d'origine. Le remplaçant
  prend le POSTE de la personne remplacée (expert-comptable ou comptable). Tout est tracé.
- Plus tard dans « Gestion » : un vrai module de vision du cabinet et de facturation.
- Rapport personnel du temps passé sur les dossiers.

**Dates officielles du SPF (à construire, demande de Jeremy 25/10)** : l'outil doit aller chercher
chaque année les dates limites publiées par le SPF (IPP, ISOC…) et s'adapter aux délais
supplémentaires accordés. Proposition : l'outil surveille les pages officielles et PROPOSE la
nouvelle date ; un administrateur la valide (lien vers l'annonce gardé) ; les échéances et
l'Accueil suivent. À vérifier : quelles pages publiques sont lisibles de façon fiable.

**Test réel** (plus tard) : essayer l'Accueil avec de vraies échéances du cabinet.

**Gestion hybride des dossiers — CONSTRUITE (D-063)** ; reste : la modification en masse dans
« Gestion des dossiers » (onglet Administrateur) :
- Option à activer (désactivée par défaut) : sans elle, rien ne change.
- Expert-comptable : toujours attitré au dossier.
- Dossiers TVA et dossiers « réguliers » (définis par le patron) : comptable FIXE, comme
  aujourd'hui.
- Les autres (HTVA, dossiers qu'on ne travaille pas tous les mois) : PAS de comptable fixe.
  Un comptable qui a du temps libre en prend un (« Je le prends ») ; tout le monde voit
  « pris en charge par X » pour ne pas travailler à deux sur le même dossier. Exception
  voulue à la règle « pas de nom de collègue » : ici le nom évite le travail en double.
- Accueil en période calme : mes dossiers attitrés à traiter + les dossiers libres qu'on peut
  prendre (avec qui a pris quoi). Maquette à faire.
- Fiche client › équipe : pour le comptable, on choisit une personne OU « Hybride » (idée de
  Jeremy). « Hybride » = dossier sans comptable fixe, pris par qui est libre ; badge visible
  dans l'en-tête du dossier. Le choix « Hybride » n'apparaît que si l'option est activée.
  Modifiable aussi en masse dans Gestion des dossiers.
- Proposé par défaut (Jeremy sans préférence) : liste triée par urgence, chacun choisit ; un dossier pris
  sans avancée pendant X jours revient libre (à confirmer).

**Ma boîte mail — à ajouter** : mise en forme comme une vraie messagerie (gras, souligné,
listes…), envoi programmé (vérifier ce que Microsoft Graph permet), consultation des e-mails
envoyés (le dossier « Envoyés » existe déjà, à enrichir). Attention sécurité : le texte mis en
forme doit être nettoyé (seulement des balises sûres) avant envoi et affichage.

**Onglet TVA (idée)** : e-mail « l'échéance TVA approche » aux clients dont « Doc. reçus » est
vide (texte proposé, envoi au clic ; bouton ou automatique : à décider).

**Écarté** : mur d'annonces, « qui est là », compteurs « 12 cartes reçues », « à nous / on attend
le client », bouton dossier suivant, capture rapide, charge 8 semaines, rendez-vous du jour,
aide-mémoire fiscal, mémo de saison, rythme projeté (gardé seulement ce qui est listé ci-dessus).

**Kit de test** : cahier de recette (page en ligne, réponses lisibles par Claude) + fichiers
fictifs. Jeremy n'a pas encore pu relier Mail.Read (écran d'erreur Microsoft).

## Session — 23 octobre 2026 : paperasse anti-blanchiment (mandat « révolutionne tout »)

**Fait** (D-048 à D-051)
- Signature en ligne par le client (certificat, preuve, copie par e-mail).
- Fiche de risque guidée (pré-remplie, niveau, révision, validation AMLCO, PDF).
- Documents obsolètes repérés + échéances automatiques (fiche de risque, extrait UBO).
- Menu « Conformité » + demande groupée (un e-mail, un lien, une relance par client).

**À valider par Jeremy / l'AMLCO**
- Barème de la fiche de risque, liste des secteurs sensibles et des pays, durées de révision.
- Entrée « Conformité » dans le menu principal (pas un onglet du dossier).
- Signature qualifiée (itsme/eID) : utile ? (prestataire payant).

**Reste proposé, non fait** : mises à jour automatiques, onglets Clôture / Versements
anticipés / Facturation, documents RGPD, modèles du cabinet (lettre de mission, procuration).

## Session — 20 octobre 2026 : TVA, dépôt unique, Outlook, mise en ligne

**Fait** (décisions D-039 à D-044)
- Documents générés (lettre de mission, identifications, déclaration UBO, procuration),
  aperçu signé par le cabinet, « Envoyer au client ».
- Onglet **Déclaration TVA** (grille FID : Doc. reçus, Fini, Déposée, IC, solde 71/72,
  Com. client, acomptes déjà payés, remarques ; 4 états au clic).
- **Déposer des documents** (barre du haut) : XML/PDF Intervat et cartes d'identité classés
  seuls ; sinon « À classer » (visible par le déposant, effacé après 30 jours).
- E-mail TVA au client : personne de contact (civilité), montant, acomptes, reste à payer,
  bénéficiaire/compte/BIC/communication lus sur le PDF de l'administration, PDF joint,
  envoi seulement aux adresses de la fiche.
- **Outlook** : envoi depuis la boîte de chaque employé (Graph, droit d'envoi seul, jeton
  chiffré). Testé par Jeremy avec une adresse Outlook personnelle (« consumers ») : OK.
- **Installation chez Jeremy** : Google Cloud (essai gratuit, europe-west1), projet
  `outil-cabinet-512217`, service `outil` (deux adresses Google acceptées). Données fictives
  seulement. Installateur `deploy/installer.sh`, guides `docs/INSTALLATION.md`,
  `docs/OUTLOOK.md`.

**Choix de Jeremy en attente de réalisation**
- Mises à jour **automatiques** de l'outil en ligne depuis GitHub (sans clé : fédération
  d'identité Google, limitée au dépôt).
- Cartes d'identité demandées au client : **lien sécurisé** de dépôt plutôt que réponse par
  e-mail.

**À faire plus tard**
- Onglets Clôture, Versements anticipés, Facturation (contenu à définir avec Jeremy).
- Documents RGPD avant toute donnée réelle : registre des traitements, analyse d'impact,
  contrat de sous-traitance Google, droits des personnes.
- Outlook du cabinet : inscription par l'administrateur Microsoft 365, accord du cabinet.
- Modèles du cabinet (lettre de mission, procuration…), fiche de risque guidée.
- Rappel : un vrai PDF de client a été transmis dans la conversation pour montrer la mise en
  page ; rien n'a été conservé. Ne transmettre que des documents anonymisés.

## Session 1 — 13 octobre 2026 : socle et module clients

**Fait**
- Projet Django 6.1 / Python 3.13 / PostgreSQL 16, réglages par environnement, CI GitHub
  Actions (format, lint, mypy strict, migrations, tests, contrôles de déploiement), Dockerfile
  Cloud Run.
- Comptes sans inscription, double authentification obligatoire, connexion exigée partout,
  administration derrière la même connexion.
- Profils de sécurité (capacités) et portefeuilles privés ; trois profils et le portefeuille
  « Cabinet » créés par migration.
- Journal des consultations inaltérable (déclencheur PostgreSQL), connexions/échecs journalisés,
  IP fiable derrière le répartiteur Google.
- Journal d'événements avec exécution unique et reprise des échecs ; commande `run_jobs`.
- Clients : fiche complète, recherche en direct (accents, numéros, nom + prénom), filtres,
  export Excel journalisé, numéro national masqué (affichage journalisé), coordonnées,
  relations (dirigeants, actionnaires, mandats, proches), équipe, historique des changements.
- Calcul des bénéficiaires effectifs (direct, indirect, contrôle, repli sur les dirigeants,
  ASBL) avec comparaison aux bénéficiaires déclarés.
- BCE Open Data : import complet et mises à jour, recherche, préremplissage d'une nouvelle
  fiche, complétion automatique, différences à valider, alertes faillite/radiation à l'accueil.
- VIES : vérification TVA avec preuve conservée.
- Reprise FID-Manager : analyse à blanc puis import de l'export clients Excel (mapping YAML).
- Commande `demo` (données fictives).
- Relecture indépendante (sécurité) puis corrections : écran de connexion de l'administration
  sans second facteur supprimé, recherche par numéro national séparée et journalisée, fiches
  privées masquées (UBO, recherche BCE, relations, administration), journal vidé par TRUNCATE
  bloqué, fichiers de reprise gardés en base 24 h au plus, double confirmation d'import
  verrouillée, import BCE complet sans verrou de lecture et resynchronisation des clients,
  sonde de santé compatible Cloud Run, journalisation des modifications manquantes.
- 120 tests, tous au vert ; ruff, mypy strict, migrations, `check --deploy` au vert.

**Ajout (demande de Jeremy, même jour)** : navigation centrée sur le client, « comme
Horus ». Sélecteur de dossier en haut (recherche, récents, Ctrl+K), dossier actif mémorisé,
menu du dossier (synthèse, identité, relations, bénéficiaires, équipe, BCE/TVA, historique ;
modules à venir grisés), changement de client en gardant la rubrique, synthèse avec points
d'attention, historique avec les consultations du dossier pour l'AMLCO.

Code poussé sur GitHub : `jeremydewaelheyns1-creator/Outil-cabinet-` (privé), branche `main`.

**Épique 4 (après-midi)** : moteur d'échéances. Règles en YAML (TVA mensuelle et
trimestrielle, listing clients, AG, dépôt des comptes, ISOC, IPP), jours fériés belges et report
au jour ouvrable, génération sans doublon qui suit la fiche et l'équipe, rubrique « Échéances »
du dossier (en retard / à venir / plus tard / terminées, check-lists, responsable, statut,
ajout manuel), échéancier du cabinet filtrable, alerte « en retard » dans la synthèse.

**Soirée (demandes de Jeremy)** : dossier en cinq onglets (D-021 à D-023), en-tête riche à
la FID (relations cliquables, icônes société/personne/ASBL), page Identité enrichie. Sites
officiels (D-024) : fonctions BCE comparées aux relations et reprises en un clic, publications
du Moniteur belge, comptes annuels BNB (API officielle), relevés datés, consultation
hebdomadaire automatique, points d'attention ; carte « Registre UBO » sur la page des
bénéficiaires effectifs.

**Reste à faire / en attente**
- **Onglet Documents (D-033, D-034)** : cases et base commune faites (stockage privé, dépôt,
  lecture journalisée, demandes « À recevoir », relances, rangement) et chaîne « Pièces
  d'identité » (D-035 : OCR local Tesseract, contrôles MRZ, application automatique,
  annulation, demandes avant expiration). À vérifier sur de vraies photos de cartes dans
  l'environnement du cabinet (Jeremy propose de tester avec ses propres données, là-bas
  seulement). Puis étape 3 : messagerie du cabinet (à
  connaître) et IA de lecture dans le Google Cloud du cabinet (projet à créer, seau
  `GS_DOCUMENTS_BUCKET` à prévoir).
- Ancienne note — onglet Documents (en haut). Pour Jeremy, c'est là que doit se jouer la
  plus-value sur FID-Manager : le développer au maximum pour tout automatiser. Tout ce qui
  touche aux UBO doit s'y retrouver (calcul, registre UBO, déclarations, justificatifs,
  confirmation annuelle, questionnaire client) ; la page « Bénéficiaires effectifs » du panneau
  de gauche ne sert alors plus à grand-chose : à confirmer avec lui avant de la retirer.
- En attente de sa réponse : propositions sur Mandataires / Actionnaires (colonne %, total des
  parts, clic sur la ligne) et retrait du cadre « Registre UBO ».
- Vérifier sur l'environnement d'essai que les pages réelles de la BCE et du Moniteur sont
  bien lues (analyseurs écrits sans accès réseau à ces sites, testés sur des pages fictives).
- Clé d'accès gratuite de la Banque Nationale (developer.cbso.nbb.be, produit « Authentic
  Query ») à demander par le cabinet ; à placer dans `NBB_CBSO_KEY`.
- Structure réelle de l'export clients FID-Manager (en-têtes uniquement + lignes inventées).
- Déploiement de l'environnement d'essai sur le Google Cloud du cabinet.
- Page d'accueil (quand aucun dossier n'est ouvert) : à définir avec Jeremy.
- Validation des délais des règles d'échéances par le cabinet ; date IPP de l'année.
- Suite : épique 5 (tâches TVA détaillées).
