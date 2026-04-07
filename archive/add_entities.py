import json

with open('data/actions.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Company/entity tags to move out of tags and into entities field
company_tags = {
    'UnitedHealth', 'Kaiser Permanente', 'Humana', 'Aetna', 'Elevance',
    'CVS Health', 'CVS', 'Cigna', 'Independent Health',
}

moved = 0
for a in data['actions']:
    tags = a.get('tags') or []
    entities = []
    new_tags = []
    for t in tags:
        if t in company_tags:
            entities.append(t)
            moved += 1
        else:
            new_tags.append(t)
    a['tags'] = new_tags
    a['entities'] = entities if entities else []

print(f"Moved {moved} company tags to entities field")

# Show which entries have entities
for a in data['actions']:
    if a.get('entities'):
        print(f"  {a['id']}: {a['entities']}")

with open('data/actions.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("Saved.")
