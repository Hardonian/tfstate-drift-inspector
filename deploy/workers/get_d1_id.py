import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        for d in data:
            if d.get('name') == 'drift_inspector':
                print(d.get('id') or d.get('uuid') or '')
                break
    elif isinstance(data, dict) and 'result' in data:
        for d in data['result']:
            if d.get('name') == 'drift_inspector':
                print(d.get('id') or d.get('uuid') or '')
                break
except Exception as e:
    pass