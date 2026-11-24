"""Account for observable recorder service time on the activity clock."""

from .recorder_capture import decode
from .timeline import append_slice


def assess(document, session):
    evidence = decode(document)
    if (evidence['start'], evidence['end']) != (session['start'], session['end']):
        raise ValueError('recorder packet and session bounds differ')
    window = evidence['start']
    state = 'unknown'
    timeline = []
    for at, new_state in [*evidence['observations'], (evidence['end'], 'unknown')]:
        if window < at:
            append_slice(timeline, (window, at), state=state)
        window = at
        state = new_state
    seconds = dict.fromkeys(('up', 'down', 'unknown'), 0)
    for item in timeline:
        seconds[item['state']] += item['end'] - item['start']
    return {'feed': evidence['feed'], 'session': session['id'], 'timeline': timeline,
            'seconds': seconds, 'raw': document}
