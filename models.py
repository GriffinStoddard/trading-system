"""
Data models for the trading system.
Handles account parsing, holdings, and cash management.
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Holding:
    """Represents a stock or cash equivalent holding."""
    symbol: str
    shares: float
    price: Optional[float] = None
    market_value: Optional[float] = None


@dataclass
class Account:
    """Represents an investment account with holdings, cash, and cash equivalents."""
    account_num: str
    client_name: str = ""
    holdings: list = field(default_factory=list)
    cash: float = 0.0
    cash_equivalents: list = field(default_factory=list)

    def add_holding(self, holding: Holding):
        self.holdings.append(holding)
    
    def add_cash_equivalent(self, holding: Holding):
        self.cash_equivalents.append(holding)
    
    def get_cash_equivalents_value(self) -> float:
        return sum(ce.market_value or 0 for ce in self.cash_equivalents)
    
    def get_holdings_value(self) -> float:
        return sum(h.market_value or 0 for h in self.holdings)
    
    def get_total_value(self) -> float:
        return self.cash + self.get_cash_equivalents_value() + self.get_holdings_value()
    
    def get_holding(self, symbol: str) -> Optional[Holding]:
        """Get a specific holding by symbol."""
        symbol = symbol.upper()
        for h in self.holdings:
            if h.symbol.upper() == symbol:
                return h
        return None
    
    def get_holding_allocation(self, symbol: str) -> float:
        """Get the current allocation percentage for a holding."""
        total = self.get_total_value()
        if total == 0:
            return 0.0
        holding = self.get_holding(symbol)
        if holding and holding.market_value:
            return holding.market_value / total
        return 0.0
    
    def get_cash_equivalent(self, symbol: str) -> Optional[Holding]:
        """Get a specific cash equivalent by symbol."""
        symbol = symbol.upper()
        for ce in self.cash_equivalents:
            if ce.symbol.upper() == symbol:
                return ce
        return None


class AccountParser:
    """Parser to read Excel files and create Account objects."""

    def __init__(self, excel_file_path: str):
        self.excel_file_path = excel_file_path
        self.accounts: dict[str, Account] = {}
        # Load cash equivalents from config
        from config import get_cash_equivalents
        self.cash_equivalents = set(get_cash_equivalents())
    
    # Column name variations we accept
    ACCOUNT_COL_NAMES = ['Account Number', 'LPL Account Number', 'Account', 'Account No', 'Account #', 'Acct Number']

    def _find_account_column(self, df) -> Optional[str]:
        """Find the account number column in the dataframe."""
        for col_name in self.ACCOUNT_COL_NAMES:
            if col_name in df.columns:
                return col_name
        return None

    def parse_accounts(self, sheet_name=0) -> dict[str, Account]:
        """Parse the Excel file and create Account objects.

        Args:
            sheet_name: Sheet to read. Defaults to 0 (first sheet).
                        Can also pass a string name if needed.

        Automatically detects if headers are on row 1 or row 2 (common when
        users put a title or other data in the first cell).
        """
        # Try reading with headers on row 0 (default)
        df = pd.read_excel(self.excel_file_path, sheet_name=sheet_name)
        account_col = self._find_account_column(df)

        # If not found, try headers on row 1 (row 2 in Excel terms)
        if account_col is None:
            df = pd.read_excel(self.excel_file_path, sheet_name=sheet_name, header=1)
            account_col = self._find_account_column(df)

        # If still not found, try row 2 (row 3 in Excel terms)
        if account_col is None:
            df = pd.read_excel(self.excel_file_path, sheet_name=sheet_name, header=2)
            account_col = self._find_account_column(df)

        if account_col is None:
            raise ValueError(f"Could not find Account Number column. Expected one of: {', '.join(self.ACCOUNT_COL_NAMES)}")

        # Check for client/account name column (supports multiple naming conventions)
        name_col = None
        for col_name in ['Account Name', 'Client Name', 'Client name', 'account name', 'Name']:
            if col_name in df.columns:
                name_col = col_name
                break
        has_client_name = name_col is not None

        account_numbers = df[account_col].unique()

        for account_num in account_numbers:
            if pd.isna(account_num):
                continue

            account_num_str = str(account_num)
            account_data = df[df[account_col] == account_num]
            
            # Get client name from first row of account data
            client_name = ""
            if has_client_name:
                first_name = account_data[name_col].iloc[0]
                client_name = str(first_name) if pd.notna(first_name) else ""
            
            account = Account(account_num=account_num_str, client_name=client_name)
            
            for _, row in account_data.iterrows():
                symbol = row['Symbol / CUSIP / ID']
                quantity = row['Quantity']
                price = row['Price / NAV']
                market_value = row['Market Value']
                
                # Handle Cash entries
                if pd.isna(symbol) or str(symbol).strip().upper() == 'CASH':
                    if pd.notna(market_value):
                        account.cash = float(market_value)
                
                # Handle securities
                elif pd.notna(symbol) and pd.notna(quantity):
                    symbol_str = str(symbol).strip().upper()
                    shares = float(quantity)
                    price_val = float(price) if pd.notna(price) else None
                    mv = float(market_value) if pd.notna(market_value) else None
                    
                    holding = Holding(symbol_str, shares, price_val, mv)
                    
                    if symbol_str in self.cash_equivalents:
                        account.add_cash_equivalent(holding)
                    else:
                        account.add_holding(holding)
            
            self.accounts[account_num_str] = account
        
        return self.accounts
    
    def get_account(self, account_num: str) -> Optional[Account]:
        return self.accounts.get(str(account_num))
    
    def get_all_accounts(self) -> dict[str, Account]:
        return self.accounts
