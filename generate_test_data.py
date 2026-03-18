import csv
import json
import random
from datetime import datetime, timedelta

def generate_showtimes(genre):
    num_shows = random.randint(2, 7)
    times = []
    
    if genre == "Horror":
        # Night time: 18:00 to 23:30
        start_hour = 18
        end_hour = 23
    elif genre == "Kids":
        # Morning till afternoon: 08:00 to 16:00
        start_hour = 8
        end_hour = 16
    else:
        # All day: 08:00 to 23:30
        start_hour = 8
        end_hour = 23
        
    for _ in range(num_shows):
        hour = random.randint(start_hour, end_hour)
        minute = random.choice([0, 15, 30, 45])
        
        # Ensure it doesn't go past 23:30
        if hour == 23 and minute > 30:
            minute = random.choice([0, 15, 30])
            
        t_str = f"{hour:02d}:{minute:02d}"
        if t_str not in times:
            times.append(t_str)
            
    times.sort()
    return times

movies_raw = [
    # Kids
    ("Inside Out 2", 95, "Kids"), ("Despicable Me 4", 90, "Kids"), ("Moana 2", 100, "Kids"), 
    ("Sonic the Hedgehog 3", 110, "Kids"), ("Mufasa: The Lion King", 118, "Kids"), ("The Garfield Movie", 101, "Kids"),
    ("Kung Fu Panda 4", 94, "Kids"), ("Paddington in Peru", 105, "Kids"), ("Wonka", 116, "Kids"),
    ("Wish", 95, "Kids"), ("Elemental", 101, "Kids"), ("Spider-Man: Beyond the Spider-Verse", 140, "Kids"),
    
    # Horror
    ("Smile 2", 127, "Horror"), ("Terrifier 3", 125, "Horror"), ("Nosferatu", 132, "Horror"),
    ("A Quiet Place: Day One", 99, "Horror"), ("The Watchers", 102, "Horror"), ("Longlegs", 101, "Horror"),
    ("MaXXXine", 103, "Horror"), ("Trap", 105, "Horror"), ("Speak No Evil", 110, "Horror"),
    ("Wolf Man", 115, "Horror"), ("Five Nights at Freddy's 2", 110, "Horror"), ("Saw XI", 110, "Horror"),

    # Action / Drama / Comedy
    ("Dune: Part Two", 166, "Action"), ("The Batman 2", 170, "Action"), ("Gladiator II", 148, "Action"),
    ("Joker: Folie à Deux", 138, "Drama"), ("A Complete Unknown", 140, "Drama"), ("The Apprentice", 120, "Drama"),
    ("Furiosa: A Mad Max Saga", 148, "Action"), ("Deadpool & Wolverine", 127, "Action"), ("The Fall Guy", 126, "Action"),
    ("Twisters", 122, "Action"), ("Kingdom of the Planet of the Apes", 145, "Action"), ("Civil War", 109, "Action"),
    ("The Ministry of Ungentlemanly Warfare", 120, "Action"), ("Bikeriders", 116, "Drama"), ("Kraven the Hunter", 127, "Action"),
    ("Red One", 123, "Comedy"), ("Bad Boys: Ride or Die", 115, "Action"), ("Fly Me to the Moon", 132, "Comedy"),
    ("Argylle", 139, "Action"), ("The Beekeeper", 105, "Action"), ("Bob Marley: One Love", 107, "Drama"),
    ("Ghostbusters: Frozen Empire", 115, "Action"), ("The Idea of You", 115, "Comedy"), ("Hit Man", 115, "Comedy"),
    ("Challengers", 131, "Drama"), ("It Ends with Us", 130, "Drama")
]

# Ensure we have exactly 50
final_list = movies_raw[:50]

# Generate data
json_data = []
csv_data = []

for title, duration, genre in final_list:
    times = generate_showtimes(genre)
    
    json_data.append({
        "movie_title": title,
        "time": times,
        "duration_minutes": duration
    })
    
    csv_data.append({
        "movie_title": title,
        "time": ",".join(times),
        "duration_minutes": duration
    })

# Save JSON
with open('s:/StickyEvents-Codes/movie-day/test_cinema.json', 'w', encoding='utf-8') as f:
    json.dump(json_data, f, indent=4)

# Save CSV
with open('s:/StickyEvents-Codes/movie-day/test_cinema.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=["movie_title", "time", "duration_minutes"])
    writer.writeheader()
    writer.writerows(csv_data)

print("Generated test_cinema.json and test_cinema.csv with 50 movies.")
