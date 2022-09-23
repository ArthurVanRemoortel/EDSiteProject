from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

try:
    from EDSite import models
except ImproperlyConfigured:
    import django
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EDSiteProject.settings")
    django.setup()
    from EDSite import models


def createSuperpowers():
    if models.Superpower.objects.count() == len(models.Superpowers):
        print("SEEDER: Superpowers already seeded.")
        return
    with transaction.atomic():
        for integer, name in models.Superpowers.choices:
            obj, created = models.Superpower.objects.get_or_create(id=integer, name=name)
            if created:
                print(f"Seeded {obj}")


def createGovernments():
    if models.Government.objects.count() == len(models.Governments):
        print("SEEDER: Governments already seeded.")
        return
    with transaction.atomic():
        for integer, name in models.Governments.choices:
            obj, created = models.Government.objects.get_or_create(id=integer, name=name)
            if created:
                print(f"Seeded {obj}")


def createStates():
    if models.State.objects.count() == len(models.States):
        print("SEEDER: States already seeded.")
        return
    with transaction.atomic():
        for integer, name in models.States.choices:
            obj, created = models.State.objects.get_or_create(id=integer, name=name)
            if created:
                print(f"Seeded {obj}")
