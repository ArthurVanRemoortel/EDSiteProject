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


def seedGeneric(model_cls, enum):
    if model_cls.objects.count() == len(enum):
        print(f"SEEDER: {model_cls.__name__} already seeded.")
        return
    with transaction.atomic():
        for integer, name in enum.choices:
            obj, created = model_cls.objects.get_or_create(
                id=integer, name=name
            )
            if created:
                print(f"Seeded {enum.__name__}: {obj}")


def seedAll():
    # seedGeneric(SecurityState, SecurityStates)
    seedGeneric(models.State, models.States)
