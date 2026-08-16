from itertools import combinations
from datetime import timedelta, datetime
from typing import List, Dict, Any
from .models import Person, Movie, Showtime, Preference
from django.utils import timezone

def generate_schedule(persons: List[Person], target_date, cinemas: List[Any], 
                      allow_overlap: bool=False, max_overlap_minutes: int=0, 
                      movie_ids: Dict[str, Any]=None, breaks: Dict[str, List[Dict]] = None,
                      transit_times: Dict[str, int] = None):
    """
    Generates an optimized schedule for a full day at the cinema.
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
    showtimes = Showtime.objects.filter(
        cinema__in=q_cinemas,
        movie__in=desired_movies,
        datetime__date=target_date
    ).select_related('movie', 'cinema').order_by('datetime')
    
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

    # 3. Path Generation per Person
    person_top_paths = {}
    
    for p in persons:
        p_pref = person_prefs.get(p.name, {})
        if not p_pref:
            person_top_paths[p.name] = []
            continue
            
        interest_st = [st for st in showtimes if str(st.movie.id) in p_pref]
        must_sees = {int(mid) for mid, status in p_pref.items() if status == "must"}
        p_breaks = processed_breaks.get(p.name, [])
        
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
                            transit_req = transit_times.get(key1, transit_times.get(key2, 30))
                        
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
                
                social_score = sum((count - 1) * 20 for count in st_counts.values() if count > 1)
                base_score = sum(
                    10000 * len(frozenset(st.movie.id for st in new_dict[n]).intersection({int(mid) for mid, status in person_prefs.get(n, {}).items() if status == "must"})) +
                    100 * len(new_dict[n])
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
