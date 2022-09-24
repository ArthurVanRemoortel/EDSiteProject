# Generated by Django 4.0.6 on 2022-09-24 10:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('EDSite', '0016_delete_securitystate'),
    ]

    operations = [
        migrations.AddField(
            model_name='system',
            name='security',
            field=models.PositiveSmallIntegerField(choices=[(1, 'Lockdown'), (2, 'Civil Unrest'), (3, 'None'), (4, 'Civil Liberty')], null=True),
        ),
    ]
