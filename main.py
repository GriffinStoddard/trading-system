#!/usr/bin/env python3
"""
Trading System - Main CLI Application

A financial advisor tool that uses an LLM to interpret natural language trading
specifications and generate buy/sell order sheets.

Usage:
    python main.py
    
Or run the compiled executable:
    trading_system.exe
"""

import os
import sys
import pandas as pd
from datetime import datetime
from pathlib import Path

from models import AccountParser
from execution_plan import (
    ExecutionPlan, BuyRule, SellRule, CashManagement,
    QuantityType, AllocationMethod, CashSource
)
from order_generator import OrderGenerator, Order
from report_generator import generate_summary_report, print_confirmation_prompt
from config import load_config, save_config, get_api_key


# Version info
VERSION = "2.0.0"


def get_friendly_error_message(error: Exception) -> str:
    """Convert an exception into a user-friendly error message."""
    error_str = str(error).lower()
    error_type = type(error).__name__

    # Excel/file reading errors
    if "no such file" in error_str or "file not found" in error_str or isinstance(error, FileNotFoundError):
        return "Could not find the specified file. Please check that the file exists and the path is correct."

    if "permission denied" in error_str or isinstance(error, PermissionError):
        return "Permission denied. The file may be open in another program (like Excel). Please close it and try again."

    if "account number" in error_str:
        return "The Excel file is missing the required 'Account Number' column. Please check your file format."

    if "symbol" in error_str and "cusip" in error_str:
        return "The Excel file is missing the required 'Symbol / CUSIP / ID' column. Please check your file format."

    if "quantity" in error_str:
        return "The Excel file is missing the required 'Quantity' column. Please check your file format."

    if "price" in error_str and "nav" in error_str:
        return "The Excel file is missing the required 'Price / NAV' column. Please check your file format."

    if "market value" in error_str:
        return "The Excel file is missing the required 'Market Value' column. Please check your file format."

    if "worksheet" in error_str or "sheet" in error_str:
        return "Could not read the Excel worksheet. Please make sure the file is a valid Excel file (.xlsx)."

    if isinstance(error, pd.errors.EmptyDataError):
        return "The file appears to be empty. Please check that it contains data."

    if "ticker" in error_str or "price" in error_str:
        return "Error reading the stock prices file. Please make sure it has 'TICKER' and 'PRICE' columns."

    # API/Network errors
    if "api" in error_str or "unauthorized" in error_str or "authentication" in error_str:
        return "API authentication failed. Please check that your API key in config.json is correct."

    if "connection" in error_str or "network" in error_str or "timeout" in error_str:
        return "Network connection error. Please check your internet connection and try again."

    if "rate limit" in error_str:
        return "API rate limit reached. Please wait a moment and try again."

    # JSON/Config errors
    if "json" in error_str or isinstance(error, (ValueError,)) and "json" in error_type.lower():
        return "Configuration file error. The config.json file may be corrupted. Try deleting it to reset to defaults."

    # Generic fallback with the actual error for unknown cases
    return f"An error occurred: {error}"


def get_base_path() -> Path:
    """Get the base path for finding data files."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        return Path(sys.executable).parent
    else:
        # Running as script
        return Path(__file__).parent


def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def display_header():
    """Display the program header."""
    print("\n" + "=" * 80)
    print(f"   TRADING SYSTEM v{VERSION} - LLM-Powered Order Generation")
    print("   Natural Language → Structured Trades")
    print("=" * 80)


def load_stock_prices(prices_file: str) -> tuple[dict[str, float], list[str]]:
    """Load stock prices from CSV file."""
    base_path = get_base_path()
    full_path = base_path / prices_file
    
    if not full_path.exists():
        print(f"Warning: Prices file '{full_path}' not found.")
        return {}, []
    
    df = pd.read_csv(full_path)
    prices = {}
    buy_list = []
    
    for _, row in df.iterrows():
        ticker = str(row['TICKER']).strip().upper()
        try:
            price = float(row['PRICE'])
            if price > 0:
                prices[ticker] = price
                buy_list.append(ticker)
        except (ValueError, TypeError):
            pass
    
    return prices, buy_list


def display_account_summary(accounts: dict):
    """Display a summary of all accounts."""
    print("\n" + "=" * 80)
    print("PORTFOLIO OVERVIEW")
    print("=" * 80)
    
    total_value_all = 0
    
    for account_num, account in accounts.items():
        total_value = account.get_total_value()
        cash = account.cash
        ce_value = account.get_cash_equivalents_value()
        
        name_str = f" ({account.client_name})" if account.client_name else ""
        
        print(f"\nAccount {account_num}{name_str}:")
        print(f"  Total Value: ${total_value:,.2f}")
        print(f"  Cash: ${cash:,.2f} ({cash/total_value*100:.1f}%)")
        print(f"  Cash Equivalents: ${ce_value:,.2f} ({ce_value/total_value*100:.1f}%)")
        print(f"  Holdings: {len(account.holdings)} positions")
        
        total_value_all += total_value
    
    print(f"\n{'=' * 40}")
    print(f"TOTAL PORTFOLIO VALUE: ${total_value_all:,.2f}")
    print("=" * 80)


def display_detailed_holdings(accounts: dict):
    """Display detailed holdings for all accounts."""
    print("\n" + "=" * 80)
    print("DETAILED HOLDINGS")
    print("=" * 80)
    
    for account_num, account in accounts.items():
        name_str = f" - {account.client_name}" if account.client_name else ""
        print(f"\n--- Account {account_num}{name_str} ---")
        total = account.get_total_value()
        
        if account.holdings:
            print("\n  Stock Holdings:")
            print(f"  {'Symbol':<10} {'Shares':<12} {'Price':<12} {'Value':<15} {'Alloc':<8}")
            print(f"  {'-' * 57}")
            
            for h in account.holdings:
                alloc = (h.market_value or 0) / total * 100 if total > 0 else 0
                print(f"  {h.symbol:<10} {h.shares:<12,.0f} ${h.price or 0:<10,.2f} ${h.market_value or 0:<13,.2f} {alloc:.1f}%")
        
        if account.cash_equivalents:
            print("\n  Cash Equivalents:")
            print(f"  {'Symbol':<10} {'Shares':<12} {'Price':<12} {'Value':<15} {'Alloc':<8}")
            print(f"  {'-' * 57}")
            
            for ce in account.cash_equivalents:
                alloc = (ce.market_value or 0) / total * 100 if total > 0 else 0
                print(f"  {ce.symbol:<10} {ce.shares:<12,.0f} ${ce.price or 0:<10,.2f} ${ce.market_value or 0:<13,.2f} {alloc:.1f}%")
        
        print(f"\n  Cash Balance: ${account.cash:,.2f}")


def display_buy_list(buy_list: list[str], stock_prices: dict[str, float]):
    """Display the current buy list with prices."""
    print("\n" + "-" * 40)
    print("CURRENT BUY LIST")
    print("-" * 40)
    
    if not buy_list:
        print("No stocks in buy list.")
        return
    
    print(f"{'#':<4} {'Ticker':<10} {'Price':<12}")
    print("-" * 26)
    
    for i, ticker in enumerate(buy_list, 1):
        price = stock_prices.get(ticker, 0)
        print(f"{i:<4} {ticker:<10} ${price:,.2f}")


def get_specification_from_user() -> str:
    """Get the trading specification from the user."""
    print("\n" + "=" * 80)
    print("ENTER TRADING SPECIFICATION")
    print("=" * 80)
    print("\nDescribe what you want to do in natural language.")
    print("Examples:")
    print("  - 'Buy 2.5% of each stock, skip if already own 2%, sell cash equivalents if needed'")
    print("  - 'Sell all LUMN and COMM, buy GOOGL with proceeds'")
    print("  - 'Raise $50,000 cash by selling largest positions first'")
    print("\nEnter your specification (or 'cancel' to go back):")
    print("-" * 80)
    
    lines = []
    print("> ", end="")
    while True:
        line = input()
        if line.lower() == 'cancel':
            return ""
        if line == "":
            break
        lines.append(line)
        print("  ", end="")
    
    return " ".join(lines)


def create_default_plan(buy_list: list[str], config: dict) -> ExecutionPlan:
    """
    Create the default execution plan based on config settings.
    """
    target_alloc = config.get("default_target_allocation_percent", 0.025)
    skip_above = config.get("default_skip_if_above_percent", 0.02)
    cash_floor = config.get("default_cash_floor_percent", 0.02)
    
    return ExecutionPlan(
        description=f"Buy to {target_alloc*100}% target allocation per stock. Skip if >= {skip_above*100}% owned. "
                    f"Sell cash equivalents (largest first) if needed. Maintain {cash_floor*100}% cash floor.",
        buy_rules=[
            BuyRule(
                tickers=buy_list,
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=target_alloc,
                allocation_method=AllocationMethod.EQUAL_WEIGHT,
                skip_if_allocation_above=skip_above,
                buy_only_to_target=True,
                cash_source=CashSource.CASH_EQUIVALENTS,
                sell_cash_equiv_if_needed=True
            )
        ],
        cash_management=CashManagement(
            min_cash_percent=cash_floor,
            cash_equiv_sell_order="largest_first"
        )
    )


def execute_with_plan(
    accounts: dict,
    stock_prices: dict[str, float],
    plan: ExecutionPlan
) -> tuple[list[Order], list[Order], list]:
    """Execute an execution plan and generate orders."""
    generator = OrderGenerator(accounts, stock_prices)
    sell_orders, buy_orders = generator.execute_plan(plan)
    return sell_orders, buy_orders, generator.get_analyses()


def export_orders(
    sell_orders: list[Order],
    buy_orders: list[Order],
    output_prefix: str = None
) -> tuple[str, str]:
    """Export orders to CSV files."""
    base_path = get_base_path()

    date_str = datetime.now().strftime("%m-%d-%Y")

    sell_filename = f"sell_order_{date_str}.csv"
    buy_filename = f"buy_order_{date_str}.csv"
    
    sell_path = base_path / sell_filename
    buy_path = base_path / buy_filename
    
    # Export sell orders
    if sell_orders:
        sell_data = [{
            'Account Number': o.account_num,
            'Security': o.security,
            'Action': o.action,
            'Share Quantity': o.shares,
            'Dollar Amount': ''
        } for o in sell_orders]
        pd.DataFrame(sell_data).to_csv(sell_path, index=False)
    else:
        pd.DataFrame(columns=['Account Number', 'Security', 'Action', 'Share Quantity', 'Dollar Amount']).to_csv(sell_path, index=False)
    
    # Export buy orders
    if buy_orders:
        buy_data = [{
            'Account Number': o.account_num,
            'Security': o.security,
            'Action': o.action,
            'Share Quantity': o.shares,
            'Dollar Amount': ''
        } for o in buy_orders]
        pd.DataFrame(buy_data).to_csv(buy_path, index=False)
    else:
        pd.DataFrame(columns=['Account Number', 'Security', 'Action', 'Share Quantity', 'Dollar Amount']).to_csv(buy_path, index=False)
    
    return sell_filename, buy_filename


def run_trade_workflow(accounts: dict, stock_prices: dict[str, float], buy_list: list[str], config: dict):
    """Run the main trade generation workflow."""
    
    # Show current buy list
    display_buy_list(buy_list, stock_prices)
    
    print("\n" + "-" * 80)
    print("SELECT MODE")
    print("-" * 80)
    print("1. Use default specification (from config.json)")
    print("2. Enter custom specification (requires API key)")
    print("3. Cancel")
    
    choice = input("\nSelect option: ").strip()
    
    if choice == '3':
        return
    
    if choice == '2':
        # Check for API key
        api_key = get_api_key()
        if not api_key:
            print("\n⚠ No API key found in config.json")
            print("Please add your Anthropic API key to config.json")
            print("\nFalling back to default specification.")
            choice = '1'
    
    # Get the execution plan
    if choice == '1':
        plan = create_default_plan(buy_list, config)
        print(f"\nUsing default plan: {plan.description}")
    else:
        spec = get_specification_from_user()
        if not spec:
            print("Cancelled.")
            return
        
        print("\nInterpreting specification with LLM...")
        try:
            from llm_interpreter import interpret_specification
            plan = interpret_specification(spec, accounts, buy_list, stock_prices)
            print(f"\nInterpreted as: {plan.description}")
        except Exception as e:
            print(f"\nFailed to interpret specification: {get_friendly_error_message(e)}")
            print("Falling back to default plan.")
            plan = create_default_plan(buy_list, config)
    
    # Execute the plan
    print("\nGenerating orders...")
    sell_orders, buy_orders, analyses = execute_with_plan(accounts, stock_prices, plan)
    
    # Show confirmation
    confirmation = print_confirmation_prompt(plan.description, analyses, sell_orders, buy_orders)
    print(confirmation)
    
    if not sell_orders and not buy_orders:
        print("\nNo orders were generated. Nothing to do.")
        return
    
    # Ask for confirmation
    confirm = input("\nProceed with export? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return
    
    # Export orders
    sell_file, buy_file = export_orders(sell_orders, buy_orders)
    
    # Generate and print the full report
    report = generate_summary_report(
        analyses, sell_orders, buy_orders,
        plan.description, sell_file, buy_file
    )
    print(report)
    
    # Also save report to file
    base_path = get_base_path()
    date_str = datetime.now().strftime("%m-%d-%Y")
    report_file = f"trade_report_{date_str}.txt"
    report_path = base_path / report_file
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\nReport saved to: {report_file}")


def manage_prices_menu(prices_file: str):
    """Menu for managing the stock prices CSV file."""
    base_path = get_base_path()
    full_path = base_path / prices_file
    
    while True:
        print("\n" + "-" * 40)
        print("PRICE MANAGEMENT")
        print("-" * 40)
        print("1. View current prices")
        print("2. Add new ticker")
        print("3. Update ticker price")
        print("4. Remove ticker")
        print("5. Back to main menu")
        
        choice = input("\nSelect option: ").strip()
        
        if choice == '1':
            if full_path.exists():
                df = pd.read_csv(full_path)
                print(f"\nCurrent stock prices ({prices_file}):")
                print(f"\n{'#':<4} {'TICKER':<10} {'PRICE':<12}")
                print("-" * 26)
                for i, row in df.iterrows():
                    print(f"{i+1:<4} {row['TICKER']:<10} ${row['PRICE']:<11,.2f}")
            else:
                print(f"\nPrices file not found: {prices_file}")
        
        elif choice == '2':
            ticker = input("Enter ticker symbol: ").strip().upper()
            try:
                price = float(input("Enter price: $").strip())
                
                if full_path.exists():
                    df = pd.read_csv(full_path)
                else:
                    df = pd.DataFrame(columns=['TICKER', 'PRICE'])
                
                if ticker in df['TICKER'].values:
                    print(f"Ticker {ticker} already exists. Use 'Update' to change price.")
                else:
                    new_row = pd.DataFrame({'TICKER': [ticker], 'PRICE': [price]})
                    df = pd.concat([df, new_row], ignore_index=True)
                    df.to_csv(full_path, index=False)
                    print(f"Added {ticker} at ${price:.2f}")
            except ValueError:
                print("Invalid price entered.")
        
        elif choice == '3':
            if full_path.exists():
                df = pd.read_csv(full_path)
                ticker = input("Enter ticker to update: ").strip().upper()
                
                if ticker in df['TICKER'].values:
                    try:
                        new_price = float(input(f"Enter new price for {ticker}: $").strip())
                        df.loc[df['TICKER'] == ticker, 'PRICE'] = new_price
                        df.to_csv(full_path, index=False)
                        print(f"Updated {ticker} to ${new_price:.2f}")
                    except ValueError:
                        print("Invalid price entered.")
                else:
                    print(f"Ticker {ticker} not found.")
            else:
                print("Prices file not found.")
        
        elif choice == '4':
            if full_path.exists():
                df = pd.read_csv(full_path)
                ticker = input("Enter ticker to remove: ").strip().upper()
                
                if ticker in df['TICKER'].values:
                    df = df[df['TICKER'] != ticker]
                    df.to_csv(full_path, index=False)
                    print(f"Removed {ticker}")
                else:
                    print(f"Ticker {ticker} not found.")
            else:
                print("Prices file not found.")
        
        elif choice == '5':
            break


def configure_api_key():
    """Menu option to configure the API key."""
    print("\n" + "-" * 40)
    print("API KEY CONFIGURATION")
    print("-" * 40)
    
    current_key = get_api_key()
    if current_key:
        masked = current_key[:10] + "..." + current_key[-4:]
        print(f"Current API key: {masked}")
    else:
        print("No API key configured.")
    
    print("\nOptions:")
    print("1. Enter new API key")
    print("2. Clear API key")
    print("3. Back")
    
    choice = input("\nSelect option: ").strip()
    
    if choice == '1':
        new_key = input("Enter Anthropic API key: ").strip()
        if new_key:
            from config import set_api_key
            if set_api_key(new_key):
                print("API key saved to config.json")
            else:
                print("Failed to save API key.")
    elif choice == '2':
        from config import set_api_key
        set_api_key("")
        print("API key cleared.")


def main():
    """Main program entry point - v2.0 Conversational Mode."""
    display_header()

    # Load configuration
    config = load_config()
    excel_file = config.get("default_excel_file", "investment_data.xlsx")
    prices_file = config.get("default_prices_file", "stock_prices.csv")

    base_path = get_base_path()
    excel_path = base_path / excel_file

    # Check for Excel file
    if not excel_path.exists():
        print(f"\nError: Investment data file '{excel_file}' not found.")
        print(f"Please place the file in: {base_path}")
        print("\nRequired columns:")
        print("  - Account Number")
        print("  - Account Name (optional, also accepts 'Client Name')")
        print("  - Symbol / CUSIP / ID")
        print("  - Quantity")
        print("  - Price / NAV")
        print("  - Market Value")
        input("\nPress Enter to exit...")
        return

    try:
        # Parse accounts
        print(f"\nLoading data from: {excel_file}")
        parser = AccountParser(str(excel_path))
        accounts = parser.parse_accounts()

        if not accounts:
            print("Error: No accounts found in the Excel file.")
            input("\nPress Enter to exit...")
            return

        print(f"Successfully loaded {len(accounts)} account(s)")

        # Load prices
        stock_prices, buy_list = load_stock_prices(prices_file)
        print(f"Loaded {len(stock_prices)} stock prices from {prices_file}")

    except Exception as e:
        print(f"\nError loading data: {get_friendly_error_message(e)}")
        input("\nPress Enter to exit...")
        return

    # Check for API key - required for AI agent mode
    from config import get_api_key, set_api_key
    api_key = get_api_key()

    if not api_key:
        print("\n" + "=" * 70)
        print("   API KEY REQUIRED")
        print("=" * 70)
        print("\nThis program requires an Anthropic API key to function.")
        print("You can get one from: https://console.anthropic.com/")
        print("\nEnter your API key (or 'exit' to quit):")

        while not api_key:
            key_input = input("> ").strip()

            if key_input.lower() in ['exit', 'quit', 'q']:
                print("\nExiting. Goodbye!")
                return

            if len(key_input) < 20:
                print("That doesn't look like a valid API key. Please try again:")
                continue

            # Try to validate the key by making a simple API call
            print("Validating API key...")
            try:
                import anthropic
            except ImportError:
                print("Error: anthropic package not installed. Run: pip install anthropic")
                return

            try:
                client = anthropic.Anthropic(api_key=key_input)
                # Make a minimal API call to validate
                client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hi"}]
                )
                api_key = key_input
                set_api_key(api_key)
                print("API key validated and saved!")
            except anthropic.AuthenticationError:
                print("Invalid API key. Please check and try again:")
            except Exception as e:
                print(f"Error validating key: {e}")
                print("Please try again:")

    # Initialize conversational agent
    from conversation_agent import ConversationAgent
    agent = ConversationAgent(accounts, stock_prices, buy_list, config)
    agent.api_key = api_key  # Ensure agent has the key

    # Set up export callback
    agent.export_orders_callback = export_orders

    # Welcome message
    print(agent.get_welcome_message())

    # Conversation loop
    while True:
        try:
            print()  # Blank line before prompt
            user_input = input("You: ").strip()
            if not user_input:
                continue

            print("\nProcessing...")
            response = agent.chat(user_input)
            print(f"\nAssistant: {response}")

            if agent.should_exit:
                break

        except EOFError:
            # Handle Ctrl+D
            print("\n\nExiting. Goodbye!")
            break


def main_menu_mode():
    """Legacy menu-driven mode (v1.x compatibility)."""
    display_header()

    # Load configuration
    config = load_config()
    excel_file = config.get("default_excel_file", "investment_data.xlsx")
    prices_file = config.get("default_prices_file", "stock_prices.csv")

    base_path = get_base_path()
    excel_path = base_path / excel_file

    # Check for Excel file
    if not excel_path.exists():
        print(f"\nError: Investment data file '{excel_file}' not found.")
        print(f"Please place the file in: {base_path}")
        print("\nRequired columns:")
        print("  - Account Number")
        print("  - Account Name (optional, also accepts 'Client Name')")
        print("  - Symbol / CUSIP / ID")
        print("  - Quantity")
        print("  - Price / NAV")
        print("  - Market Value")
        input("\nPress Enter to exit...")
        return

    try:
        # Parse accounts
        print(f"\nLoading data from: {excel_file}")
        parser = AccountParser(str(excel_path))
        accounts = parser.parse_accounts()

        if not accounts:
            print("Error: No accounts found in the Excel file.")
            input("\nPress Enter to exit...")
            return

        print(f"Successfully loaded {len(accounts)} account(s)")

        # Load prices
        stock_prices, buy_list = load_stock_prices(prices_file)
        print(f"Loaded {len(stock_prices)} stock prices from {prices_file}")

        # Display initial summary
        display_account_summary(accounts)

    except Exception as e:
        print(f"\nError loading data: {get_friendly_error_message(e)}")
        input("\nPress Enter to exit...")
        return

    # Main menu loop
    while True:
        print("\n" + "-" * 80)
        print("MAIN MENU")
        print("-" * 80)
        print("1. Trade    - Generate buy/sell orders")
        print("2. View     - Display detailed holdings")
        print("3. Prices   - Manage stock prices/buy list")
        print("4. Summary  - Show account summary")
        print("5. Settings - Configure API key")
        print("6. Exit")
        print("-" * 80)

        action = input("Select option (1-6): ").strip()

        if action == '1':
            # Reload prices in case they changed
            stock_prices, buy_list = load_stock_prices(prices_file)
            if not buy_list:
                print("\n! No stocks in buy list. Add stocks via 'Prices' menu first.")
                continue
            run_trade_workflow(accounts, stock_prices, buy_list, config)

        elif action == '2':
            display_detailed_holdings(accounts)

        elif action == '3':
            manage_prices_menu(prices_file)
            # Reload after changes
            stock_prices, buy_list = load_stock_prices(prices_file)

        elif action == '4':
            display_account_summary(accounts)

        elif action == '5':
            configure_api_key()
            # Reload config
            config = load_config()

        elif action == '6':
            print("\nExiting. Goodbye!")
            break

        else:
            print("Invalid option. Please select 1-6.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProgram interrupted. Exiting...")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {get_friendly_error_message(e)}")
        input("\nPress Enter to exit...")
        sys.exit(1)
