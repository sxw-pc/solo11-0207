def span(row):
    return row['start'], row['end']


def clip(a, b):
    left, right = max(a[0], b[0]), min(a[1], b[1])
    return (left, right) if left < right else None


def covers(outer, inner):
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def slices(bounds, labeled):
    clipped = [(part, value) for region, value in labeled if (part := clip(bounds, region))]
    points = sorted({*bounds, *(p for region, _ in clipped for p in region)})
    for left, right in zip(points, points[1:]):
        yield (left, right), [value for (lo, hi), value in clipped if lo <= left < hi]


def append_slice(records, region, **data):
    if records and records[-1]['end'] == region[0] and all(records[-1][key] == val for key, val in data.items()):
        records[-1]['end'] = region[1]
    else:
        records.append({'start': region[0], 'end': region[1], **data})
