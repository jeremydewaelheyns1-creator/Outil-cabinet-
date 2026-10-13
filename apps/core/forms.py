"""Rendu des formulaires : chaque champ est enveloppé dans un bloc (libellé, erreurs, aide)."""

from django.forms.renderers import TemplatesSetting


class FormRenderer(TemplatesSetting):
    field_template_name = "components/field.html"
