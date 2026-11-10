from django.contrib import admin
from .models import Person, Movie, Cinema, Hall, Showtime, Preference

@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('name', 'user')

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ('title', 'imdb_id')
    search_fields = ('title',)

@admin.register(Cinema)
class CinemaAdmin(admin.ModelAdmin):
    list_display = ('name', 'url')

@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ('name', 'cinema', 'hall_type')
    list_filter = ('cinema', 'hall_type')
    search_fields = ('name', 'cinema__name')

@admin.register(Showtime)
class ShowtimeAdmin(admin.ModelAdmin):
    list_display = ('movie', 'cinema', 'hall', 'datetime')
    list_filter = ('cinema', 'hall', 'movie', 'datetime')

@admin.register(Preference)
class PreferenceAdmin(admin.ModelAdmin):
    list_display = ('person', 'movie')
    list_filter = ('person', 'movie')
