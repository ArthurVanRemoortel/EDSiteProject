# Generated by Django 4.0.6 on 2022-09-24 12:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('EDSite', '0018_securitystate'),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemSecurity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(choices=[(1, 'Low'), (2, 'Medium'), (3, 'High'), (4, 'Anarchy'), (5, 'Lawless')], max_length=100)),
            ],
        ),
    ]
