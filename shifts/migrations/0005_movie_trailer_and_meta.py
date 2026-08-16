from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shifts', '0004_movie_poster_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='movie',
            name='trailer_url',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='movie',
            name='page_url',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='movie',
            name='meta_checked',
            field=models.BooleanField(default=False),
        ),
    ]
