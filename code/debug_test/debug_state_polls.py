#!/usr/bin/env python3
"""
Debug script to check state poll data in the JSON file
"""
import json

def debug_state_polls():
    # Load the JSON file
    with open('data/json_output/all_polls.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("JSON structure:")
    print(f"Keys: {list(data.keys())}")
    print(f"Total polls: {len(data['polls'])}")
    
    # Check for state polls
    state_polls = [poll for poll in data['polls'] if poll.get('scope') == 'state']
    print(f"State polls: {len(state_polls)}")
    
    if state_polls:
        print("\nFirst state poll:")
        print(json.dumps(state_polls[0], indent=2, ensure_ascii=False))
        
        # Check unique states
        states = set(poll.get('state') for poll in state_polls if poll.get('state'))
        print(f"\nUnique states: {sorted(states)}")
        
        # Check for Baden-Württemberg specifically
        bw_polls = [poll for poll in state_polls if poll.get('state') == 'BW']
        print(f"\nBaden-Württemberg polls: {len(bw_polls)}")
        
        if bw_polls:
            print("\nFirst BW poll:")
            print(json.dumps(bw_polls[0], indent=2, ensure_ascii=False))

if __name__ == "__main__":
    debug_state_polls()
