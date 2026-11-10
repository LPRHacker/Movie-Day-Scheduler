# 🍿 Movie Day Scheduler

**Movie Day Scheduler** is a high-performance cinema day planning application. It helps groups of friends coordinate a full day at the cinema, ensuring everyone sees as many movies as possible while staying together for as many shows as social glue suggests.

## 🚀 Key Features

- **Optimal Pathfinding**: Uses a sophisticated **Beam Search Algorithm** to find the most efficient movie flow for each individual.
- **Multi-Cinema Coordination**: Support for selecting multiple theaters simultaneously to find the best overall group path.
- **Transit Time Validation**: Automatic calculation and validation of travel times between different cinemas, saved for everyone or for one person who travels separately.
- **Personalized Breaks**: Schedule "Quiet Time" or meal breaks; the algorithm treats them as high-priority constraints.
- **Availability Windows**: Give each person an optional "from" time and an optional "until" time (each enabled by its own checkbox, so one-sided limits work); only screenings that fit inside those hours are offered to them.
- **Hall Criteria**: Every screening belongs to a hall with a type (Regular, VIP, Premium, 3D, XD). Hall type and individual halls by name/number are two separate criteria that narrow the movies shown for all selected cinemas, and reset on their own or when the cinema selection is cleared. Cinemas that publish only formats and no room numbers (MovieLand, Hot Cinema) are filtered by hall type only. The criteria apply to **Everyone** by default, and any participant can get their own halls/types (“Applies to” chips) while the rest of the group keeps the shared criteria; a person's unset criterion follows the group.
- **24-Hour Times**: Every time in the app is shown and typed as 24-hour `HH:MM` (`945` becomes `09:45`), with no AM/PM.
- **Social Optimization**: Prioritizes shared showtimes so friends can watch together, weighting a showing by how many people can actually attend it.
- **Must-See Prioritization**: Mark a movie with a ⭐ to ensure the algorithm locks it in.
- **Poster Integration**: Rich visual experience with movie posters fetched directly from cinema sources.
- **Print-Friendly Export**: One-click professional schedule print-outs with a dedicated layout.
- **Tree-Flow Visualization**: A Git-style timeline interface to see precisely how everyone's day unfolds.

## 🛠️ Technology Stack

- **Backend**: Django (Python 3)
- **Database**: SQLite (Timezone-aware queries)
- **Frontend**: Vanilla JS with a Premium Dark Mode UI
- **Algorithm**: Multi-pass Dynamic Programming / Beam Search

## 🏃 How to Run

1.  **Start Server**:
    ```bash
    python manage.py runserver 8001
    ```
2.  **Access App**: Open `http://127.0.0.1:8001/` in your browser.
3.  **Populate Data**: Use the `🔍 View All Showtimes` link or the `/scrape/` endpoint to seed the mock cinema data. Halls (and their types) are created from the cinema feed while scraping, so re-scrape a day once to make its halls filterable.
4.  **External Cinema File Guide**:
    You can use your own showtimes by selecting **"External cinema file"** and uploading a `.csv` or `.json` file.
    
    ### Accepted Formats:
    
    **CSV**:
    ```csv
    movie_title,time,duration_minutes
    "Dune: Part Two","07:00,15:00,19:00",166
    "Kung Fu Panda 4","10:00,14:30,17:27,20:30",94
    ```

    **JSON**:
    ```json
    [
      {
        "movie_title": "Dune: Part Two",
        "time": ["07:00", "15:00", "19:00"],
        "duration_minutes": 166
      },
      {
        "movie_title": "Kung Fu Panda 4",
        "time": ["10:00", "14:30", "17:27", "20:30"],
        "duration_minutes": 94
      }
    ]
    ```
    *Note: `time` can be a string (comma-separated for CSV) or an array (JSON). Values must be in `HH:MM` format. `duration_minutes` defaults to 120 if omitted.*

---
**Movie Day, built upon [django-shift](https://github.com/mtribaldos/django-shift).**

