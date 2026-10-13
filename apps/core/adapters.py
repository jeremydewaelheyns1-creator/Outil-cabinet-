from allauth.account.adapter import DefaultAccountAdapter
from django.http import HttpRequest


class AccountAdapter(DefaultAccountAdapter):
    """Pas d'inscription libre : les comptes sont créés par un administrateur."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return False
