#!/usr/bin/env python3
"""
Debug raw API data for INSA polls to see what's wrong with party data
"""

import sys
import os
import json
import pandas as pd

# Ensure imports work when running from code/ directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_fetcher import PollingDataFetcher

def main():
    # Fetch raw data from API
    fetcher = PollingDataFetcher()
    raw_polls = fetcher.fetch_all_polls()
    
    # Filter for INSA federal polls
    insa_federal_polls = []
    for poll in raw_polls:
        if poll.get('institute_id') == 'INSA' and poll.get('scope') == 'federal':
            insa_federal_polls.append(poll)
    
    print(f"Found {len(insa_federal_polls)} INSA federal polls in raw API data")
    
    # Check recent polls
    recent_polls = insa_federal_polls[-10:]  # Last 10 polls
    
    print("\nAnalyzing recent INSA federal polls from raw API data:")
    print("=" * 80)
    
    for i, poll in enumerate(recent_polls):
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
                else:
                    print(f"  Parties is not a string: {parties_raw}")
            except json.JSONDecodeError as e:
                print(f"  JSON decode error: {e}")
            except Exception as e:
                print(f"  Other error: {e}")
        else:
            print("  No parties field found")
        
        print("-" * 40)
    
    # Check for any patterns in the data
    print("\n" + "=" * 80)
    print("Checking for patterns in INSA poll data:")
    print("=" * 80)
    
    # Count polls with different party field types
    party_field_types = {}
    party_field_lengths = {}
    
    for poll in insa_federal_polls:
        parties_raw = poll.get('parties')
        field_type = type(parties_raw).__name__
        party_field_types[field_type] = party_field_types.get(field_type, 0) + 1
        
        if isinstance(parties_raw, str):
            try:
                parties_dict = json.loads(parties_raw)
                length = len(parties_dict)
                party_field_lengths[length] = party_field_lengths.get(length, 0) + 1
            except:
                party_field_lengths['parse_error'] = party_field_lengths.get('parse_error', 0) + 1
        elif parties_raw is None:
            party_field_lengths['None'] = party_field_lengths.get('None', 0) + 1
        else:
            party_field_lengths['other'] = party_field_lengths.get('other', 0) + 1
    
    print("Party field types:")
    for field_type, count in party_field_types.items():
        print(f"  {field_type}: {count}")
    
    print("\nParty field lengths (for string fields):")
    for length, count in party_field_lengths.items():
        print(f"  {length}: {count}")

if __name__ == "__main__":
    main()
