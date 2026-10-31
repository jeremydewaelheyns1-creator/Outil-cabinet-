"""Banc d'essai de la lecture des modèles (D-132) : des documents entièrement inventés, de styles
différents, avec les bonnes réponses. Chaque document passe par la vraie chaîne du dépôt
(assistant IA puis garde-fous), le modèle obtenu est rempli pour un client « témoin », et on
vérifie, ligne par ligne, que chaque élément a reçu la bonne chose, que le texte du cabinet
n'a pas bougé et qu'il ne reste rien du client d'origine.

Aucune donnée réelle : noms, numéros et montants sont inventés. Lancé par
`manage.py banc_ia` (et par GitHub sur la branche `ia-banc`, avec la vraie IA).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from apps.core.text import normalize_text

# --- Documents fictifs ------------------------------------------------------------------------


def _docx(lines: list[Any]) -> bytes:
    """Une ligne de texte = un paragraphe ; une liste de listes = un tableau."""
    from docx import Document as Word

    document = Word()
    for line in lines:
        if isinstance(line, list):
            table = document.add_table(rows=0, cols=len(line[0]))
            for row in line:
                cells = table.add_row().cells
                for cell, text in zip(cells, row, strict=True):
                    cell.text = text
        else:
            document.add_paragraph(line)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


@dataclass
class Case:
    name: str
    kind: str
    content: bytes
    # (ancre : texte du cabinet qui reste sur la ligne — « ^ » : l'en-tête —, codes acceptés,
    # mots de l'intitulé)
    expect: list[tuple[str, tuple[str, ...], str]]
    keep: list[str]  # texte du cabinet qui ne doit pas bouger
    gone: list[str]  # données du client d'origine qui ne doivent plus être là


ASK = "demander"
NAME = ("client.denomination",)
ADDRESS = ("client.adresse", "client.siege")
PLACE = ("client.localite", "client.siege", "client.ville")
LEADER = ("client.representant", "client.dirigeants")


def cases() -> list[Case]:
    found = []
    # 1. PV rempli, mise en page d'un cabinet belge : en-tête, tableaux « libellé | (+) | montant ».
    found.append(Case(
        "PV rempli avec tableaux", "pv_ag",
        _docx([
            "Agence Essai Immo SRL", "Rue du Modèle 8", "1410 Waterloo",
            "R.P.M. 0987.654.394", "T.V.A. : N.A.",
            "PROCÈS-VERBAL DE L'ASSEMBLÉE GÉNÉRALE ORDINAIRE DES ASSOCIÉS",
            "L'an 2026 le 30/09/2026, s'est tenue au siège social l'assemblée générale ordinaire.",
            "La séance est ouverte à 18h00 sous la présidence de Julie Exemplaire.",
            "Sont présents les associés suivants :", "1. Julie Exemplaire (100 %)",
            "b) Examen et approbation des comptes annuels arrêtés au 31/03/2026 ;",
            "Résolution 2 :",
            "L'assemblée approuve les Comptes Annuels arrêtés au 31/03/2026 :",
            [["- Bénéfice d'exploitation", "(+)", "€", "100.000,00"],
             ["- Produits financiers", "(+)", "", "50.000,00"],
             ["- Charges financières", "(-)", "", "25.000,00"],
             ["- Impôts sur le résultat", "(-)", "", "25.000,00"],
             ["- Bénéfice net de l'exercice à affecter", "", "€", "100.000,00"]],
            "Résolution 3 :",
            "L'assemblée décide de reporter l'intégralité du bénéfice de l'exercice, "
            "soit 100.000,00.",
            "Résolution 5 :", "Les émoluments de l'Administrateur se décomposent comme suit :",
            [["- Rémunération ordinaire", "€", "20.000,00"], ["- ATN Télécom.", "", "1.000,00"],
             ["- ATN Cotisations sociales", "", "1.000,00"], ["- ATN PLCI", "", "1.000,00"],
             ["- ATN Auto", "", "1.000,00"], ["- Remboursement frais dirigeant", "", "500,00"],
             ["- Emoluments de l'exercice", "€", "24.500,00"]],
            "Résolution 6 :",
            "L'AGO confirme le mandat donné à la Fiduciaire Témoin & Associés SRL pour déposer les "
            "comptes annuels à la BNB.",
            "La séance est levée à 18h30 après lecture et approbation du présent procès-verbal.",
            "Julie Exemplaire", "Administrateur", "Fait à Waterloo", "Le 30/09/2026",
        ]),
        [("^", NAME, ""), ("^", ADDRESS, ""), ("^", PLACE, ""),
         ("R.P.M.", ("client.numero",), ""), ("L'an", ("ag.annee", "ag.date"), ""),
         ("ouverte à", ("ag.debut",), ""), ("présidence", LEADER, ""),
         ("Examen et approbation", ("exercice.cloture",), ""),
         ("Bénéfice d'exploitation", (ASK,), "exploitation"),
         ("Produits financiers", (ASK,), "produits financiers"),
         ("Charges financières", (ASK,), "charges financieres"),
         ("Impôts sur le résultat", (ASK,), "impots"),
         ("à affecter", (ASK,), "affecter"), ("intégralité", (ASK,), ""),
         ("Rémunération ordinaire", (ASK,), "remuneration ordinaire"),
         ("ATN Télécom", (ASK,), "telecom"), ("ATN Cotisations", (ASK,), "cotisations"),
         ("ATN PLCI", (ASK,), "plci"), ("ATN Auto", (ASK,), "auto"),
         ("Remboursement frais", (ASK,), "remboursement"),
         ("Emoluments de l'exercice", (ASK,), "emoluments"),
         ("levée à", ("ag.fin",), ""), ("Fait à", PLACE, "")],
        ["ATN Télécom.", "ATN Auto", "Administrateur", "Fiduciaire Témoin & Associés SRL",
         "Résolution 3 :", "Bénéfice d'exploitation", "T.V.A. : N.A."],
        ["Agence Essai Immo", "Julie Exemplaire", "Rue du Modèle 8", "0987.654.394",
         "100.000,00", "24.500,00", "Waterloo"],
    ))  # fmt: skip
    # 2. Modèle vide d'un autre cabinet, avec ses propres repères et des « XXX ».
    found.append(Case(
        "PV vide avec repères", "pv_ag",
        _docx([
            "[DENOMINATION SOCIALE]", "Société à responsabilité limitée",
            "au capital de [MONTANT DU CAPITAL SOCIAL] euros",
            "Siège social : [ADRESSE SIEGE SOCIAL]", "R.P.M. [TRIBUNAL COMPETENT]",
            "PROCÈS-VERBAL DE L'ASSEMBLÉE GÉNÉRALE DU [DATE]",
            "Le [DATE], à [HEURE], les associés de la société [DENOMINATION SOCIALE] se sont "
            "réunis en assemblée générale, [LIEU DE REUNION], sur convocation du "
            "[NOM ET PRENOM DU DIRIGEANT].",
            "Sont présents :", "XXX, titulaire de XXX parts sociales",
            "L'assemblée est présidée par [NOM ET PRENOM DU DIRIGEANT].",
            "Ordre du jour : [OBJET DE LA MODIFICATION].",
            "L'assemblée décide de [OBJET DE LA MODIFICATION].",
            "Cette résolution est adoptée à l'unanimité.",
            "La séance est levée à [HEURE DE FIN].",
        ]),
        [("au capital", (ASK,), "capital"), ("Siège social", ADDRESS, ""),
         ("R.P.M.", (ASK,), "tribunal"), ("GÉNÉRALE DU", ("ag.date",), ""),
         ("se sont", ("ag.date", "ag.debut", ASK, "client.denomination"), ""),
         ("présidée", LEADER, ""), ("Ordre du jour", (ASK,), "objet"),
         ("décide de", (ASK,), "objet"), ("levée à", ("ag.fin",), "")],
        ["Cette résolution est adoptée à l'unanimité.", "Ordre du jour", "Sont présents :"],
        [],
    ))  # fmt: skip
    # 3. PV rédigé en phrases, sans tableau : parts, dates en lettres, dividende.
    found.append(Case(
        "PV en phrases avec dividende", "pv_ag",
        _docx([
            "BRASSERIE IMAGINAIRE", "S.R.L.", "Chaussée de Namur 120 boîte 3",
            "5030 Gembloux", "Numéro d'entreprise : 0876.543.219",
            "Procès-verbal de l'assemblée générale ordinaire du 15 juin 2026",
            "L'an deux mille vingt-six, le quinze juin, à dix-huit heures, s'est réunie "
            "l'assemblée générale ordinaire des associés.",
            "Sont présents : Monsieur Marc Essaiun, titulaire de 60 parts, et Madame Claire "
            "Essaideux, titulaire de 40 parts.",
            "La séance est présidée par Monsieur Marc Essaiun, gérant.",
            "L'assemblée approuve les comptes annuels clôturés le 31 décembre 2025, qui font "
            "apparaître un bénéfice à affecter de 85.250,00 €.",
            "L'assemblée décide de distribuer un dividende brut de 30.000,00 € et de reporter "
            "le solde, soit 55.250,00 €.",
            "Par vote spécial, décharge est donnée au gérant.",
            "La séance est levée à dix-huit heures trente.",
            "Marc Essaiun, gérant              Claire Essaideux, associée",
        ]),
        [("^", NAME, ""), ("^", ADDRESS, ""), ("^", PLACE, ""),
         ("Numéro d'entreprise", ("client.numero",), ""),
         ("ordinaire du", ("ag.date", "ag.date_longue"), ""),
         ("présidée", LEADER, ""), ("clôturés le", ("exercice.cloture",), ""),
         ("bénéfice à affecter", (ASK,), "affecter"), ("dividende brut", (ASK,), "dividende"),
         ("s'est réunie", ("ag.date", "ag.date_longue", "ag.annee", "ag.debut"), ""),
         ("Sont présents", ("client.associes", ASK, "client.representant"), "")],
        ["Par vote spécial, décharge est donnée au gérant.", "dividende brut"],
        ["BRASSERIE IMAGINAIRE", "Marc Essaiun", "Claire Essaideux", "0876.543.219",
         "85.250,00", "Gembloux"],
    ))  # fmt: skip
    # 4. Lettre de mission remplie pour un client.
    found.append(Case(
        "Lettre de mission remplie", "lettre",
        _docx([
            "LETTRE DE MISSION",
            "Entre la Fiduciaire Témoin & Associés SRL, représentée par son associé, d'une part,",
            "et la société Menuiserie Fictive SRL, dont le siège social est situé Rue des Essais "
            "11, 5000 Namur, inscrite à la Banque-Carrefour des Entreprises sous le numéro "
            "0765.432.108, représentée par Monsieur Paul Essaitrois, d'autre part.",
            "La présente mission prend cours à partir de l'exercice 2026.",
            "Les honoraires sont fixés à 2.400,00 EUR hors TVA par an, payables à 30 jours.",
            "Le cabinet conserve les documents pendant 7 ans.",
            "Fait à Namur, le 12/01/2026, en deux exemplaires.",
        ]),
        [("et la société", NAME + LEADER + ADDRESS + ("client.numero",), ""),
         ("prend cours", (ASK,), "exercice"), ("honoraires", (ASK,), "honoraires"),
         ("Fait à", (*PLACE, ASK, "date.jour"), "")],
        ["Fiduciaire Témoin & Associés SRL", "pendant 7 ans", "payables à 30 jours"],
        ["Menuiserie Fictive", "Paul Essaitrois", "0765.432.108", "2.400,00", "Rue des Essais"],
    ))  # fmt: skip
    # 5. Lettre de mission vide, trous « XXX » et pointillés.
    found.append(Case(
        "Lettre de mission vide", "lettre",
        _docx([
            "Lettre de mission",
            "Entre le cabinet, d'une part, et la société XXX, dont le siège est situé XXX, "
            "numéro d'entreprise XXX, représentée par XXX, d'autre part.",
            "Honoraires : …… EUR hors TVA par mois.",
            "Fait à ……, le ……",
        ]),
        [("Honoraires", (ASK,), "honoraires")],
        ["Entre le cabinet, d'une part"],
        [],
    ))  # fmt: skip
    # 6. Modèle vide « à la française » : lignes d'associés en XXX, article de statuts, signature.
    found.append(Case(
        "PV vide avec XXX", "pv_ag",
        _docx([
            "[DENOMINATION SOCIALE]", "Société par actions simplifiée",
            "au capital de [MONTANT DU CAPITAL SOCIAL] euros", "Siège social : [ADRESSE]",
            "PROCÈS-VERBAL DE L'ASSEMBLÉE GÉNÉRALE EXTRAORDINAIRE",
            "L'an deux mille vingt-trois, le [DATE], à [HEURE],",
            "Sont présents :", "XXX, titulaire de XXX droits sociaux",
            "XXX, titulaire de XXX droits sociaux",
            "L'Assemblée est présidée par Monsieur [NOM DU DIRIGEANT], en sa qualité de "
            "[GERANT / PRESIDENT].",
            "Les associés présents possèdent [XXX] droits sociaux sur les [XXX] composant le "
            "capital social.",
            "Première résolution",
            "L'Assemblée Générale décide de modifier les statuts comme suit :",
            "« ARTICLE XXX : XXX »",
            "Cette résolution est adoptée à l'unanimité.",
            "M. XXX", "Président de séance",
        ]),
        [("capital de", (ASK,), "capital"), ("Siège social", ADDRESS, ""),
         ("L'an", ("ag.annee", "ag.date"), ""), ("présidée", LEADER, ""),
         ("en sa qualité", (ASK,), "qualit|gerant|president"), ("possèdent", (ASK,), "droits"),
         ("ARTICLE", (ASK,), "article"), ("titulaire de", ("client.associes", ASK), ""),
         ("^M", (*LEADER, ASK), "")],
        ["Cette résolution est adoptée à l'unanimité.", "Président de séance",
         "Première résolution"],
        [],
    ))  # fmt: skip
    # 7. AGE de transfert de siège : l'ANCIENNE adresse est celle de la fiche, la NOUVELLE est à
    # demander (piège pour des règles qui voient une adresse partout).
    found.append(Case(
        "AGE transfert de siège", "pv_ag",
        _docx([
            "Garage Imaginaire SRL", "Rue Ancienne 4", "5000 Namur",
            "Procès-verbal de l'assemblée générale extraordinaire du 3 mars 2026",
            "La séance est ouverte à 10h00 sous la présidence de Madame Sophie Essaisix.",
            "L'assemblée décide de transférer le siège de la société de la Rue Ancienne 4, 5000 "
            "Namur, vers l'Avenue Nouvelle 77, 4000 Liège, à partir du 1er avril 2026.",
            "L'assemblée donne pouvoir à Madame Sophie Essaisix pour les formalités.",
            "La séance est levée à 10h30.",
        ]),
        [("^", NAME, ""), ("ouverte à", ("ag.debut",), ""), ("présidence", LEADER, ""),
         ("vers l", (ASK,), ""), ("donne pouvoir", LEADER, ""), ("levée à", ("ag.fin",), "")],
        ["L'assemblée décide de transférer le siège de la société",
         "donne pouvoir à", "pour les formalités"],
        ["Garage Imaginaire", "Sophie Essaisix", "Avenue Nouvelle 77", "Rue Ancienne 4"],
    ))  # fmt: skip
    # 8. Lettre de mission dont le client et les honoraires sont dans des tableaux.
    found.append(Case(
        "Lettre de mission en tableaux", "lettre",
        _docx([
            "CONVENTION DE MISSION",
            [["Client :", "Boucherie Essai SRL"], ["Siège :", "Place du Marché 2, 5500 Dinant"],
             ["Numéro d'entreprise :", "0654.321.097"], ["Représentée par :", "Luc Essaisept"]],
            "Le cabinet est chargé des missions suivantes, aux honoraires annuels indiqués :",
            [["Tenue de la comptabilité", "3.600,00 €"], ["Déclarations TVA", "900,00 €"],
             ["Comptes annuels et déclaration ISOC", "1.500,00 €"]],
            "Les honoraires sont indexés chaque année au 1er janvier.",
            "Fait à Dinant, le 2 février 2026.",
        ]),
        [("Client :", NAME, ""), ("Siège :", ADDRESS + PLACE, ""),
         ("Numéro d'entreprise", ("client.numero",), ""), ("Représentée", LEADER, ""),
         ("Tenue de la comptabilité", (ASK,), "comptabilit"),
         ("Déclarations TVA", (ASK,), "tva"), ("Comptes annuels", (ASK,), "comptes annuels")],
        ["Tenue de la comptabilité", "Déclarations TVA", "indexés chaque année"],
        ["Boucherie Essai", "Luc Essaisept", "0654.321.097", "3.600,00", "Place du Marché"],
    ))  # fmt: skip
    return found


# --- Client témoin et notation ------------------------------------------------------------------

WITNESS_CONTEXT = {
    "date": "DATEAG", "date_longue": "DATEAG", "annee": "ANNEEAG", "debut": "HEUREDEBUT",
    "fin": "HEUREFIN", "exercice_debut": "DEBUTEX", "exercice_fin": "CLOTUREEX",
    "dividende": "non", "dividende_montant": "", "autres": "",
}  # fmt: skip
TOKENS = {
    "client.denomination": "TEMOINSOC", "client.forme": "SRL", "client.numero": "0123.456.749",
    "client.siege": "Rue Témoin", "client.adresse": "Rue Témoin",
    "client.localite": "Témoinville", "client.ville": "Témoinville",
    "client.representant": "Jean Témoin", "client.dirigeants": "Jean Témoin",
    "client.associes": "Jean Témoin", "ag.date": "DATEAG", "ag.date_longue": "DATEAG",
    "ag.annee": "ANNEEAG", "ag.debut": "HEUREDEBUT", "ag.fin": "HEUREFIN",
    "exercice.debut": "DEBUTEX", "exercice.cloture": "CLOTUREEX",
}  # fmt: skip


def witness() -> Any:
    """Le client « témoin » (inventé) pour qui chaque modèle est rempli."""
    from apps.clients.models import Relation
    from apps.core.testing.factories import ClientFactory, PersonFactory

    company: Any = ClientFactory(  # type: ignore[no-untyped-call]
        name="TEMOINSOC",
        legal_form="SRL",
        street="Rue Témoin 1",
        postal_code="9999",
        city="Témoinville",
        enterprise_number="0123456749",
    )
    leader: Any = PersonFactory(name="Témoin", first_name="Jean")  # type: ignore[no-untyped-call]
    Relation.objects.create(entity=company, person=leader, role=Relation.Role.MANAGER)
    Relation.objects.create(entity=company, person=leader, role=Relation.Role.SHAREHOLDER,
                            share_percentage=100)  # fmt: skip
    return company


def _lines(content: bytes) -> list[str]:
    """Le document en lignes : un paragraphe, ou une ligne de tableau entière."""
    from apps.ai import model_reader

    return [re.sub(r"^P\d+(?: \[[^\]]*\])? ?: ", "", line) for _, line in
            model_reader.blocks(content)]  # fmt: skip


@dataclass
class Score:
    name: str
    ok: int = 0
    total: int = 0
    misses: list[str] = field(default_factory=list)
    read_by_ai: bool = False

    def check(self, passed: bool, what: str) -> None:
        self.total += 1
        if passed:
            self.ok += 1
        else:
            self.misses.append(what)


def run(use_ai: bool = True, user: Any = None) -> list[Score]:
    """Passe chaque document fictif dans la chaîne du dépôt et note le résultat."""
    from types import SimpleNamespace

    from apps.documents import from_example, letter

    company = witness()
    scores = []
    for case in cases():
        built = from_example.build(case.content, case.kind, None, user, use_ai=use_ai)
        template = SimpleNamespace(content=built.content, holes=built.holes, options={},
                                   kind=case.kind)  # fmt: skip
        answers = {
            key: f"⟦{label}⟧" for key, label in letter.questions(template)
            if key.startswith("trou:")
        }  # fmt: skip
        filled = letter.fill(template, company, answers, WITNESS_CONTEXT)
        model_text = "\n".join(_lines(built.content))
        lines = _lines(filled)
        score = Score(case.name, read_by_ai=built.read_by_ai)
        for anchor, codes, words in case.expect:
            # « ^ » : l'en-tête (les premières lignes, entièrement propres au client).
            if anchor == "^":
                line = "\n".join(lines[:6])
            elif anchor.startswith("^"):  # une ligne qui COMMENCE par ce texte
                line = next((x for x in lines if x.startswith(anchor[1:])), "")
            else:
                line = next((x for x in lines if anchor in x), "")
            if not line:
                score.check(False, f"ligne « {anchor} » introuvable après remplissage")
                continue
            passed = False
            for code in codes:
                if code == ASK:
                    asked = re.findall(r"⟦([^⟧]*)⟧", line)
                    options = [normalize_text(w) for w in words.split("|")]
                    passed = passed or any(o in normalize_text(a) for a in asked for o in options)
                elif TOKENS.get(code, "\0") in line:
                    passed = True
            what = " / ".join(codes) + (f" « {words} »" if words else "")
            score.check(passed, f"« {anchor} » → attendu {what} ; obtenu : {line[:140]}")
        for text in case.keep:
            score.check(text in "\n".join(lines), f"texte du cabinet modifié : « {text} »")
        for text in case.gone:
            score.check(text not in model_text, f"reste du client d'origine : « {text} »")
        scores.append(score)
    return scores


def report(scores: list[Score], label: str) -> str:
    ok = sum(s.ok for s in scores)
    total = sum(s.total for s in scores)
    lines = [f"# Banc d'essai — {label}", "",
             f"**Score : {ok}/{total} ({round(100 * ok / max(total, 1))} %)**", ""]  # fmt: skip
    for score in scores:
        how = "IA" if score.read_by_ai else "règles seules"
        lines.append(f"## {score.name} — {score.ok}/{score.total} ({how})")
        lines += [f"- {miss}" for miss in score.misses] or ["- tout est bon"]
        lines.append("")
    return "\n".join(lines)
