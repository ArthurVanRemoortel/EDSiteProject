# Generated by Django 4.0.6 on 2022-09-23 18:31

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('EDSite', '0008_faction_home_system_station_population_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='system',
            name='allegiance',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='systems', to='EDSite.superpower'),
        ),
        migrations.AddField(
            model_name='system',
            name='government',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='systems', to='EDSite.government'),
        ),
    ]
