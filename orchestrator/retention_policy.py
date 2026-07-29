"""State records-retention policies — ported verbatim from the Pinpoint 311
app's services/retention_service.py.

The control plane is the *state* in the app's model, so this is the policy the
hosting organization sets once and pushes down to every town it hosts (via the
per-tenant managed settings). The state table, ``get_all_states`` and
``get_retention_policy`` are the app's, unchanged — the towns and the panel must
agree on what a state's retention period is, so this table must not fork.
"""

from typing import Any, Dict, List


STATE_RETENTION_POLICIES: Dict[str, Dict[str, Any]] = {
    # Alabama
    "AL": {"days": 5 * 365, "name": "Alabama", "source": "AL State Records Commission", "public_records_law": "Alabama Open Records Act"},
    # Alaska
    "AK": {"days": 5 * 365, "name": "Alaska", "source": "AK State Archives", "public_records_law": "Alaska Public Records Act"},
    # Arizona
    "AZ": {"days": 5 * 365, "name": "Arizona", "source": "AZ State Library", "public_records_law": "Arizona Public Records Law"},
    # Arkansas
    "AR": {"days": 5 * 365, "name": "Arkansas", "source": "AR State Archives", "public_records_law": "FOIA (Arkansas)"},
    # California
    "CA": {"days": 5 * 365, "name": "California", "source": "CA Secretary of State", "public_records_law": "CPRA (California Public Records Act)"},
    # Colorado
    "CO": {"days": 5 * 365, "name": "Colorado", "source": "CO State Archives", "public_records_law": "CORA (Colorado Open Records Act)"},
    # Connecticut
    "CT": {"days": 6 * 365, "name": "Connecticut", "source": "CT Public Records Administrator", "public_records_law": "FOIA (Connecticut)"},
    # Delaware
    "DE": {"days": 5 * 365, "name": "Delaware", "source": "DE Public Archives", "public_records_law": "FOIA (Delaware)"},
    # District of Columbia
    "DC": {"days": 5 * 365, "name": "District of Columbia", "source": "DC Archives", "public_records_law": "DC FOIA"},
    # Florida
    "FL": {"days": 5 * 365, "name": "Florida", "source": "FL Division of Library & Information Services", "public_records_law": "Florida Sunshine Law"},
    # Georgia
    "GA": {"days": 3 * 365, "name": "Georgia", "source": "GA Archives", "public_records_law": "Georgia Open Records Act"},
    # Hawaii
    "HI": {"days": 5 * 365, "name": "Hawaii", "source": "HI State Archives", "public_records_law": "UIPA (Uniform Information Practices Act)"},
    # Idaho
    "ID": {"days": 5 * 365, "name": "Idaho", "source": "ID State Historical Society", "public_records_law": "Idaho Public Records Law"},
    # Illinois
    "IL": {"days": 5 * 365, "name": "Illinois", "source": "IL Local Records Commission", "public_records_law": "FOIA (Illinois)"},
    # Indiana
    "IN": {"days": 5 * 365, "name": "Indiana", "source": "IN Commission on Public Records", "public_records_law": "APRA (Access to Public Records Act)"},
    # Iowa
    "IA": {"days": 5 * 365, "name": "Iowa", "source": "IA State Archives", "public_records_law": "Iowa Open Records Law"},
    # Kansas
    "KS": {"days": 5 * 365, "name": "Kansas", "source": "KS State Historical Society", "public_records_law": "KORA (Kansas Open Records Act)"},
    # Kentucky
    "KY": {"days": 5 * 365, "name": "Kentucky", "source": "KY Dept for Libraries & Archives", "public_records_law": "Kentucky Open Records Act"},
    # Louisiana
    "LA": {"days": 5 * 365, "name": "Louisiana", "source": "LA State Archives", "public_records_law": "Louisiana Public Records Act"},
    # Maine
    "ME": {"days": 5 * 365, "name": "Maine", "source": "ME State Archives", "public_records_law": "FOAA (Freedom of Access Act)"},
    # Maryland
    "MD": {"days": 5 * 365, "name": "Maryland", "source": "MD State Archives", "public_records_law": "MPIA (Maryland Public Information Act)"},
    # Massachusetts
    "MA": {"days": 3 * 365, "name": "Massachusetts", "source": "MA Municipal Records Schedule", "public_records_law": "Massachusetts Public Records Law"},
    # Michigan
    "MI": {"days": 6 * 365, "name": "Michigan", "source": "MI Archives", "public_records_law": "FOIA (Michigan)"},
    # Minnesota
    "MN": {"days": 5 * 365, "name": "Minnesota", "source": "MN State Archives", "public_records_law": "MGDPA (Minnesota Data Practices Act)"},
    # Mississippi
    "MS": {"days": 5 * 365, "name": "Mississippi", "source": "MS Dept of Archives & History", "public_records_law": "Mississippi Public Records Act"},
    # Missouri
    "MO": {"days": 5 * 365, "name": "Missouri", "source": "MO Secretary of State", "public_records_law": "Missouri Sunshine Law"},
    # Montana
    "MT": {"days": 5 * 365, "name": "Montana", "source": "MT Historical Society", "public_records_law": "Montana Constitution Article II, Sec 9"},
    # Nebraska
    "NE": {"days": 5 * 365, "name": "Nebraska", "source": "NE State Historical Society", "public_records_law": "Nebraska Public Records Statutes"},
    # Nevada
    "NV": {"days": 5 * 365, "name": "Nevada", "source": "NV State Library & Archives", "public_records_law": "Nevada Public Records Act"},
    # New Hampshire
    "NH": {"days": 5 * 365, "name": "New Hampshire", "source": "NH Division of Archives", "public_records_law": "Right-to-Know Law"},
    # New Jersey
    "NJ": {"days": 7 * 365, "name": "New Jersey", "source": "NJ Division of Archives & Records Management", "public_records_law": "OPRA (Open Public Records Act)"},
    # New Mexico
    "NM": {"days": 5 * 365, "name": "New Mexico", "source": "NM State Records Center", "public_records_law": "IPRA (Inspection of Public Records Act)"},
    # New York
    "NY": {"days": 6 * 365, "name": "New York", "source": "NY Arts & Cultural Affairs Law §57.25", "public_records_law": "FOIL (Freedom of Information Law)"},
    # North Carolina
    "NC": {"days": 5 * 365, "name": "North Carolina", "source": "NC DNCR", "public_records_law": "North Carolina Public Records Law"},
    # North Dakota
    "ND": {"days": 5 * 365, "name": "North Dakota", "source": "ND State Archives", "public_records_law": "North Dakota Open Records Law"},
    # Ohio
    "OH": {"days": 5 * 365, "name": "Ohio", "source": "OH Historical Society", "public_records_law": "Ohio Public Records Act"},
    # Oklahoma
    "OK": {"days": 5 * 365, "name": "Oklahoma", "source": "OK Dept of Libraries", "public_records_law": "Oklahoma Open Records Act"},
    # Oregon
    "OR": {"days": 5 * 365, "name": "Oregon", "source": "OR State Archives", "public_records_law": "Oregon Public Records Law"},
    # Pennsylvania
    "PA": {"days": 7 * 365, "name": "Pennsylvania", "source": "PA Municipal Records Manual", "public_records_law": "RTKL (Right-to-Know Law)"},
    # Rhode Island
    "RI": {"days": 5 * 365, "name": "Rhode Island", "source": "RI State Archives", "public_records_law": "APRA (Access to Public Records Act)"},
    # South Carolina
    "SC": {"days": 5 * 365, "name": "South Carolina", "source": "SC Dept of Archives & History", "public_records_law": "FOIA (South Carolina)"},
    # South Dakota
    "SD": {"days": 5 * 365, "name": "South Dakota", "source": "SD State Historical Society", "public_records_law": "South Dakota Open Records Law"},
    # Tennessee
    "TN": {"days": 5 * 365, "name": "Tennessee", "source": "TN State Library & Archives", "public_records_law": "Tennessee Public Records Act"},
    # Texas
    "TX": {"days": 10 * 365, "name": "Texas", "source": "TX State Library & Archives Commission", "public_records_law": "TPIA (Texas Public Information Act)"},
    # Utah
    "UT": {"days": 5 * 365, "name": "Utah", "source": "UT State Archives", "public_records_law": "GRAMA (Government Records Access and Management Act)"},
    # Vermont
    "VT": {"days": 5 * 365, "name": "Vermont", "source": "VT State Archives", "public_records_law": "Vermont Public Records Act"},
    # Virginia
    "VA": {"days": 5 * 365, "name": "Virginia", "source": "Library of Virginia", "public_records_law": "VFOIA (Virginia Freedom of Information Act)"},
    # Washington
    "WA": {"days": 6 * 365, "name": "Washington", "source": "WA State Archives", "public_records_law": "Washington Public Records Act"},
    # West Virginia
    "WV": {"days": 5 * 365, "name": "West Virginia", "source": "WV State Archives", "public_records_law": "FOIA (West Virginia)"},
    # Wisconsin
    "WI": {"days": 7 * 365, "name": "Wisconsin", "source": "WI Public Records Board", "public_records_law": "Wisconsin Open Records Law"},
    # Wyoming
    "WY": {"days": 5 * 365, "name": "Wyoming", "source": "WY State Archives", "public_records_law": "Wyoming Public Records Act"},
    
    # Default for unlisted jurisdictions
    "DEFAULT": {"days": 7 * 365, "name": "Default", "source": "Conservative 7-year default", "public_records_law": "Federal FOIA"},
}


def get_all_states() -> List[Dict[str, Any]]:
    """Get list of all supported states with their retention policies."""
    states = []
    for code, policy in STATE_RETENTION_POLICIES.items():
        if code != "DEFAULT":
            states.append({
                "code": code,
                "name": policy["name"],
                "retention_days": policy["days"],
                "retention_years": policy["days"] // 365,
                "source": policy["source"],
                "public_records_law": policy.get("public_records_law", "Public Records Act")
            })
    return sorted(states, key=lambda x: x["name"])


def get_retention_policy(state_code: str) -> Dict[str, Any]:
    """
    Get retention policy for a specific state.
    
    Args:
        state_code: Two-letter state code (e.g., "NJ", "TX")
        
    Returns:
        Dict with days, name, source, years, and public_records_law
    """
    state_code = state_code.upper() if state_code else "DEFAULT"
    policy = STATE_RETENTION_POLICIES.get(state_code, STATE_RETENTION_POLICIES["DEFAULT"])
    
    return {
        "state_code": state_code,
        "name": policy["name"],
        "retention_days": policy["days"],
        "retention_years": policy["days"] // 365,
        "source": policy["source"],
        "public_records_law": policy.get("public_records_law", "Public Records Act")
    }

