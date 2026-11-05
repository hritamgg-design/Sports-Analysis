#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

EVENTS = {
    "100m":      {"unit": "s", "better": "lower",  "lo": 9.0,   "hi": 20.0},
    "400m":      {"unit": "s", "better": "lower",  "lo": 40.0,  "hi": 100.0},
    "1500m":     {"unit": "s", "better": "lower",  "lo": 200.0, "hi": 400.0},
    "long_jump": {"unit": "m", "better": "higher", "lo": 3.0,   "hi": 9.0},
}

ID_PATTERN = re.compile(r"^A\d{2,4}$")  # anonymised IDs: A01, A02, ...
SESSION_FILE = "sessions.csv"
ATHLETE_FILE = "athletes.json"

def validate_score(event: str, value) -> tuple[bool, str]:

    if event not in EVENTS:
        return False, f"unknown event '{event}'"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, f"score '{value}' is not numeric"
    if not math.isfinite(v):
        return False, "score is NaN/infinite"
    spec = EVENTS[event]
    if not (spec["lo"] <= v <= spec["hi"]):
        return False, f"score {v} outside plausible range {spec['lo']}-{spec['hi']} {spec['unit']}"
    return True, "ok"


def validate_record(athlete_id, event, session_date, score) -> tuple[bool, str]:

    if not ID_PATTERN.match(str(athlete_id)):
        return False, f"bad athlete id '{athlete_id}' (expected like A01)"
    try:
        d = datetime.strptime(str(session_date), "%Y-%m-%d").date()
    except ValueError:
        return False, f"bad date '{session_date}' (expected YYYY-MM-DD)"
    if d > date.today():
        return False, f"date {d} is in the future"
    return validate_score(event, score)


def rank_scores(values: dict[str, float], better: str) -> list[tuple[str, float, int]]:
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=(better == "higher"))
    ranked, prev_val, prev_rank = [], None, 0
    for pos, (aid, val) in enumerate(ordered, start=1):
        rank = prev_rank if (prev_val is not None and math.isclose(val, prev_val)) else pos
        ranked.append((aid, val, rank))
        prev_val, prev_rank = val, rank
    return ranked

class Athlete:


    def __init__(self, athlete_id: str, alias: str = "", age_group: str = ""):
        if not ID_PATTERN.match(athlete_id):
            raise ValueError(f"Invalid athlete id: {athlete_id}")
        self.athlete_id = athlete_id
        self.alias = alias or athlete_id
        self.age_group = age_group
        self._sessions: dict[str, dict[str, float]] = {}  # event -> {iso_date: score}

    # ---- record handling ----
    def add_session(self, event: str, session_date: str, score: float) -> None:
        ok, reason = validate_record(self.athlete_id, event, session_date, score)
        if not ok:
            raise ValueError(reason)
        self._sessions.setdefault(event, {})[session_date] = float(score)

    @property
    def events(self) -> list[str]:
        return sorted(self._sessions)

    def series(self, event: str) -> tuple[list[str], np.ndarray]:

        data = self._sessions.get(event, {})
        dates = sorted(data)
        return dates, np.array([data[d] for d in dates], dtype=float)


    def mean(self, event: str) -> float:
        _, s = self.series(event)
        return float(np.mean(s)) if s.size else float("nan")

    def std(self, event: str) -> float:
        _, s = self.series(event)
        return float(np.std(s, ddof=1)) if s.size > 1 else float("nan")

    def cv(self, event: str) -> float:

        m, sd = self.mean(event), self.std(event)
        return float(sd / m * 100) if m and not math.isnan(sd) else float("nan")

    def best(self, event: str) -> float:
        _, s = self.series(event)
        if not s.size:
            return float("nan")
        return float(s.min() if EVENTS[event]["better"] == "lower" else s.max())

    def improvement(self, event: str) -> dict:
        _, s = self.series(event)
        n = s.size
        if n < 2:
            return {"pct_change": float("nan"), "slope": float("nan")}
        sign = -1.0 if EVENTS[event]["better"] == "lower" else 1.0
        k = max(1, n // 3)
        first, last = np.mean(s[:k]), np.mean(s[-k:])
        pct = sign * (last - first) / first * 100
        slope = sign * float(np.polyfit(np.arange(n), s, 1)[0])
        return {"pct_change": float(pct), "slope": slope}

    def evaluate(self, event: str) -> dict:
        _, s = self.series(event)
        n = s.size
        if n < 4:
            return {"trend": "Insufficient data", "consistency": "n/a"}
        imp = self.improvement(event)
        total_gain = imp["slope"] * (n - 1)       # fitted gain across all sessions
        sd = self.std(event)
        if total_gain > sd:
            trend = "Improving"
        elif total_gain < -sd:
            trend = "Declining"
        else:
            trend = "Stable"
        cv = self.cv(event)
        consistency = "Very consistent" if cv < 1.5 else "Consistent" if cv < 4 else "Variable"
        return {"trend": trend, "consistency": consistency}

    # ---- persistence helpers ----
    def meta(self) -> dict:
        return {"alias": self.alias, "age_group": self.age_group}

    def __repr__(self) -> str:
        n = sum(len(v) for v in self._sessions.values())
        return f"Athlete({self.athlete_id}, events={self.events}, sessions={n})"


def save_data(athletes: dict[str, Athlete], data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / ATHLETE_FILE, "w", encoding="utf-8") as f:
        json.dump({a.athlete_id: a.meta() for a in athletes.values()}, f, indent=2)
    rows = [
        {"athlete_id": a.athlete_id, "event": ev, "date": d, "score": sc}
        for a in athletes.values() for ev in a.events
        for d, sc in zip(*a.series(ev))
    ]
    pd.DataFrame(rows, columns=["athlete_id", "event", "date", "score"]).to_csv(
        data_dir / SESSION_FILE, index=False)


def load_data(data_dir: Path) -> tuple[dict[str, Athlete], list[str]]:

    athletes: dict[str, Athlete] = {}
    rejected: list[str] = []
    meta_path, sess_path = data_dir / ATHLETE_FILE, data_dir / SESSION_FILE
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    for aid, m in meta.items():
        try:
            athletes[aid] = Athlete(aid, m.get("alias", ""), m.get("age_group", ""))
        except ValueError as e:
            rejected.append(str(e))
    if sess_path.exists():
        df = pd.read_csv(sess_path, dtype=str)
        for i, row in df.iterrows():
            aid = row["athlete_id"]
            try:
                athletes.setdefault(aid, Athlete(aid))
                athletes[aid].add_session(row["event"], row["date"], row["score"])
            except (ValueError, KeyError, TypeError) as e:
                rejected.append(f"row {i + 2}: {e}")
    return athletes, rejected


def append_record(athletes: dict[str, Athlete], data_dir: Path,
                  athlete_id: str, event: str, session_date: str, score: float) -> None:

    athletes.setdefault(athlete_id, Athlete(athlete_id)).add_session(event, session_date, score)
    save_data(athletes, data_dir)


def create_sample_data(data_dir: Path, seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    athletes = {f"A{i:02d}": Athlete(f"A{i:02d}", alias=f"Athlete {i}",
                                     age_group=rng.choice(["U18", "U23", "Senior"]))
                for i in range(1, 9)}
    # (base performance, improvement per session in % of base, noise in % of base)
    plan = {
        "100m":      (11.6, 0.8),
        "400m":      (53.0, 0.7),
        "1500m":     (262.0, 0.5),
        "long_jump": (6.4, 0.6),
    }
    start = date.today() - timedelta(weeks=12)
    for idx, a in enumerate(athletes.values()):
        evs = [list(plan)[idx % 4], list(plan)[(idx + 1) % 4]]
        for ev in evs:
            base, step = plan[ev]
            base *= rng.normal(1.0, 0.04)
            trend = rng.choice([-0.15, 0.0, 0.5, 1.0]) * step / 100   # some decline, flat, improve
            noise = rng.uniform(0.004, 0.025)
            sign = -1 if EVENTS[ev]["better"] == "lower" else 1
            for s in range(12):
                val = base * (1 + sign * trend * s + rng.normal(0, noise))
                a.add_session(ev, (start + timedelta(weeks=s)).isoformat(), round(val, 2))
    save_data(athletes, data_dir)
    # inject invalid rows to demonstrate validation on load
    with open(data_dir / SESSION_FILE, "a", encoding="utf-8") as f:
        f.write("A01,100m,2025-02-30,11.5\n")      # impossible date
        f.write("A02,100m,2025-02-01,3.2\n")       # out-of-range time
        f.write("X9,400m,2025-02-01,55\n")         # bad id
        f.write("A03,javelin,2025-02-01,60\n")     # unknown event


def sessions_dataframe(athletes: dict[str, Athlete]) -> pd.DataFrame:
    rows = [{"athlete_id": a.athlete_id, "event": ev, "date": pd.to_datetime(d), "score": sc}
            for a in athletes.values() for ev in a.events for d, sc in zip(*a.series(ev))]
    return pd.DataFrame(rows, columns=["athlete_id", "event", "date", "score"])


def event_report(athletes: dict[str, Athlete], event: str) -> pd.DataFrame:

    spec = EVENTS[event]
    rows = []
    for a in athletes.values():
        if event not in a.events:
            continue
        imp, ev = a.improvement(event), a.evaluate(event)
        rows.append({
            "athlete": a.athlete_id, "sessions": len(a.series(event)[1]),
            "best": a.best(event), "mean": a.mean(event), "std": a.std(event),
            "cv_%": a.cv(event), "improve_%": imp["pct_change"],
            "gain/session": imp["slope"], "trend": ev["trend"],
            "consistency": ev["consistency"],
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("athlete")
    best_rank = {aid: r for aid, _, r in rank_scores(df["best"].to_dict(), spec["better"])}
    mean_rank = {aid: r for aid, _, r in rank_scores(df["mean"].to_dict(), spec["better"])}
    df["rank_best"] = df.index.map(best_rank)
    df["rank_mean"] = df.index.map(mean_rank)
    return df.sort_values("rank_best").round(3)


def overall_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Dataset-level summary per event (pandas groupby)."""
    return (df.groupby("event")["score"]
            .agg(athletes=lambda s: s.index.size, mean="mean", std="std", min="min", max="max")
            .join(df.groupby("event")["athlete_id"].nunique().rename("n_athletes"))
            .drop(columns="athletes").round(3))

def plot_comparison_bars(report: pd.DataFrame, event: str, out_dir: Path, plt) -> Path:
    spec = EVENTS[event]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(len(report))
    ax1.bar(x, report["mean"], yerr=report["std"].fillna(0), capsize=4,
            color="#4C78A8", label="Mean ± SD")
    ax1.scatter(x, report["best"], color="#F58518", zorder=3, marker="D", label="Best")
    ax1.set_xticks(x, report.index)
    lo = min(report["best"].min(), (report["mean"] - report["std"].fillna(0)).min())
    hi = max(report["best"].max(), (report["mean"] + report["std"].fillna(0)).max())
    pad = (hi - lo) * 0.25 or 1
    ax1.set_ylim(lo - pad, hi + pad)   # zoomed axis so differences are visible
    ax1.set_ylabel(f"Score ({spec['unit']})")
    ax1.set_title(f"{event}: average performance ({spec['better']} is better)")
    ax1.legend()

    colors = ["#54A24B" if v >= 0 else "#E45756" for v in report["improve_%"].fillna(0)]
    ax2.bar(x, report["improve_%"].fillna(0), color=colors)
    ax2.axhline(0, color="black", lw=0.8)
    ax2.set_xticks(x, report.index)
    ax2.set_ylabel("Improvement (%)  (+ = better)")
    ax2.set_title(f"{event}: improvement first→last third of sessions")
    fig.tight_layout()
    path = out_dir / f"bars_{event}.png"
    fig.savefig(path, dpi=130)
    return path


def plot_time_series(sessions: pd.DataFrame, event: str, out_dir: Path, plt) -> Path:
    """Score vs date per athlete, with dashed linear trend lines."""
    spec = EVENTS[event]
    fig, ax = plt.subplots(figsize=(10, 5))
    for aid, g in sessions[sessions["event"] == event].groupby("athlete_id"):
        g = g.sort_values("date")
        line, = ax.plot(g["date"], g["score"], marker="o", ms=4, label=aid)
        if len(g) > 1:
            xs = np.arange(len(g))
            fit = np.polyval(np.polyfit(xs, g["score"], 1), xs)
            ax.plot(g["date"], fit, "--", lw=1, color=line.get_color(), alpha=0.6)
    ax.set_xlabel("Session date")
    ax.set_ylabel(f"Score ({spec['unit']})")
    ax.set_title(f"{event}: performance over sessions (dashed = linear trend)")
    ax.grid(alpha=0.3)
    ax.legend(ncol=2, fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    path = out_dir / f"timeseries_{event}.png"
    fig.savefig(path, dpi=130)
    return path

def evaluate_event(report: pd.DataFrame, event: str) -> list[str]:
    """Narrative findings for one event."""
    spec = EVENTS[event]
    lines = []
    top = report.iloc[0]
    lines.append(f"Top performer (best {event}): {report.index[0]} with {top['best']} {spec['unit']}.")
    mr = report.sort_values("rank_mean")
    lines.append(f"Highest average level: {mr.index[0]} (mean {mr.iloc[0]['mean']} {spec['unit']}).")
    valid = report.dropna(subset=["improve_%"])
    if not valid.empty:
        bi, wi = valid["improve_%"].idxmax(), valid["improve_%"].idxmin()
        lines.append(f"Most improved: {bi} ({valid.loc[bi, 'improve_%']:+.2f}%).")
        lines.append(f"Least improved / declining: {wi} ({valid.loc[wi, 'improve_%']:+.2f}%).")
    cons = report.dropna(subset=["cv_%"])
    if not cons.empty:
        lines.append(f"Most consistent: {cons['cv_%'].idxmin()} (CV {cons['cv_%'].min():.2f}%); "
                     f"most variable: {cons['cv_%'].idxmax()} (CV {cons['cv_%'].max():.2f}%).")
    counts = report["trend"].value_counts().to_dict()
    lines.append("Trend breakdown: " + ", ".join(f"{k}: {v}" for k, v in counts.items()) + ".")
    # does the best-ranked athlete also look reliable?
    if top["cv_%"] > report["cv_%"].median():
        lines.append(f"Note: {report.index[0]}'s results are more variable than the group median - "
                     "peak result may overstate typical performance.")
    return lines

def main() -> None:
    ap = argparse.ArgumentParser(description="Sports-performance statistics explorer")
    ap.add_argument("--data-dir", default="sports_data", help="folder for athletes.json / sessions.csv")
    ap.add_argument("--out-dir", default="sports_plots", help="folder for saved plots")
    ap.add_argument("--event", choices=list(EVENTS), help="analyse a single event")
    ap.add_argument("--add", nargs=4, metavar=("ID", "EVENT", "DATE", "SCORE"),
                    help="append a validated session record, e.g. A03 100m 2025-03-01 11.42")
    ap.add_argument("--show", action="store_true", help="display plots in windows")
    ap.add_argument("--reset", action="store_true", help="regenerate sample data")
    args = ap.parse_args()

    if not args.show:
        matplotlib.use("Agg")           # headless-safe
    import matplotlib.pyplot as plt

    data_dir, out_dir = Path(args.data_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.reset or not (data_dir / SESSION_FILE).exists():
        create_sample_data(data_dir)
        print(f"[info] sample data created in '{data_dir}/'")

    athletes, rejected = load_data(data_dir)
    print(f"[info] loaded {len(athletes)} athletes; rejected {len(rejected)} invalid row(s)")
    for msg in rejected:
        print(f"   - rejected: {msg}")

    if args.add:
        aid, ev, d, sc = args.add
        try:
            append_record(athletes, data_dir, aid, ev, d, float(sc))
            print(f"[ok] added {aid} {ev} {d} {sc}")
        except ValueError as e:
            print(f"[error] record not added: {e}")

    sessions = sessions_dataframe(athletes)
    if sessions.empty:
        print("No valid data to analyse.")
        return

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print("\n=== DATASET SUMMARY ===")
    print(overall_summary(sessions))

    for event in ([args.event] if args.event else list(EVENTS)):
        report = event_report(athletes, event)
        if report.empty:
            continue
        unit = EVENTS[event]["unit"]
        print(f"\n=== EVENT REPORT: {event} ({unit}, {EVENTS[event]['better']} is better) ===")
        print(report.to_string())
        print("\nEvaluation:")
        for line in evaluate_event(report, event):
            print(f"  * {line}")
        p1 = plot_comparison_bars(report, event, out_dir, plt)
        p2 = plot_time_series(sessions, event, out_dir, plt)
        print(f"  plots saved: {p1}, {p2}")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()