def test_the_test_site_says_so_on_every_page(client, make_user, settings):
    from django.urls import reverse

    client.force_login(make_user())
    assert "Site d'essai" not in client.get(reverse("core:settings")).content.decode()
    settings.SITE_ESSAI = True
    assert (
        "Site d'essai — données fictives" in client.get(reverse("core:settings")).content.decode()
    )
