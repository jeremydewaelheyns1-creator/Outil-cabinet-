"""Formulaires de la fiche client."""

from __future__ import annotations

from typing import Any, ClassVar, cast

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import EmailValidator, URLValidator

from apps.core.capabilities import Capability
from apps.core.models import Portfolio, User

from .identifiers import normalize_enterprise_number, normalize_national_number
from .models import Assignment, Client, ContactPoint, Relation


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(format="%Y-%m-%d", **kwargs)


class ClientForm(forms.ModelForm[Client]):
    # Saisie libre (« BE 0123.456.789 ») : normalisée en 10 chiffres à la validation.
    enterprise_number = forms.CharField(
        label="Numéro d'entreprise",
        required=False,
        max_length=20,
        help_text="Avec ou sans BE, points ou espaces.",
    )
    new_national_number = forms.CharField(
        label="Numéro national",
        required=False,
        max_length=20,
        help_text="Laisser vide pour conserver le numéro enregistré.",
    )

    class Meta:
        model = Client
        fields: ClassVar = [
            "kind",
            "status",
            "portfolio",
            "name",
            "first_name",
            "legal_form",
            "language",
            "enterprise_number",
            "reference",
            "birth_date",
            "nationality",
            "street",
            "house_number",
            "box",
            "postal_code",
            "city",
            "country",
            "vat_status",
            "vat_periodicity",
            "fiscal_year_end_month",
            "fiscal_year_end_day",
            "client_since",
            "client_until",
            "contact_title",
            "contact_name",
            "notes",
        ]
        widgets: ClassVar = {
            "birth_date": DateInput(),
            "client_since": DateInput(),
            "client_until": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args: Any, user: User, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        portfolio_field = cast("forms.ModelChoiceField[Portfolio]", self.fields["portfolio"])
        portfolio_field.queryset = Portfolio.objects.visible_to(user)
        portfolio_field.empty_label = None
        if not user.has_capability(Capability.CLIENTS_SENSITIVE):
            del self.fields["new_national_number"]
        elif self.instance.national_number:
            self.fields["new_national_number"].widget.attrs["placeholder"] = (
                self.instance.national_number_masked
            )
        self.fields["enterprise_number"].widget.attrs["placeholder"] = "0123.456.789"

    def clean_enterprise_number(self) -> str | None:
        return normalize_enterprise_number(self.cleaned_data.get("enterprise_number")) or None

    def clean_new_national_number(self) -> str:
        number = normalize_national_number(self.cleaned_data.get("new_national_number"))
        if (
            number
            and Client.objects.exclude(pk=self.instance.pk).filter(national_number=number).exists()
        ):
            raise ValidationError("Ce numéro national est déjà attribué à une autre fiche.")
        return number

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if data.get("new_national_number"):
            self.instance.national_number = data["new_national_number"]
        return data

    def _update_errors(self, errors: ValidationError) -> None:
        # Les erreurs du modèle sur le numéro national s'affichent sur le champ du formulaire.
        error_dict = getattr(errors, "error_dict", None)
        if error_dict and "national_number" in error_dict:
            target = (
                "new_national_number" if "new_national_number" in self.fields else NON_FIELD_ERRORS
            )
            error_dict.setdefault(target, []).extend(error_dict.pop("national_number"))
        super()._update_errors(errors)  # type: ignore[misc]  # API interne de ModelForm


class ContactPointForm(forms.ModelForm[ContactPoint]):
    class Meta:
        model = ContactPoint
        fields: ClassVar = ["kind", "value", "label", "is_primary"]

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        kind, value = data.get("kind"), (data.get("value") or "").strip()
        if kind == ContactPoint.Kind.EMAIL and value:
            EmailValidator(message="Adresse e-mail invalide.")(value)
            data["value"] = value.lower()
        elif kind == ContactPoint.Kind.WEBSITE and value:
            if "://" not in value:
                value = f"https://{value}"
            URLValidator(message="Adresse web invalide.", schemes=["http", "https"])(value)
            data["value"] = value
        client_id = self.instance.client_id
        if client_id and kind and data.get("value"):
            duplicate = ContactPoint.objects.filter(
                client_id=client_id, kind=kind, value=data["value"]
            ).exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise ValidationError("Cette coordonnée est déjà enregistrée.")
        return data


class RelationForm(forms.ModelForm[Relation]):
    other = forms.ModelChoiceField(
        queryset=Client.objects.none(),
        label="Personne ou société",
        error_messages={"required": "Choisissez une fiche dans la liste."},
    )

    class Meta:
        model = Relation
        fields: ClassVar = [
            "role",
            "share_percentage",
            "voting_percentage",
            "start_date",
            "end_date",
            "notes",
        ]
        widgets: ClassVar = {"start_date": DateInput(), "end_date": DateInput()}

    def __init__(
        self, *args: Any, client: Client, as_person: bool, user: User, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.client = client
        self.as_person = as_person
        other = cast("forms.ModelChoiceField[Client]", self.fields["other"])
        other.queryset = Client.objects.visible_to(user).exclude(pk=client.pk)
        if as_person:
            other.label = "Société ou association"
        if self.instance.pk:
            other.initial = self.instance.entity if as_person else self.instance.person

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        other = data.get("other")
        if other is not None:
            if self.as_person:
                self.instance.person, self.instance.entity = self.client, other
            else:
                self.instance.entity, self.instance.person = self.client, other
        return data


class AssignmentForm(forms.Form):
    """Une liste déroulante par rôle : le collaborateur affecté au client."""

    def __init__(self, *args: Any, client: Client, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.client = client
        current = {a.role: a.user_id for a in client.assignments.all()}
        users = User.objects.filter(is_active=True)
        for role, label in Assignment.Role.choices:
            self.fields[role] = forms.ModelChoiceField(
                queryset=users, required=False, label=label, initial=current.get(role)
            )

    def save(self) -> None:
        for role, _label in Assignment.Role.choices:
            user = self.cleaned_data.get(role)
            if user is None:
                for assignment in Assignment.objects.filter(client=self.client, role=role):
                    assignment.delete()
            else:
                Assignment.objects.update_or_create(
                    client=self.client, role=role, defaults={"user": user}
                )
