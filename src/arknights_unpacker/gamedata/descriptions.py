"""Shared safe rich-text interpreter. Unknown placeholders remain visible."""
import html
import re

PLACEHOLDER = re.compile(r'\{([^{}:]+)(?::([^{}]+))?\}')
TAG = re.compile(r'<(?:@[^>]*|/?(?:color|b|i|size|u)(?:=[^>]*)?|/)>')
TERM = re.compile(r'<\$([^>]+)>(.*?)</>', re.S)


def blackboard_map(board):
    if isinstance(board, dict):
        return {str(key).lower():value for key,value in board.items()}
    return {str(item['key']).lower(): item.get('valueStr') if item.get('valueStr') is not None else item.get('value') for item in board or [] if isinstance(item, dict) and 'key' in item}


def render_description(description, blackboard=None, terms=None, inherited=None):
    diagnostics = []
    if description is None:
        return '', diagnostics
    values = blackboard_map(inherited)
    values.update(blackboard_map(blackboard))
    def substitute(match):
        key, spec = match.group(1).lower(), match.group(2)
        # Leading '-' is a formatting operation in the game's templates.
        negate = key.startswith('-') and key not in values
        lookup = key[1:] if negate else key
        if lookup not in values or values[lookup] is None:
            diagnostics.append(f'unresolved placeholder: {match.group(0)}')
            return match.group(0)
        value = values[lookup]
        if negate and isinstance(value, (int, float)):
            value = -value
        if not spec:
            return f'{value:g}' if isinstance(value, (int, float)) else str(value)
        if not isinstance(value, (int, float)):
            diagnostics.append(f'non-numeric format: {match.group(0)}')
            return match.group(0)
        if not re.fullmatch(r'0(?:\.[0#]+)?%?', spec):
            diagnostics.append(f'unsupported format: {match.group(0)}')
            return match.group(0)
        percent = spec.endswith('%')
        decimals = len(spec.rstrip('%').split('.')[1]) if '.' in spec else 0
        return f'{value * (100 if percent else 1):.{decimals}f}' + ('%' if percent else '')
    result = PLACEHOLDER.sub(substitute, str(description))
    def term(match):
        key, label = match.groups()
        entry = (terms or {}).get(key)
        if not entry:
            diagnostics.append(f'unresolved term: {key}')
            return label + f' [术语:{key}]'
        text = entry.get('description', '') if isinstance(entry, dict) else str(entry)
        # Keep the term explanation adjacent so exports retain the semantics.
        return label + ('（' + TAG.sub('', text) + '）' if text else '')
    result = TERM.sub(term, result)
    result = re.sub(r'<br\s*/?>', '\n', result, flags=re.I)
    result = TAG.sub('', result)
    return html.unescape(result).replace('\\n', '\n'), diagnostics
