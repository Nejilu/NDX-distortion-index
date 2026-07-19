"""CLI to compute snapshots once or on a daily loop."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta

from snapshot_service import recompute_all_snapshots, recompute_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calcule et enregistre le NDX-WDI.")
    parser.add_argument("--mode", choices=["auto", "live", "sample"], default=None)
    parser.add_argument(
        "--universe", choices=["all", "non_ucits", "ucits"], default="all"
    )
    parser.add_argument(
        "--basis",
        choices=["float", "total"],
        default="float",
        help="Contrefactuel: capitalisation flottante ou capitalisation cotée totale.",
    )
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--holdings-csv", default=None, help="CSV QQQ local compatible Invesco.")
    parser.add_argument("--daily", action="store_true", help="Répète le snapshot chaque jour.")
    parser.add_argument("--at", default="18:00", help="Heure locale quotidienne au format HH:MM.")
    return parser


def run_once(args: argparse.Namespace) -> None:
    if args.universe == "all":
        if args.holdings_csv:
            raise ValueError("--holdings-csv exige --universe non_ucits ou ucits.")
        outcomes = recompute_all_snapshots(
            mode=args.mode,
            db_path=args.db_path,
            weighting_basis=args.basis,
        )
        payload = {outcome.universe: outcome.summary() for outcome in outcomes}
    else:
        outcome = recompute_snapshot(
            mode=args.mode,
            db_path=args.db_path,
            holdings_csv=args.holdings_csv,
            universe=args.universe,
            weighting_basis=args.basis,
        )
        payload = outcome.summary()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def seconds_until(local_time: str, now: datetime | None = None) -> float:
    hour, minute = (int(part) for part in local_time.split(":"))
    current = now or datetime.now()
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return (target - current).total_seconds()


def main() -> None:
    args = build_parser().parse_args()
    if not args.daily:
        run_once(args)
        return
    while True:
        delay = seconds_until(args.at)
        print(f"Prochain snapshot dans {delay / 3600:.2f} heures ({args.at}, heure locale).")
        time.sleep(delay)
        try:
            run_once(args)
        except Exception as exc:
            # Keep the scheduler alive; failures remain visible in the process log.
            print(f"Échec du snapshot quotidien: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
