"""Decode local recorder management-console status samples."""


def decode(document):
    if not isinstance(document, dict) or set(document) != {'feed', 'start', 'end', 'samples'}:
        raise ValueError('invalid recorder observation packet')
    feed, start, end, samples = (document[key] for key in ('feed', 'start', 'end', 'samples'))
    if not isinstance(feed, str) or not feed.strip() or type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError('invalid recorder or bounds')
    if not isinstance(samples, list):
        raise ValueError('samples must be an array')
    entries = []
    start_after = start - 1
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {'at', 'state'}:
            raise ValueError('invalid recorder observation')
        at, state = sample['at'], sample['state']
        if type(at) is not int or not start_after < at < end or state not in ('up', 'down'):
            raise ValueError(f'invalid or reordered recorder observation: {at}')
        entries.append((at, state))
        start_after = at
    return {'feed': feed, 'start': start, 'end': end, 'observations': entries}
