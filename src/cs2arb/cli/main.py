"""
CLI application for CS2 Arbitrage Bot.

Provides commands for database management, scanning, and viewing opportunities.
"""

from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..config import get_config
from ..core.arbitrage_engine import compute_csfloat_to_buff_signals, get_top_signals
from ..db import get_session, init_engine
from ..db.init_db import create_database
from ..db.models import ArbitrageSignal, BuffItem, BuffPriceSnapshot, CSFloatListing, Trade
from ..ingestion import ingest_buff_prices_once, ingest_csfloat_listings_once
from ..logging_config import setup_logging

app = typer.Typer(
    name="cs2arb",
    help="CS2 Arbitrage Bot - Find profitable arbitrage opportunities between Buff163 and CSFloat",
    add_completion=False,
)

console = Console()


@app.callback()
def main_callback():
    """Initialize logging on startup."""
    setup_logging()


@app.command("init-db")
def init_db():
    """
    Initialize the SQLite database and create all tables.
    
    Creates the data directory and database file if they don't exist.
    """
    console.print("[bold blue]Initializing database...[/bold blue]")
    
    try:
        create_database()
        console.print("[bold green]✓ Database initialized successfully![/bold green]")
    except Exception as e:
        console.print(f"[bold red]✗ Failed to initialize database: {e}[/bold red]")
        raise typer.Exit(1)


@app.command("scan-once")
def scan_once(
    buff: bool = typer.Option(True, help="Fetch Buff prices"),
    csfloat: bool = typer.Option(True, help="Fetch CSFloat listings"),
    compute: bool = typer.Option(True, help="Compute arbitrage signals"),
    max_pages: Optional[int] = typer.Option(None, help="Max Buff pages to fetch"),
):
    """
    Run a single scan cycle.
    
    Fetches prices from Buff and/or CSFloat, then computes arbitrage signals.
    """
    config = get_config()
    init_engine()
    
    console.print("[bold blue]Starting scan cycle...[/bold blue]\n")
    
    with get_session() as session:
        # Buff ingestion
        if buff:
            console.print("[yellow]Fetching Buff prices...[/yellow]")
            try:
                items, snapshots = ingest_buff_prices_once(session, config, max_pages=max_pages)
                console.print(f"[green]  ✓ Processed {items} items, {snapshots} snapshots[/green]")
            except Exception as e:
                console.print(f"[red]  ✗ Buff ingestion failed: {e}[/red]")
        
        # CSFloat ingestion
        csfloat_listings = []
        if csfloat:
            console.print("[yellow]Fetching CSFloat listings...[/yellow]")
            try:
                csfloat_listings = ingest_csfloat_listings_once(session, config)
                console.print(f"[green]  ✓ Processed {len(csfloat_listings)} listings[/green]")
            except Exception as e:
                console.print(f"[red]  ✗ CSFloat ingestion failed: {e}[/red]")
        
        # Compute signals
        if compute:
            console.print("[yellow]Computing arbitrage signals...[/yellow]")
            try:
                signals = compute_csfloat_to_buff_signals(
                    session, config, listings=csfloat_listings if csfloat_listings else None
                )
                console.print(f"[green]  ✓ Created {len(signals)} signals[/green]")
                
                # Show top signals
                if signals:
                    console.print("\n[bold]Top Opportunities:[/bold]")
                    _print_signals_table(signals[:5])
                    
            except Exception as e:
                console.print(f"[red]  ✗ Signal computation failed: {e}[/red]")
    
    console.print("\n[bold green]Scan cycle complete![/bold green]")


@app.command("list-opps")
def list_opps(
    direction: Optional[str] = typer.Option(
        None, 
        "--direction", "-d",
        help="Filter by direction (csfloat-to-buff, buff-to-csfloat)"
    ),
    min_roi: Optional[float] = typer.Option(
        None, 
        "--min-roi", "-r",
        help="Minimum ROI threshold (e.g., 0.10 for 10%)"
    ),
    limit: int = typer.Option(20, "--limit", "-l", help="Number of results to show"),
    all_signals: bool = typer.Option(False, "--all", "-a", help="Include inactive signals"),
):
    """
    List current arbitrage opportunities.
    
    Shows signals sorted by ROI, with optional filtering.
    """
    init_engine()
    
    # Map direction names
    direction_map = {
        "csfloat-to-buff": "CSFLOAT_TO_BUFF",
        "buff-to-csfloat": "BUFF_TO_CSFLOAT",
    }
    db_direction = direction_map.get(direction) if direction else None
    
    with get_session() as session:
        signals = get_top_signals(
            session,
            direction=db_direction,
            min_roi=min_roi,
            limit=limit,
            active_only=not all_signals,
        )
        
        if not signals:
            console.print("[yellow]No arbitrage opportunities found.[/yellow]")
            return
        
        _print_signals_table(signals)
        console.print(f"\n[dim]Showing {len(signals)} opportunities[/dim]")


def _print_signals_table(signals: list[ArbitrageSignal]) -> None:
    """Print a table of arbitrage signals."""
    table = Table(title="Arbitrage Opportunities", show_header=True, header_style="bold cyan")
    
    table.add_column("Direction", style="dim", width=12)
    table.add_column("Item", max_width=40)
    table.add_column("Buy ($)", justify="right", style="red")
    table.add_column("Sell ($)", justify="right", style="green")
    table.add_column("ROI", justify="right", style="bold")
    table.add_column("Age", justify="right", style="dim")
    
    for signal in signals:
        direction_short = "CF→Buff" if signal.direction == "CSFLOAT_TO_BUFF" else "Buff→CF"
        
        buy_price = signal.csfloat_price_usd if signal.direction == "CSFLOAT_TO_BUFF" else signal.buff_floor_usd
        sell_price = signal.buff_floor_usd if signal.direction == "CSFLOAT_TO_BUFF" else signal.csfloat_price_usd
        
        buy_str = f"${buy_price:.2f}" if buy_price else "—"
        sell_str = f"${sell_price:.2f}" if sell_price else "—"
        
        roi_str = f"{signal.roi_pct:.1%}"
        roi_style = "green bold" if signal.roi_pct >= 0.15 else ("yellow" if signal.roi_pct >= 0.10 else "white")
        
        age = datetime.utcnow() - signal.created_at
        if age.days > 0:
            age_str = f"{age.days}d"
        elif age.seconds > 3600:
            age_str = f"{age.seconds // 3600}h"
        else:
            age_str = f"{age.seconds // 60}m"
        
        table.add_row(
            direction_short,
            signal.market_hash_name[:40],
            buy_str,
            sell_str,
            f"[{roi_style}]{roi_str}[/{roi_style}]",
            age_str,
        )
    
    console.print(table)


@app.command("dashboard")
def dashboard(
    refresh: int = typer.Option(5, "--refresh", "-r", help="Refresh interval in seconds"),
    limit: int = typer.Option(15, "--limit", "-l", help="Number of opportunities to show"),
):
    """
    Start a live-updating terminal dashboard.
    
    Shows top arbitrage opportunities with auto-refresh.
    Press Ctrl+C to exit.
    """
    from ..dashboard.live_dashboard import run_dashboard
    
    console.print("[bold blue]Starting live dashboard...[/bold blue]")
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")
    
    try:
        run_dashboard(refresh_interval=refresh, limit=limit)
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")


@app.command("show-item")
def show_item(
    name: str = typer.Argument(..., help="Market hash name of the item"),
):
    """
    Show detailed information about a specific item.
    
    Displays Buff floor prices, CSFloat listings, and recent signals.
    """
    init_engine()
    
    with get_session() as session:
        # Find Buff item
        buff_item = session.query(BuffItem).filter(
            BuffItem.market_hash_name == name
        ).first()
        
        console.print(Panel(f"[bold]{name}[/bold]", title="Item Details"))
        
        # Buff info
        if buff_item:
            console.print("\n[bold cyan]Buff163 Data:[/bold cyan]")
            console.print(f"  Goods ID: {buff_item.goods_id}")
            console.print(f"  Weapon: {buff_item.weapon or '—'}")
            console.print(f"  Skin: {buff_item.skin_name or '—'}")
            console.print(f"  Wear: {buff_item.wear or '—'}")
            console.print(f"  Last Seen: {buff_item.last_seen_at}")
            
            # Latest snapshot
            snapshot = session.query(BuffPriceSnapshot).filter(
                BuffPriceSnapshot.goods_id == buff_item.goods_id
            ).order_by(BuffPriceSnapshot.timestamp.desc()).first()
            
            if snapshot:
                config = get_config()
                floor_usd = snapshot.overall_min_price * config.fx_cny_to_usd
                console.print(f"\n  [bold]Floor Price:[/bold]")
                console.print(f"    ¥{snapshot.overall_min_price:.2f} CNY")
                console.print(f"    ${floor_usd:.2f} USD (at {config.fx_cny_to_usd} FX)")
                console.print(f"    Updated: {snapshot.timestamp}")
        else:
            console.print("\n[yellow]No Buff data found for this item.[/yellow]")
        
        # CSFloat listings
        listings = session.query(CSFloatListing).filter(
            CSFloatListing.market_hash_name == name,
            CSFloatListing.is_active == True,
        ).order_by(CSFloatListing.price_cents.asc()).limit(5).all()
        
        if listings:
            console.print("\n[bold cyan]CSFloat Listings (active):[/bold cyan]")
            
            table = Table(show_header=True)
            table.add_column("Price", justify="right")
            table.add_column("Discount", justify="right")
            table.add_column("Float", justify="right")
            table.add_column("Seen")
            
            for listing in listings:
                discount_str = f"{listing.discount:.1%}" if listing.discount else "—"
                float_str = f"{listing.float_value:.6f}" if listing.float_value else "—"
                
                table.add_row(
                    f"${listing.price_usd:.2f}",
                    discount_str,
                    float_str,
                    listing.seen_at.strftime("%Y-%m-%d %H:%M"),
                )
            
            console.print(table)
        else:
            console.print("\n[yellow]No active CSFloat listings found.[/yellow]")
        
        # Recent signals
        signals = session.query(ArbitrageSignal).filter(
            ArbitrageSignal.market_hash_name == name,
        ).order_by(ArbitrageSignal.created_at.desc()).limit(5).all()
        
        if signals:
            console.print("\n[bold cyan]Recent Signals:[/bold cyan]")
            
            table = Table(show_header=True)
            table.add_column("Direction")
            table.add_column("ROI", justify="right")
            table.add_column("Created")
            table.add_column("Active")
            
            for signal in signals:
                direction = "CF→Buff" if signal.direction == "CSFLOAT_TO_BUFF" else "Buff→CF"
                active_str = "[green]Yes[/green]" if signal.is_active else "[dim]No[/dim]"
                
                table.add_row(
                    direction,
                    f"{signal.roi_pct:.1%}",
                    signal.created_at.strftime("%Y-%m-%d %H:%M"),
                    active_str,
                )
            
            console.print(table)


@app.command("record-trade")
def record_trade(
    direction: str = typer.Option(..., "--direction", "-d", help="Trade direction (csfloat-to-buff, buff-to-csfloat)"),
    buy_market: str = typer.Option(..., "--buy-market", "-bm", help="Market where you bought (csfloat, buff)"),
    sell_market: str = typer.Option(None, "--sell-market", "-sm", help="Market where you sold (optional if not yet sold)"),
    buy_price: float = typer.Option(..., "--buy-price", "-bp", help="Buy price in USD"),
    sell_price: Optional[float] = typer.Option(None, "--sell-price", "-sp", help="Sell price in USD (optional)"),
    item_name: Optional[str] = typer.Option(None, "--item", "-i", help="Item name (optional if signal-id provided)"),
    signal_id: Optional[int] = typer.Option(None, "--signal-id", "-s", help="Signal ID this trade is based on"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Optional note"),
):
    """
    Record a trade you've executed.
    
    Logs the trade for tracking your P&L.
    """
    init_engine()
    
    # Map direction
    direction_map = {
        "csfloat-to-buff": "CSFLOAT_TO_BUFF",
        "buff-to-csfloat": "BUFF_TO_CSFLOAT",
    }
    db_direction = direction_map.get(direction)
    if not db_direction:
        console.print(f"[red]Invalid direction: {direction}[/red]")
        raise typer.Exit(1)
    
    with get_session() as session:
        # Get item name from signal if provided
        market_hash_name = item_name
        if signal_id:
            signal = session.query(ArbitrageSignal).filter(
                ArbitrageSignal.id == signal_id
            ).first()
            if signal:
                market_hash_name = signal.market_hash_name
                # Mark signal as acted on
                signal.acted_on = True
        
        if not market_hash_name:
            console.print("[red]Must provide --item or valid --signal-id[/red]")
            raise typer.Exit(1)
        
        # Create trade
        trade = Trade(
            signal_id=signal_id,
            market_hash_name=market_hash_name,
            direction=db_direction,
            buy_market=buy_market,
            sell_market=sell_market,
            buy_price_usd=buy_price,
            sell_price_usd=sell_price,
            sell_time=datetime.utcnow() if sell_price else None,
            note=note,
        )
        session.add(trade)
        session.commit()
        
        console.print(f"[green]✓ Trade recorded (ID: {trade.id})[/green]")
        
        if trade.roi_pct is not None:
            console.print(f"  ROI: {trade.roi_pct:.1%}")
            console.print(f"  Profit: ${trade.profit_usd:.2f}")


@app.command("list-trades")
def list_trades(
    limit: int = typer.Option(50, "--limit", "-l", help="Number of trades to show"),
    open_only: bool = typer.Option(False, "--open", "-o", help="Only show open trades"),
):
    """
    List your trade history.
    
    Shows trades with ROI and profit calculations.
    """
    init_engine()
    
    with get_session() as session:
        query = session.query(Trade).order_by(Trade.buy_time.desc())
        
        if open_only:
            query = query.filter(Trade.sell_price_usd == None)
        
        trades = query.limit(limit).all()
        
        if not trades:
            console.print("[yellow]No trades found.[/yellow]")
            return
        
        table = Table(title="Trade History", show_header=True, header_style="bold cyan")
        
        table.add_column("ID", style="dim")
        table.add_column("Item", max_width=35)
        table.add_column("Dir", width=8)
        table.add_column("Buy", justify="right")
        table.add_column("Sell", justify="right")
        table.add_column("ROI", justify="right")
        table.add_column("Profit", justify="right")
        table.add_column("Status", width=8)
        
        total_profit = 0.0
        
        for trade in trades:
            direction = "CF→B" if trade.direction == "CSFLOAT_TO_BUFF" else "B→CF"
            sell_str = f"${trade.sell_price_usd:.2f}" if trade.sell_price_usd else "—"
            
            if trade.roi_pct is not None:
                roi_str = f"{trade.roi_pct:.1%}"
                profit_str = f"${trade.profit_usd:.2f}"
                status = "[green]CLOSED[/green]"
                total_profit += trade.profit_usd
            else:
                roi_str = "—"
                profit_str = "—"
                status = "[yellow]OPEN[/yellow]"
            
            table.add_row(
                str(trade.id),
                trade.market_hash_name[:35],
                direction,
                f"${trade.buy_price_usd:.2f}",
                sell_str,
                roi_str,
                profit_str,
                status,
            )
        
        console.print(table)
        
        if total_profit != 0:
            console.print(f"\n[bold]Total Realized Profit: ${total_profit:.2f}[/bold]")


@app.command("update-trade")
def update_trade(
    trade_id: int = typer.Argument(..., help="Trade ID to update"),
    sell_price: float = typer.Option(..., "--sell-price", "-sp", help="Sell price in USD"),
    sell_market: Optional[str] = typer.Option(None, "--sell-market", "-sm", help="Market where you sold"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Add/update note"),
):
    """
    Update a trade (e.g., record the sell price).
    """
    init_engine()
    
    with get_session() as session:
        trade = session.query(Trade).filter(Trade.id == trade_id).first()
        
        if not trade:
            console.print(f"[red]Trade {trade_id} not found.[/red]")
            raise typer.Exit(1)
        
        trade.sell_price_usd = sell_price
        trade.sell_time = datetime.utcnow()
        
        if sell_market:
            trade.sell_market = sell_market
        if note:
            trade.note = note
        
        session.commit()
        
        console.print(f"[green]✓ Trade {trade_id} updated[/green]")
        console.print(f"  ROI: {trade.roi_pct:.1%}")
        console.print(f"  Profit: ${trade.profit_usd:.2f}")
        console.print(f"  Hold time: {trade.hold_days} days")


if __name__ == "__main__":
    app()

