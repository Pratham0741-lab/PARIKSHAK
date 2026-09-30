"""
High-Performance Database Seeder Script for ISRO SIH26170 Burn-In Screening Dataset.
Executes synthetic data generation and performs bulk batch inserts into PostgreSQL.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Reconfigure stdout/stderr for UTF-8 on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.models import BurnInReading, Component, Lot
from data_engine.physics_generator import make_generator

console = Console(highlight=False)


def clear_existing_data(session: Session) -> None:
    """Truncates existing burn-in screening tables in reverse dependency order."""
    console.print("[yellow]Clearing existing database records...[/yellow]")
    # Using cascade delete on lots removes components and readings automatically,
    # but explicit deletes ensure complete cleanup across all tables
    session.execute(delete(BurnInReading))
    session.execute(delete(Component))
    session.execute(delete(Lot))
    session.commit()
    console.print("[green]Existing data cleared successfully.[/green]")


def seed_database(
    num_lots: int = 10,
    components_per_lot: int = 100,
    random_seed: int = 42,
    batch_size: int = 2000,
    drop_existing: bool = True,
    dry_run: bool = False,
    generator: str = "legacy",
) -> Dict[str, Any]:
    """
    Generates synthetic data and seeds the PostgreSQL database using bulk insert mappings.

    Returns:
        Dict[str, Any]: Summary metrics for reporting and verification.
    """
    start_time = time.perf_counter()

    console.print(
        Panel.fit(
            f"[bold cyan]ISRO SIH26170 Burn-In Database Seeder[/bold cyan]\n"
            f"[dim]Lots: {num_lots} | Components/Lot: {components_per_lot} | "
            f"Expected Readings: {num_lots * components_per_lot * 4} | Seed: {random_seed}[/dim]",
            border_style="cyan",
        )
    )

    # 1. Run the Synthetic Generator
    console.print("[cyan]-> Emulating semiconductor physics & trajectories...[/cyan]")
    gen = make_generator(
        generator,
        num_lots=num_lots,
        components_per_lot=components_per_lot,
        random_seed=random_seed,
        leakage_max_ua=settings.DATASHEET_LEAKAGE_MAX_UA,
        iddq_max_ma=settings.DATASHEET_IDDQ_MAX_MA,
        delay_max_ns=settings.DATASHEET_DELAY_MAX_NS,
    )
    records = gen.generate_records()
    console.print("[green]✓ Physics emulation completed.[/green]")

    lots = records["lots"]
    components = records["components"]
    readings = records["readings"]

    total_lots = len(lots)
    total_components = len(components)
    total_readings = len(readings)

    if dry_run:
        console.print("[bold yellow]DRY RUN ACTIVE: Skipping database insertion.[/bold yellow]")
    else:
        # 2. Database Bulk Batch Insertion
        with SessionLocal() as session:
            try:
                if drop_existing:
                    clear_existing_data(session)

                console.print(f"[cyan]-> Bulk inserting {total_lots} lots...[/cyan]")
                session.execute(insert(Lot), lots)
                session.flush()

                console.print(f"[cyan]-> Bulk inserting {total_components} components in batches...[/cyan]")
                for i in range(0, total_components, batch_size):
                    chunk = components[i : i + batch_size]
                    session.execute(insert(Component), chunk)
                session.flush()

                console.print(f"[cyan]-> Bulk inserting {total_readings} readings in batches of {batch_size}...[/cyan]")
                for i in range(0, total_readings, batch_size):
                    chunk = readings[i : i + batch_size]
                    session.execute(insert(BurnInReading), chunk)

                session.commit()
                console.print("[bold green]✓ All records successfully committed to PostgreSQL![/bold green]")
            except Exception as e:
                session.rollback()
                console.print(f"[bold red]Database seeding failed: {e}[/bold red]")
                raise e

    elapsed_time = time.perf_counter() - start_time

    # 3. Compute and Display Summary Statistics
    summary = compute_summary_statistics(components, readings, total_lots, elapsed_time)
    display_summary(summary)

    return summary


def compute_summary_statistics(
    components: List[Dict[str, Any]],
    readings: List[Dict[str, Any]],
    total_lots: int,
    elapsed_time: float,
) -> Dict[str, Any]:
    """Calculates distribution statistics across component classes and parameters."""
    total_components = len(components)
    total_readings = len(readings)

    # Class distribution
    class_counts: Dict[str, int] = {}
    anomaly_counts = {"NORMAL": 0, "ANOMALOUS": 0}
    breach_count = 0

    for c in components:
        lbl = c["ground_truth_label"]
        class_counts[lbl] = class_counts.get(lbl, 0) + 1
        if c["ground_truth_flag"]:
            anomaly_counts["ANOMALOUS"] += 1
        else:
            anomaly_counts["NORMAL"] += 1
        if c["is_datasheet_breached"]:
            breach_count += 1

    throughput = total_readings / max(elapsed_time, 1e-3)

    return {
        "total_lots": total_lots,
        "total_components": total_components,
        "total_readings": total_readings,
        "elapsed_seconds": round(elapsed_time, 2),
        "throughput_readings_per_sec": round(throughput, 1),
        "class_counts": class_counts,
        "anomaly_counts": anomaly_counts,
        "breach_count": breach_count,
        "clean_count": total_components - breach_count,
    }


def display_summary(summary: Dict[str, Any]) -> None:
    """Renders formatted tables with rich logging."""
    # Summary Metrics Table
    meta_table = Table(title="ISRO Burn-In Dataset Seed Summary", style="cyan", show_header=True)
    meta_table.add_column("Metric", style="bold white")
    meta_table.add_column("Value", style="green")

    meta_table.add_row("Total Manufacturing Lots", str(summary["total_lots"]))
    meta_table.add_row("Total Components Tracked", f"{summary['total_components']:,}")
    meta_table.add_row("Total Parametric Readings", f"{summary['total_readings']:,}")
    meta_table.add_row("Readings per Component", "4 intervals (0h, 24h, 96h, 168h)")
    meta_table.add_row("Execution Elapsed Time", f"{summary['elapsed_seconds']} s")
    meta_table.add_row("Ingestion Throughput", f"{summary['throughput_readings_per_sec']:,} readings/s")
    meta_table.add_row("Datasheet Ceiling Breaches", f"{summary['breach_count']} (gross defects)")
    meta_table.add_row("Subtle In-Spec Screening Outliers", f"{summary['anomaly_counts']['ANOMALOUS'] - summary['breach_count']} (latent anomalies)")

    console.print(meta_table)

    # Defect Class Distribution Table
    dist_table = Table(title="Component Ground-Truth Class Distribution", style="magenta", show_header=True)
    dist_table.add_column("Ground Truth Class", style="bold")
    dist_table.add_column("Part Count", justify="right")
    dist_table.add_column("Percentage", justify="right")
    dist_table.add_column("Anomaly Flag", justify="center")
    dist_table.add_column("Physical Defect Signature", style="dim")

    signatures = {
        "NORMAL": "Stable baseline, slight infant settling, normal fab variance",
        "LEVEL_OUTLIER": "Elevated 4-6 MADs from t=0h; stationary below 50 uA",
        "STEEP_DRIFT": "Starts at baseline, progressively drifts past 35 uA by 168h",
        "LATE_DRIFT": "Flat through 96h; late oxide wear-out surge at 168h",
        "SUBTLE_MULTIVARIATE": "Simultaneous +1.8 MAD elevation across leakage, iddq, and delay",
    }

    tot = summary["total_components"]
    for label, count in sorted(summary["class_counts"].items(), key=lambda x: -x[1]):
        pct = (count / tot) * 100
        flag_str = "[red]TRUE[/red]" if label != "NORMAL" else "[green]FALSE[/green]"
        desc = signatures.get(label, "Injected synthetic defect")
        dist_table.add_row(label, f"{count:,}", f"{pct:5.2f}%", flag_str, desc)

    console.print(dist_table)


def main() -> None:
    """CLI entry point for running the seeder."""
    parser = argparse.ArgumentParser(
        description="ISRO SIH26170 Burn-In Synthetic Data Generator & Database Seeder"
    )
    parser.add_argument(
        "--lots",
        "-l",
        type=int,
        default=settings.DEFAULT_NUM_LOTS,
        help="Number of fabrication lots (default: settings.DEFAULT_NUM_LOTS)",
    )
    parser.add_argument(
        "--components",
        "-c",
        type=int,
        default=settings.DEFAULT_COMPONENTS_PER_LOT,
        help="Number of components per lot (default: 100)",
    )
    parser.add_argument(
        "--seed",
        "-s",
        type=int,
        default=settings.SYNTHETIC_RANDOM_SEED,
        help="Random seed for deterministic generation (default: 42)",
    )
    parser.add_argument(
        "--generator",
        "-g",
        choices=("physics", "legacy"),
        default=settings.DEFAULT_GENERATOR,
        help="Synthetic generator (default: settings.DEFAULT_GENERATOR = physics)",
    )
    parser.add_argument(
        "--batch-size",
        "-b",
        type=int,
        default=2000,
        help="Batch size for bulk database inserts (default: 2000)",
    )
    parser.add_argument(
        "--no-drop",
        action="store_true",
        help="Do not clear existing database tables before inserting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run generation and print statistics without writing to database",
    )

    args = parser.parse_args()

    try:
        seed_database(
            num_lots=args.lots,
            components_per_lot=args.components,
            random_seed=args.seed,
            batch_size=args.batch_size,
            drop_existing=not args.no_drop,
            dry_run=args.dry_run,
            generator=args.generator,
        )
    except Exception as exc:
        console.print(f"[bold red]Execution error: {exc}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
