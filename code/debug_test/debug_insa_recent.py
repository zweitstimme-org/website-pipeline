#!/usr/bin/env python3
"""
Debug recent INSA polls to see the current format
"""

import sys
import os
import json
import pandas as pd
from datetime import datetime, timedelta

# Ensure imports work when running from code/ directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_fetcher import PollingDataFetcher

def main():
    # Fetch raw data from API
    fetcher = PollingDataFetcher()
    raw_polls = fetcher.fetch_all_polls()
    
    # Filter for recent INSA federal polls (last 6 months)
    recent_cutoff = datetime.now() - timedelta(days=180)
    recent_insa_polls = []
    
    for poll in raw_polls:
        if poll.get('institute_id') == 'INSA' and poll.get('scope') == 'federal':
            try:
                poll_date = datetime.strptime(poll.get('publish_date', ''), '%Y-%m-%d')
                if poll_date >= recent_cutoff:
                    recent_insa_polls.append(poll)
            except:
                continue
    
    print(f"Found {len(recent_insa_polls)} recent INSA federal polls")
    
    # Sort by date (newest first)
    recent_insa_polls.sort(key=lambda x: x.get('publish_date', ''), reverse=True)
    
    print("\nAnalyzing recent INSA federal polls:")
    print("=" * 80)
    
    for i, poll in enumerate(recent_insa_polls[:20]):  # Show last 20 polls
        print(f"\nPoll {i+1}: {poll.get('publish_date')} (ID: {poll.get('id')})")
        print(f"  Institute ID: {poll.get('institute_id')}")
        print(f"  Scope: {poll.get('scope')}")
        print(f"  Respondents: {poll.get('respondents')}")
        
        # Check parties field
        parties_raw = poll.get('parties')
        print(f"  Raw parties field: {parties_raw}")
        print(f"  Parties field type: {type(parties_raw)}")
        
        if parties_raw:
            try:
                # Try to parse as JSON
                if isinstance(parties_raw, str):
                    parties_dict = json.loads(parties_raw)
                    print(f"  Parsed parties: {parties_dict}")
                    print(f"  Number of parties: {len(parties_dict)}")
                    
                    # Check each party value
                    for party, value in parties_dict.items():
                        print(f"    {party}: {value} (type: {type(value)})")
                        
                        # Try to convert to float
                        if isinstance(value, str):
                            try:
                                clean_value = value.replace('%', '').replace(' ', '').strip()
                                if clean_value and clean_value != 'nan':
                                    clean_value = clean_value.replace(',', '.')
                                    float_value = float(clean_value)
                                    print(f"      -> Converted to float: {float_value}")
                                else:
                                    print(f"      -> Could not convert (empty/nan)")
                            except ValueError as e:
                                print(f"      -> Conversion error: {e}")
                else:
                    print(f"  Parties is not a string: {parties_raw}")
            except json.JSONDecodeError as e:
                print(f"  JSON decode error: {e}")
            except Exception as e:
                print(f"  Other error: {e}")
        else:
            print("  No parties field found")
        
        print("-" * 40)

if __name__ == "__main__":
    main()
