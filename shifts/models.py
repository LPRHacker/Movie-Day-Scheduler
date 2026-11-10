from django.db import models
from django.contrib.auth.models import User

class Person(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)
    
    def __str__(self):
        return self.name

class Movie(models.Model):
    title = models.CharField(max_length=200)
    imdb_id = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    duration_minutes = models.PositiveIntegerField(default=120)
    poster_url = models.URLField(blank=True, null=True)
    trailer_url = models.URLField(blank=True, null=True)
    # Page on the cinema site for this movie (used to enrich poster/trailer)
    page_url = models.URLField(blank=True, null=True)
    # Whether enrichment (poster/trailer lookup) has already been attempted
    meta_checked = models.BooleanField(default=False)
    
    def __str__(self):
        return self.title

class Cinema(models.Model):
    name = models.CharField(max_length=100)
    location_id = models.CharField(max_length=50, blank=True, null=True)
    url = models.URLField(blank=True, null=True)

    def __str__(self):
        return self.name

class Hall(models.Model):
    """A screening room inside a cinema ("Hall 3", "אולם 2 VIP", ...)."""

    REGULAR = 'regular'
    VIP = 'vip'
    PREMIUM = 'premium'
    THREE_D = '3d'
    XD = 'xd'

    HALL_TYPES = (
        (REGULAR, 'Regular'),
        (VIP, 'VIP'),
        (PREMIUM, 'Premium'),
        (THREE_D, '3D'),
        (XD, 'XD (more than 3D)'),
    )

    # Feeds that only expose screening formats (MovieLand, Hot Cinema) file their
    # screenings under a hall named after the format itself. Such a hall carries
    # no room information, so it is not offered as a hall to pick from.
    GENERIC_NAMES = frozenset(
        label.strip().lower() for _, label in HALL_TYPES
    ) | {'atmos'}

    cinema = models.ForeignKey(Cinema, on_delete=models.CASCADE, related_name='halls')
    name = models.CharField(max_length=50)
    hall_type = models.CharField(max_length=20, choices=HALL_TYPES, default=REGULAR)

    class Meta:
        unique_together = ('cinema', 'name')
        ordering = ('cinema__name', 'name')

    @property
    def is_generic(self):
        """True for a format-named hall ("VIP", "3D") rather than a real room."""
        return self.name.strip().lower() in self.GENERIC_NAMES

    def __str__(self):
        return f"{self.cinema.name} · {self.name} ({self.get_hall_type_display()})"

class Showtime(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    cinema = models.ForeignKey(Cinema, on_delete=models.CASCADE)
    hall = models.ForeignKey(Hall, on_delete=models.SET_NULL, null=True, blank=True, related_name='showtimes')
    datetime = models.DateTimeField()

    def __str__(self):
        hall = f" [{self.hall.name}]" if self.hall else ""
        return f"{self.movie.title} at {self.cinema.name}{hall} on {self.datetime}"

class Preference(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('person', 'movie')

    def __str__(self):
        return f"{self.person.name} wants to see {self.movie.title}"
