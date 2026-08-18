#!/usr/bin/env python3
"""
Debug specific frontend issues by simulating the data processing logic
"""

import requests
import json

def debug_frontend_issues():
    """Debug the specific frontend issues"""
    print("=== Debugging Frontend Issues ===\n")
    
    base_url = "http://localhost:1313"
    
    # Test 1: Federal data processing (the issue was 0 parties and 0 data length)
    print("1. Testing federal data processing...")
    try:
        response = requests.get(f"{base_url}/data/current_latent_support_federal.json", timeout=5)
        if response.status_code == 200:
            federal_data = response.json()
            
            if 'current_support' in federal_data:
                parties = list(federal_data['current_support'].keys())
                values = list(federal_data['current_support'].values())
                
                print(f"✓ Federal parties: {parties}")
                print(f"✓ Federal values: {values}")
                print(f"✓ Parties length: {len(parties)}")
                print(f"✓ Values length: {len(values)}")
                
                # Check if any values are None or 0
                zero_values = [i for i, v in enumerate(values) if v == 0 or v is None]
                if zero_values:
                    print(f"⚠ Zero/None values at indices: {zero_values}")
                else:
                    print("✓ All values are non-zero")
                    
            else:
                print("✗ Federal data missing 'current_support'")
        else:
            print(f"✗ Federal data not accessible: HTTP {response.status_code}")
    except Exception as e:
        print(f"✗ Federal data error: {e}")
    
    # Test 2: State data processing
    print("\n2. Testing state data processing...")
    try:
        response = requests.get(f"{base_url}/data/current_latent_support_states.json", timeout=5)
        if response.status_code == 200:
            state_data = response.json()
            
            if isinstance(state_data, dict):
                states = list(state_data.keys())
                print(f"✓ Available states: {states}")
                
                if states:
                    # Test first state
                    first_state = state_data[states[0]]
                    if 'current_support' in first_state:
                        parties = list(first_state['current_support'].keys())
                        values = list(first_state['current_support'].values())
                        print(f"✓ Sample state ({states[0]}) parties: {parties}")
                        print(f"✓ Sample state ({states[0]}) values: {values}")
                        print(f"✓ Sample state parties length: {len(parties)}")
                        print(f"✓ Sample state values length: {len(values)}")
                    else:
                        print(f"✗ Sample state missing 'current_support'")
                        
                    # Test Baden-Württemberg specifically (from the logs)
                    if 'BW' in state_data:
                        bw_state = state_data['BW']
                        if 'current_support' in bw_state:
                            bw_parties = list(bw_state['current_support'].keys())
                            bw_values = list(bw_state['current_support'].values())
                            print(f"✓ BW parties: {bw_parties}")
                            print(f"✓ BW values: {bw_values}")
                        else:
                            print("✗ BW missing 'current_support'")
                    else:
                        print("✗ BW not found in state data")
            else:
                print("✗ State data not in expected format")
        else:
            print(f"✗ State data not accessible: HTTP {response.status_code}")
    except Exception as e:
        print(f"✗ State data error: {e}")
    
    # Test 3: Poll data processing
    print("\n3. Testing poll data processing...")
    try:
        response = requests.get(f"{base_url}/data/all_polls_1m.json", timeout=5)
        if response.status_code == 200:
            poll_data = response.json()
            
            if 'polls' in poll_data and len(poll_data['polls']) > 0:
                polls = poll_data['polls']
                print(f"✓ Total polls: {len(polls)}")
                
                # Check first poll structure
                first_poll = polls[0]
                if isinstance(first_poll, list):
                    print(f"✓ First poll is array with {len(first_poll)} elements")
                    print(f"✓ First poll sample: {first_poll[:5]}...")
                    
                    # Check if it has the expected structure: [id, date, survey_start, survey_end, respondents, institute_idx, source_idx, scope_idx, state_idx, method_idx, parties]
                    if len(first_poll) >= 11:
                        poll_id = first_poll[0]
                        poll_date = first_poll[1]
                        poll_parties = first_poll[10] if len(first_poll) > 10 else None
                        print(f"✓ Poll ID: {poll_id}")
                        print(f"✓ Poll date: {poll_date}")
                        print(f"✓ Poll parties: {poll_parties}")
                    else:
                        print(f"✗ Poll array too short: {len(first_poll)} elements")
                else:
                    print(f"✓ First poll is object with keys: {list(first_poll.keys())}")
                    
                # Check metadata
                if 'metadata' in poll_data:
                    metadata = poll_data['metadata']
                    print(f"✓ Metadata keys: {list(metadata.keys())}")
                    
                    if 'original_metadata' in metadata:
                        original_metadata = metadata['original_metadata']
                        if 'dictionaries' in original_metadata:
                            dictionaries = original_metadata['dictionaries']
                            print(f"✓ Dictionary keys: {list(dictionaries.keys())}")
                        else:
                            print("✗ Missing dictionaries in original_metadata")
                    else:
                        print("✗ Missing original_metadata")
                else:
                    print("✗ Missing metadata")
            else:
                print("✗ No polls found or polls array missing")
        else:
            print(f"✗ Poll data not accessible: HTTP {response.status_code}")
    except Exception as e:
        print(f"✗ Poll data error: {e}")
    
    print("\n=== Frontend Issues Debug Complete ===")

if __name__ == "__main__":
    debug_frontend_issues()
