# Nouveautés

Ce qui a été ajouté à l'outil, du plus récent au plus ancien. Toutes les données de la démo
sont inventées.

## 24 octobre 2026 — Nouveau look

- L'outil fait peau neuve, dans un style épuré inspiré d'Apple : cartes blanches arrondies,
  barre du haut translucide, onglets du dossier en bouton segmenté, grands titres, pastilles
  de couleur pour l'état des documents. Rien ne change dans le fonctionnement.

## 24 octobre 2026 — Rappels de la carte d'identité et clients qui ne répondent pas

- Carte d'identité : l'outil la demande au client 15 jours avant l'expiration, puis lui
  envoie un rappel **15 jours** et **30 jours après** l'expiration.
- Toujours rien 15 jours après le dernier rappel ? Une **pastille rouge « sans réponse »**
  apparaît en haut de l'écran du gestionnaire du dossier, avec la liste des clients à
  reprendre en main, et un badge dans l'en-tête du dossier.

## 24 octobre 2026 — Rappels automatiques et résumé du mois

- La nouvelle carte d'identité est demandée **15 jours** avant l'expiration (la ligne passe en
  orange au même moment).
- Un extrait du registre UBO rangé sans date est considéré valable un an.
- Page d'accueil : vos dossiers incomplets et à revoir, en un coup d'œil.
- L'écran Conformité s'affiche beaucoup plus vite.
- La démo montre une fiche de risque guidée, une demande groupée et les notifications.

- Quand la carte d'identité d'un client expire, l'outil lui écrit tout seul. S'il y a
  plusieurs cartes pour le même client, tout part dans **un seul e-mail**.
- Nouvelle **cloche** en haut de l'écran : chaque début de mois, un résumé de vos dossiers à
  mettre en ordre et de ce que l'outil a fait seul (demandes, rappels, documents reçus).

## 23 octobre 2026 — La paperasse anti-blanchiment en pilote automatique

- **Signature en ligne** : le client reçoit un lien, lit le document sur son téléphone, signe
  du doigt. Le document signé (avec son certificat) se range seul et le client en reçoit une
  copie.
- **Fiche de risque guidée** : l'outil pré-remplit ce qu'il sait (activité BCE, pays,
  structure), calcule le niveau et la date de la prochaine révision, et fabrique le PDF.
  Risque élevé : validation de l'AMLCO.
- **Documents à mettre à jour** : si l'adresse, les mandataires ou les bénéficiaires changent,
  le document concerné passe en orange, et une échéance est créée pour le gestionnaire. Idem
  pour la fiche de risque et l'extrait UBO qui expirent.
- **Nouvel écran « Conformité »** : tous les dossiers, ce qui manque, et un bouton pour tout
  demander aux clients — **un seul e-mail, un seul lien** par client pour déposer les cartes
  et signer les documents.

## 20 octobre 2026 — Archives des courriels plus claires

- Une demande annulée disparaît des archives « Courriels ».
- Sous l'e-mail de demande, la pièce renvoyée par le client apparaît (« Réponse du client,
  reçue le … »), à ouvrir d'un clic.
- Lien sécurisé : correction de l'envoi qui était refusé, et les fichiers choisis s'affichent.

## 20 octobre 2026 — Lien sécurisé pour les documents demandés

- L'e-mail de demande contient un **lien personnel** : le client y dépose la photo du recto
  et du verso de sa carte (ou un PDF), sans créer de compte. La carte est aussitôt lue,
  vérifiée et rangée dans son dossier.
- Le lien ne sert qu'à déposer, il expire après 14 jours (prolongé à chaque relance) et ne
  marche plus une fois la pièce reçue.

## 20 octobre 2026 — Les demandes de documents partent vraiment

- Une demande de carte d'identité (et ses relances) part maintenant de la boîte Outlook
  reliée, avec un texte plus clair et personnalisé (« Bonjour Madame X, »).
- Chaque e-mail envoyé est gardé dans **Archives › Courriels** du dossier.
- E-mail TVA : le bloc commence par « Pour le paiement : ».

## 20 octobre 2026 — TVA : paiement prêt à copier, cases alignées

- L'e-mail TVA reprend la ligne de paiement du PDF de l'administration : bénéficiaire
  (TVA-BTW), compte, BIC, montant et communication structurée, prêts à copier-coller.
- Les boutons XML et PDF sont maintenant dans la case « Déposée » : toutes les cases d'une
  ligne ont la même taille.

## 20 octobre 2026 — Le dépôt de documents fonctionne dans la démo

- Sur la page **Déposer des documents** de cette démo, on peut maintenant essayer : un lien
  permet de télécharger une déclaration TVA fictive, à redéposer ensuite. L'outil la lit dans
  le navigateur et indique où il la range (dossier, trimestre, montant). Rien n'est
  enregistré.
- La lecture des PDF et des cartes d'identité ne marche que dans l'outil installé.

## 20 octobre 2026 — Envoyer depuis sa boîte Outlook (préparé)

- Nouvelle page **Ma boîte mail** (en haut à droite) : chaque employé pourra relier sa boîte
  Outlook avec « Se connecter avec Microsoft ». Les e-mails envoyés depuis l'outil partiront
  alors de sa propre adresse et resteront dans ses « Éléments envoyés ».
- L'outil ne voit jamais le mot de passe et ne peut pas lire la boîte : il peut seulement
  envoyer ce que vous validez.
- À activer quand l'outil sera installé chez le cabinet (pas dans cette démo).

## 20 octobre 2026 — E-mails personnalisés

- Page **Identité** : nouvelle case **Personne de contact** (Monsieur, Madame, Docteur,
  Maître… + nom). Les e-mails commencent par « Bonjour Monsieur Dubois, ».
- E-mail TVA : quand le PDF de la déclaration contient le compte et la communication
  structurée, l'outil les recopie dans l'e-mail, prêts à copier-coller pour le paiement.

## 20 octobre 2026 — E-mail TVA au client, acomptes déduits

- Colonne **Acomptes** : on y indique les acomptes déjà payés par le client. Le reste à payer
  s'affiche sous le solde.
- Dans la case **Com. client** : « Préparer l'e-mail au client ». L'outil écrit l'e-mail
  (montant de la déclaration, acomptes déjà payés, reste à payer, date limite), on le relit,
  on le modifie si besoin, puis **Envoyer au client** en bas à droite. Le PDF de la
  déclaration est joint (case à décocher si on ne veut pas).
- L'e-mail ne peut partir qu'à une adresse de la fiche du client. Tant que la messagerie du
  cabinet n'est pas branchée, il est enregistré mais ne part pas encore.

## 20 octobre 2026 — Un seul endroit pour déposer les documents

- Nouveau bouton **Déposer des documents** en haut de l'écran : on y glisse n'importe quel
  fichier, de n'importe quel client. L'outil trouve seul le dossier et la place.
- Reconnus pour l'instant : les déclarations TVA et listings IC d'Intervat (XML et PDF) et les
  cartes d'identité. Le reste va dans **À classer** (visible par vous seul, effacé après 30
  jours), à ranger en deux clics.
- Onglet TVA : quatre choix par case (**Fini, Travail en cours, Avertissement, Pas
  nécessaire**). Recliquer sur le choix en cours vide la case. Dans cette démo, on peut cocher
  pour essayer (rien n'est enregistré).

## 20 octobre 2026 — Onglet Déclaration TVA, comme FID

- Une ligne par trimestre (ou par mois) avec les cases **Doc. reçus, Fini, Déposée, IC,
  Com. client**. Un clic sur une case propose les sept états de FID (fait, en cours, en
  attente, avertissement, pas nécessaire…), avec la date et une remarque.
- **Import des déclarations** : on dépose le XML et le PDF sortis d'Intervat, même de
  plusieurs dossiers à la fois. L'outil reconnaît seul le dossier et la période, coche
  « Déposée », reprend le solde (grille 71 ou 72) et range les fichiers dans les archives TVA.
- La ligne passe au vert quand tout est fait, et l'échéance du dossier se clôture d'elle-même.

## 20 octobre 2026 — Générer un document et l'envoyer au client pour signature

- Dans l'onglet **Documents**, un bouton **Générer** (document jamais fait) ou **Mettre à
  jour** (document qui expire ou n'est plus à jour) produit le document avec les données du
  dossier et la date du jour.
- L'aperçu s'ouvre aussitôt, comme pour les autres documents : déjà signé par le cabinet, la
  case du client vide. En bas à droite : **Envoyer au client** (ou **Valider et ranger** pour
  les documents que le client ne signe pas).
- Documents concernés pour l'instant : identification du client, identification des
  mandataires, déclaration des bénéficiaires effectifs, lettre de mission et procuration
  (ces deux derniers avec un modèle provisoire, en attendant ceux du cabinet).

## 15 octobre 2026 — Un rectangle par document, comme la liste de FID

- L'onglet **Documents** a maintenant un rectangle pour chaque ligne de la rubrique
  « Loi anti-blanchiment » de FID : À recevoir, Lettre de mission, Cartes d'identité,
  Déclaration des bénéficiaires effectifs, Identification du client, Identification des
  mandataires, Procuration, Fiche de détermination du niveau de risque, UBO.
- Chaque rectangle a son état (à jour, à confirmer, problème, vide) et l'icône pour ouvrir le
  document en un clic. Présentation sur deux colonnes, comme avant.

## 15 octobre 2026 — Documents anti-blanchiment (comme FID)

- Les cases **Anti-blanchiment**, **Bénéficiaires effectifs** et **Lettre de mission** listent
  chaque document exigé, une ligne par document (et une par mandataire quand il en faut une
  par personne) : identification du client, identification des mandataires, fiche de
  détermination du niveau de risque, procuration, déclaration des bénéficiaires effectifs,
  extrait du registre UBO, lettre de mission.
- Chaque ligne montre le document, sa date et sa date d'expiration. Elle est **surlignée en
  orange** si le document expire dans les deux mois ou si sa date d'expiration est indéfinie,
  **en rouge** s'il manque ou est expiré.
- L'état de chaque case suit automatiquement et dit quel est le problème (par exemple « Fiche
  de détermination du niveau de risque : expire dans 44 jours »).
- **« Demander au client »** sur une ligne envoie la demande ; quand le document arrive, il se
  range tout seul à la bonne ligne. Un nouveau document remplace l'ancien, qui part aux
  Archives.

## 15 octobre 2026 — Visualiseur de documents

- Un clic sur un document l'ouvre **en grand, par-dessus la page**, comme dans FID : on ne
  quitte pas l'écran où l'on était, « Fermer » y ramène.
- En haut : le titre, la date, où il est rangé, la personne concernée, et les boutons
  **Imprimer** et **Télécharger**.
- Onglets : **Aperçu** (les pages du document), **Informations** (fichier, origine, date,
  empreinte) et, pour une carte d'identité, **Données lues**.
- Un seul clic sur l'icône d'un rectangle ouvre directement le document (le plus récent) ;
  s'il y en a plusieurs, les flèches ‹ › du visualiseur passent de l'un à l'autre.
- Dans la démo : onglet Documents de la Boulangerie, icône à côté de « Lettre de mission ».

## 15 octobre 2026 — Accès direct aux documents

- Dans l'onglet **Documents**, une petite icône apparaît à côté de l'état quand la case contient
  un document ; un clic l'ouvre directement. Pas de document, pas d'icône.

## 15 octobre 2026 — Pièces d'identité automatiques

- La case **Pièces d'identité** liste chaque personne du dossier (gérants, administrateurs,
  actionnaires) avec sa carte : vert si elle est valable, orange si elle expire dans les deux
  mois, rouge si elle manque ou est expirée.
- **15 jours avant l'expiration**, l'outil demande tout seul la nouvelle carte au client (elle
  apparaît dans « À recevoir », avec les relances).
- Quand la carte arrive, l'outil **lit les lignes codées au dos** et vérifie tout (chiffres de
  contrôle, nom, numéro national, validité). Si tout concorde, la fiche est mise à jour sans
  rien demander ; la ligne indique « classé automatiquement » et peut être annulée pendant
  7 jours. Au moindre doute, la carte est « à confirmer », avec la raison.
- La lecture se fait sur le serveur du cabinet : la carte n'est envoyée nulle part. Le numéro
  national lu n'est jamais affiché ni conservé ; le numéro de carte est masqué.
- Dans la démo : à la Boulangerie, la carte de Lambert Sophie est valable, celle de Dubois Marc
  expire bientôt et a déjà été redemandée.

## 15 octobre 2026 — Documents : dépôt, demandes au client et relances

- On peut **déposer un document** dans chaque case de l'onglet Documents et dans chaque dossier
  des Archives (PDF, photo, Word, Excel). Il est rangé en sécurité ; chaque ouverture est
  enregistrée dans le journal.
- **À recevoir** : on demande une pièce au client (par exemple la carte d'identité d'un gérant).
  L'outil prépare l'e-mail et le **relance tout seul** après 7 jours, deux fois. Sans réponse
  ensuite, la case passe en rouge (« problème »).
- Quand la pièce arrive, un clic sur « Reçu » la range au bon endroit : une carte d'identité va
  dans Pièces d'identité et l'ancienne carte part aux Archives.
- Les e-mails ne sont **pas encore réellement envoyés** : ils sont affichés dans l'outil en
  attendant de brancher la messagerie du cabinet.
- Dans la démo : la Boulangerie a une demande en attente, le Garage une demande restée sans
  réponse (case rouge). Les documents de la démo sont fictifs ; on ne peut pas les ouvrir dans
  la démo en ligne.

## 14 octobre 2026 — Onglet Documents

- L'onglet **Documents** montre un rectangle par sujet : À recevoir, Pièces d'identité,
  Bénéficiaires effectifs (UBO), Anti-blanchiment, Lettre de mission.
- Chaque rectangle indique son état : « à jour » (vert), « à confirmer » (orange),
  « problème » (rouge), « bientôt » (pas encore en place).
- Les **Bénéficiaires effectifs** sont maintenant dans leur case (ils quittent la gauche).

## 14 octobre 2026 — Archives

- À gauche, un nouveau groupe **Archives**, comme dans FID : Légal et statuts, Moniteur belge,
  Comptes annuels (BNB), ISOC (ou IPP pour une personne), TVA, Administratif, Courriels.
- Le dossier **Moniteur belge** liste déjà les publications de la société. Les autres se
  rempliront avec l'onglet Documents.
- Anti-blanchiment et Pièces d'identité quittent la gauche : ils iront dans l'onglet Documents.

## 13 octobre 2026 — « Autres relations » supprimé

- La page « Autres relations » disparaît du panneau de gauche. Le conjoint reste visible sous le
  nom du client.

## 13 octobre 2026 — Fiche allégée

- Les pages « BCE et TVA », « Moniteur belge » et « Équipe du cabinet » disparaissent du panneau
  de gauche.
- Sur **Identité et coordonnées** : un bandeau signale une publication récente au Moniteur
  (avec le PDF), et un encadré propose de reprendre ce qui diffère de la BCE (nom, adresse…).
  Rien ne s'affiche quand tout est en ordre.
- Sur **Mandataires** : les administrateurs et gérants publiés à la BCE, avec un bouton
  « Ajouter aux mandataires » pour ceux qui manquent.
- **VIES** devient un simple lien vers le site officiel, comme dans FID.

## 13 octobre 2026 — Un dossier s'ouvre sur « Identité et coordonnées »

- Quand on ouvre un client (depuis la liste, le sélecteur du haut ou une relation), on arrive
  toujours sur « Identité et coordonnées ».

## 13 octobre 2026 — Onglets du haut réordonnés

- Nouvel ordre : Clôture, Déclaration TVA, Versements anticipés, Documents.
- L'onglet Time sheet est retiré pour l'instant.

## 13 octobre 2026 — Nouvelle organisation du dossier (comme FID-Manager)

- **En haut**, sous le nom du client, les onglets du travail de tous les jours : Documents,
  Clôture, Versements anticipés, Déclaration TVA (seulement si le client est assujetti) et
  Time sheet. Leur contenu sera défini un par un.
- **À gauche**, un panneau pour la paperasse, comme dans FID : Fiche, Organisation, Suivi,
  Conformité, Facturation. Tout est à un clic.
- L'ancienne page « Relations » est découpée en **Mandataires**, **Actionnaires** et **Autres
  relations**, avec le nombre de fiches à côté de chacune, comme les **Bénéficiaires
  effectifs (UBO)**.

## 13 octobre 2026 — Plus d'onglet « Synthèse »

- L'onglet « Synthèse » est supprimé. Quand on ouvre un client, on arrive directement sur sa
  **Fiche** (identité et coordonnées). Il reste quatre onglets : Fiche, Travail, Documents et
  conformité, Facturation.

## 13 octobre 2026 — Les sites officiels dans le dossier (BCE, Moniteur belge, Banque Nationale)

- Dans l'onglet **Fiche** d'une société, deux nouveaux sous-onglets : **Moniteur belge**
  (toutes les publications : constitution, nominations, démissions, transfert de siège…, avec
  le PDF) et **Comptes annuels** (exercices déposés à la Banque Nationale, date de dépôt, date
  de l'assemblée générale).
- Dans **BCE et TVA** : les administrateurs et gérants publiés à la BCE, comparés aux relations
  de la fiche. S'il en manque un, un bouton « Ajouter aux relations » le reprend en un clic.
- Chaque page a un bouton qui ouvre directement la page officielle du client, et un bouton
  « Actualiser ». L'outil consulte aussi ces sites tout seul, une fois par semaine.
- La **Synthèse** signale ce qui bouge : publication récente au Moniteur, dirigeant publié à la
  BCE mais absent des relations.
- **Bénéficiaires effectifs** : ils ne sont pas publiés à la BCE. La page explique où les
  vérifier (registre UBO dans MyMinfin) et propose les raccourcis utiles.
- Dans la démo, ces informations sont inventées. Dans l'outil du cabinet, elles seront lues
  sur les vrais sites. Pour la Banque Nationale, le cabinet devra demander une clé d'accès
  gratuite.

## 13 octobre 2026 — Plus d'informations d'un coup d'œil (inspiré de FID-Manager)

- Sous le nom du client : la liste de ses relations (gérant, associés, conjoint, sociétés dont
  il est administrateur…). Un clic ouvre la fiche de la relation, sur le même onglet.
- Une petite icône distingue partout une société, une personne physique (IPP) et une ASBL :
  en-tête, sélecteur de client, liste des clients, relations.
- La page « Identité et coordonnées » est plus complète : toutes les informations en deux
  colonnes, une zone « Note », les e-mails et téléphones, l'adresse avec lien Google Maps,
  des boutons pour copier les numéros, la date d'ajout et de dernière modification.
- En bas de la fiche d'une société : boutons qui ouvrent directement la BCE, la Banque
  Nationale (comptes annuels), le Moniteur belge et Companyweb sur ce client.

## 13 octobre 2026 — Menu réduit à l'essentiel

- Le menu de gauche ne contient plus que « Accueil » et « Tous les clients ».
- Les outils d'administration (reprise FID-Manager, données BCE, journal des consultations,
  comptes) sont masqués du menu ; ils restent accessibles à l'adresse /parametres/.

## 13 octobre 2026 — Menu de l'accueil allégé

- Le menu de gauche ne contient plus « Échéancier » ni « Nouveau client » : on crée un client
  depuis « Tous les clients ».

## 13 octobre 2026 — Onglets à venir cliquables

- « Documents » et « Conformité » sont regroupés en un seul onglet « Documents et conformité ».
- Les onglets pas encore construits s'ouvrent et montrent ce qu'ils contiendront.

## 13 octobre 2026 — Dossier client réorganisé en onglets

- Dans un client, l'écran ne montre plus que le dossier : un en-tête toujours visible (nom,
  numéro, responsable, retards) et un onglet « Accueil » pour revenir aux écrans du cabinet.
- Six grands onglets qui ne bougeront plus : Synthèse, Fiche, Travail, Documents,
  Conformité, Facturation. Les nouvelles fonctions viendront se ranger dedans, en sous-onglets.
- Fiche : identité, relations, bénéficiaires effectifs, BCE et TVA, équipe.
- Travail : échéances (avec le nombre de retards sur l'onglet).
- Les sous-onglets prévus sont déjà visibles en grisé.

## 13 octobre 2026 — Démo en ligne

- Cette démo se met à jour toute seule à chaque fois qu'une étape est terminée.
- On peut naviguer partout ; les boutons qui enregistrent (Terminer, Ajouter…) sont désactivés.

## 13 octobre 2026 — Échéances

- Chaque dossier reçoit automatiquement ses échéances selon sa fiche : déclarations TVA
  (mensuelles ou trimestrielles), listing clients, assemblée générale, dépôt des comptes
  annuels, ISOC.
- Les dates tombant un week-end ou un jour férié belge sont reportées au jour ouvrable suivant.
- Chaque échéance est attribuée d'après l'équipe du dossier et a sa check-list.
- Nouvelle rubrique « Échéances » dans chaque dossier, et « Échéancier » pour tout le cabinet
  (menu de gauche).
- La synthèse du dossier signale les échéances en retard.
- À faire valider par le cabinet : les délais légaux utilisés et la date IPP de l'année.

## 13 octobre 2026 — Navigation par dossier

- On choisit le client en haut de l'écran (recherche ou derniers dossiers, raccourci Ctrl+K).
- Le menu de gauche montre les rubriques du dossier : synthèse, échéances, identité,
  relations, bénéficiaires effectifs, équipe, BCE et TVA, historique.
- Changer de client garde la rubrique ouverte.
- La synthèse commence par les points d'attention du dossier.

## 13 octobre 2026 — Fiches clients

- Fiches des sociétés et des personnes, recherche instantanée, export Excel.
- Relations : gérants, administrateurs, actionnaires, conjoints ; chaque personne n'a qu'une
  fiche, reliée aux sociétés.
- Calcul automatique des bénéficiaires effectifs, y compris via une holding.
- Banque-Carrefour des Entreprises : préremplissage d'une nouvelle fiche, alertes faillite et
  radiation.
- Vérification TVA dans VIES avec preuve conservée.
- Reprise de l'export clients de FID-Manager (analyse avant import, jamais d'écrasement).
- Sécurité : double authentification obligatoire, numéro national masqué, journal de qui a
  consulté quoi.
