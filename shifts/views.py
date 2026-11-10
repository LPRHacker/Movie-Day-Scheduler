from django.shortcuts import render
from django.views import View
from django.utils.dateparse import parse_date
import datetime
import json
from .models import Cinema, Hall, Preference, Person, Showtime, Movie
from .algorithm import generate_schedule
from django.utils import timezone
from django.db.models import Q
from django.http import JsonResponse, HttpResponse

def _clean_person_criteria(raw, valid_types):
    """{person: {'halls': [ids], 'types': [keys]}} from the posted JSON.

    An empty list means "no restriction" for that person (every type is
    selected), so it is kept and the algorithm treats it as "all".
    """
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}

    cleaned = {}
    for name, criteria in data.items():
        if not isinstance(criteria, dict):
            continue
        own = {}
        if 'halls' in criteria and isinstance(criteria['halls'], list):
            own['halls'] = [int(h) for h in criteria['halls'] if str(h).isdigit()]
        if 'types' in criteria and isinstance(criteria['types'], list):
            types = [t for t in criteria['types'] if t in valid_types]
            if len(types) == len(valid_types):
                types = []
            own['types'] = types
        if own:
            cleaned[name] = own
    return cleaned


def _clean_person_transits(raw):
    """{person: {'cinemaA-cinemaB': minutes}} from the posted JSON."""
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}

    cleaned = {}
    for name, times in data.items():
        if not isinstance(times, dict):
            continue
        own = {}
        for key, minutes in times.items():
            try:
                own[str(key)] = int(minutes)
            except (TypeError, ValueError):
                continue
        if own:
            cleaned[name] = own
    return cleaned


class HomeView(View):
    def get(self, request, *args, **kwargs):
        context = {
            'cinemas': Cinema.objects.all().order_by('name'),
            'current_date': datetime.date.today().isoformat(),
            'hall_types': list(Hall.HALL_TYPES),
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
        halls_raw = request.POST.get('halls', '')
        types_raw = request.POST.get('types', '')
        availability_raw = request.POST.get('availability', '{}')
        person_criteria_raw = request.POST.get('person_criteria', '{}')
        person_transits_raw = request.POST.get('person_transits', '{}')
        
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

        selected_halls = [h.strip() for h in halls_raw.split(',') if h.strip()]
        # Only real Hall rows can reach the database query; mock ids are ignored.
        hall_ids = [int(h) for h in selected_halls if h.isdigit()]
        valid_types = {key for key, _ in Hall.HALL_TYPES}
        selected_types = [t.strip() for t in types_raw.split(',') if t.strip() in valid_types]
        if len(selected_types) == len(valid_types):
            selected_types = []

        try:
            availability = json.loads(availability_raw) if availability_raw else {}
        except:
            availability = {}

        # Per-person criteria and travel times: each person may narrow (or widen)
        # the group-wide halls/types and set their own transit for themselves.
        person_criteria = _clean_person_criteria(person_criteria_raw, valid_types)
        person_transits = _clean_person_transits(person_transits_raw)

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
                transit_times=transit_times,
                availability=availability,
                hall_ids=hall_ids,
                hall_types=selected_types,
                person_criteria=person_criteria,
                person_transits=person_transits
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
                # Compare in local wall-clock time: the timeline is built from a
                # naive 10:00 day start, while DB datetimes come back as UTC.
                if timezone.is_aware(st_time):
                    st_time = timezone.localtime(st_time)
                st_time = st_time.replace(tzinfo=None)
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
            'halls_json': json.dumps(selected_halls),
            'types_json': json.dumps(selected_types),
            'person_criteria_json': json.dumps(person_criteria),
            'person_transits_json': json.dumps(person_transits),
            'hall_types': list(Hall.HALL_TYPES),
            'availability_json': json.dumps(availability),
            'allow_overlap': allow_overlap,
            'overlap_scaler': overlap_scaler,
            'active_p_name': active_p_name,
            'schedule': schedule
        }
        return render(request, "home.html", context)

# Synthetic halls used by the mock (debug) feed so the hall filter can be tried
# without scraping a real cinema.
MOCK_HALLS = (
    ('Hall 1', Hall.REGULAR),
    ('Hall 2', Hall.REGULAR),
    ('VIP Hall', Hall.VIP),
    ('Premium Hall', Hall.PREMIUM),
    ('Hall 5 · 3D', Hall.THREE_D),
    ('XD Hall', Hall.XD),
)


class GetShowtimesView(View):
    def get(self, request):
        from .scrapers import get_scraper, trailer_search_url
        cinema_ids_raw = request.GET.get('cinema', '')
        date_str = request.GET.get('date', '')
        debug = request.GET.get('debug') == 'true'
        halls_raw = request.GET.get('halls', '')
        types_raw = request.GET.get('types', '')
        
        if not cinema_ids_raw or not date_str:
            return JsonResponse({'error': 'Missing parameters'}, status=400)
            
        cinema_ids = [cid.strip() for cid in cinema_ids_raw.split(',') if cid.strip()]
        target_date = parse_date(date_str) or datetime.date.today()

        # Hall filter: mock halls use "mock-..." ids, real ones are digits.
        selected_halls = {h.strip() for h in halls_raw.split(',') if h.strip()}
        hall_ids = [int(h) for h in selected_halls if h.isdigit()]

        # Hall type criterion, applied on top of (and independently of) halls.
        # A screening without a recorded hall counts as regular.
        valid_types = {key for key, _ in Hall.HALL_TYPES}
        selected_types = {t.strip() for t in types_raw.split(',') if t.strip() in valid_types}
        if selected_types == valid_types:
            selected_types = set()

        results = []
        halls_result = []
        known_hall_ids = set()

        def add_hall(hall_id, name, hall_type, cinema_name):
            hall_id = str(hall_id)
            if hall_id in known_hall_ids:
                return
            known_hall_ids.add(hall_id)
            halls_result.append({
                'id': hall_id,
                'name': name,
                'type': hall_type,
                'type_label': dict(Hall.HALL_TYPES).get(hall_type, hall_type),
                'cinema': cinema_name,
            })

        for cid in cinema_ids:
            if cid == 'external':
                cinema = Cinema.objects.filter(name="External Cinema").first()
            else:
                try:
                    cinema = Cinema.objects.get(id=cid)
                except:
                    continue
            
            if not cinema: continue

            # Every real hall of the cinema is always listed, whatever the
            # current criteria match, so the filter itself never disappears.
            # Format-named halls ("VIP", "3D") are not rooms and stay out of it.
            for hall in Hall.objects.filter(cinema=cinema).order_by('name'):
                if hall.is_generic:
                    continue
                add_hall(hall.id, hall.name, hall.hall_type, cinema.name)

            tz = timezone.get_current_timezone()
            day_start = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(0, 0)), tz)
            day_end = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(23, 59, 59)), tz)

            day_showtimes = Showtime.objects.filter(cinema=cinema, datetime__range=(day_start, day_end))
            
            # Scrape only when the day really has no data at all, so a hall
            # filter that matches nothing does not trigger a re-scrape.
            if not day_showtimes.exists() and not debug:
                scraper = get_scraper(cinema)
                if scraper:
                    try:
                        scraper.fetch_and_save(cinema, target_date)
                        for hall in Hall.objects.filter(cinema=cinema).order_by('name'):
                            add_hall(hall.id, hall.name, hall.hall_type, cinema.name)
                    except: pass

            showtime_qs = day_showtimes
            if hall_ids:
                showtime_qs = showtime_qs.filter(hall_id__in=hall_ids)
            if selected_types:
                type_q = Q(hall__hall_type__in=selected_types)
                if Hall.REGULAR in selected_types:
                    # Screenings without a recorded hall are regular by default.
                    type_q |= Q(hall__isnull=True)
                showtime_qs = showtime_qs.filter(type_q)
            showtimes = list(showtime_qs.select_related('movie', 'hall'))
            
            if not showtimes and debug:
                # Mock data for this cinema
                mock_titles = ["Dune: Part Two", "The Batman", "Kung Fu Panda 4", "Moana 2", "Gladiator II", "Wicked"]
                for i, title in enumerate(mock_titles):
                    hall_name, hall_type = MOCK_HALLS[i % len(MOCK_HALLS)]
                    mock_hall_id = f"mock-{cid}-{i % len(MOCK_HALLS)}"
                    add_hall(mock_hall_id, hall_name, hall_type, cinema.name)
                    if selected_halls and mock_hall_id not in selected_halls:
                        continue
                    if selected_types and hall_type not in selected_types:
                        continue
                    results.append({
                        'movie_id': 1000 + int(cid if cid.isdigit() else 999) + i,
                        'movie_title': f"{title} (Mock)",
                        'datetime': timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(12+i, 0))).isoformat(),
                        'duration': 120,
                        'cinema': cinema.name,
                        'poster': "",
                        'trailer': trailer_search_url(title),
                        'hall_id': mock_hall_id,
                        'hall_name': hall_name,
                        'hall_type': hall_type,
                        'hall_type_label': dict(Hall.HALL_TYPES).get(hall_type, hall_type),
                    })
            else:
                for st in showtimes:
                    trailer = st.movie.trailer_url or trailer_search_url(st.movie.title)
                    hall = st.hall
                    # A format-named hall already says the type, so don't repeat it.
                    type_label = '' if (hall and hall.is_generic) else (
                        hall.get_hall_type_display() if hall else '')
                    results.append({
                        'movie_id': st.movie.id,
                        'movie_title': st.movie.title,
                        'datetime': st.datetime.isoformat(),
                        'duration': st.movie.duration_minutes,
                        'cinema': st.cinema.name,
                        'poster': st.movie.poster_url or "",
                        'trailer': trailer,
                        'hall_id': str(hall.id) if hall else '',
                        'hall_name': hall.name if hall else '',
                        'hall_type': hall.hall_type if hall else '',
                        'hall_type_label': type_label,
                    })

        return JsonResponse({'showtimes': results, 'halls': halls_result})


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
        hall_id = request.GET.get('hall', '')
        hall_type = request.GET.get('type', '')

        cinemas = list(Cinema.objects.all().order_by('name'))
        selected = None
        if cinema_id:
            selected = Cinema.objects.filter(id=cinema_id).first()
        if not selected and cinemas:
            selected = cinemas[0]

        # Format-named halls ("VIP", "3D") are not rooms, so they are not
        # offered as a hall filter; the hall type dropdown covers them.
        halls = [h for h in Hall.objects.filter(cinema=selected).order_by('name')
                 if not h.is_generic] if selected else []
        if hall_id and not any(str(h.id) == hall_id for h in halls):
            hall_id = ''
        hall_type_labels = dict(Hall.HALL_TYPES)
        if hall_type not in hall_type_labels:
            hall_type = ''

        grouped_shows = OrderedDict()
        if selected:
            tz = timezone.get_current_timezone()
            day_start = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(0, 0)), tz)
            day_end = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(23, 59, 59)), tz)
            showtime_qs = Showtime.objects.filter(cinema=selected, datetime__range=(day_start, day_end))
            if hall_id:
                showtime_qs = showtime_qs.filter(hall_id=hall_id)
            if hall_type:
                type_q = Q(hall__hall_type=hall_type)
                if hall_type == Hall.REGULAR:
                    type_q |= Q(hall__isnull=True)
                showtime_qs = showtime_qs.filter(type_q)
            showtimes = showtime_qs.select_related('movie', 'hall').order_by('movie__title', 'datetime')

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
                grouped_shows[movie.title]['times'].append({
                    'time': st.datetime,
                    'hall': st.hall.name if st.hall else '',
                    'hall_type': ('' if (not st.hall or st.hall.is_generic)
                                  else st.hall.get_hall_type_display()),
                })

        context = {
            'cinemas': cinemas,
            'selected_cinema': selected,
            'selected_hall_id': hall_id,
            'selected_hall_type': hall_type,
            'hall_type_labels': hall_type_labels,
            'halls': halls,
            'target_date': target_date,
            'grouped_shows': grouped_shows
        }
        return render(request, "list_shows.html", context)

class UploadCinemaFileView(View):
    def post(self, request):
        return JsonResponse({'error': 'Not implemented in this view'}, status=501)
