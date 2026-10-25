# Feuille de route

Ordre des épiques (cahier des charges « parité FID-Manager »). Une épique est terminée quand
son critère de fin est vérifié par des tests et sur l'environnement d'essai.

| # | Épique | État |
| --- | --- | --- |
| 1 | Fondations : comptes, double authentification, droits, journaux, événements, CI | ✅ socle livré (déploiement Google Cloud à faire avec le cabinet) |
| 2 | Clients : fiche, recherche, relations, équipe, historique, export | ✅ première version |
| 3 | Données publiques : BCE, VIES, Peppol, UBO | 🟡 BCE + VIES + calcul UBO faits ; reste : téléchargement BCE automatique, annuaire Peppol, registre UBO |
| 4 | Moteur de tâches (règles en YAML, échéances) | ✅ première version (règles TVA, listing, AG, comptes annuels, ISOC, IPP) |
| 5 | Tâches TVA (déclarations, listings, relevé intracom.) | ⏳ |
| 6 | Documents (Cloud Storage, classement, conservation) | ⏳ |
| 7 | Reconnaissance (IA Vertex : lecture et classement des pièces, cartes d'identité) | ⏳ |
| 8 | Communication (Microsoft 365 : e-mails entrants/sortants, modèles) | 🟡 envoi depuis Outlook (D-044) + « Ma boîte mail » : lecture, classement par dossier, recherche (D-060) |
| 9 | Anti-blanchiment (KYC, grille de risque, sanctions UE, pièces d'identité) | ⏳ |
| 10 | Migration FID-Manager complète (FID-Drive, autres exports) | 🟡 import des clients fait |
| 11 | Clôtures annuelles | ⏳ |
| 12 | IPP | ⏳ |
| 13 | Précomptes, UBO (déclarations) | ⏳ |
| 14 | Tâches ponctuelles | ⏳ |
| 15 | Signature électronique (itsme via eID Easy) | ⏳ |
| 16 | Portail client | ⏳ |
| 17 | Procédures internes | ⏳ |
| 18 | Timesheet | 🟡 première version (feuille de temps, temps passé par dossier) |
| 19 | Facturation (Peppol via Billit) | ⏳ |
| 20 | Envois et exports | ⏳ |
| 21 | RH | ⏳ |
| 22 | Analyse (tableaux de bord) | ⏳ |
| 23 | Intégrations secondaires | ⏳ |

## Prochaines étapes immédiates

1. Recevoir la **structure** (en-têtes + lignes inventées) de l'export clients FID-Manager et
   compléter `config/reprise/clients.yaml`.
2. Faire valider les délais de `config/taches/regles.yaml` par le cabinet ; date IPP à renseigner.
3. Épique 5 : tâches TVA (relevé intracommunautaire, acomptes, suivi des paiements).
4. Déploiement de l'environnement d'essai sur le Google Cloud du cabinet.

## Dette connue

- Recherche clients par `unaccent icontains` : suffisant pour quelques milliers de fiches ;
  ajouter un index trigramme sur un champ normalisé au-delà.
- Calcul UBO : des chemins de détention qui se recoupent peuvent être comptés deux fois
  (signalé comme estimation à l'écran).
- L'import BCE complet remplace les tables par DELETE dans une transaction (lecture non
  bloquée, mais base plus volumineuse jusqu'au prochain VACUUM) : à lancer la nuit.
- `retry_pending` ignore un événement dès qu'un de ses traitements a épuisé ses 5 essais
  (cas d'un traitement abonné plus tard) : à revoir si cela arrive.
- Mise en service : les échéances des 60 derniers jours apparaîtront « en retard » ; prévoir une
  clôture groupée de l'existant (déjà traité dans FID-Manager).
- Unicité du numéro national : un utilisateur au profil « données sensibles » apprend qu'un
  numéro existe dans un portefeuille privé (inévitable, contrainte d'unicité).
