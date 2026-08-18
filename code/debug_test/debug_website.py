#!/usr/bin/env python3
"""
Debug script to check website functionality and console output
"""

import requests
import json
import time
from pathlib import Path

def check_website_data():
    """Check if the website data files are accessible and valid"""
    print("Checking website data files...")
    
    # Check if server is running
    try:
        response = requests.get("http://localhost:1313", timeout=5)
        print(f"✓ Server is running (status: {response.status_code})")
    except requests.exceptions.RequestException as e:
        print(f"✗ Server not running: {e}")
        return False
    
    # Check key data files
    data_files = [
        "/data/current_latent_support_federal.json",
        "/data/current_latent_support_states.json", 
        "/data/all_polls_1m.json",
        "/data/all_polls_10y.json"
    ]
    
    for file_path in data_files:
        try:
            response = requests.get(f"http://localhost:1313{file_path}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ {file_path} - accessible ({len(data.get('polls', [])) if 'polls' in data else 'N/A'} polls)")
            else:
                print(f"✗ {file_path} - HTTP {response.status_code}")
        except Exception as e:
            print(f"✗ {file_path} - error: {e}")
    
    return True

def check_poll_data_structure():
    """Check the structure of poll data files"""
    print("\nChecking poll data structure...")
    
    try:
        response = requests.get("http://localhost:1313/data/all_polls_1m.json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            if 'polls' in data and len(data['polls']) > 0:
                first_poll = data['polls'][0]
                print(f"✓ First poll structure: {type(first_poll)}")
                if isinstance(first_poll, list):
                    print(f"  Array format: {len(first_poll)} elements")
                    print(f"  Sample: {first_poll[:5]}...")
                elif isinstance(first_poll, dict):
                    print(f"  Key-value format: {list(first_poll.keys())}")
                    print(f"  Sample: {list(first_poll.items())[:3]}")
            else:
                print("✗ No polls found in data")
                
            if 'metadata' in data:
                print(f"✓ Metadata available: {list(data['metadata'].keys())}")
        else:
            print(f"✗ Failed to load poll data: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"✗ Error checking poll data: {e}")

def check_federal_data():
    """Check federal data structure"""
    print("\nChecking federal data...")
    
    try:
        response = requests.get("http://localhost:1313/data/current_latent_support_federal.json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            if 'current_support' in data:
                parties = data['current_support']
                print(f"✓ Federal parties: {list(parties.keys())}")
                print(f"✓ Federal values: {list(parties.values())}")
            else:
                print("✗ No current_support found in federal data")
        else:
            print(f"✗ Failed to load federal data: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"✗ Error checking federal data: {e}")

def check_state_data():
    """Check state data structure"""
    print("\nChecking state data...")
    
    try:
        response = requests.get("http://localhost:1313/data/current_latent_support_states.json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            # Check if data has states wrapper or is direct state objects
            if 'states' in data:
                states = data['states']
                print(f"✓ Available states (wrapped): {list(states.keys())}")
                
                # Check first state structure
                first_state = list(states.values())[0] if states else None
                if first_state and 'current_support' in first_state:
                    parties = first_state['current_support']
                    print(f"✓ Sample state parties: {list(parties.keys())}")
                    print(f"✓ Sample state values: {list(parties.values())}")
            else:
                # Direct state objects
                states = data
                print(f"✓ Available states (direct): {list(states.keys())}")
                
                # Check first state structure
                first_state = list(states.values())[0] if states else None
                if first_state and 'current_support' in first_state:
                    parties = first_state['current_support']
                    print(f"✓ Sample state parties: {list(parties.keys())}")
                    print(f"✓ Sample state values: {list(parties.values())}")
                else:
                    print("✗ No current_support found in state data")
        else:
            print(f"✗ Failed to load state data: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"✗ Error checking state data: {e}")

if __name__ == "__main__":
    print("=== Website Debug Check ===\n")
    
    if check_website_data():
        check_poll_data_structure()
        check_federal_data()
        check_state_data()
    
    print("\n=== Debug Check Complete ===")
