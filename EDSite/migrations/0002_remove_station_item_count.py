# Generated by Django 4.0.6 on 2022-09-17 12:11

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("EDSite", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="station",
            name="item_count",
        ),
    ]
