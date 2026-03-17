from django.shortcuts import render
from django.views import View
from django.utils.dateparse import parse_date
import datetime
from .models import Cinema, Preference, Person, Showtime, Movie
from .algorithm import generate_schedule

class HomeView(View):
    def get(self, request, *args, **kwargs):
        context = {
            'cinemas': Cinema.objects.all(),
            'preferences': Preference.objects.all(),
            'current_date': datetime.date.today().isoformat()
        }
        return render(request, "home.html", context)

    def post(self, request, *args, **kwargs):
        # Extract form data
        import json
        
        target_date_str = request.POST.get('date')
        cinema_id = request.POST.get('cinema')
        allow_overlap = request.POST.get('allow_overlap') == 'on'
        overlap_scaler = int(request.POST.get('overlap_scaler', 30))
        active_p_name = request.POST.get('active_participant_hidden', '')
        pref_ids_raw = request.POST.get('preferences', '{}')
        participants_raw = request.POST.get('selected_participants', '[]')
        
        try:
            pref_ids = json.loads(pref_ids_raw) if pref_ids_raw else {}
        except:
            pref_ids = {}
            
        try:
            participant_names = json.loads(participants_raw) if participants_raw else []
        except:
            participant_names = []
            
        print(f"DEBUG POST: active={active_p_name}, prefs_count={len(pref_ids)}, persons_count={len(participant_names)}")

        target_date = parse_date(target_date_str) if target_date_str else datetime.date.today()
        
        print(f"DEBUG POST: date={target_date_str}, cinema={cinema_id}, overlap={allow_overlap}, scaler={overlap_scaler}")
        print(f"DEBUG PREFS: {pref_ids}")
        print(f"DEBUG PERSONS: {participant_names}")
        
        # In a real scenario we'd extract users from preferences
        if participant_names:
            # Filter participants who were selected
            persons = list(Person.objects.filter(name__in=participant_names))
            # If some people aren't in DB, create/mock them for the algorithm
            existing_names = [p.name for p in persons]
            for name in participant_names:
                if name not in existing_names:
                    persons.append(Person(name=name))
            
            cinema = Cinema.objects.filter(id=cinema_id).first()
            
            # The algorithm now needs to know which movies were selected
            # For now we'll just filter showtimes by these movies in the algorithm
            # (I'll need to pass selected_movie_ids to generate_schedule or filter Showtime query)
        else:
            persons = []
            cinema = None
            
        # Call algorithm
        schedule = generate_schedule(
            persons=persons, 
            target_date=target_date, 
            cinema=cinema,
            allow_overlap=allow_overlap,
            max_overlap_minutes=overlap_scaler,
            movie_ids=pref_ids
        )
        
        # If no DB objects, populate with mock data for visuals
        if not persons:
            now = datetime.datetime.now()
            s1 = {
                "id": 1,
                "time": now.replace(hour=19, minute=0, second=0, microsecond=0),
                "end_time": now.replace(hour=21, minute=0, second=0, microsecond=0),
                "duration": 120,
                "movie": "Dune: Part Two",
                "attendees": ["Alice", "Bob"]
            }
            s2 = {
                "id": 2,
                "time": now.replace(hour=20, minute=30, second=0, microsecond=0),
                "end_time": now.replace(hour=22, minute=0, second=0, microsecond=0),
                "duration": 90,
                "movie": "Kung Fu Panda 4",
                "attendees": ["Charlie"]
            }
            s3 = {
                "id": 3,
                "time": now.replace(hour=21, minute=30, second=0, microsecond=0),
                "end_time": now.replace(hour=23, minute=30, second=0, microsecond=0),
                "duration": 120,
                "movie": "The Batman",
                "attendees": ["Alice", "Bob", "Charlie"]
            }
            schedule = {
                "slots": [s1, s2, s3],
                "person_paths": {
                    "Alice": [s1, s3],
                    "Bob": [s1, s3],
                    "Charlie": [s2, s3]
                }
            }

        # Post-process schedule for visualization (Tree Flow)
        # We'll normalize times between 10 AM and Midnight (14 hours)
        day_start = datetime.datetime.combine(target_date, datetime.time(10, 0))
        day_end = datetime.datetime.combine(target_date, datetime.time(23, 59))
        day_duration_mins = (day_end - day_start).total_seconds() / 60

        def process_path(path):
            processed = []
            for slot in path:
                # Ensure time is datetime
                st_time = slot['time']
                if isinstance(st_time, str):
                    st_time = datetime.datetime.fromisoformat(st_time)
                
                offset_mins = (st_time.replace(tzinfo=None) - day_start.replace(tzinfo=None)).total_seconds() / 60
                offset_pct = max(0, min(100, (offset_mins / day_duration_mins) * 100))
                width_pct = max(1, min(100, (slot['duration'] / day_duration_mins) * 100))
                
                new_slot = slot.copy()
                new_slot['offset_pct'] = offset_pct
                new_slot['width_pct'] = width_pct
                processed.append(new_slot)
            return processed

        if schedule and 'person_paths' in schedule:
            new_paths = {}
            for person, path in schedule['person_paths'].items():
                new_paths[person] = process_path(path)
            schedule['person_paths'] = new_paths

        context = {
            'cinemas': Cinema.objects.all(),
            'preferences': Preference.objects.all(),
            'persons': Person.objects.all(),
            'current_date': target_date_str,
            'participant_names': participant_names,
            'preferences_json': json.dumps(pref_ids),
            'allow_overlap': allow_overlap,
            'overlap_scaler': overlap_scaler,
            'active_p_name': active_p_name,
            'schedule': schedule
        }
        
        return render(request, "home.html", context)

class ListShowsView(View):
    def get(self, request, *args, **kwargs):
        from django.utils import timezone
        
        cinema_id = request.GET.get('cinema', '1')
        date_str = request.GET.get('date', datetime.date.today().isoformat())
        target_date = parse_date(date_str) or datetime.date.today()
        
        try:
            c_id = int(cinema_id)
        except:
            c_id = 1
            
        cinema = Cinema.objects.filter(id=c_id).first()
        if not cinema:
            cinema, _ = Cinema.objects.get_or_create(id=c_id, defaults={'name': f"Mock Cinema {c_id}"})

        tz = timezone.get_current_timezone()
        day_start = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(0, 0)), tz)
        day_end = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(23, 59, 59)), tz)
        
        showtimes = Showtime.objects.filter(
            cinema=cinema,
            datetime__range=(day_start, day_end)
        ).select_related('movie').order_by('movie__title', 'datetime')
        
        # Group by movie
        grouped_shows = {}
        for st in showtimes:
            m_title = st.movie.title
            if m_title not in grouped_shows:
                grouped_shows[m_title] = []
            grouped_shows[m_title].append(timezone.localtime(st.datetime))
            
        context = {
            'cinema': cinema,
            'target_date': target_date,
            'grouped_shows': grouped_shows,
            'cinemas': Cinema.objects.all(),
        }
        return render(request, "list_shows.html", context)


from django.http import JsonResponse

class GetShowtimesView(View):
    def get(self, request, *args, **kwargs):
        import random
        from django.utils import timezone
        import datetime
        
        try:
            cinema_id = request.GET.get('cinema')
            date_str = request.GET.get('date')
            
            if not cinema_id or not date_str:
                return JsonResponse({'error': 'Missing parameters'}, status=400)
                
            target_date = parse_date(date_str)
            if not target_date:
                 return JsonResponse({'error': 'Invalid date'}, status=400)

            print(f"--- API REQUEST: cinema={cinema_id}, date={date_str} ---")
            
            try:
                c_id = int(cinema_id)
            except:
                c_id = 1
                
            cinema, _ = Cinema.objects.get_or_create(id=c_id, defaults={'name': f"Mock Cinema {c_id}"})
            
            # Make dates aware
            tz = timezone.get_current_timezone()
            day_start = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(0, 0)), tz)
            day_end = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(23, 59, 59)), tz)
            
            showtimes = Showtime.objects.filter(
                cinema=cinema,
                datetime__range=(day_start, day_end)
            ).select_related('movie')
            
            if not showtimes.exists():
                print(f"Generating mock showtimes for {target_date}...")
                movies_data = [
                    ("Dune: Part Two", 166), ("Kung Fu Panda 4", 94), ("The Batman", 176),
                    ("Joker: Folie à Deux", 138), ("Gladiator II", 148), ("Wicked", 160),
                    ("Moana 2", 100), ("Sonic the Hedgehog 3", 110), ("Mufasa: The Lion King", 118),
                    ("Nosferatu", 132), ("A Complete Unknown", 140), ("Better Man", 136),
                    ("Paddington in Peru", 105), ("Kraven the Hunter", 127), ("Red One", 123),
                    ("Venom: The Last Dance", 109), ("Smile 2", 127), ("Terrifier 3", 125),
                    ("We Live in Time", 107), ("Anora", 139)
                ]
                
                movies = []
                for title, duration in movies_data:
                    m, _ = Movie.objects.get_or_create(title=title, defaults={'duration_minutes': duration})
                    movies.append(m)
                
                random.seed(f"WEEKDAY-{target_date.weekday()}-C-{cinema.id}")
                
                new_slots = []
                for t in range(10): # 10 theaters
                    curr_time = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time(10, 0)), tz)
                    curr_time += datetime.timedelta(minutes=t * 15)
                    random.shuffle(movies)
                    
                    m_idx = 0
                    while curr_time < day_end - datetime.timedelta(hours=2):
                        movie = movies[m_idx % len(movies)]
                        m_idx += 1
                        new_slots.append(Showtime(
                            movie=movie,
                            cinema=cinema,
                            datetime=curr_time
                        ))
                        curr_time += datetime.timedelta(minutes=movie.duration_minutes + random.randint(20, 40))
                
                Showtime.objects.bulk_create(new_slots)
                print(f"Created {len(new_slots)} showtimes.")

                showtimes = Showtime.objects.filter(
                    cinema=cinema,
                    datetime__range=(day_start, day_end)
                ).select_related('movie')

            data = []
            for st in showtimes:
                localized_time = timezone.localtime(st.datetime)
                data.append({
                    'id': st.id,
                    'movie_id': st.movie.id,
                    'movie_title': st.movie.title,
                    'time': localized_time.strftime('%H:%M'),
                    'duration': st.movie.duration_minutes
                })
            
            data.sort(key=lambda x: x['time'])
            print(f"Returning {len(data)} showtimes.")
            return JsonResponse({'showtimes': data})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)

from django.http import HttpResponse

def onduty_current_week(request):
    return HttpResponse("Onduty: Current Week (Stub)")

def onduty_next_week(request):
    return HttpResponse("Onduty: Next Week (Stub)")

def onduty_previous_week(request):
    return HttpResponse("Onduty: Previous Week (Stub)")

def reset(request):
    return HttpResponse("Control: Reset (Stub)")

def switch_shifts(request):
    return HttpResponse("Control: Switch Not Implemented")

def change_password(request):
    from django.http import HttpResponseRedirect
    return HttpResponseRedirect('/admin/password_change/')

def trigger_scraper(request):
    from .scrapers import MockCinepolisScraper
    scraper = MockCinepolisScraper()
    scraper.fetch_and_save()
    return HttpResponse("Scraper Triggered and DB Populated!")
