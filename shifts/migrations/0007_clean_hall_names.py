import re

from django.db import migrations

# Feeds sometimes glue the screening format onto the hall name
# ("אולם 17(Lounge)"). Hall types are tracked separately, so existing halls are
# renamed to their plain name/number, merging duplicates.
FORMAT_SUFFIX = re.compile(
    r'\s*[\(\[]\s*(?:lounge|prime|premium|vip|xd|imax|3d|screenx|סינמקס|cinemax)\s*[\)\]]\s*$',
    re.IGNORECASE,
)


def clean_hall_names(apps, schema_editor):
    Hall = apps.get_model('shifts', 'Hall')
    Showtime = apps.get_model('shifts', 'Showtime')

    for hall in Hall.objects.all():
        cleaned = FORMAT_SUFFIX.sub('', hall.name).strip()
        if not cleaned or cleaned == hall.name:
            continue
        existing = Hall.objects.filter(cinema_id=hall.cinema_id, name=cleaned).first()
        if existing is None:
            hall.name = cleaned
            hall.save(update_fields=['name'])
        else:
            Showtime.objects.filter(hall=hall).update(hall=existing)
            hall.delete()


def restore_hall_names(apps, schema_editor):
    # Renaming is not reversible without the original feed values.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('shifts', '0006_hall_showtime_hall'),
    ]

    operations = [
        migrations.RunPython(clean_hall_names, restore_hall_names),
    ]
