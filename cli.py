import sys
import os
import argparse
import asyncio
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TimeRemainingColumn

from backend.config import config
from backend.system_check import run_system_diagnostics
from backend.metadata import parse_track_batch, parse_track_input
from backend.downloader import MusicExtractionPipeline

console = Console()

async def run_cli_extraction(input_file: str = None, track_queries: list = None):
    console.print(Panel.fit(
        "[bold cyan]Mp3Zip - Studio Audio Extractor & MP3 Transcoder[/bold cyan]\n"
        "[dim]High-Fidelity LAME VBR V0 Studio Master Pipeline[/dim]",
        border_style="cyan"
    ))

    # Run system check
    diag = run_system_diagnostics()
    if not diag["ready"]:
        console.print("[bold red]Dependency Warning:[/bold red]")
        for item in diag["troubleshooting"]:
            console.print(f"  • {item}")
        sys.exit(1)
    
    console.print("[green]✔ FFmpeg, FFprobe & libmp3lame verified OK.[/green]\n")

    tracks_to_process = []
    if input_file:
        p = Path(input_file)
        if not p.exists():
            console.print(f"[red]Input file not found: {input_file}[/red]")
            return
        content = p.read_text(encoding="utf-8", errors="replace")
        tracks_to_process = parse_track_batch(content)
    elif track_queries:
        for q in track_queries:
            tracks_to_process.append(parse_track_input(q))

    if not tracks_to_process:
        console.print("[yellow]No tracks specified to extract.[/yellow]")
        return

    table = Table(title="Tracks to Extract", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Artist", style="bold green")
    table.add_column("Title", style="bold white")
    table.add_column("Album", style="cyan")
    table.add_column("Search Query Target", style="dim yellow")

    for i, t in enumerate(tracks_to_process, 1):
        table.add_row(str(i), t.artist, t.title, t.album, t.get_search_query())

    console.print(table)
    console.print(f"\n[bold]Target Library:[/bold] [cyan]{config.resolve_output_path()}[/cyan]")
    console.print(f"[bold]Quality Preset:[/bold] [green]MP3 VBR V0 (~245 kbps, 44.1 kHz)[/green]\n")

    pipeline = MusicExtractionPipeline()

    for idx, track in enumerate(tracks_to_process, 1):
        console.print(f"[bold cyan][{idx}/{len(tracks_to_process)}][/bold cyan] Processing: [bold white]{track.artist} - {track.title}[/bold white]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Initializing...", total=100)

            def _cli_hook(data):
                stage = data.get("stage", "Working")
                pct = data.get("progress_percent", 0.0)
                speed = data.get("speed_str", "")
                progress.update(task, completed=pct, description=f"[cyan]{stage}[/cyan] ({speed})")

            job_id = f"cli-{idx}"
            result = await pipeline.execute(job_id, track, progress_callback=_cli_hook)

            if result.get("success"):
                progress.update(task, completed=100, description="[bold green]Completed[/bold green]")
                console.print(f"  [green]✔ Saved to:[/green] {result.get('final_path')} ({result.get('file_size_formatted')})\n")
            else:
                progress.update(task, completed=0, description="[bold red]Failed[/bold red]")
                console.print(f"  [red]✖ Error:[/red] {result.get('error')}\n")

    console.print("[bold green]All extraction jobs processed.[/bold green]")

def main():
    parser = argparse.ArgumentParser(description="Mp3Zip Studio Music Extraction CLI")
    parser.add_argument("-f", "--file", help="Path to text or CSV file with track list")
    parser.add_argument("-t", "--track", nargs="+", help="One or more track titles to extract (e.g. 'Daft Punk - Get Lucky')")
    parser.add_argument("-o", "--output", help="Output directory path")
    
    args = parser.parse_args()

    if args.output:
        config.output_dir = args.output

    if not args.file and not args.track:
        parser.print_help()
        sys.exit(1)

    asyncio.run(run_cli_extraction(input_file=args.file, track_queries=args.track))

if __name__ == "__main__":
    main()
