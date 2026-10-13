from typing import Any, ClassVar, cast

from django import forms

from apps.clients.forms import DateInput
from apps.core.models import User

from .models import Task


class ManualTaskForm(forms.ModelForm[Task]):
    class Meta:
        model = Task
        fields: ClassVar = ["title", "due_date", "category", "assignee", "notes"]
        widgets: ClassVar = {
            "due_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        assignee = cast("forms.ModelChoiceField[User]", self.fields["assignee"])
        assignee.queryset = User.objects.filter(is_active=True)
        self.fields["title"].widget.attrs["placeholder"] = "Ex. : Rappeler le client pour le bilan"
