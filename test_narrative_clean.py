import json
from analysis.narrative_llm import _clean_json_response

cases = {
    'plain': '{"a": 1}',
    'code_json': '```json\n{"a": 1}\n```',
    'code_json_trailing': '```json\n{"a": 1}\n```\n',
    'prefix_code': 'some prefix\n```json\n{"a": 1}\n```\nmore',
    'only_code': '```json\n{"a": 1}\n```',
    'mixed': 'Here is the result:\n```json\n{"a": 1}\n```\n',
}

for name, value in cases.items():
    cleaned = _clean_json_response(value)
    try:
        parsed = json.loads(cleaned)
        print(f'✅ {name}: {parsed}')
    except json.JSONDecodeError as e:
        print(f'❌ {name}: {e}\n   cleaned={cleaned!r}')

print('\nAll done.')
