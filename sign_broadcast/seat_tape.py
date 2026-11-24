from .store import current


def codebook(db, cue_id):
    cue = current(db, 'cue')[cue_id]
    words = {}
    for row in current(db, 'seat_pattern').values():
        if row['cue'] != cue_id or row['cue_rev'] != cue['rev']:
            continue
        if row['label'] in words or row['pulse'] in words.values():
            raise ValueError('ambiguous seat pattern')
        words[row['label']] = row['pulse']
    if not words:
        raise ValueError('no seat patterns for the current cue')
    return cue['rev'], words


def emit(db, cue_id, labels):
    revision, words = codebook(db, cue_id)
    return {'cue': cue_id, 'cue_rev': revision,
            'frames': [words[label] for label in labels]}


def receive(db, cue_id, frames):
    revision, words = codebook(db, cue_id)
    lookup = {word: label for label, word in words.items()}
    return {'cue': cue_id, 'cue_rev': revision,
            'received': [lookup[frame] for frame in frames]}
