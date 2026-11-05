# Sports-Performance Statistics Explorer

A single-file Python tool that analyses event times and scores for anonymised athletes across training sessions. It validates the data, ranks athletes, measures average level, consistency and improvement, and produces reports and charts for each event.

## What it does

- **Validates** every score and session record (known event, plausible value, correct date, anonymised ID).
- **Ranks** athletes per event, by best result and by average result. Times rank lowest-first, distances highest-first, and ties share a rank.
- **Stores** athlete details and session records in files, so data persists between runs.
- **Calculates** with NumPy: mean, standard deviation, coefficient of variation (CV), and improvement.
- **Reports** with Pandas: a ranked table for each event and a dataset summary.
- **Plots** with Matplotlib: comparative bar charts and time-series charts.
- **Evaluates** each athlete and event in plain language: trend, consistency, most improved, and so on.

## Requirements

- Python 3.9 or newer
- `numpy`, `pandas`, `matplotlib` (3.5 or newer)

```
pip install numpy pandas matplotlib
```

## Quick start

```
python sports_stats_explorer.py
```

On the first run there is no data yet, so the tool creates sample data for 8 anonymised athletes in a folder called `sports_data/`, analyses all events, prints the reports, and saves charts to `sports_plots/`. (Use your own file name if you saved the script under a different name.)

## Command-line options

| Option | What it does |
|---|---|
| `--event 100m` | Analyse a single event (`100m`, `400m`, `1500m` or `long_jump`). |
| `--add A03 100m 2025-03-01 11.42` | Add one session record: athlete ID, event, date (`YYYY-MM-DD`) and score. It is validated first and rejected with a reason if invalid. |
| `--data-dir DIR` | Folder for the data files (default `sports_data`). |
| `--out-dir DIR` | Folder for the saved charts (default `sports_plots`). |
| `--show` | Also open the charts in windows. Without it, charts are only saved as PNG files. |
| `--reset` | Regenerate the sample data. **This overwrites the files in the data folder.** |

Examples:

```
python sports_stats_explorer.py --event 400m
python sports_stats_explorer.py --add A02 1500m 2025-04-10 258.6
python sports_stats_explorer.py --data-dir my_club_data --out-dir my_charts
```

## Supported events

| Event | Unit | Better is | Accepted range |
|---|---|---|---|
| `100m` | seconds | lower | 9 to 20 |
| `400m` | seconds | lower | 40 to 100 |
| `1500m` | seconds | lower | 200 to 400 |
| `long_jump` | metres | higher | 3 to 9 |

Scores outside the accepted range are rejected as implausible. To add another event, add an entry to the `EVENTS` dictionary near the top of the file with its unit, direction and range.

## Data files

Data lives in the data folder (default `sports_data/`):

- **`sessions.csv`** has one row per session result, with the columns `athlete_id,event,date,score`.
- **`athletes.json`** holds each athlete's alias and age group.

Example `sessions.csv`:

```
athlete_id,event,date,score
A01,100m,2025-03-01,11.42
A01,100m,2025-03-08,11.35
```

Rules for records:

- Athlete IDs must look like `A01`, `A02`, ..., `A9999` (an "A" followed by 2 to 4 digits). This keeps athletes anonymous.
- Dates must be real dates in `YYYY-MM-DD` format and cannot be in the future.
- There is one score per athlete, event and date. Adding a second score for the same date replaces the first.

When the files are loaded, invalid rows are skipped and listed with the reason, and the tool carries on with the valid data. The sample data deliberately includes four bad rows (an impossible date, an out-of-range time, a bad ID and an unknown event) to show this.

Note: whenever the tool saves (for example after `--add`), it rewrites the files from the valid data in memory, so previously rejected rows are dropped from the file.

## How the numbers are calculated

All values are calculated per athlete and per event.

| Measure | Meaning |
|---|---|
| **Best** | Fastest time (lowest) or longest distance (highest). |
| **Mean** | Average score across all sessions. |
| **Std** | Sample standard deviation: how much results vary between sessions. |
| **CV %** | Standard deviation as a percentage of the mean. It allows consistency to be compared between athletes and events. |
| **Improve %** | Compares the average of the first third of sessions with the average of the last third. It is direction-aware, so **a positive number always means better**, for both times and distances. |
| **Gain/session** | The improvement per session from a straight-line fit (`numpy.polyfit`). Positive means improving. |
| **Trend** | *Improving*, *Declining* or *Stable*. It needs at least 4 sessions (otherwise "Insufficient data"). The trend is "Improving" or "Declining" when the fitted change across all sessions is larger than the athlete's own standard deviation, and "Stable" otherwise. |
| **Consistency** | *Very consistent* (CV below 1.5%), *Consistent* (below 4%) or *Variable*. |
| **Rank** | Competition ranking (1, 2, 2, 4, ...), once by best result (`rank_best`) and once by mean (`rank_mean`). |

## Output

The console output has three parts:

1. **Dataset summary:** for each event, the mean, standard deviation, minimum, maximum and number of athletes.
2. **Event report:** a ranked table with the columns `sessions, best, mean, std, cv_%, improve_%, gain/session, trend, consistency, rank_best, rank_mean`.
3. **Evaluation:** the top performer, highest average, most and least improved, most and least consistent, a breakdown of trends, and a warning when the top-ranked athlete is more variable than the group (their best result may overstate how they usually perform).

For each event, two charts are saved in the charts folder:

- **`bars_<event>.png`**: the left chart compares each athlete's mean ± standard deviation, with their best result marked as a diamond. The right chart shows percentage improvement, in green for improving and red for declining.
- **`timeseries_<event>.png`**: every athlete's scores over time, with a dashed trend line for each.

## Project structure

Everything is in one file:

| Section | Purpose |
|---|---|
| `EVENTS` | Event definitions: unit, direction, valid range. |
| `validate_score`, `validate_record` | Validation of a score or a whole record. |
| `rank_scores` | Ranking with ties. |
| `Athlete` | Class holding an athlete's sessions, with the statistics and evaluation methods. |
| `save_data`, `load_data`, `append_record`, `create_sample_data` | File storage and sample data. |
| `sessions_dataframe`, `event_report`, `overall_summary` | Pandas reports. |
| `plot_comparison_bars`, `plot_time_series` | Charts. |
| `evaluate_event` | Plain-language findings. |
| `main` | Command-line interface. |

## Using your own data

1. Delete the `sports_data/` folder, or use `--data-dir` with a new folder name.
2. Put your results in `sessions.csv` in that folder using the format above (use anonymised IDs such as `A01`).
3. Run the tool. It only creates sample data when `sessions.csv` is missing, and `--reset` is the only option that overwrites existing files.

## Limitations

- Results with few sessions are unreliable. Trends need at least 4 sessions per athlete and event, and more is better.
- The trend and the dashed lines treat sessions as evenly spaced and use the session number, not the real dates, so large gaps between sessions are not reflected.
- Only one score per athlete, event and date is stored.
- The accepted ranges are sensible general limits rather than official rules, so adjust them for your athletes (for example, youth or para athletes).
- The sample data is randomly generated and not real results.
