from __future__ import annotations

from typing import Any, ClassVar, cast

from django import forms

from apps.clients.models import Client
from apps.core.models import User

from .models import TimeEntry


class TimeEntryForm(forms.ModelForm[TimeEntry]):
    class Meta:
        model = TimeEntry
        fields: ClassVar = ["day", "start", "end", "client", "activity", "description"]
        widgets: ClassVar = {
            "day": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "start": forms.TimeInput(attrs={"type": "time", "step": 300}, format="%H:%M"),
            "end": forms.TimeInput(attrs={"type": "time", "step": 300}, format="%H:%M"),
            "description": forms.TextInput(
                attrs={"placeholder": "Ex. : encodage des achats de septembre"}
            ),
        }

    def __init__(self, *args: Any, user: User, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        field = cast("forms.ModelChoiceField[Client]", self.fields["client"])
        visible = Client.objects.visible_to(user)
        current = self.instance.client_id
        visible = visible.exclude(status=Client.Status.FORMER) | visible.filter(pk=current or 0)
        field.queryset = visible.order_by("name", "first_name")
        field.empty_label = "— Sans dossier (interne, formation…) —"
        field.widget.attrs["data-searchable"] = ""  # liste « à taper » (static/js/app.js)
        field.label_from_instance = lambda c: (  # type: ignore[method-assign,assignment]
            f"{c.display_name}{f' · {c.reference}' if c.reference else ''}"
        )
        self.instance.user = user
