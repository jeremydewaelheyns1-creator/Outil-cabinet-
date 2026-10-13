# Nouveautés

Ce qui a été ajouté à l'outil, du plus récent au plus ancien. Toutes les données de la démo
sont inventées.

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
