# -*- coding: utf-8 -*-
# Generated by Django 1.9.2 on 2017-08-10 16:44
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('symposion_speakers', '0002_speaker_twitter_username'),
    ]

    operations = [
        migrations.CreateModel(
            name='DefaultSpeaker',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('_twitter_username', models.CharField(blank=True, help_text='Your Twitter account', max_length=15)),
            ],
        ),
        migrations.RenameModel(
            old_name='Speaker',
            new_name='SpeakerBase',
        ),
        migrations.AddField(
            model_name='defaultspeaker',
            name='speakerbase_ptr',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='symposion_speakers.SpeakerBase'),
        ),
    ]
