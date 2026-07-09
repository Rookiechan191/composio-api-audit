import json

data = json.load(open('data/composio_crosscheck.json'))

false_neg = [
    d for d in data
    if not d['agrees_with_pass1']
    and d['composio_registry_has_toolkit']
    and d['pass1_guessed_existing_mcp'] != True
]
false_pos = [
    d for d in data
    if not d['agrees_with_pass1']
    and not d['composio_registry_has_toolkit']
    and d['pass1_guessed_existing_mcp'] == True
]

print(f"Pass 1 too pessimistic (Composio has it, agent said no/unknown): {len(false_neg)}")
for d in false_neg:
    print(f"  - {d['name']}")

print(f"\nPass 1 too optimistic (agent said yes, Composio doesn't have it): {len(false_pos)}")
for d in false_pos:
    print(f"  - {d['name']}")