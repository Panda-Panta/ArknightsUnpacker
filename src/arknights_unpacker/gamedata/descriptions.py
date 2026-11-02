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


def render_description(description, blackboard=None, terms=None, inherited=None, *, term_definitions=None):
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
    collected = set()

    def clean(text):
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
        return html.unescape(TAG.sub('', text)).replace('\\n', '\n')

    def term(match, resolving):
        key, label = match.groups()
        entry = (terms or {}).get(key)
        if not entry:
            diagnostics.append(f'unresolved term: {key}')
            return label + f' [术语:{key}]'
        text = entry.get('description', '') if isinstance(entry, dict) else str(entry)
        if term_definitions is None:
            # Other description types retain their existing inline glossary.
            return label + ('（' + TAG.sub('', text) + '）' if text else '')
        if key in resolving:
            # Cold and frozen are valid mutually linked glossary entries.
            return label
        identity = (key, label)
        if text and identity not in collected:
            collected.add(identity)
            definition = {'term': clean(label), 'description': ''}
            term_definitions.append(definition)
            definition['description'] = fragment(text, (*resolving, key))
        return label

    def fragment(text, resolving=()):
        result = PLACEHOLDER.sub(substitute, str(text))
        return clean(TERM.sub(lambda match: term(match, resolving), result))

    result = fragment(description)
    if term_definitions is not None:
        # A collector may be reused across descriptions or module columns.
        unique = []
        for definition in term_definitions:
            if definition not in unique:
                unique.append(definition)
        term_definitions[:] = unique
    return result, diagnostics
