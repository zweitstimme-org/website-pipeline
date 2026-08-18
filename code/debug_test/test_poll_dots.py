#!/usr/bin/env python3
"""
Test script to verify that actual poll dates metadata is working correctly
"""

import json
from pathlib import Path
from datetime import datetime

def test_actual_poll_dates_metadata():
    """Test that state data includes actual poll dates metadata"""
    
    data_dir = Path("../data/json_output")
    
    # Test periods that should have interpolation (2y+)
    test_periods = ["2y", "5y", "10y"]
    
    for period in test_periods:
        file_path = data_dir / f"states_latent_support_{period}.json"
        
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            continue
            
        print(f"\n📊 Testing {period} period for actual poll dates metadata...")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check a few states
        test_states = ["BY", "NW", "SH"]  # Bayern, NRW, Schleswig-Holstein
        
        for state in test_states:
            if state not in data:
                print(f"  ⚠️  State {state} not found in {period} data")
                continue
                
            state_data = data[state]
            if not state_data:
                print(f"  ⚠️  State {state} has no data in {period}")
                continue
            
            # Check if metadata exists
            first_date = min(state_data.keys())
            if '_actual_poll_dates' in state_data[first_date]:
                actual_poll_dates = state_data[first_date]['_actual_poll_dates']
                print(f"  ✅ {state}: Found {len(actual_poll_dates)} actual poll dates")
                
                # Show a few examples
                if actual_poll_dates:
                    print(f"    📅 Sample dates: {actual_poll_dates[:5]}...")
                    
                    # Check if dates are reasonable (should be monthly)
                    if len(actual_poll_dates) > 1:
                        first_poll = datetime.strptime(actual_poll_dates[0], '%Y-%m-%d')
                        last_poll = datetime.strptime(actual_poll_dates[-1], '%Y-%m-%d')
                        date_range = (last_poll - first_poll).days
                        expected_months = date_range / 30
                        actual_months = len(actual_poll_dates)
                        
                        print(f"    📊 Date range: {first_poll.strftime('%Y-%m-%d')} to {last_poll.strftime('%Y-%m-%d')}")
                        print(f"    📈 Expected ~{expected_months:.1f} months, got {actual_months} poll dates")
                        
                        if abs(actual_months - expected_months) < 5:  # Allow some flexibility
                            print(f"    ✅ Poll date frequency looks reasonable")
                        else:
                            print(f"    ⚠️  Poll date frequency seems unusual")
            else:
                print(f"  ❌ {state}: No actual poll dates metadata found")

def test_federal_data():
    """Test that federal data doesn't need interpolation (already daily)"""
    
    data_dir = Path("../data/json_output")
    
    # Test 10y period
    file_path = data_dir / "federal_latent_support_10y.json"
    
    if not file_path.exists():
        print("❌ Federal 10y file not found")
        return
        
    print(f"\n📊 Testing federal 10y data...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Federal data should not have actual poll dates metadata since it's already daily
    first_date = min(data.keys())
    if '_actual_poll_dates' in data[first_date]:
        print(f"  ⚠️  Federal data has actual poll dates metadata (unexpected)")
    else:
        print(f"  ✅ Federal data correctly has no actual poll dates metadata (already daily)")

if __name__ == "__main__":
    print("🧪 Testing actual poll dates metadata...")
    test_actual_poll_dates_metadata()
    test_federal_data()
    print("\n✅ Actual poll dates metadata test complete!")

