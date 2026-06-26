"""
Rich-based terminal UI for the trading system.

All rendering lives here so the rest of the code deals only in data.
"""

from contextlib import contextmanager

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console(highlight=False)

ACCENT = "bright_blue"

LOGO = """\
   ███████╗████████╗ ██████╗ ██████╗ ██████╗  █████╗ ██████╗ ██████╗
   ██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗
   ███████╗   ██║   ██║   ██║██║  ██║██║  ██║███████║██████╔╝██║  ██║
   ╚════██║   ██║   ██║   ██║██║  ██║██║  ██║██╔══██║██╔══██╗██║  ██║
   ███████║   ██║   ╚██████╔╝██████╔╝██████╔╝██║  ██║██║  ██║██████╔╝
   ╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝

         ███████╗██╗███╗   ██╗ █████╗ ███╗   ██╗ ██████╗██╗ █████╗ ██╗
         ██╔════╝██║████╗  ██║██╔══██╗████╗  ██║██╔════╝██║██╔══██╗██║
         █████╗  ██║██╔██╗ ██║███████║██╔██╗ ██║██║     ██║███████║██║
         ██╔══╝  ██║██║╚██╗██║██╔══██║██║╚██╗██║██║     ██║██╔══██║██║
         ██║     ██║██║ ╚████║██║  ██║██║ ╚████║╚██████╗██║██║  ██║███████╗
         ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚═╝╚═╝  ╚═╝╚══════╝"""


def fmt_money(value: float) -> str:
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def banner(version: str):
    console.print(Text(LOGO, style=ACCENT))
    console.print(
        Text(f"\n   Trading System v{version} — natural language in, order sheets out\n",
             style="dim"))


def info(message: str):
    console.print(f"[dim]›[/] {message}")


def success(message: str):
    console.print(f"[green]✓[/] {message}")


def warn(message: str):
    console.print(f"[yellow]⚠[/] {message}")


def error(message: str):
    console.print(f"[red]✗[/] {message}")


def assistant(message: str):
    """Render an assistant reply as markdown inside a panel."""
    console.print(Panel(Markdown(message), title="Assistant",
                        title_align="left", border_style=ACCENT, padding=(0, 1)))


@contextmanager
def working(message: str = "Thinking..."):
    with console.status(f"[bold {ACCENT}]{message}[/]", spinner="dots"):
        yield


# ---------------------------------------------------------------------------
# Data views
# ---------------------------------------------------------------------------

def summary_table(accounts: dict) -> Table:
    table = Table(title="Portfolio Overview", box=box.SIMPLE_HEAVY,
                  title_style=f"bold {ACCENT}", header_style="bold")
    table.add_column("Account")
    table.add_column("Client")
    table.add_column("Total Value", justify="right")
    table.add_column("Cash", justify="right")
    table.add_column("Cash Equiv", justify="right")
    table.add_column("Positions", justify="right")

    total_all = 0.0
    for num, acct in accounts.items():
        total = acct.get_total_value()
        total_all += total
        cash_pct = acct.cash / total if total else 0
        ce = acct.get_cash_equivalents_value()
        ce_pct = ce / total if total else 0
        table.add_row(
            num,
            acct.client_name or "—",
            fmt_money(total),
            f"{fmt_money(acct.cash)} [dim]({fmt_pct(cash_pct)})[/]",
            f"{fmt_money(ce)} [dim]({fmt_pct(ce_pct)})[/]",
            str(len(acct.holdings)),
        )
    table.add_section()
    table.add_row("[bold]TOTAL[/]", "", f"[bold]{fmt_money(total_all)}[/]", "", "", "")
    return table


def holdings_view(accounts: dict) -> Group:
    """Detailed holdings, one table per account."""
    renderables = []
    for num, acct in accounts.items():
        total = acct.get_total_value()
        title = f"{num} — {acct.client_name}" if acct.client_name else num
        table = Table(title=title, box=box.SIMPLE, title_style=f"bold {ACCENT}",
                      header_style="bold")
        table.add_column("Symbol")
        table.add_column("Type", style="dim")
        table.add_column("Shares", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Value", justify="right")
        table.add_column("Alloc", justify="right")

        for h in acct.holdings:
            alloc = (h.market_value or 0) / total if total else 0
            table.add_row(h.symbol, "stock", f"{h.shares:,.0f}",
                          fmt_money(h.price or 0), fmt_money(h.market_value or 0),
                          fmt_pct(alloc))
        for ce in acct.cash_equivalents:
            alloc = (ce.market_value or 0) / total if total else 0
            table.add_row(f"[cyan]{ce.symbol}[/]", "cash equiv", f"{ce.shares:,.0f}",
                          fmt_money(ce.price or 0), fmt_money(ce.market_value or 0),
                          fmt_pct(alloc))
        cash_pct = acct.cash / total if total else 0
        table.add_row("[green]CASH[/]", "cash", "", "", fmt_money(acct.cash),
                      fmt_pct(cash_pct))
        renderables.append(table)
    return Group(*renderables)


def buy_list_table(buy_list: list, prices: dict, as_of: str = "") -> Table:
    title = f"Buy List [dim]· prices as of {as_of}[/]" if as_of else "Buy List"
    table = Table(title=title, box=box.SIMPLE_HEAVY,
                  title_style=f"bold {ACCENT}", header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Ticker")
    table.add_column("Price", justify="right")
    for i, ticker in enumerate(buy_list, 1):
        table.add_row(str(i), ticker, fmt_money(prices.get(ticker, 0)))
    if not buy_list:
        table.add_row("", "[dim]empty — add with: add TICKER PRICE[/]", "")
    return table


# ---------------------------------------------------------------------------
# Trade preview / confirmation
# ---------------------------------------------------------------------------

def orders_preview(plan_description: str, analyses: list,
                   sell_orders: list, buy_orders: list,
                   alerts: list = None, diff: str = None) -> Panel:
    """Compact preview of a proposed trade, shown before confirmation."""
    sell_total = sum(o.estimated_value for o in sell_orders)
    buy_total = sum(o.estimated_value for o in buy_orders)

    header = Table.grid(padding=(0, 2))
    header.add_column(style="dim")
    header.add_column()
    header.add_row("Plan", plan_description)
    header.add_row("Accounts", str(len(analyses)))
    header.add_row("Sells", f"{len(sell_orders)} orders · {fmt_money(sell_total)}")
    header.add_row("Buys", f"{len(buy_orders)} orders · {fmt_money(buy_total)}")
    if diff:
        header.add_row("Changes", f"[cyan]{diff}[/]")

    renderables = [header]

    if alerts:
        alert_text = Text()
        alert_text.append("PRE-FLIGHT CHECKS\n", style="bold red")
        for a in alerts:
            alert_text.append(f"● {a}\n", style="red")
        renderables.append(alert_text)

    by_account = {}
    for o in sell_orders + buy_orders:
        by_account.setdefault((o.account_num, o.client_name), []).append(o)

    if by_account:
        table = Table(box=box.SIMPLE, header_style="bold", expand=False)
        table.add_column("Account")
        table.add_column("Action")
        table.add_column("Ticker")
        table.add_column("Shares", justify="right")
        table.add_column("Est. Value", justify="right")
        for (num, name), orders in by_account.items():
            label = f"{num} [dim]{name}[/]" if name else num
            first = True
            for o in orders:
                style = "red" if o.action == "Sell" else "green"
                table.add_row(
                    label if first else "",
                    f"[{style}]{o.action.upper()}[/]",
                    o.security,
                    f"{o.shares:,}",
                    fmt_money(o.estimated_value),
                )
                first = False
        renderables.append(table)

    warnings = [w for a in analyses for w in a.warnings]
    if warnings:
        warn_text = Text()
        for w in warnings[:12]:
            warn_text.append(f"⚠ {w}\n", style="yellow")
        if len(warnings) > 12:
            warn_text.append(f"… and {len(warnings) - 12} more warnings", style="dim")
        renderables.append(warn_text)

    return Panel(Group(*renderables), title="Proposed Trades", title_align="left",
                 border_style="yellow", padding=(0, 1))


def export_result(folder: str, n_sells: int, n_buys: int) -> Panel:
    body = Table.grid(padding=(0, 2))
    body.add_column(style="dim")
    body.add_column()
    body.add_row("Folder", folder)
    body.add_row("sell_order.csv", f"{n_sells} orders  [dim](execute these FIRST)[/]")
    body.add_row("buy_order.csv", f"{n_buys} orders  [dim](execute after sells settle)[/]")
    body.add_row("trade_report.txt", "full audit report")
    return Panel(body, title="✓ Orders Exported", title_align="left",
                 border_style="green", padding=(0, 1))


HELP_TEXT = """\
**Talk to me in plain English** — for example:

- `Buy everything on the buy list at 2.5%, skip if I already own 2%`
- `Sell all LUMN and COMM, put the proceeds into GOOGL`
- `Raise $50,000 in cash, don't touch the Smith accounts`
- `How does the cash floor work?`

**Instant commands** (no AI involved):

| Command | What it does |
|---|---|
| `summary` | Portfolio overview by account |
| `holdings` | Detailed positions for every account |
| `buy list` / `prices` | Show the buy list with prices |
| `refresh prices` | Pull live prices for the buy list |
| `add TICKER PRICE` | Add a ticker to the buy list |
| `update TICKER PRICE` | Change a ticker's price |
| `remove TICKER` | Remove a ticker from the buy list |
| `default` | Run the default trade specification |
| `api key` | Show / set your Anthropic API key |
| `help` | This message |
| `exit` | Quit |

Proposed trades are **never executed automatically** — you'll always see a preview
and confirm with yes/no before any order files are written. Instead of answering
yes/no you can also revise the proposal ("make it 3%", "skip the Smith accounts")
and the new preview will show what changed.
"""


def help_panel() -> Panel:
    return Panel(Markdown(HELP_TEXT), title="Help", title_align="left",
                 border_style=ACCENT, padding=(0, 1))
