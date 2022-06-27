# Generated by Django 2.0.7 on 2018-09-12 20:32

import coderedcms.blocks.base_blocks
import coderedcms.fields
from django.db import migrations, models
import wagtail.contrib.table_block.blocks
import wagtail.blocks
import wagtail.fields
import wagtail.documents.blocks
import wagtail.images.blocks
import wagtail.snippets.blocks


class Migration(migrations.Migration):

    dependencies = [
        ('coderedcms', '0002_auto_20180829_1538'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReusableContent',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Name')),
                ('content', coderedcms.fields.CoderedStreamField([], blank=True, verbose_name='content')),
            ],
            options={
                'verbose_name': 'Reusable Content',
                'verbose_name_plural': 'Reusable Content',
            },
        ),
        migrations.AlterField(
            model_name='contentwall',
            name='content',
            field=coderedcms.fields.CoderedStreamField([], blank=True, verbose_name='Content'),
        ),
        migrations.AlterField(
            model_name='footer',
            name='content',
            field=coderedcms.fields.CoderedStreamField([], blank=True, verbose_name='Content'),
        ),
    ]
