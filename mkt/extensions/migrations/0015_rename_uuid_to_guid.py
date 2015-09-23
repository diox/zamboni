# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('extensions', '0014_change_uuid_to_charfield'),
    ]

    operations = [
        migrations.RenameField(
            model_name='extension',
            old_name='uuid',
            new_name='guid',
        ),
    ]
