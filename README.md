# 🍿 Movie Day Scheduler

**Movie Day Scheduler** is a high-performance cinema day planning application. It helps groups of friends coordinate a full day at the cinema, ensuring everyone sees as many movies as possible while staying together for as many shows as social glue suggests.

## 🚀 Key Features

- **Optimal Pathfinding**: Uses a sophisticated **Beam Search Algorithm** to find the most efficient movie flow for each individual.
- **Social Optimization**: Prioritizes shared showtimes so friends can watch together.
- **Must-See Prioritization**: Mark a movie with a ⭐ to ensure the algorithm locks it in, regardless of complexity.
- **Dynamic Overlap Handling**: Configurable "overlap scaler" to allow for credit-skipping or tight transitions.
- **Fairness Logic**: Ensures every participant gets a balanced schedule with a "one movie per person" rule.
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
3.  **Populate Data**: Use the `🔍 View All Showtimes` link or the `/scrape/` endpoint to seed the mock cinema data.
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

