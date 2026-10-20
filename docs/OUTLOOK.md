# Relier Outlook à l'outil (D-044) — guide de mise en route

But : les e-mails envoyés depuis l'outil partent de la boîte Outlook de l'employé qui clique
sur « Envoyer », et restent dans ses « Éléments envoyés ».

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
   `Mail.Send`, `User.Read`, `offline_access`. Puis **Accorder un consentement
   d'administrateur**. Ne rien ajouter d'autre (surtout pas `Mail.Read`).
6. **Certificats et secrets** → **Nouveau secret client** (durée : 24 mois, noter la date de
   fin). ⚠️ La valeur du secret ne s'affiche qu'une fois : la coller **directement** dans le
   gestionnaire de secrets de Google Cloud (étape 2). Ne jamais l'envoyer par e-mail, chat,
   ni à Claude.

## Étape 2 — Donner les valeurs à l'outil (dans Google Cloud)

Dans les réglages du service (variables et secrets) :

| Nom | Valeur |
|---|---|
| `OUTLOOK_TENANT_ID` | ID de l'annuaire (locataire) |
| `OUTLOOK_CLIENT_ID` | ID d'application (client) |
| `OUTLOOK_CLIENT_SECRET` | le secret client (en **secret**, pas en variable visible) |
| `MAILBOX_TOKEN_KEY` | clé de chiffrement des jetons (en **secret**), générée lors de l'installation |

## Étape 3 — Chaque employé relie sa boîte

En haut de l'écran : **Ma boîte mail** → **Se connecter avec Microsoft**. Il se connecte chez
Microsoft (l'outil ne voit pas son mot de passe). C'est fait.

## Sécurité, en bref

- Droits : envoyer seulement. L'outil ne peut pas lire les boîtes.
- L'outil garde l'adresse et un jeton chiffré ; jamais de mot de passe.
- Délier : depuis « Ma boîte mail », ou par l'administrateur Microsoft (Applications
  d'entreprise → Outil cabinet → Utilisateurs / Révoquer).
- Avant la fin de validité du secret client : en créer un nouveau et le remplacer dans
  Google Cloud.
