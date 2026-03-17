from itertools import combinations
from datetime import timedelta
from typing import List, Dict
from .models import Person, Movie, Showtime, Preference

def generate_schedule(persons: List[Person], target_date, cinema, allow_overlap: bool=False, max_overlap_minutes: int=0, movie_ids: List[int]=None):
    """
    Generates an optimized schedule for a full day at the cinema.
    Tries to maximize common movies and minimize wait times.
    
    allow_overlap: if true, allows overlapping scheduled times (either for the same person clipping credits or for the group splitting and having different end times).
    max_overlap_minutes: scaler representing the max overlap in minutes.
    """
    # 1. Parse Preferences
    person_prefs = {}
    all_desired_ids = set()
    
    if isinstance(movie_ids, dict):
        for p_name, prefs in movie_ids.items():
            if isinstance(prefs, dict):
                person_prefs[p_name] = prefs
                for mid in prefs.keys():
                    if str(mid).isdigit():
                        all_desired_ids.add(int(mid))
            elif isinstance(prefs, list):
                # Backwards compatibility
                person_prefs[p_name] = {str(mid): "normal" for mid in prefs}
                for mid in prefs:
                    if str(mid).isdigit():
                        all_desired_ids.add(int(mid))
    
    # 2. Fetch movies and showtimes
    if all_desired_ids:
        desired_movies = Movie.objects.filter(id__in=all_desired_ids)
    else:
        # Fallback to general preferences in DB
        preferences = Preference.objects.filter(person__in=persons)
        desired_movies = set([pref.movie for pref in preferences])
    
    showtimes = Showtime.objects.filter(
        cinema=cinema,
        movie__in=desired_movies,
        datetime__date=target_date
    ).select_related('movie').order_by('datetime')
    
    # 3. Path Generation per Person using Beam Search
    person_top_paths = {}
    
    for p in persons:
        p_pref = person_prefs.get(p.name, {})
        if not p_pref:
            person_top_paths[p.name] = []
            continue
            
        interest_st = [st for st in showtimes if str(st.movie.id) in p_pref]
        must_sees = {int(mid) for mid, status in p_pref.items() if status == "must"}
        
        # State: (score, path_tuple, seen_movies, last_end_time)
        states = [(0, (), frozenset(), None)]
        
        for st in interest_st:
            duration = st.movie.duration_minutes
            st_start = st.datetime
            st_end = st.datetime + timedelta(minutes=duration)
            
            new_states = []
            for score, path, seen, last_end in states:
                # Option 1: Keep path without this showtime
                new_states.append((score, path, seen, last_end))
                
                # Option 2: Add this showtime
                if st.movie.id not in seen:
                    valid = True
                    if last_end and st_start < last_end:
                        if not allow_overlap:
                            valid = False
                        else:
                            overlap_mins = (last_end - st_start).total_seconds() / 60
                            if overlap_mins > max_overlap_minutes:
                                valid = False
                    
                    if valid:
                        new_seen = seen | {st.movie.id}
                        new_path = path + (st,)
                        new_last_end = max(last_end, st_end) if last_end else st_end
                        
                        m_score = 10000 * len(new_seen.intersection(must_sees))
                        t_score = 100 * len(new_seen)
                        
                        c_score = m_score + t_score
                        new_states.append((c_score, new_path, new_seen, new_last_end))
                        
            # Prune states: keep unique combinations of paths to avoid memory explosion
            unique_states = {}
            for s in new_states:
                path_ids = tuple(x.id for x in s[1])
                if path_ids not in unique_states or unique_states[path_ids][0] < s[0]:
                    unique_states[path_ids] = s
                    
            sorted_states = sorted(unique_states.values(), key=lambda x: x[0], reverse=True)
            states = sorted_states[:100]  # Keep top 100 partial paths
            
        person_top_paths[p.name] = states[:20]  # Store top 20 candidate paths for combinator
        
    # 4. Global Combination using Beam Search (Social Overlap Maximization)
    combo_states = [(0, {})] # (total_score, {p_name: path_tuple})
    
    for p in persons:
        candidates = person_top_paths.get(p.name, [])
        if not candidates:
            for s in combo_states:
                s[1][p.name] = ()
            continue
            
        new_combo_states = []
        for combo_score, path_dict in combo_states:
            for p_score, path_tuple, _, _ in candidates:
                new_dict = path_dict.copy()
                new_dict[p.name] = path_tuple
                
                # Evaluate social score for this combination
                st_counts = {}
                for name, p_path in new_dict.items():
                    for st in p_path:
                        st_counts[st.id] = st_counts.get(st.id, 0) + 1
                        
                social_score = sum((count - 1) * 10 for count in st_counts.values() if count > 1)
                
                # Base score sum
                base_score = sum(
                    10000 * len(frozenset(st.movie.id for st in new_dict[n]).intersection({int(mid) for mid, status in person_prefs.get(n, {}).items() if status == "must"})) +
                    100 * len(new_dict[n])
                    for n in new_dict.keys()
                )
                
                total_c_score = base_score + social_score
                new_combo_states.append((total_c_score, new_dict))
                
        sorted_combos = sorted(new_combo_states, key=lambda x: x[0], reverse=True)
        combo_states = sorted_combos[:100]

    # 5. Extract Final Schedule
    best_combo = combo_states[0][1] if combo_states else {p.name: () for p in persons}
    
    schedule = {"slots": [], "person_paths": {p.name: [] for p in persons}}
    unique_slots = {}
    
    for p_name, path in best_combo.items():
        for st in path:
            if st.id not in unique_slots:
                unique_slots[st.id] = {
                    "id": st.id,
                    "time": st.datetime,
                    "end_time": st.datetime + timedelta(minutes=st.movie.duration_minutes),
                    "duration": st.movie.duration_minutes,
                    "movie": st.movie.title,
                    "attendees": []
                }
            unique_slots[st.id]["attendees"].append(p_name)
            
    schedule["slots"] = list(unique_slots.values())
    schedule["slots"].sort(key=lambda x: x["time"])
    
    for p_name, path in best_combo.items():
        for st in path:
            schedule["person_paths"][p_name].append(unique_slots[st.id])
        schedule["person_paths"][p_name].sort(key=lambda x: x["time"])
        
    return schedule
