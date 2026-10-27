"""Fiche de détermination du niveau de risque, guidée (D-049).

Base : loi du 18 septembre 2017 (art. 19 et annexes I à III), norme ITAA anti-blanchiment
(points 3.5, 4.1, 4.2, 4.7 à 4.9). L'outil **propose** une réponse à chaque question à partir
de ce qu'il sait (fiche, BCE, structure de détention, documents) et dit pourquoi ; le
gestionnaire valide ou corrige. Puis :
- points → niveau faible / moyen / élevé ; certains facteurs imposent « élevé » (PPE, pays à
  haut risque, actionnaires apparents) ;
- prochaine révision selon le niveau (`RISK_REVIEW_YEARS`) → la fiche expire à cette date et
  l'outil la signale à l'avance, comme les autres documents ;
- risque élevé : la fiche attend la validation de l'AMLCO (capacité « aml.decide »).

Les listes (secteurs sensibles, pays) sont des points de départ à valider par l'AMLCO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.clients.models import Client
from apps.core import events
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


# Les 4 critères du formulaire de synthèse de l'ITAA (modèle 5.2) — D-076.
CRITERIA: tuple[tuple[str, str], ...] = (
    ("client", "Client"),
    ("activite", "Activité / secteur"),
    ("geographie", "Géographique"),
    ("mission", "Nature de la mission"),
)


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    help: str
    points: int
    forces_high: bool = False
    criterion: str = "client"

    @property
    def criterion_label(self) -> str:
        return dict(CRITERIA)[self.criterion]


QUESTIONS: tuple[Question, ...] = (
    Question("pep", "Une personne politiquement exposée (PPE) est-elle concernée ?",
             "Dirigeant, bénéficiaire effectif ou client lui-même, ou un proche (art. 41).", 3,
             forces_high=True),
    Question("high_risk_country", "Lien avec un pays à haut risque (listes GAFI / UE) ?",
             "Siège, résidence, activité ou flux financiers.", 3, forces_high=True,
             criterion="geographie"),
    Question("nominee", "Actionnaires apparents (prête-noms) ou titres au porteur ?",
             "Annexe III, 1, c).", 3, forces_high=True),
    Question("foreign", "Client ou structure établie hors de l'Union européenne ?",
             "Siège ou résidence hors UE/EEE.", 2, criterion="geographie"),
    Question("complex_structure", "Structure de propriété inhabituelle ou complexe ?",
             "Plusieurs niveaux de sociétés, sociétés étrangères, bénéficiaires non résolus.", 2),
    Question("sensitive_sector", "Activité dans un secteur sensible ?",
             "Construction, horeca, véhicules, immobilier, bijouterie, jeux… (analyses CTIF).", 2,
             criterion="activite"),
    Question("cash", "Activité utilisant beaucoup d'espèces ?", "Annexe III, 1, d).", 2,
             criterion="activite"),
    Question("distance", "Relation à distance, sans rencontre ni signature électronique ?",
             "Annexe III, 2, c).", 1, criterion="mission"),
    Question("new_client", "Client depuis moins d'un an ?", "Relation encore peu connue.", 1),
    Question("risky_mission", "Mission à risque (domiciliation, constitution de sociétés, "
             "gestion de fonds de tiers) ?", "Services particulièrement exposés.", 2,
             criterion="mission"),
    Question("unusual", "Circonstances inhabituelles ou paiements de tiers inconnus ?",
             "Annexe III, 1, a) et 2, e).", 3),
)  # fmt: skip
BY_KEY = {q.key: q for q in QUESTIONS}
THRESHOLDS = ((6, RiskAssessment.Level.HIGH), (3, RiskAssessment.Level.MEDIUM))


@dataclass(frozen=True)
class Proposal:
    question: Question
    answer: bool | None  # None : l'outil ne sait pas, à répondre
    reason: str


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


def _structure(client: Client) -> tuple[bool | None, str]:
    if client.is_person:
        return False, "Personne physique."
    from apps.clients.services import ubo

    analysis = ubo.analyse(client)
    depth = max((len(h.chain) for c in analysis.candidates for h in c.holdings), default=0)
    foreign = [
        p for c in analysis.candidates for h in c.holdings for p in h.chain
        if (getattr(p, "country", "") or "BE") != "BE"
    ]  # fmt: skip
    if analysis.unresolved_entities:
        return True, "Des sociétés actionnaires n'ont pas de bénéficiaire identifié."
    if depth > 2 or foreign:
        return True, "Détention à plusieurs niveaux" + (" via l'étranger." if foreign else ".")
    if not analysis.candidates:
        return None, "Actionnariat inconnu dans l'outil : à vérifier."
    return False, "Détention simple et connue."


def _declared_pep(client: Client) -> tuple[bool, str] | None:
    """Réponse PEP reprise de la dernière déclaration UBO signée en ligne (D-071)."""
    from .signing import latest_answers

    found = latest_answers(client)
    if found is None:
        return None
    when = f"{timezone.localtime(found.signed_at):%d/%m/%Y}"
    peps = [a.get("name", "") for a in found.answers.values() if a.get("pep")]
    if peps:
        return True, f"Déclaré par le client le {when} (déclaration UBO) : {', '.join(peps)}."
    return False, (
        f"Aucune selon la déclaration UBO signée le {when}. Vérifier aussi les bases PPE."
    )


def propose(client: Client, today: date | None = None) -> list[Proposal]:
    """Une réponse proposée par question, avec la raison (None = à répondre)."""
    today = today or timezone.localdate()
    country = (client.country or "BE").upper()
    sector, sector_reason = _sector(client)
    structure, structure_reason = _structure(client)
    previous = client.risk_assessments.first()
    answers: dict[str, tuple[bool | None, str]] = {
        "pep": (None, "À vérifier (déclaration du client, bases de données PPE)."),
        "high_risk_country": (
            (True, f"Pays de la fiche : {HIGH_RISK_COUNTRIES[country]}.")
            if country in HIGH_RISK_COUNTRIES
            else (None, f"Pays de la fiche : {country}. Vérifier aussi les flux financiers.")
        ),
        "nominee": (None, "À vérifier."),
        "foreign": ((country not in EU_EEA, f"Pays de la fiche : {country}.")),
        "complex_structure": (structure, structure_reason),
        "sensitive_sector": (sector, sector_reason),
        "cash": (
            sector,
            "Proposé d'après le secteur : à confirmer." if sector is not None else "À vérifier.",
        ),
        "distance": (None, "À vérifier."),
        "new_client": (
            (
                client.client_since > today - timedelta(days=365),
                f"Client depuis le {client.client_since:%d/%m/%Y}.",
            )
            if client.client_since
            else (None, "Date de début de relation inconnue.")
        ),
        "risky_mission": (None, "Selon la lettre de mission."),
        "unusual": (None, "Selon votre connaissance du dossier."),
    }
    declared = _declared_pep(client)
    if declared is not None:
        answers["pep"] = declared
    if previous is not None:
        for key, value in (previous.answers or {}).items():
            current = answers.get(key)
            if key in BY_KEY and current is not None and current[0] is None:
                answers[key] = (bool(value), "Réponse de la fiche précédente.")
    return [Proposal(q, *answers[q.key]) for q in QUESTIONS]


ORDER: dict[str, int] = {
    RiskAssessment.Level.LOW: 0,
    RiskAssessment.Level.MEDIUM: 1,
    RiskAssessment.Level.HIGH: 2,
}


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    level: str
    motivation: str


def criteria(answers: dict[str, bool]) -> list[Criterion]:
    """Niveau et motivation par critère du modèle ITAA 5.2 : élevé si un facteur décisif,
    standard si un autre facteur, faible sinon."""
    result = []
    for key, label in CRITERIA:
        found = [q for q in QUESTIONS if q.criterion == key and answers.get(q.key)]
        if any(q.forces_high for q in found):
            level = RiskAssessment.Level.HIGH
        elif found:
            level = RiskAssessment.Level.MEDIUM
        else:
            level = RiskAssessment.Level.LOW
        motivation = " ; ".join(q.text.rstrip(" ?") for q in found) or "Aucun facteur relevé."
        result.append(Criterion(key, label, level, motivation))
    return result


def evaluate(answers: dict[str, bool]) -> tuple[int, str]:
    """Points (indicatifs) et synthèse : le niveau le plus haut des 4 critères, relevé d'un cran
    si les facteurs s'accumulent (6 points ou plus)."""
    score = sum(q.points for q in QUESTIONS if answers.get(q.key))
    level = max((c.level for c in criteria(answers)), key=ORDER.__getitem__)
    for threshold, minimum in THRESHOLDS:
        if score >= threshold and ORDER[minimum] > ORDER[level]:
            level = minimum
    return score, level


def next_review(level: str, today: date) -> date:
    years = int(settings.RISK_REVIEW_YEARS.get(level, 1))
    try:
        return today.replace(year=today.year + years)
    except ValueError:  # 29 février
        return today.replace(year=today.year + years, day=28)


def _pdf(assessment: RiskAssessment, proposals: list[Proposal]) -> bytes:
    from weasyprint import HTML

    html = render_to_string(
        "documents/modeles/fiche_risque.html",
        {
            "cabinet": settings.CABINET_NAME,
            "client": assessment.client,
            "today": timezone.localdate(),
            "doc_label": "Fiche de détermination du niveau de risque",
            "assessment": assessment,
            "rows": [
                (p.question, assessment.answers.get(p.question.key), p.reason) for p in proposals
            ],
            "criteria": criteria(assessment.answers),
            "levels": RiskAssessment.Level.choices,
            "author": assessment.created_by,
        },
    )
    return bytes(HTML(string=html).write_pdf())


def save(
    client: Client, answers: dict[str, bool], *, user: User | None, comment: str = ""
) -> RiskAssessment:
    """Enregistre la fiche, fabrique son PDF et le range (l'ancienne part aux archives)."""
    from . import services

    proposals = propose(client)
    today = timezone.localdate()
    clean = {q.key: bool(answers.get(q.key)) for q in QUESTIONS}
    score, level = evaluate(clean)
    with transaction.atomic():
        assessment = RiskAssessment.objects.create(
            client=client, answers=clean, score=score, level=level,
            next_review=next_review(level, today), comment=comment.strip()[:2000],
            created_by=user,
        )  # fmt: skip
        if (
            user is not None
            and level == RiskAssessment.Level.HIGH
            and user.has_capability("aml.decide")
        ):
            assessment.approved_at, assessment.approved_by = timezone.now(), user
            assessment.save(update_fields=["approved_at", "approved_by"])
        content = _pdf(assessment, proposals)
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
    """Validation d'un risque élevé par l'AMLCO."""
    if not user.has_capability("aml.decide"):
        raise PermissionError("Réservé à l'AMLCO.")
    assessment.approved_at, assessment.approved_by = timezone.now(), user
    assessment.save(update_fields=["approved_at", "approved_by"])
    if assessment.document is not None:
        # Le PDF est refait : il porte maintenant la validation de l'AMLCO (modèle ITAA 5.2).
        import hashlib

        from django.core.files.base import ContentFile

        document = assessment.document
        content = _pdf(assessment, propose(assessment.client))
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
