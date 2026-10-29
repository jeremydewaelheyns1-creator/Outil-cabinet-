"""Fiche d'évaluation du niveau de risque du client, sur les modèles ITAA 5.1 et 5.2 (D-049,
D-087).

Base : loi du 18 septembre 2017 (art. 19 et annexes I à III), norme ITAA anti-blanchiment.
- Modèle 5.1 : 9 blocs, une quarantaine de critères, chacun noté faible / standard / élevé
  avec un commentaire. L'outil **propose** un niveau quand il le peut (BCE, pays, structure de
  détention, déclaration UBO, fiche précédente) et dit pourquoi ; le gestionnaire complète et
  corrige.
- Synthèse : proposée au niveau le plus élevé des critères ; le gestionnaire peut l'abaisser en
  motivant, sauf si un critère décisif (PPE, gel des fonds, pays à haut risque) est élevé.
- Modèle 5.2 : les 4 critères de synthèse (client, activité, géographie, mission), déduits des
  blocs du 5.1, et la validation de l'AMLCO quand le risque est élevé (capacité
  « aml.decide »).
- Prochaine révision selon le niveau (`RISK_REVIEW_YEARS`) → la fiche expire à cette date.

Les listes (secteurs sensibles, pays) sont des points de départ à valider par l'AMLCO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.clients.models import Client
from apps.core import events
from apps.core.cabinet import cabinet_name
from apps.core.models import User

from .models import RiskAssessment

# Secteurs sensibles (codes NACE-BEL, préfixes) : activités où les espèces ou les montages
# sont fréquents, d'après les analyses sectorielles de la CTIF. À adapter par l'AMLCO.
SENSITIVE_SECTORS: dict[str, str] = {
    "41": "construction de bâtiments",
    "42": "génie civil",
    "43": "travaux de construction spécialisés",
    "451": "commerce de véhicules",
    "4677": "commerce de déchets et débris (métaux)",
    "4648": "commerce de gros d'horlogerie et de bijouterie",
    "4777": "commerce de détail d'horlogerie et de bijouterie",
    "3212": "fabrication de bijouterie",
    "4932": "transports de voyageurs par taxis",
    "55": "hébergement",
    "56": "restauration et débits de boissons",
    "68": "activités immobilières",
    "6612": "courtage de valeurs mobilières",
    "6619": "autres activités auxiliaires de services financiers",
    "8010": "activités de sécurité privée",
    "8121": "nettoyage courant des bâtiments",
    "92": "jeux de hasard et d'argent",
}
# Pays à haut risque (liste noire du GAFI, appel à contre-mesures). À tenir à jour par l'AMLCO
# avec les listes du GAFI et de la Commission européenne.
HIGH_RISK_COUNTRIES = {"KP": "Corée du Nord", "IR": "Iran", "MM": "Myanmar"}
_EU_EEA = "AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK"
_EU_EEA += " IS LI NO"  # EEE
EU_EEA = set(_EU_EEA.split(" "))


Level = RiskAssessment.Level
LOW, MEDIUM, HIGH = Level.LOW, Level.MEDIUM, Level.HIGH
ORDER: dict[str, int] = {LOW: 0, MEDIUM: 1, HIGH: 2}

# Les 9 blocs du formulaire d'évaluation du niveau de risque de l'ITAA (modèle 5.1) — D-087.
BLOCKS: tuple[tuple[str, str], ...] = (
    ("mission", "Nature de la mission (annexe I de la LAB)"),
    ("client", "Facteurs de risques liés au client"),
    ("comportement", "Facteurs de risque liés à la nature, la réputation et le comportement "
     "du client"),
    ("geo", "Risques liés à certains facteurs géographiques"),
    ("services", "Facteurs de risques liés aux services ou aux transactions"),
    ("client3", "Client (annexe III de la LAB)"),
    ("activite3", "Activité (annexe III de la LAB)"),
    ("localisation3", "Localisation (annexe III de la LAB)"),
    ("varia", "Varia"),
)  # fmt: skip

# Les 4 critères du formulaire de synthèse (modèle 5.2) et les blocs du 5.1 qui les nourrissent.
CRITERIA: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("client", "Client", ("client", "comportement", "client3")),
    ("activite", "Activité / secteur", ("activite3", "varia")),
    ("geographie", "Géographique", ("geo", "localisation3")),
    ("mission", "Nature de la mission", ("mission", "services")),
)


@dataclass(frozen=True)
class Question:
    """Un critère du modèle 5.1, noté faible / standard / élevé avec un commentaire."""

    key: str
    block: str
    text: str
    help: str = ""
    # Élevé ici → la synthèse ne peut pas être plus basse (vigilance accrue imposée par la loi :
    # PPE, pays à haut risque, gel des avoirs).
    decisive: bool = False

    @property
    def block_label(self) -> str:
        return dict(BLOCKS)[self.block]


Q = Question
QUESTIONS: tuple[Question, ...] = (
    Q("mission_objet", "mission", "Objet et nature de la relation d'affaires",
      "Missions confiées au cabinet (lettre de mission)."),
    Q("mission_duree", "mission", "Régularité ou durée de la relation d'affaires",
      "Relation suivie et connue, ou nouvelle relation."),
    Q("activite", "client", "Description de l'activité du client",
      "L'activité est-elle connue, claire et cohérente ?"),
    Q("secteurs_risque", "client",
      "Liens avec des secteurs exposés à un risque élevé de blanchiment ou de financement "
      "du terrorisme", "Construction, horeca, véhicules, immobilier, bijouterie… (CTIF)."),
    Q("secteurs_politique", "client", "Liens avec des secteurs liés à la politique",
      "Marchés publics, partis, organismes publics."),
    Q("controle", "client",
      "Environnement opérationnel et de contrôle adapté à la taille et à l'activité",
      "Comptabilité tenue, contrôle interne, organisation."),
    Q("presse", "comportement", "Informations négatives dans la presse ou d'autres sources",
      "Recherche sur le client, ses dirigeants et ses bénéficiaires effectifs."),
    Q("gel", "comportement",
      "Le client ou un bénéficiaire effectif fait l'objet d'une mesure de gel des fonds",
      "Listes de sanctions belges, européennes et de l'ONU.", decisive=True),
    Q("actionnariat", "comportement",
      "Transparence et cohérence de la structure d'actionnariat et de contrôle",
      "Bénéficiaires effectifs identifiés, actionnaires apparents, titres au porteur."),
    Q("operations", "comportement",
      "Opérations complexes, inhabituelles ou d'un montant anormalement élevé"),
    Q("transparence", "comportement",
      "Transparence du client et des bénéficiaires effectifs envers le cabinet",
      "Documents et informations fournis sans difficulté."),
    Q("origine_fonds", "comportement", "Origine du patrimoine ou des fonds facile à expliquer"),
    Q("pep", "comportement",
      "Le client ou un bénéficiaire effectif est une personne politiquement exposée (PPE)",
      "Ou un membre de sa famille ou une personne connue pour lui être étroitement associée.",
      decisive=True),
    Q("bourse", "comportement", "Le client ou son mandataire est une société cotée en bourse",
      "Une société cotée est soumise à des obligations de transparence (risque plus faible)."),
    Q("zone_euro", "geo", "Activités exercées dans la zone euro / l'Union européenne",
      "Siège, résidence et activités."),
    Q("paradis_fiscal", "geo", "Liens avec un paradis fiscal ou un pays à haut risque",
      "Siège, résidence, activité ou flux financiers (listes GAFI et UE).", decisive=True),
    Q("anonymat", "services",
      "Le service ou la transaction permet l'anonymat ou la dissimulation"),
    Q("transactions", "services", "Transparence sur les transactions réalisées"),
    Q("legal", "services", "Le service demandé est conforme à la loi et cohérent avec "
      "l'activité"),
    Q("circonstances", "client3", "Relation d'affaires dans des circonstances inhabituelles"),
    Q("detention_actifs", "client3", "Structure de détention d'actifs personnels",
      "Société patrimoniale, holding de placement."),
    Q("especes", "client3", "Activité nécessitant beaucoup d'espèces"),
    Q("structure", "client3",
      "Structure de propriété inhabituelle ou excessivement complexe au regard de l'activité",
      "Plusieurs niveaux de sociétés, sociétés étrangères, bénéficiaires non résolus."),
    Q("produits_anonymes", "activite3", "Produits ou transactions favorisant l'anonymat"),
    Q("distance", "activite3",
      "Relation ou opérations à distance sans garanties (signature électronique)",
      "Client jamais rencontré et identifié sans moyen électronique fiable."),
    Q("paiements_tiers", "activite3", "Paiements reçus de tiers inconnus ou non associés"),
    Q("nouveautes", "activite3",
      "Nouveaux produits, pratiques commerciales ou technologies"),
    Q("pays_lbc", "localisation3",
      "Pays sans dispositif efficace de lutte contre le blanchiment", "Listes GAFI et UE.",
      decisive=True),
    Q("pays_corruption", "localisation3",
      "Pays à niveau significatif de corruption ou d'autres activités criminelles"),
    Q("pays_sanctions", "localisation3", "Pays soumis à des sanctions ou à des embargos",
      decisive=True),
    Q("pays_terrorisme", "localisation3",
      "Pays finançant ou soutenant des activités terroristes", decisive=True),
    Q("v_jeux", "varia", "Jeux de hasard"),
    Q("v_immobilier", "varia", "Agent immobilier"),
    Q("v_asbl", "varia", "ASBL religieuse ou sportive"),
    Q("v_monnaie", "varia", "Monnaie électronique ou transfert de fonds"),
    Q("v_virtuel", "varia", "Monnaies virtuelles ou financement participatif (crowdfunding)"),
    Q("v_fintech", "varia", "FinTech"),
    Q("v_credit", "varia", "Crédit à la consommation ou petits prêts"),
    Q("v_paris", "varia", "Paris sportifs ou en ligne"),
    Q("v_or", "varia", "Commerce d'or, de diamants, de bijoux ou de montres"),
    Q("v_art", "varia", "Commerce d'objets d'art ou de biens culturels"),
)  # fmt: skip
BY_KEY = {q.key: q for q in QUESTIONS}

# Varia : codes NACE-BEL (préfixes) qui rattachent le client à chaque ligne. Point de départ.
VARIA_SECTORS: dict[str, tuple[str, ...]] = {
    "v_jeux": ("9200",),
    "v_immobilier": ("6831",),
    "v_asbl": ("9491", "9312", "9319"),
    "v_monnaie": ("6419", "6612"),
    "v_virtuel": (),
    "v_fintech": (),
    "v_credit": ("6492",),
    "v_paris": ("9200",),
    "v_or": ("3212", "3213", "4648", "4672", "4777"),
    "v_art": ("4778", "4779", "9003"),
}
HOLDING_SECTORS = ("6420", "6430", "6810", "6820")
FINANCE_IT = ("62", "63", "64", "65", "66")


@dataclass(frozen=True)
class Proposal:
    question: Question
    answer: str | None  # niveau proposé ; None : l'outil ne sait pas, à remplir
    reason: str
    comment: str = ""  # commentaire repris de la fiche précédente


def _nace(client: Client) -> list[tuple[str, str]]:
    codes = []
    for item in client.nace_codes or []:
        raw = item.get("code", "") if isinstance(item, dict) else str(item)
        label = item.get("label", "") if isinstance(item, dict) else ""
        codes.append((re.sub(r"\D", "", raw), label))
    return codes


def _sector(client: Client) -> tuple[bool | None, str]:
    codes = _nace(client)
    if not codes:
        return None, "Aucune activité NACE connue (BCE) : à vérifier."
    for code, label in codes:
        for prefix, name in SENSITIVE_SECTORS.items():
            if code.startswith(prefix):
                return True, f"Activité BCE {code} ({label or name}) : secteur « {name} »."
    return False, "Activités BCE hors des secteurs sensibles de la liste."


def _structure(client: Client) -> tuple[str | None, str]:
    if client.is_person:
        return LOW, "Personne physique."
    from apps.clients.services import ubo

    analysis = ubo.analyse(client)
    depth = max((len(h.chain) for c in analysis.candidates for h in c.holdings), default=0)
    foreign = [
        p for c in analysis.candidates for h in c.holdings for p in h.chain
        if (getattr(p, "country", "") or "BE") != "BE"
    ]  # fmt: skip
    if analysis.unresolved_entities:
        return HIGH, "Des sociétés actionnaires n'ont pas de bénéficiaire identifié."
    if depth > 2 or foreign:
        return MEDIUM, "Détention à plusieurs niveaux" + (" via l'étranger." if foreign else ".")
    if not analysis.candidates:
        return None, "Actionnariat inconnu dans l'outil : à vérifier."
    return LOW, "Détention simple et connue."


def _declared_pep(client: Client) -> tuple[str, str] | None:
    """Réponse PEP reprise de la dernière déclaration UBO signée en ligne (D-071)."""
    from .signing import latest_answers

    found = latest_answers(client)
    if found is None:
        return None
    when = f"{timezone.localtime(found.signed_at):%d/%m/%Y}"
    peps = [a.get("name", "") for a in found.answers.values() if a.get("pep")]
    if peps:
        return HIGH, f"Déclaré par le client le {when} (déclaration UBO) : {', '.join(peps)}."
    return LOW, f"Aucune selon la déclaration UBO signée le {when}. Vérifier aussi les bases PPE."


# Anciennes fiches (D-049, oui/non) : question d'alors → critère du modèle 5.1.
LEGACY: dict[str, str] = {
    "pep": "pep", "high_risk_country": "pays_lbc", "nominee": "actionnariat",
    "foreign": "zone_euro", "complex_structure": "structure",
    "sensitive_sector": "secteurs_risque", "cash": "especes", "distance": "distance",
    "new_client": "mission_duree", "risky_mission": "mission_objet", "unusual": "circonstances",
}  # fmt: skip
LEGACY_HIGH = {"pep", "high_risk_country", "nominee"}


def normalise(answers: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """Réponses au format 5.1 ({critère: {level, comment}}), anciennes fiches comprises."""
    result: dict[str, dict[str, str]] = {}
    for key, value in (answers or {}).items():
        if isinstance(value, dict) and key in BY_KEY and value.get("level") in ORDER:
            result[key] = {
                "level": value["level"],
                "comment": str(value.get("comment", "")),
                "reason": str(value.get("reason", "")),
            }
        elif isinstance(value, bool) and key in LEGACY and LEGACY[key] not in result:
            level = (HIGH if key in LEGACY_HIGH else MEDIUM) if value else LOW
            result[LEGACY[key]] = {"level": level, "comment": "", "reason": ""}
    return result


def pep_of(assessment: RiskAssessment) -> bool | None:
    """La fiche dit-elle qu'une PPE est concernée ? None si la question n'y figure pas."""
    found = normalise(assessment.answers).get("pep")
    return None if found is None else found["level"] != LOW


def propose(client: Client, today: date | None = None) -> list[Proposal]:
    """Un niveau proposé par critère, avec la raison (None = à remplir)."""
    today = today or timezone.localdate()
    country = (client.country or "BE").upper()
    in_eu = country in EU_EEA
    risky = country in HIGH_RISK_COUNTRIES
    sector, sector_reason = _sector(client)
    structure = _structure(client)
    codes = [code for code, _ in _nace(client)]
    no_activity = client.is_person and not client.enterprise_number and not codes
    where = f"Pays de la fiche : {HIGH_RISK_COUNTRIES.get(country, country)}."
    country_level = (HIGH, where) if risky else (LOW, where + " Vérifier aussi les flux.")
    answers: dict[str, tuple[str | None, str]] = {key: (None, "À évaluer.") for key in BY_KEY}
    if client.client_since:
        recent = client.client_since > today - timedelta(days=365)
        answers["mission_duree"] = (
            MEDIUM if recent else LOW,
            f"Client depuis le {client.client_since:%d/%m/%Y}"
            + (" : nouvelle relation." if recent else "."),
        )
    if codes:
        labels = ", ".join(label or code for code, label in _nace(client))
        answers["activite"] = (MEDIUM if sector else LOW, f"Activité BCE : {labels}.")
    elif no_activity:
        answers["activite"] = (LOW, "Personne physique sans activité inscrite à la BCE.")
    if sector is not None:
        answers["secteurs_risque"] = (MEDIUM if sector else LOW, sector_reason)
        answers["especes"] = (
            MEDIUM if sector else LOW,
            "Proposé d'après le secteur : à confirmer.",
        )
    elif no_activity:
        answers["secteurs_risque"] = answers["especes"] = (LOW, "Pas d'activité professionnelle.")
    answers["actionnariat"] = answers["structure"] = structure
    if client.is_person:
        answers["bourse"] = (LOW, "Personne physique : sans objet.")
        answers["detention_actifs"] = (
            (LOW, "Personne physique.") if no_activity else (None, "À évaluer.")
        )
    elif codes:
        holding = any(code.startswith(HOLDING_SECTORS) for code in codes)
        answers["detention_actifs"] = (
            (MEDIUM, "Activité BCE de holding ou de gestion de patrimoine.")
            if holding else (LOW, "Activité BCE opérationnelle.")
        )  # fmt: skip
    answers["zone_euro"] = (LOW if in_eu else MEDIUM, where)
    if risky:
        answers["paradis_fiscal"] = (HIGH, where)
    for key in ("pays_lbc", "pays_sanctions", "pays_terrorisme"):
        if risky or in_eu:
            answers[key] = country_level
    if in_eu:
        answers["pays_corruption"] = country_level
    for key, prefixes in VARIA_SECTORS.items():
        hit = next((c for c in codes if prefixes and c.startswith(prefixes)), None)
        if hit:
            answers[key] = (MEDIUM, f"Activité BCE {hit}.")
        elif codes and prefixes:
            answers[key] = (LOW, "Pas d'activité BCE de ce type.")
        elif codes and not any(c.startswith(FINANCE_IT) for c in codes):
            answers[key] = (LOW, "Activité BCE hors finance et informatique.")
        elif no_activity:
            answers[key] = (LOW, "Pas d'activité professionnelle.")
    declared = _declared_pep(client)
    if declared is not None:
        answers["pep"] = declared
    comments: dict[str, str] = {}
    previous = client.risk_assessments.first()
    if previous is not None:
        when = f"{timezone.localtime(previous.created_at):%d/%m/%Y}"
        for key, value in normalise(previous.answers).items():
            comments[key] = value["comment"]
            if answers[key][0] is None:
                answers[key] = (value["level"], f"Repris de la fiche du {when}.")
    return [Proposal(q, *answers[q.key], comments.get(q.key, "")) for q in QUESTIONS]


def _highest(levels: list[str]) -> str:
    return max(levels, key=ORDER.__getitem__, default=LOW)


def floor(answers: dict[str, dict[str, str]]) -> str:
    """Niveau minimal de la synthèse : élevé si un critère décisif est élevé."""
    decisive = [q for q in QUESTIONS if q.decisive]
    return HIGH if any(answers.get(q.key, {}).get("level") == HIGH for q in decisive) else LOW


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    level: str
    motivation: str


def criteria(answers: dict[str, Any]) -> list[Criterion]:
    """Les 4 lignes du modèle 5.2 : le niveau le plus haut des blocs du 5.1 qui les nourrissent,
    et pour motivation les critères relevés (standard ou élevé) avec leur commentaire."""
    clean = normalise(answers)
    labels = dict(Level.choices)
    result = []
    for key, label, blocks in CRITERIA:
        found = [q for q in QUESTIONS if q.block in blocks and q.key in clean]
        level = _highest([clean[q.key]["level"] for q in found])
        raised = [q for q in found if clean[q.key]["level"] != LOW]
        motivation = (
            " ; ".join(
                f"{q.text} ({labels[clean[q.key]['level']].lower()})"
                + (f" — {clean[q.key]['comment']}" if clean[q.key]["comment"] else "")
                for q in raised
            )
            or "Aucun facteur relevé."
        )
        result.append(Criterion(key, label, level, motivation))
    return result


def evaluate(answers: dict[str, Any]) -> tuple[int, str]:
    """Points (indicatifs : 2 par critère élevé, 1 par standard) et synthèse proposée : le
    niveau le plus haut des critères du 5.1."""
    clean = normalise(answers)
    levels = [value["level"] for value in clean.values()]
    score = sum(ORDER[level] for level in levels)
    return score, _highest(levels)


def next_review(level: str, today: date) -> date:
    years = int(settings.RISK_REVIEW_YEARS.get(level, 1))
    try:
        return today.replace(year=today.year + years)
    except ValueError:  # 29 février
        return today.replace(year=today.year + years, day=28)


def _pdf(assessment: RiskAssessment) -> bytes:
    from weasyprint import HTML

    answers = normalise(assessment.answers)
    rows = [
        (q, *(answers[q.key][f] for f in ("level", "comment", "reason")))
        if q.key in answers else (q, None, "", "")
        for q in QUESTIONS
    ]  # fmt: skip
    html = render_to_string(
        "documents/modeles/fiche_risque.html",
        {
            "cabinet": cabinet_name(),
            "client": assessment.client,
            "today": timezone.localdate(),
            "doc_label": "Évaluation du niveau de risque du client",
            "assessment": assessment,
            "rows": rows,
            "criteria": criteria(assessment.answers),
            "levels": Level.choices,
            "author": assessment.created_by,
        },
    )
    return bytes(HTML(string=html).write_pdf())


class Incomplete(ValueError):
    """Fiche refusée : critère sans niveau, ou synthèse abaissée sans motivation."""


def check(answers: dict[str, dict[str, str]], synthesis: str, comment: str) -> list[str]:
    """Ce qui empêche d'enregistrer la fiche (liste vide : tout est en ordre)."""
    problems = []
    missing = [q for q in QUESTIONS if answers.get(q.key, {}).get("level") not in ORDER]
    if missing:
        problems.append(f"{len(missing)} critère(s) sans niveau de risque.")
    if synthesis not in ORDER:
        problems.append("Choisissez le niveau de la synthèse.")
        return problems
    if ORDER[synthesis] < ORDER[floor(answers)]:
        problems.append(
            "Synthèse : un critère décisif (PPE, gel des fonds, pays à haut risque) est élevé, "
            "la synthèse doit être élevée."
        )
    elif not missing and ORDER[synthesis] < ORDER[evaluate(answers)[1]] and not comment.strip():
        problems.append(
            "Synthèse plus basse que le critère le plus élevé : expliquez pourquoi dans la "
            "motivation."
        )
    return problems


def save(
    client: Client,
    answers: dict[str, dict[str, str]],
    *,
    user: User | None,
    synthesis: str | None = None,
    comment: str = "",
) -> RiskAssessment:
    """Enregistre la fiche (modèle 5.1 + synthèse 5.2), fabrique son PDF et le range."""
    from . import services

    # Ce que l'outil avait vérifié est gardé avec la fiche : le PDF refait plus tard (validation
    # de l'AMLCO) montre les mêmes éléments.
    reasons = {p.question.key: p.reason for p in propose(client) if p.answer is not None}
    clean = {
        q.key: {
            "level": answers[q.key]["level"],
            "comment": str(answers[q.key].get("comment", "")).strip()[:500],
            "reason": reasons.get(q.key, ""),
        }
        for q in QUESTIONS
        if answers.get(q.key, {}).get("level") in ORDER
    }
    score, proposed = evaluate(clean)
    level = synthesis or proposed
    problems = check(clean, level, comment)
    if problems:
        raise Incomplete(" ".join(problems))
    today = timezone.localdate()
    with transaction.atomic():
        assessment = RiskAssessment.objects.create(
            client=client, answers=clean, score=score, level=level,
            next_review=next_review(level, today), comment=comment.strip()[:2000],
            created_by=user,
        )  # fmt: skip
        if user is not None and level == HIGH and user.has_capability("aml.decide"):
            assessment.approved_at, assessment.approved_by = timezone.now(), user
            assessment.save(update_fields=["approved_at", "approved_by"])
        content = _pdf(assessment)
        upload = SimpleUploadedFile("fiche-risque.pdf", content, content_type="application/pdf")
        document = services.store(
            client, upload, title=f"Fiche de risque — {assessment.get_level_display()} "
            f"({today:%d/%m/%Y})", case="fiche-risque", doc_type="fiche_risque",
            expires_on=assessment.next_review, user=user,
        )  # fmt: skip
        if assessment.awaiting_approval:
            document.review_needed = True
            document.review_reason = "Risque élevé : validation de l'AMLCO requise"
            document.save(update_fields=["review_needed", "review_reason"])
        assessment.document = document
        assessment.save(update_fields=["document"])
    events.emit(
        "risk.assessed", subject=client, actor=user,
        payload={"niveau": level, "points": score},
    )  # fmt: skip
    return assessment


def approve(assessment: RiskAssessment, user: User) -> None:
    """Signature de la fiche par l'AMLCO : obligatoire pour un risque élevé, possible pour
    tous les niveaux (D-103)."""
    if not user.has_capability("aml.decide"):
        raise PermissionError("Réservé à l'AMLCO.")
    assessment.approved_at, assessment.approved_by = timezone.now(), user
    assessment.save(update_fields=["approved_at", "approved_by"])
    if assessment.document is not None:
        # Le PDF est refait : il porte maintenant la validation de l'AMLCO (modèle ITAA 5.2).
        import hashlib

        from django.core.files.base import ContentFile

        document = assessment.document
        content = _pdf(assessment)
        old = document.file.name
        document.file.save("fiche-risque.pdf", ContentFile(content), save=False)
        document.size, document.sha256 = len(content), hashlib.sha256(content).hexdigest()
        document.review_needed, document.review_reason = False, ""
        document.save(update_fields=["file", "size", "sha256", "review_needed", "review_reason"])
        if old and old != document.file.name:
            document.file.storage.delete(old)  # pas de copie oubliée de l'ancienne version
    events.emit(
        "risk.approved", subject=assessment.client, actor=user,
        payload={"evaluation": assessment.pk},
    )  # fmt: skip
