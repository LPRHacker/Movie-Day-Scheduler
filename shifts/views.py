from django.shortcuts import render
from django.views import View
from django.utils.dateparse import parse_date
import datetime
import json
from .models import Cinema, Preference, Person, Showtime, Movie
from .algorithm import generate_schedule
from django.utils import timezone
from django.http import JsonResponse, HttpResponse

class HomeView(View):
    def get(self, request, *args, **kwargs):
        context = {
            'cinemas': Cinema.objects.all().order_by('name'),
            'current_date': datetime.date.today().isoformat()
        }
        return render(request, "home.html", context)

    def post(self, request, *args, **kwargs):
        target_date_str = request.POST.get('date')
        cinema_ids_raw = request.POST.get('cinemas', '') 
        cinema_ids = [c for c in cinema_ids_raw.split(',') if c] if cinema_ids_raw else []
        
        allow_overlap = request.POST.get('allow_overlap') == 'on'
        overlap_scaler = int(request.POST.get('overlap_scaler', 30))
        active_p_name = request.POST.get('active_participant_hidden', '')
        pref_ids_raw = request.POST.get('preferences', '{}')
        participants_raw = request.POST.get('selected_participants', '[]')
        breaks_raw = request.POST.get('breaks', '{}')
        transits_raw = request.POST.get('transits', '{}')
        
        try:
            pref_ids = json.loads(pref_ids_raw) if pref_ids_raw else {}
        except:
            pref_ids = {}
            
        try:
            participant_names = json.loads(participants_raw) if participants_raw else []
        except:
            participant_names = []

        try:
            person_breaks = json.loads(breaks_raw) if breaks_raw else {}
        except:
            person_breaks = {}

        try:
            transit_times = json.loads(transits_raw) if transits_raw else {}
        except:
            transit_times = {}

        target_date = parse_date(target_date_str) if target_date_str else datetime.date.today()
        print(f"DEBUG POST: cinemas={cinema_ids}, date={target_date}")

        persons = []
        if participant_names:
            persons = list(Person.objects.filter(name__in=participant_names))
            existing_names = [p.name for p in persons]
            for name in participant_names:
                if name not in existing_names:
                    persons.append(Person(name=name))
            
            cinemas = list(Cinema.objects.filter(id__in=cinema_ids))
            
            schedule = generate_schedule(
                persons=persons, 
                target_date=target_date, 
                cinemas=cinemas,
                allow_overlap=allow_overlap,
                max_overlap_minutes=overlap_scaler,
                movie_ids=pref_ids,
                breaks=person_breaks,
                transit_times=transit_times
            )
        else:
            schedule = None

        # Post-process for visualization
        day_start = datetime.datetime.combine(target_date, datetime.time(10, 0))
        day_end = datetime.datetime.combine(target_date, datetime.time(23, 59))
        day_duration_mins = (day_end - day_start).total_seconds() / 60

        from .scrapers import trailer_search_url

        def process_path(path, trailer_map):
            processed = []
            for slot in path:
                st_time = slot['time']
                if isinstance(st_time, str): st_time = datetime.datetime.fromisoformat(st_time)
                # Make naive for comparison
                st_time = st_time.replace(tzinfo=None) if st_time.tzinfo else st_time
                offset_mins = (st_time - day_start).total_seconds() / 60
                offset_pct = max(0, min(100, (offset_mins / day_duration_mins) * 100))
                width_pct = max(1, min(100, (slot['duration'] / day_duration_mins) * 100))
                
                new_slot = slot.copy()
                new_slot['offset_pct'] = offset_pct
                new_slot['width_pct'] = width_pct
                # Attach trailer link (fallback: trailer search)
                if new_slot.get('type') == 'movie' and not new_slot.get('trailer'):
                    title = new_slot.get('movie', '')
                    new_slot['trailer'] = trailer_map.get(title) or trailer_search_url(title)
                processed.append(new_slot)
            return processed

        if schedule and 'person_paths' in schedule:
            # Build title -> trailer map for timeline nodes
            trailer_by_title = {}
            titles = set()
            for path in schedule['person_paths'].values():
                for slot in path:
                    if slot.get('type') == 'movie':
                        titles.add(slot.get('movie'))
            for m in Movie.objects.filter(title__in=titles):
                trailer_by_title[m.title] = m.trailer_url or trailer_search_url(m.title)

            new_paths = {}
            for person, path in schedule['person_paths'].items():
                new_paths[person] = process_path(path, trailer_by_title)
            schedule['person_paths'] = new_paths

        # Use a dictionary or more careful filtering to keep name and id
        selected_objs = []
        for cid in cinema_ids:
            if cid == 'external':
                selected_objs.append({'id': 'external', 'name': 'External Cinema'})
            else:
                c = Cinema.objects.filter(id=cid).first()
                if c:
                    selected_objs.append({'id': str(c.id), 'name': c.name})

        context = {
            'cinemas': Cinema.objects.all().order_by('name'),
            'current_date': target_date_str,
            'selected_cinemas_json': json.dumps(selected_objs),
            'participant_names': participant_names,
            'preferences_json': json.dumps(pref_ids),
            'breaks_json': json.dumps(person_breaks),
            'transits_json': json.dumps(transit_times),
            'allow_overlap': allow_overlap,
            'overlap_scaler': overlap_scaler,
            'active_p_name': active_p_name,
            'schedule': schedule
        }
        return render(request, "home.html", context)

class GetShowtimesView(View):
    def get(self, request):
        from .scrapers import get_scraper, trailer_search_url
        cinema_ids_raw = request.GET.get('cinema', '')
        date_str = request.GET.get('date', '')
        debug = request.GET.get('debug') == 'true'
        
        if not cinema_ids_raw or not date_str:
            return JsonResponse({'error': 'Missing parameters'}, status=400)
            
        cinema_ids = [cid.strip() for cid in cinema_ids_raw.split(',') if cid.strip()]
        target_date = parse_date(date_str) or datetime.date.today()
        
        results = []
        for cid in cinema_ids:
            if cid == 'external':
                cinema = Cinema.objects.filter(name="External Cinema").first()
            else:
                try:
                    cinema = Cinema.objects.get(id=cid)
                except:
                    continue
            
            if not cinema: continue

            tz = timezone.get_current_timezone()
            day_start = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(0, 0)), tz)
            day_end = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(23, 59, 59)), tz)
            
            showtimes = list(Showtime.objects.filter(cinema=cinema, datetime__range=(day_start, day_end)).select_related('movie'))
            
            if not showtimes and not debug:
                scraper = get_scraper(cinema)
                if scraper:
                    try:
                        scraper.fetch_and_save(cinema, target_date)
                        showtimes = list(Showtime.objects.filter(cinema=cinema, datetime__range=(day_start, day_end)).select_related('movie'))
                    except: pass
            
            if not showtimes and debug:
                # Mock data for this cinema
                mock_titles = ["Dune: Part Two", "The Batman", "Kung Fu Panda 4", "Moana 2", "Gladiator II", "Wicked"]
                for i, title in enumerate(mock_titles):
                    results.append({
                        'movie_id': 1000 + int(cid if cid.isdigit() else 999) + i,
                        'movie_title': f"{title} (Mock)",
                        'datetime': timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(12+i, 0))).isoformat(),
                        'duration': 120,
                        'cinema': cinema.name,
                        'poster': "",
                        'trailer': trailer_search_url(title)
                    })
            else:
                for st in showtimes:
                    trailer = st.movie.trailer_url or trailer_search_url(st.movie.title)
                    results.append({
                        'movie_id': st.movie.id,
                        'movie_title': st.movie.title,
                        'datetime': st.datetime.isoformat(),
                        'duration': st.movie.duration_minutes,
                        'cinema': st.cinema.name,
                        'poster': st.movie.poster_url or "",
                        'trailer': trailer
                    })

        return JsonResponse({'showtimes': results})


class MovieMetaView(View):
    """Lazily enrich a movie's poster/trailer metadata (no API keys)."""
    def get(self, request):
        from .movie_meta import enrich_movie
        movie_id = request.GET.get('id')
        if not movie_id:
            return JsonResponse({'error': 'Missing movie id'}, status=400)
        try:
            movie = Movie.objects.get(id=movie_id)
        except Movie.DoesNotExist:
            return JsonResponse({'error': 'Movie not found'}, status=404)
        poster, trailer = enrich_movie(movie)
        return JsonResponse({
            'movie_id': movie.id,
            'movie_title': movie.title,
            'poster': poster or "",
            'trailer': trailer or ""
        })

# Stubs for other views
def onduty_current_week(request): return HttpResponse("Stub")
def onduty_next_week(request): return HttpResponse("Stub")
def onduty_previous_week(request): return HttpResponse("Stub")
def reset(request): return HttpResponse("Stub")
def switch_shifts(request): return HttpResponse("Stub")
def change_password(request): from django.http import HttpResponseRedirect; return HttpResponseRedirect('/admin/password_change/')
def trigger_scraper(request): return HttpResponse("Stub")

class ListShowsView(View):
    def get(self, request):
        from .scrapers import trailer_search_url
        from collections import OrderedDict

        date_str = request.GET.get('date', '')
        target_date = parse_date(date_str) if date_str else datetime.date.today()
        cinema_id = request.GET.get('cinema')

        cinemas = list(Cinema.objects.all().order_by('name'))
        selected = None
        if cinema_id:
            selected = Cinema.objects.filter(id=cinema_id).first()
        if not selected and cinemas:
            selected = cinemas[0]

        grouped_shows = OrderedDict()
        if selected:
            tz = timezone.get_current_timezone()
            day_start = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(0, 0)), tz)
            day_end = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(23, 59, 59)), tz)
            showtimes = list(Showtime.objects.filter(
                cinema=selected, datetime__range=(day_start, day_end)
            ).select_related('movie').order_by('movie__title', 'datetime'))

            for st in showtimes:
                movie = st.movie
                if movie.title not in grouped_shows:
                    grouped_shows[movie.title] = {
                        'title': movie.title,
                        'poster': movie.poster_url or "",
                        'trailer': movie.trailer_url or trailer_search_url(movie.title),
                        'duration': movie.duration_minutes,
                        'times': []
                    }
                grouped_shows[movie.title]['times'].append(st.datetime)

        context = {
            'cinemas': cinemas,
            'selected_cinema': selected,
            'target_date': target_date,
            'grouped_shows': grouped_shows
        }
        return render(request, "list_shows.html", context)

class UploadCinemaFileView(View):
    def post(self, request):
        return JsonResponse({'error': 'Not implemented in this view'}, status=501)
