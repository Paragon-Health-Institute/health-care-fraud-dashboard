import json

with open('data/actions.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Person tags to remove from rectangular tags
# These should only appear in the officials field
person_tags = {
    'Dr. Oz', 'Oz', 'Vance', 'Newsom', 'Hochul', 'Governor Walz', 'AG Ellison',
    'RFK Jr.', 'NFL',
}

# Company tags to KEEP in rectangular tags (they're entities, not shown elsewhere)
# Kaiser Permanente, UnitedHealth, Humana, Aetna, Elevance, CVS, Cigna, Independent Health

# State/place tags to remove from rectangular tags
# These are redundant with the state field pin
state_tags = {
    'California', 'Texas', 'Minnesota', 'Arizona', 'Florida', 'Massachusetts',
    'New York', 'New Jersey', 'Colorado', 'Georgia', 'Virginia', 'Arkansas',
    'North Carolina', 'Louisiana', 'Illinois', 'Wisconsin', 'Michigan',
    'Kentucky', 'Tennessee', 'Pennsylvania', 'Oregon', 'Maine',
}

# For entries with person tags but no officials, add to officials
person_to_official = {
    'Dr. Oz': 'Dr. Mehmet Oz (CMS Administrator)',
    'Oz': 'Dr. Mehmet Oz (CMS Administrator)',
    'Vance': 'J.D. Vance (Vice President)',
    'Newsom': 'Gov. Gavin Newsom (CA)',
    'Hochul': 'Gov. Kathy Hochul (NY)',
    'Governor Walz': 'Gov. Tim Walz (MN)',
    'AG Ellison': 'AG Keith Ellison (MN)',
    'RFK Jr.': 'Robert F. Kennedy Jr. (HHS Secretary)',
    'NFL': None,  # not a person for officials
}

# For entries with state tags but no state field, set state
state_tag_to_code = {
    'California': 'CA', 'Texas': 'TX', 'Minnesota': 'MN', 'Arizona': 'AZ',
    'Florida': 'FL', 'Massachusetts': 'MA', 'New York': 'NY', 'New Jersey': 'NJ',
    'Colorado': 'CO', 'Georgia': 'GA', 'Virginia': 'VA', 'Arkansas': 'AR',
    'North Carolina': 'NC', 'Louisiana': 'LA', 'Illinois': 'IL', 'Wisconsin': 'WI',
    'Michigan': 'MI', 'Kentucky': 'KY', 'Tennessee': 'TN', 'Pennsylvania': 'PA',
    'Oregon': 'OR', 'Maine': 'ME',
}

tag_removals = 0
officials_added = 0
states_set = 0

for a in data['actions']:
    tags = a.get('tags') or []
    officials = a.get('officials') or []
    official_names = ' '.join(officials).lower()

    # Add missing officials from person tags
    for t in tags:
        if t in person_to_official and person_to_official[t]:
            official_val = person_to_official[t]
            # Check if already present (by last name)
            last_name = official_val.split('(')[0].strip().split()[-1].lower()
            if last_name not in official_names:
                officials.append(official_val)
                official_names += ' ' + official_val.lower()
                officials_added += 1
                print(f"  Added official '{official_val}' to {a['id']}")
    a['officials'] = officials

    # Set state from state tags if missing
    if not a.get('state'):
        for t in tags:
            if t in state_tag_to_code:
                a['state'] = state_tag_to_code[t]
                states_set += 1
                print(f"  Set state {a['state']} on {a['id']}")
                break  # use first state tag found

    # Remove person and state tags from rectangular tags
    new_tags = []
    for t in tags:
        if t in person_tags or t in state_tags:
            tag_removals += 1
        else:
            new_tags.append(t)
    a['tags'] = new_tags

print(f"\nRemoved {tag_removals} person/state tags from pills")
print(f"Added {officials_added} officials")
print(f"Set {states_set} missing state fields")

# Save
with open('data/actions.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# Verify: any person/state tags remaining?
remaining = set()
for a in data['actions']:
    for t in (a.get('tags') or []):
        if t in person_tags or t in state_tags:
            remaining.add(t)
if remaining:
    print(f"WARNING: still found: {remaining}")
else:
    print("All person/state tags removed from pills.")
print(f"Total entries: {len(data['actions'])}")
