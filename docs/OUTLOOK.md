# Relier Outlook à l'outil (D-044) — guide de mise en route

But : les e-mails envoyés depuis l'outil partent de la boîte Outlook de l'employé qui clique
sur « Envoyer », et restent dans ses « Éléments envoyés ». Depuis D-060, chaque employé peut
aussi, s'il le veut, faire lire sa boîte par l'outil (onglet « Ma boîte mail »).

## Ce qu'il faut avant

1. L'outil installé chez le cabinet (Google Cloud), avec son adresse définitive
   (ex. `https://outil.cabinet.be`).
2. Une personne qui a les droits d'administration du Microsoft 365 du cabinet.

## Étape 1 — Inscrire l'application chez Microsoft (une seule fois, par l'administrateur)

1. Aller sur <https://entra.microsoft.com> → **Applications** → **Inscriptions
   d'applications** → **Nouvelle inscription**.
2. Nom : `Outil cabinet`. Types de comptes : **Comptes dans cet annuaire organisationnel
   uniquement**.
3. URI de redirection : type **Web**, adresse `https://<adresse de l'outil>/ma-boite-mail/retour/`.
4. Sur la page de l'application, noter **ID d'application (client)** et **ID de l'annuaire
   (locataire)** : ce ne sont pas des secrets.
5. **API autorisées** → Ajouter → Microsoft Graph → **Autorisations déléguées** : cocher
   `Mail.Send`, `Mail.Read`, `User.Read`, `offline_access`. Puis **Accorder un consentement
   d'administrateur**. Ne rien ajouter d'autre (surtout pas `Mail.ReadWrite`,
   `Mail.Read.Shared` ni aucune autorisation « d'application »).
   - Déjà inscrite avant D-060 ? Il suffit d'ajouter `Mail.Read` (déléguée) et de cliquer à
     nouveau sur **Accorder un consentement d'administrateur**.
6. **Certificats et secrets** → **Nouveau secret client** (durée : 24 mois, noter la date de
   fin). ⚠️ La valeur du secret ne s'affiche qu'une fois : la coller **directement** dans le
   gestionnaire de secrets de Google Cloud (étape 2). Ne jamais l'envoyer par e-mail, chat,
   ni à Claude.

## Étape 2 — Donner les valeurs à l'outil (Cloud Shell)

Les trois valeurs sont rangées dans Secret Manager (Belgique) ; l'installateur les reprend à
chaque mise à jour. Pour chacune : coller la commande, Entrée, coller la valeur, Entrée, puis
Ctrl+D. La valeur collée s'affiche à l'écran (pas dans l'historique des commandes) : taper
`clear` ensuite.

**Secret expiré (renouvellement)** : créer un nouveau secret dans Entra, puis dans Cloud Shell
(la valeur collée reste invisible) :

```bash
read -rs S && printf '%s' "$S" | gcloud secrets versions add OUTLOOK_CLIENT_SECRET --data-file=- ; unset S
```

Coller la valeur, Entrée. Puis la commande `gcloud run services update` ci-dessous.

```bash
gcloud secrets create OUTLOOK_TENANT_ID --replication-policy=user-managed --locations=europe-west1 --data-file=-
gcloud secrets create OUTLOOK_CLIENT_ID --replication-policy=user-managed --locations=europe-west1 --data-file=-
gcloud secrets create OUTLOOK_CLIENT_SECRET --replication-policy=user-managed --locations=europe-west1 --data-file=-
```

Puis brancher l'outil dessus (une minute, sans reconstruire) :

```bash
gcloud run services update outil --region=europe-west1 --update-secrets=OUTLOOK_TENANT_ID=OUTLOOK_TENANT_ID:latest,OUTLOOK_CLIENT_ID=OUTLOOK_CLIENT_ID:latest,OUTLOOK_CLIENT_SECRET=OUTLOOK_CLIENT_SECRET:latest
```

## Étape 3 — Chaque employé relie sa boîte

En haut de l'écran : **Liaison Outlook** → **Se connecter avec Microsoft**. Il se connecte chez
Microsoft (l'outil ne voit pas son mot de passe). C'est fait.

## Étape 4 (facultative) — Faire lire sa boîte par l'outil

Menu de gauche : **Ma boîte mail** → **Activer avec Microsoft**. L'employé accepte chez
Microsoft le droit de lecture. Seuls les e-mails reçus **à partir de ce moment** sont copiés.
Désactiver à tout moment depuis **Liaison Outlook** : toutes les copies sont effacées.
⚠️ Avant l'usage réel : analyse d'impact (AIPD) et note d'information aux employés.

## Sécurité, en bref

- Droits : envoyer ; lire seulement pour l'employé qui l'a activé, et seulement sa boîte.
  L'outil ne peut ni modifier, ni supprimer, ni déplacer un e-mail dans Outlook.
- Chaque employé est seul à voir ses e-mails dans l'outil.
- L'outil garde l'adresse et un jeton chiffré ; jamais de mot de passe.
- Délier : depuis « Ma boîte mail », ou par l'administrateur Microsoft (Applications
  d'entreprise → Outil cabinet → Utilisateurs / Révoquer).
- Avant la fin de validité du secret client : en créer un nouveau et le remplacer dans
  Google Cloud.
