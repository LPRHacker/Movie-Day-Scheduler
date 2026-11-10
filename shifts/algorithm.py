from itertools import combinations
from datetime import timedelta, datetime
from typing import List, Dict, Any
from .models import Person, Movie, Showtime, Preference, Hall
from django.utils import timezone

# Score awarded to every pair of people watching the same show together. The
# bonus grows quadratically with the attendee count (2 people = 1 pair,
# 3 people = 3 pairs, 4 people = 6 pairs), so a showing that more people can
# actually attend outweighs a showing only two people can make.
SOCIAL_PAIR_WEIGHT = 20


def _score_path(path, must_sees):
    """Per-person score: must-sees dominate, then the number of movies seen."""
    seen_movies = frozenset(st.movie.id for st in path)
    return 10000 * len(seen_movies.intersection(must_sees)) + 100 * len(path)


def _social_score(st_counts):
    """Bonus for shared showings, weighted by how many people attend."""
    return sum(
        SOCIAL_PAIR_WEIGHT * (count * (count - 1) // 2)
        for count in st_counts.values() if count > 1
    )


def _day_bound(target_date, value):
    """Aware datetime for a "HH:MM" string on target_date (None if unusable)."""
    if not value:
        return None
    try:
        return timezone.make_aware(
            datetime.combine(target_date, datetime.strptime(str(value), "%H:%M").time())
        )
    except (TypeError, ValueError):
        return None


def _hall_matches(showtime, hall_ids, hall_types):
    """True when a screening passes one person's hall and hall-type criteria."""
    if hall_ids and showtime.hall_id not in hall_ids:
        return False
    if hall_types:
        # Rentals without a hall row are regular screenings.
        hall_type = showtime.hall.hall_type if showtime.hall else Hall.REGULAR
        if hall_type not in hall_types:
            return False
    return True


def generate_schedule(persons: List[Person], target_date, cinemas: List[Any], 
                      allow_overlap: bool=False, max_overlap_minutes: int=0, 
                      movie_ids: Dict[str, Any]=None, breaks: Dict[str, List[Dict]] = None,
                      transit_times: Dict[str, int] = None,
                      availability: Dict[str, Dict[str, str]] = None,
                      hall_ids: List[int] = None,
                      hall_types: List[str] = None,
                      person_criteria: Dict[str, Dict[str, Any]] = None,
                      person_transits: Dict[str, Dict[str, int]] = None):
    """
    Generates an optimized schedule for a full day at the cinema.

    availability: {person: {'start': 'HH:MM', 'end': 'HH:MM'}} - the hours that
        person is actually at the cinema. Either bound may be missing (a person
        can be limited by only a start or only an end). Shows that start before
        the start bound or end after the end bound are not offered to them.
    hall_ids: restrict the schedule to these Hall ids (empty/None = all halls).
        This is the group-wide hall criterion.
    hall_types: restrict the schedule to these hall types (empty/None = all).
    person_criteria: {person: {'halls': [ids], 'types': [keys]}} - a person's own
        criteria, replacing the group-wide ones for that person only. Missing
        entries inherit hall_ids/hall_types, so one run serves both the people
        who filter individually and those who follow the group.
    person_transits: {person: {'id1-id2': minutes}} - travel times that apply to
        that person, layered over the group-wide transit_times.
    """
    person_prefs = {}
    all_desired_ids = set()
    
    if isinstance(movie_ids, dict):
        for p_name, prefs in movie_ids.items():
            if isinstance(prefs, dict):
                person_prefs[p_name] = prefs
                for mid in prefs.keys():
                    if str(mid).isdigit(): all_desired_ids.add(int(mid))
            elif isinstance(prefs, list):
                person_prefs[p_name] = {str(mid): "normal" for mid in prefs}
                for mid in prefs:
                    if str(mid).isdigit(): all_desired_ids.add(int(mid))
    
    # 2. Fetch showtimes for all selected cinemas
    if all_desired_ids:
        desired_movies = Movie.objects.filter(id__in=all_desired_ids)
    else:
        preferences = Preference.objects.filter(person__in=persons)
        desired_movies = set([pref.movie for pref in preferences])
    
    q_cinemas = cinemas if cinemas else []
    showtime_qs = Showtime.objects.filter(
        cinema__in=q_cinemas,
        movie__in=desired_movies,
        datetime__date=target_date
    )
    # Hall criteria are applied per person below, because a person may override
    # the group-wide halls/types and needs to see screenings the group excluded.
    showtimes = showtime_qs.select_related('movie', 'cinema', 'hall').order_by('datetime')
    
    # Process breaks into datetime ranges
    processed_breaks = {}
    for p_name, p_breaks in (breaks or {}).items():
        processed_breaks[p_name] = []
        for b in p_breaks:
            try:
                # Assuming target_date is context
                start_dt = timezone.make_aware(datetime.combine(target_date, datetime.strptime(b['start'], "%H:%M").time()))
                end_dt = timezone.make_aware(datetime.combine(target_date, datetime.strptime(b['end'], "%H:%M").time()))
                processed_breaks[p_name].append({
                    'start': start_dt,
                    'end': end_dt,
                    'strict': b.get('strictness') == 'strict'
                })
            except: continue

    # Process availability bounds into datetimes (a person is at the cinema
    # from 'start' and/or until 'end'); unusable bounds are ignored.
    person_windows = {}
    for p_name, window in (availability or {}).items():
        if not isinstance(window, dict):
            continue
        start_dt = _day_bound(target_date, window.get('start'))
        end_dt = _day_bound(target_date, window.get('end'))
        if start_dt is None and end_dt is None:
            continue
        if start_dt and end_dt and end_dt <= start_dt:
            continue
        person_windows[p_name] = (start_dt, end_dt)

    # 3. Path Generation per Person
    person_top_paths = {}
    
    for p in persons:
        p_pref = person_prefs.get(p.name, {})
        if not p_pref:
            person_top_paths[p.name] = []
            continue

        own = (person_criteria or {}).get(p.name) or {}
        p_halls = own.get('halls') if 'halls' in own else hall_ids
        p_types = own.get('types') if 'types' in own else hall_types

        interest_st = [
            st for st in showtimes
            if str(st.movie.id) in p_pref and _hall_matches(st, p_halls, p_types)
        ]
        # A person can only attend a screening that fits inside the hours they
        # are at the cinema (either bound may be unset).
        window = person_windows.get(p.name)
        if window:
            start_dt, end_dt = window
            interest_st = [
                st for st in interest_st
                if (start_dt is None or st.datetime >= start_dt)
                and (end_dt is None
                     or st.datetime + timedelta(minutes=st.movie.duration_minutes) <= end_dt)
            ]
        must_sees = {int(mid) for mid, status in p_pref.items() if status == "must"}
        p_breaks = processed_breaks.get(p.name, [])
        p_transit = dict(transit_times or {})
        p_transit.update((person_transits or {}).get(p.name) or {})
        
        # State: (score, path_tuple, seen_movies, last_st)
        states = [(0, (), frozenset(), None)]
        
        for st in interest_st:
            duration = st.movie.duration_minutes
            st_start = st.datetime
            st_end = st.datetime + timedelta(minutes=duration)
            
            new_states = []
            for score, path, seen, last_st in states:
                # Option 1: Skip
                new_states.append((score, path, seen, last_st))
                
                # Option 2: Add
                if st.movie.id not in seen:
                    valid = True
                    # Check overlap with last movie
                    if last_st:
                        last_end = last_st.datetime + timedelta(minutes=last_st.movie.duration_minutes)
                        
                        # Transit check
                        transit_req = 0
                        if st.cinema.id != last_st.cinema.id:
                            # Try to find transit time
                            key1 = f"{last_st.cinema.id}-{st.cinema.id}"
                            key2 = f"{st.cinema.id}-{last_st.cinema.id}"
                            transit_req = p_transit.get(key1, p_transit.get(key2, 30))
                        
                        required_gap = timedelta(minutes=transit_req)
                        if st_start < last_end + required_gap:
                            # Check if we can overlap via generic settings
                            if not allow_overlap or st.cinema.id != last_st.cinema.id:
                                # CANNOT overlap across different cinemas
                                valid = False
                            else:
                                overlap_mins = (last_end - st_start).total_seconds() / 60
                                if overlap_mins > max_overlap_minutes:
                                    valid = False

                    # Check overlap with breaks
                    if valid:
                        for b in p_breaks:
                            overlap_start = max(st_start, b['start'])
                            overlap_end = min(st_end, b['end'])
                            if overlap_start < overlap_end:
                                overlap_dur = (overlap_end - overlap_start).total_seconds() / 60
                                if b['strict'] or overlap_dur > 30: # 30m allowance for flexible breaks
                                    valid = False
                                    break

                    if valid:
                        new_seen = seen | {st.movie.id}
                        new_path = path + (st,)
                        
                        # Scoring
                        m_score = 10000 * len(new_seen.intersection(must_sees))
                        t_score = 100 * len(new_seen)
                        
                        c_score = m_score + t_score
                        new_states.append((c_score, new_path, new_seen, st))
                        
            # Prune
            unique_states = {}
            for s in new_states:
                path_ids = tuple(x.id for x in s[1])
                if path_ids not in unique_states or unique_states[path_ids][0] < s[0]:
                    unique_states[path_ids] = s
            states = sorted(unique_states.values(), key=lambda x: x[0], reverse=True)[:100]
            
        person_top_paths[p.name] = states[:20]

    # 4. Global Combination
    must_by_person = {
        name: {int(mid) for mid, status in prefs.items() if status == "must"}
        for name, prefs in person_prefs.items() if isinstance(prefs, dict)
    }
    combo_states = [(0, {})]
    for p in persons:
        candidates = person_top_paths.get(p.name, [])
        if not candidates:
            for s in combo_states: s[1][p.name] = ()
            continue
            
        new_combo_states = []
        for combo_score, path_dict in combo_states:
            for p_score, path_tuple, _, _ in candidates:
                new_dict = path_dict.copy()
                new_dict[p.name] = path_tuple
                
                st_counts = {}
                for name, p_path in new_dict.items():
                    for st in p_path:
                        st_counts[st.id] = st_counts.get(st.id, 0) + 1
                
                social_score = _social_score(st_counts)
                base_score = sum(
                    _score_path(new_dict[n], must_by_person.get(n, set()))
                    for n in new_dict.keys()
                )
                new_combo_states.append((base_score + social_score, new_dict))
        combo_states = sorted(new_combo_states, key=lambda x: x[0], reverse=True)[:50]

    # 5. Extract Final Schedule
    best_combo = combo_states[0][1] if combo_states else {p.name: () for p in persons}
    schedule = {"slots": [], "person_paths": {p.name: [] for p in persons}}
    unique_slots = {}
    
    all_items = []
    for p_name, path in best_combo.items():
        # Add movies
        for st in path:
            st_end = st.datetime + timedelta(minutes=st.movie.duration_minutes)
            if st.id not in unique_slots:
                unique_slots[st.id] = {
                    "id": st.id,
                    "time": st.datetime,
                    "end_time": st_end,
                    "duration": st.movie.duration_minutes,
                    "movie": st.movie.title,
                    "cinema": st.cinema.name,
                    "hall": st.hall.name if st.hall else None,
                    # A format-named hall ("VIP") already states the type.
                    "hall_type": (None if (not st.hall or st.hall.is_generic)
                                  else st.hall.get_hall_type_display()),
                    "poster": st.movie.poster_url,
                    "attendees": [],
                    "type": "movie"
                }
            unique_slots[st.id]["attendees"].append(p_name)
        
        # Add breaks to person paths (for visualization)
        p_breaks = processed_breaks.get(p_name, [])
        for b in p_breaks:
            schedule["person_paths"][p_name].append({
                "time": b['start'],
                "end_time": b['end'],
                "duration": (b['end'] - b['start']).total_seconds() / 60,
                "movie": "Break ☕",
                "type": "break",
                "attendees": [p_name]
            })

    schedule["slots"] = list(unique_slots.values())
    schedule["slots"].sort(key=lambda x: x["time"])
    
    for p_name, path in best_combo.items():
        for st in path:
            schedule["person_paths"][p_name].append(unique_slots[st.id])
        
        # Add transit nodes
        p_path = sorted(schedule["person_paths"][p_name], key=lambda x: x["time"])
        new_p_path = []
        for i in range(len(p_path)):
            new_p_path.append(p_path[i])
            if i < len(p_path) - 1:
                cur = p_path[i]
                nxt = p_path[i+1]
                if cur["end_time"] < nxt["time"]:
                    # Check if different cinemas or significant gap
                    is_transit = False
                    label = "Gap"
                    if cur.get("cinema") and nxt.get("cinema") and cur["cinema"] != nxt["cinema"]:
                        is_transit = True
                        label = f"{cur['cinema']} ➔ {nxt['cinema']}"
                    
                    if is_transit:
                        new_p_path.append({
                            "time": cur["end_time"],
                            "end_time": nxt["time"],
                            "duration": (nxt["time"] - cur["end_time"]).total_seconds() / 60,
                            "movie": label,
                            "type": "transit",
                            "attendees": [p_name]
                        })
        schedule["person_paths"][p_name] = sorted(new_p_path, key=lambda x: x["time"])
        
    return schedule
