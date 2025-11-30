"""
Live terminal dashboard for CS2 Arbitrage Bot.

Uses Rich's Live display for real-time updates.
"""

import time
from datetime import datetime, timedelta

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import get_config
from ..core.arbitrage_engine import get_top_signals
from ..db import get_session, init_engine
from ..db.models import ArbitrageSignal, BuffPriceSnapshot, CSFloatListing
from ..logging_config import get_logger

logger = get_logger(__name__)
console = Console()


def create_header() -> Panel:
    """Create the dashboard header."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right")
    
    grid.add_row(
        "[bold cyan]CS2 Arbitrage Bot[/bold cyan] 🎮",
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
    )
    
    return Panel(grid, style="bold white on dark_blue", height=3)


def create_stats_panel() -> Panel:
    """Create the statistics panel."""
    init_engine()
    
    with get_session() as session:
        # Count active signals
        active_signals = session.query(ArbitrageSignal).filter(
            ArbitrageSignal.is_active == True
        ).count()
        
        # Count signals above 10% ROI
        high_roi_signals = session.query(ArbitrageSignal).filter(
            ArbitrageSignal.is_active == True,
            ArbitrageSignal.roi_pct >= 0.10,
        ).count()
        
        # Count signals above 15% ROI
        very_high_roi_signals = session.query(ArbitrageSignal).filter(
            ArbitrageSignal.is_active == True,
            ArbitrageSignal.roi_pct >= 0.15,
        ).count()
        
        # Recent snapshot count
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_snapshots = session.query(BuffPriceSnapshot).filter(
            BuffPriceSnapshot.timestamp >= one_hour_ago
        ).count()
        
        # Active CSFloat listings
        active_listings = session.query(CSFloatListing).filter(
            CSFloatListing.is_active == True
        ).count()
    
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    
    grid.add_row(
        f"[bold white]Active Signals[/bold white]\n[bold cyan]{active_signals}[/bold cyan]",
        f"[bold white]≥10% ROI[/bold white]\n[bold yellow]{high_roi_signals}[/bold yellow]",
        f"[bold white]≥15% ROI[/bold white]\n[bold green]{very_high_roi_signals}[/bold green]",
        f"[bold white]Buff Updates (1h)[/bold white]\n[bold blue]{recent_snapshots}[/bold blue]",
        f"[bold white]CSFloat Listings[/bold white]\n[bold magenta]{active_listings}[/bold magenta]",
    )
    
    return Panel(grid, title="📊 Statistics", border_style="blue")


def create_opportunities_table(limit: int = 15) -> Panel:
    """Create the arbitrage opportunities table."""
    init_engine()
    
    with get_session() as session:
        signals = get_top_signals(
            session,
            limit=limit,
            active_only=True,
        )
    
    table = Table(
        show_header=True,
        header_style="bold cyan",
        expand=True,
        box=None,
        padding=(0, 1),
    )
    
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Direction", width=10)
    table.add_column("Item", ratio=2)
    table.add_column("Buy $", justify="right", width=10)
    table.add_column("Sell $", justify="right", width=10)
    table.add_column("ROI", justify="right", width=8)
    table.add_column("Age", justify="right", width=6)
    
    if not signals:
        table.add_row(
            "",
            "",
            "[dim]No opportunities found. Run 'scan-once' to fetch data.[/dim]",
            "",
            "",
            "",
            "",
        )
    else:
        for i, signal in enumerate(signals, 1):
            direction = "CF→Buff" if signal.direction == "CSFLOAT_TO_BUFF" else "Buff→CF"
            direction_style = "cyan" if signal.direction == "CSFLOAT_TO_BUFF" else "magenta"
            
            buy_price = signal.csfloat_price_usd if signal.direction == "CSFLOAT_TO_BUFF" else signal.buff_floor_usd
            sell_price = signal.buff_floor_usd if signal.direction == "CSFLOAT_TO_BUFF" else signal.csfloat_price_usd
            
            buy_str = f"${buy_price:.2f}" if buy_price else "—"
            sell_str = f"${sell_price:.2f}" if sell_price else "—"
            
            # ROI styling
            if signal.roi_pct >= 0.20:
                roi_style = "bold green"
            elif signal.roi_pct >= 0.15:
                roi_style = "green"
            elif signal.roi_pct >= 0.10:
                roi_style = "yellow"
            else:
                roi_style = "white"
            
            roi_str = f"{signal.roi_pct:.1%}"
            
            # Age
            age = datetime.utcnow() - signal.created_at
            if age.days > 0:
                age_str = f"{age.days}d"
            elif age.seconds > 3600:
                age_str = f"{age.seconds // 3600}h"
            else:
                age_str = f"{age.seconds // 60}m"
            
            # Truncate item name
            item_name = signal.market_hash_name
            if len(item_name) > 45:
                item_name = item_name[:42] + "..."
            
            table.add_row(
                str(i),
                f"[{direction_style}]{direction}[/{direction_style}]",
                item_name,
                f"[red]{buy_str}[/red]",
                f"[green]{sell_str}[/green]",
                f"[{roi_style}]{roi_str}[/{roi_style}]",
                f"[dim]{age_str}[/dim]",
            )
    
    return Panel(
        table,
        title="💰 Top Arbitrage Opportunities",
        border_style="green",
        padding=(0, 1),
    )


def create_footer() -> Panel:
    """Create the footer with help text."""
    config = get_config()
    
    text = Text()
    text.append("FX: ", style="dim")
    text.append(f"¥1 = ${config.fx_cny_to_usd:.4f}", style="cyan")
    text.append(" | ", style="dim")
    text.append("Min ROI: ", style="dim")
    text.append(f"{config.min_roi_csfloat_to_buff:.0%}", style="yellow")
    text.append(" | ", style="dim")
    text.append("Price Range: ", style="dim")
    text.append(f"${config.min_price_usd:.0f}–${config.max_price_usd:.0f}", style="green")
    text.append(" | ", style="dim")
    text.append("Press Ctrl+C to exit", style="bold red")
    
    return Panel(text, style="dim", height=3)


def generate_dashboard(limit: int = 15) -> Group:
    """Generate the complete dashboard layout."""
    return Group(
        create_header(),
        create_stats_panel(),
        create_opportunities_table(limit=limit),
        create_footer(),
    )


def run_dashboard(refresh_interval: int = 5, limit: int = 15) -> None:
    """
    Run the live dashboard.
    
    Args:
        refresh_interval: Seconds between refreshes.
        limit: Number of opportunities to show.
    """
    init_engine()
    
    with Live(
        generate_dashboard(limit=limit),
        console=console,
        refresh_per_second=1,
        screen=True,
    ) as live:
        try:
            while True:
                time.sleep(refresh_interval)
                live.update(generate_dashboard(limit=limit))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    run_dashboard()

