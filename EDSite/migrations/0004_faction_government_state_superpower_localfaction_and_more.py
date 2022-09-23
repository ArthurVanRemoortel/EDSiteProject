# Generated by Django 4.0.6 on 2022-09-22 13:23

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('EDSite', '0003_alter_livelisting_station_tradedangerous_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='Faction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('is_player', models.BooleanField()),
            ],
        ),
        migrations.CreateModel(
            name='Government',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(choices=[('1', 'Anarchy'), ('2', 'Communism'), ('3', 'Confederacy'), ('4', 'Cooperative'), ('5', 'Corporate'), ('6', 'Democracy'), ('7', 'Dictatorship'), ('8', 'Feudal'), ('9', 'Patronage'), ('10', 'Prison Colony'), ('11', 'Theocracy')], max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='State',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(choices=[('1', 'Incursion'), ('2', 'Infested'), ('3', 'Blight'), ('4', 'Drought'), ('5', 'Outbreak'), ('6', 'infrastructure Failure'), ('7', 'Natural Disaster'), ('8', 'Revolution'), ('9', 'Cold War'), ('10', 'Trade War'), ('11', 'Pirate Attack'), ('12', 'Terrorist Attack'), ('13', 'Public Holiday'), ('14', 'Technological Leap'), ('15', 'Historic Event'), ('16', 'Colonisation'), ('17', 'War'), ('18', 'Civil War'), ('19', 'Elections'), ('20', 'Retreat'), ('21', 'Expansion')], max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='Superpower',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(choices=[('1', 'Empire'), ('2', 'Independent'), ('3', 'Alliance'), ('4', 'Federation')], max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='LocalFaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('happiness', models.PositiveSmallIntegerField(choices=[(1, 'Despondent'), (2, 'Unhappy'), (3, 'Discontented'), (4, 'Happy'), (5, 'Elated')])),
                ('influence', models.FloatField()),
                ('last_update', models.DateTimeField(null=True)),
                ('faction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='states', to='EDSite.faction')),
                ('pending_states', models.ManyToManyField(related_name='pending_factions', to='EDSite.state')),
                ('recovering_states', models.ManyToManyField(related_name='recovering_factions', to='EDSite.state')),
                ('states', models.ManyToManyField(related_name='factions', to='EDSite.state')),
                ('system', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='faction_states', to='EDSite.system')),
            ],
        ),
        migrations.AddField(
            model_name='faction',
            name='allegiance',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='factions', to='EDSite.superpower'),
        ),
        migrations.AddField(
            model_name='faction',
            name='government',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='factions', to='EDSite.government'),
        ),
        migrations.AddField(
            model_name='system',
            name='controlling_faction',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='controls', to='EDSite.faction'),
        ),
    ]