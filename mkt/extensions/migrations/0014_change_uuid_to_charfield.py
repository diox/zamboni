# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('extensions', '0013_add_disabled_field_alter_status_and_last_updated'),
    ]

    operations = [
        migrations.AlterField(
            model_name='extension',
            name='uuid',
            field=models.CharField(unique=True, max_length=255, editable=False),
            preserve_default=True,
        ),
    ]
