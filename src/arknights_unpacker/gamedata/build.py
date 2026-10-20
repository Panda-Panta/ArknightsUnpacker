"""Shared build validation and provenance, independent of profile implementations."""


def build_state(ch, spec):
    phases = ch.get('phases') or []
    if not phases:
        raise ValueError('character has no usable phase data')
    phase = len(phases) - 1 if spec.phase is None else spec.phase
    if not isinstance(phase, int) or not 0 <= phase < len(phases):
        raise ValueError('phase outside character bounds')
    level = phases[phase]['maxLevel'] if spec.level is None else spec.level
    if not 1 <= level <= phases[phase]['maxLevel']:
        raise ValueError('level outside character bounds')
    maximum = ch.get('maxPotentialLevel', len(ch.get('potentialRanks') or [])) + 1
    potential = maximum if spec.potential is None else spec.potential
    if not 1 <= potential <= maximum or not 0 <= spec.trust <= 200:
        raise ValueError('potential or trust outside bounds')
    return phase, level, potential - 1


def metadata(data, table, pointer):
    source = dict(data.sources.get(table, {}))
    source['pointer'] = pointer
    return {'version': data.version, 'resource_version': data.resource_version,
            'locale': data.locale, 'source': source, 'snapshot_id': data.snapshot_id}
