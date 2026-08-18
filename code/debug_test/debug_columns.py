#!/usr/bin/env python3
"""
Debug script to check what columns are available in the API data
"""

from data_fetcher import PollingDataFetcher
import pandas as pd

def debug_columns():
    """Check what columns are available in the API data"""
    
    # Fetch all polls from API
    fetcher = PollingDataFetcher()
    all_polls = fetcher.fetch_all_polls()
    
    if not all_polls:
        print("No polls found!")
        return
    
    # Convert to DataFrame
    df = pd.DataFrame(all_polls)
    
    print("=== AVAILABLE COLUMNS ===")
    print(f"Total columns: {len(df.columns)}")
    print("Column names:")
    for i, col in enumerate(df.columns):
        print(f"  {i}: {col}")
    
    print("\n=== SAMPLE DATA ===")
    print("First row:")
    first_row = df.iloc[0]
    for col in df.columns:
        print(f"  {col}: {first_row[col]}")

if __name__ == "__main__":
    debug_columns()
