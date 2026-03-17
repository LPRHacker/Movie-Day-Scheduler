from django.urls import path
from . import views

app_name = 'shifts'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('api/showtimes/', views.GetShowtimesView.as_view(), name='get_showtimes'),
    path('onduty/current/', views.onduty_current_week, name='onduty_current'),
    path('onduty/next/', views.onduty_next_week, name='onduty_next'),
    path('onduty/previous/', views.onduty_previous_week, name='onduty_previous'),
    path('reset/', views.reset, name='reset'),
    path('switch/', views.switch_shifts, name='switch_shifts'),
    path('password_change/', views.change_password, name='change_password'),
    path('scrape/', views.trigger_scraper, name='trigger_scraper'),
    path('list-shows/', views.ListShowsView.as_view(), name='list_shows'),
]
