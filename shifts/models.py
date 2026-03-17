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
    
    def __str__(self):
        return self.title

class Cinema(models.Model):
    name = models.CharField(max_length=100)
    url = models.URLField(blank=True, null=True)

    def __str__(self):
        return self.name

class Showtime(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    cinema = models.ForeignKey(Cinema, on_delete=models.CASCADE)
    datetime = models.DateTimeField()

    def __str__(self):
        return f"{self.movie.title} at {self.cinema.name} on {self.datetime}"

class Preference(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('person', 'movie')

    def __str__(self):
        return f"{self.person.name} wants to see {self.movie.title}"
