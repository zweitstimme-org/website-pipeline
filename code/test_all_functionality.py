#!/usr/bin/env python3
"""
Comprehensive test script to check all states, charts, and poll tables
"""

import requests
import json
import time

def test_all_functionality():
    """Test all functionality comprehensively"""
    print("=== Comprehensive Functionality Test ===\n")
    
    base_url = "http://localhost:1313"
    
    # Test 1: Check all data files are accessible
    print("1. Testing data file accessibility...")
    data_files = [
        "/data/current_latent_support_federal.json",
        "/data/current_latent_support_states.json",
        "/data/all_polls.json",
        "/data/all_polls_3m.json",
        "/data/all_polls_10y.json",
        "/data/federal_latent_support_3m.json",
        "/data/states_latent_support_3m.json",
        "/data/election_dates.json"
    ]
    
    for file_path in data_files:
        try:
            response = requests.get(f"{base_url}{file_path}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'polls' in data:
                    print(f"✓ {file_path} - accessible ({len(data['polls'])} polls)")
                elif 'states' in data or 'current_support' in data:
                    print(f"✓ {file_path} - accessible (support data)")
                elif 'elections' in data:
                    print(f"✓ {file_path} - accessible (election data)")
                else:
                    print(f"✓ {file_path} - accessible")
            else:
                print(f"✗ {file_path} - HTTP {response.status_code}")
        except Exception as e:
            print(f"✗ {file_path} - error: {e}")
    
    # Test 2: Check all states have data
    print("\n2. Testing all states have data...")
    try:
        response = requests.get(f"{base_url}/data/current_latent_support_states.json", timeout=5)
        if response.status_code == 200:
            state_data = response.json()
            states = list(state_data.keys())
            print(f"✓ Found {len(states)} states: {states}")
            
            # Check each state has current_support data
            for state in states:
                if 'current_support' in state_data[state]:
                    parties = list(state_data[state]['current_support'].keys())
                    values = list(state_data[state]['current_support'].values())
                    print(f"  ✓ {state}: {len(parties)} parties, values: {values}")
                else:
                    print(f"  ✗ {state}: missing current_support")
        else:
            print(f"✗ State data not accessible: HTTP {response.status_code}")
    except Exception as e:
        print(f"✗ State data error: {e}")
    
    # Test 3: Check poll data structure and filtering
    print("\n3. Testing poll data structure and filtering...")
    try:
        response = requests.get(f"{base_url}/data/all_polls.json", timeout=5)
        if response.status_code == 200:
            poll_data = response.json()
            
            if 'polls' in poll_data and 'metadata' in poll_data:
                polls = poll_data['polls']
                metadata = poll_data['metadata']
                
                print(f"✓ Total polls: {len(polls)}")
                print(f"✓ Metadata keys: {list(metadata.keys())}")
                
                # Check party order
                if 'party_order' in metadata:
                    party_order = metadata['party_order']
                    print(f"✓ Party order: {party_order}")
                    
                    # Check if PIRATEN/REP are in the data but should be filtered out
                    if 'PIRATEN' in party_order or 'REP' in party_order:
                        print("⚠ PIRATEN/REP found in party order - should be filtered out in tables")
                    else:
                        print("✓ PIRATEN/REP not in party order - good")
                
                # Check dictionaries
                if 'dictionaries' in metadata:
                    dictionaries = metadata['dictionaries']
                    print(f"✓ Dictionary keys: {list(dictionaries.keys())}")
                    
                    if 'states' in dictionaries:
                        states = dictionaries['states']
                        print(f"✓ Available states: {states}")
                    
                    if 'scopes' in dictionaries:
                        scopes = dictionaries['scopes']
                        print(f"✓ Available scopes: {scopes}")
                else:
                    print("✗ Missing dictionaries in metadata")
            else:
                print("✗ Poll data structure incomplete")
        else:
            print(f"✗ Poll data not accessible: HTTP {response.status_code}")
    except Exception as e:
        print(f"✗ Poll data error: {e}")
    
    # Test 4: Test state-specific poll filtering for each state
    print("\n4. Testing state-specific poll filtering...")
    try:
        response = requests.get(f"{base_url}/data/all_polls_10y.json", timeout=5)
        if response.status_code == 200:
            poll_data = response.json()
            
            if 'polls' in poll_data and 'metadata' in poll_data:
                polls = poll_data['polls']
                metadata = poll_data['metadata']
                
                # Get dictionaries for filtering
                if 'original_metadata' in metadata and 'dictionaries' in metadata['original_metadata']:
                    dictionaries = metadata['original_metadata']['dictionaries']
                    states = dictionaries.get('states', [])
                    scopes = dictionaries.get('scopes', [])
                    
                    print(f"✓ Available states for filtering: {states}")
                    print(f"✓ Available scopes: {scopes}")
                    
                    # Test filtering for each state
                    for state_code in states:
                        state_polls = []
                        for poll in polls:
                            if isinstance(poll, list) and len(poll) >= 9:
                                scope_idx = poll[7]
                                state_idx = poll[8]
                                
                                if (scope_idx == 1 and  # state poll
                                    state_idx is not None and 
                                    state_idx < len(states) and 
                                    states[state_idx] == state_code):
                                    state_polls.append(poll)
                        
                        if state_polls:
                            # Check first poll for party data
                            first_poll = state_polls[0]
                            parties = first_poll[10] if len(first_poll) > 10 else None
                            if parties:
                                valid_parties = [p for p in parties if p is not None and p > 0]
                                print(f"  ✓ {state_code}: {len(state_polls)} polls, {len(valid_parties)} valid parties")
                            else:
                                print(f"  ✗ {state_code}: {len(state_polls)} polls, but missing party data")
                        else:
                            print(f"  ⚠ {state_code}: no polls found")
                else:
                    print("✗ Missing dictionaries for filtering")
            else:
                print("✗ Poll data structure incomplete")
        else:
            print(f"✗ Poll data not accessible: HTTP {response.status_code}")
    except Exception as e:
        print(f"✗ State filtering error: {e}")
    
    # Test 5: Check federal poll filtering
    print("\n5. Testing federal poll filtering...")
    try:
        response = requests.get(f"{base_url}/data/all_polls_3m.json", timeout=5)
        if response.status_code == 200:
            poll_data = response.json()
            
            if 'polls' in poll_data and 'metadata' in poll_data:
                polls = poll_data['polls']
                metadata = poll_data['metadata']
                
                # Get dictionaries for filtering
                if 'original_metadata' in metadata and 'dictionaries' in metadata['original_metadata']:
                    dictionaries = metadata['original_metadata']['dictionaries']
                    scopes = dictionaries.get('scopes', [])
                    
                    # Filter federal polls
                    federal_polls = []
                    for poll in polls:
                        if isinstance(poll, list) and len(poll) >= 8:
                            scope_idx = poll[7]
                            if scope_idx < len(scopes) and scopes[scope_idx] == 'federal':
                                federal_polls.append(poll)
                    
                    print(f"✓ Federal polls found: {len(federal_polls)}")
                    
                    if federal_polls:
                        # Check first federal poll for party data
                        first_poll = federal_polls[0]
                        parties = first_poll[10] if len(first_poll) > 10 else None
                        if parties:
                            valid_parties = [p for p in parties if p is not None and p > 0]
                            print(f"  ✓ First federal poll has {len(valid_parties)} valid parties")
                        else:
                            print(f"  ✗ First federal poll missing party data")
                    else:
                        print("  ⚠ No federal polls found")
                else:
                    print("✗ Missing dictionaries for filtering")
            else:
                print("✗ Poll data structure incomplete")
        else:
            print(f"✗ Poll data not accessible: HTTP {response.status_code}")
    except Exception as e:
        print(f"✗ Federal filtering error: {e}")
    
    # Test 6: Check historical data for charts
    print("\n6. Testing historical data for charts...")
    try:
        # Check federal historical data
        response = requests.get(f"{base_url}/data/federal_latent_support_3m.json", timeout=5)
        if response.status_code == 200:
            federal_hist_data = response.json()
            if isinstance(federal_hist_data, dict):
                dates = list(federal_hist_data.keys())
                if dates:
                    first_date = dates[0]
                    first_date_data = federal_hist_data[first_date]
                    if isinstance(first_date_data, dict):
                        parties = [k for k in first_date_data.keys() if not k.startswith('_')]
                        print(f"✓ Federal historical data: {len(dates)} dates, {len(parties)} parties")
                    else:
                        print("✗ Federal historical data structure unexpected")
                else:
                    print("✗ No dates in federal historical data")
            else:
                print("✗ Federal historical data not in expected format")
        else:
            print(f"✗ Federal historical data not accessible: HTTP {response.status_code}")
            
        # Check state historical data
        response = requests.get(f"{base_url}/data/states_latent_support_3m.json", timeout=5)
        if response.status_code == 200:
            state_hist_data = response.json()
            if isinstance(state_hist_data, dict):
                states = list(state_hist_data.keys())
                if states:
                    first_state = states[0]
                    first_state_data = state_hist_data[first_state]
                    if isinstance(first_state_data, dict):
                        dates = list(first_state_data.keys())
                        if dates:
                            first_date = dates[0]
                            first_date_data = first_state_data[first_date]
                            if isinstance(first_date_data, dict):
                                parties = [k for k in first_date_data.keys() if not k.startswith('_')]
                                print(f"✓ State historical data: {len(states)} states, {len(dates)} dates, {len(parties)} parties")
                            else:
                                print("✗ State historical date data structure unexpected")
                        else:
                            print("✗ No dates in state historical data")
                    else:
                        print("✗ State historical state data structure unexpected")
                else:
                    print("✗ No states in state historical data")
            else:
                print("✗ State historical data not in expected format")
        else:
            print(f"✗ State historical data not accessible: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"✗ Historical data error: {e}")
    
    print("\n=== Comprehensive Functionality Test Complete ===")

if __name__ == "__main__":
    test_all_functionality()
