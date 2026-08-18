#!/usr/bin/env python3
"""
Debug INSA federal polls to identify missing major parties
"""

import json
import pandas as pd
from datetime import datetime, timedelta

# Load the all_polls_10y.json file
with open('../data/json_output/all_polls_10y.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Get metadata
metadata = data['metadata']
original_metadata = metadata['original_metadata']
institutes = original_metadata['dictionaries']['institutes']
scopes = original_metadata['dictionaries']['scopes']
states = original_metadata['dictionaries']['states']

# Filter for INSA federal polls
insa_federal_polls = []
for poll in data['polls']:
    # poll is an array: [id, publish_date, survey_start, survey_end, respondents, institute_idx, source_idx, scope_idx, state_idx, method_idx, parties]
    institute_idx = poll[5]
    scope_idx = poll[7]
    
    institute_name = institutes[institute_idx] if institute_idx < len(institutes) else "Unknown"
    scope_name = scopes[scope_idx] if scope_idx < len(scopes) else "Unknown"
    
    if institute_name == 'INSA' and scope_name == 'federal':
        insa_federal_polls.append(poll)

print(f"Found {len(insa_federal_polls)} INSA federal polls")

# Check recent polls (last 6 months)
recent_cutoff = datetime.now() - timedelta(days=180)
recent_insa_polls = []
for poll in insa_federal_polls:
    try:
        poll_date = datetime.strptime(poll[1], '%Y-%m-%d')  # publish_date is at index 1
        if poll_date >= recent_cutoff:
            recent_insa_polls.append(poll)
    except:
        continue

print(f"Recent INSA federal polls (last 6 months): {len(recent_insa_polls)}")

# Major parties that should always be present
major_parties = ['CDU/CSU', 'SPD', 'GRÜNE', 'AfD', 'LINKE', 'FDP']

# Analyze each recent poll
print("\nAnalyzing recent INSA federal polls:")
print("=" * 80)

for i, poll in enumerate(recent_insa_polls[-10:]):  # Last 10 polls
    print(f"\nPoll {i+1}: {poll[1]} (ID: {poll[0]})")  # date and id
    print(f"  Institute: INSA")
    print(f"  Respondents: {poll[4] if poll[4] else 'N/A'}")
    
    # Parse parties (parties is at index 10)
    parties_data = poll[10]
    if isinstance(parties_data, dict):
        present_parties = list(parties_data.keys())
    else:
        present_parties = []
    
    missing_major = [party for party in major_parties if party not in present_parties]
    
    print(f"  Present parties: {present_parties}")
    print(f"  Missing major parties: {missing_major}")
    
    if missing_major:
        print(f"  ⚠️  WARNING: Missing {len(missing_major)} major parties!")
    
    # Show all party values
    if isinstance(parties_data, dict):
        print("  Party values:")
        for party, value in parties_data.items():
            print(f"    {party}: {value}%")

# Check all INSA polls for missing major parties
print("\n" + "=" * 80)
print("Summary of all INSA federal polls with missing major parties:")
print("=" * 80)

polls_with_issues = []
for poll in insa_federal_polls:
    parties_data = poll[10]
    if isinstance(parties_data, dict):
        present_parties = list(parties_data.keys())
    else:
        present_parties = []
    
    missing_major = [party for party in major_parties if party not in present_parties]
    
    if missing_major:
        polls_with_issues.append({
            'date': poll[1],
            'id': poll[0],
            'missing': missing_major,
            'present': present_parties
        })

if polls_with_issues:
    print(f"Found {len(polls_with_issues)} INSA federal polls with missing major parties:")
    for poll in polls_with_issues:
        print(f"  {poll['date']} (ID: {poll['id']}): Missing {poll['missing']}")
        print(f"    Present: {poll['present']}")
else:
    print("No INSA federal polls with missing major parties found.")

# Check if this is a data parsing issue
print("\n" + "=" * 80)
print("Checking for potential data parsing issues:")
print("=" * 80)

# Look for polls with very few parties (likely parsing errors)
suspicious_polls = []
for poll in insa_federal_polls:
    parties_data = poll[10]
    if isinstance(parties_data, dict):
        party_count = len(parties_data)
    else:
        party_count = 0
    
    if party_count < 4:  # Suspicious if less than 4 parties
        if isinstance(parties_data, dict):
            parties_list = list(parties_data.keys())
        else:
            parties_list = []
        
        suspicious_polls.append({
            'date': poll[1],
            'id': poll[0],
            'party_count': party_count,
            'parties': parties_list
        })

if suspicious_polls:
    print(f"Found {len(suspicious_polls)} INSA federal polls with suspiciously few parties:")
    for poll in suspicious_polls:
        print(f"  {poll['date']} (ID: {poll['id']}): {poll['party_count']} parties - {poll['parties']}")
else:
    print("No INSA federal polls with suspiciously few parties found.")
