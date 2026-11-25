from .crew import LEAD_SECONDS


TRACKS = ('program', 'sign')
FRAGMENT_KEYS = ('track', 'target', 'session', 'asset', 'rev', 'source')
RECEIPT_KEYS = ('id', 'session', 'source', 'program_asset', 'program_rev',
                'sign_asset', 'sign_rev', 'turn', 'turn_rev', 'approved')


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} requires text')
    return value


def _rev(value, field):
    if type(value) is not int or not 1 <= value < 2**63:
        raise ValueError(f'{field} must be a positive SQLite integer')
    return value


def _interval(value, field):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(v) is not int or not 0 <= v < 2**63 for v in value)
            or not value[0] < value[1]):
        raise ValueError(f'{field} must be a [start, end) pair of nonnegative integers')
    return tuple(value)


def fragment(row):
    if not isinstance(row, dict) or set(row) != set(FRAGMENT_KEYS):
        raise ValueError(f'fragment requires {", ".join(FRAGMENT_KEYS)}')
    target = _interval(row['target'], 'fragment.target')
    source = _interval(row['source'], 'fragment.source')
    if target[1] - target[0] != source[1] - source[0]:
        raise ValueError('fragment target and source must have equal length')
    if row['track'] not in TRACKS:
        raise ValueError(f'fragment.track must be one of {", ".join(TRACKS)}')
    return {'track': row['track'], 'target': target, 'source': source,
            'session': _text(row['session'], 'fragment.session'),
            'asset': _text(row['asset'], 'fragment.asset'),
            'rev': _rev(row['rev'], 'fragment.rev')}


def receipt(row):
    if not isinstance(row, dict) or set(row) != set(RECEIPT_KEYS):
        raise ValueError(f'receipt requires {", ".join(RECEIPT_KEYS)}')
    if type(row['source']) is not int or not 0 <= row['source'] < 2**63:
        raise ValueError('receipt.source must be a nonnegative SQLite integer')
    if row['approved'] not in (0, 1):
        raise ValueError('receipt.approved must be 0 or 1')
    return {'id': _text(row['id'], 'receipt.id'),
            'session': _text(row['session'], 'receipt.session'),
            'source': row['source'],
            'program_asset': _text(row['program_asset'], 'receipt.program_asset'),
            'program_rev': _rev(row['program_rev'], 'receipt.program_rev'),
            'sign_asset': _text(row['sign_asset'], 'receipt.sign_asset'),
            'sign_rev': _rev(row['sign_rev'], 'receipt.sign_rev'),
            'turn': _text(row['turn'], 'receipt.turn'),
            'turn_rev': _rev(row['turn_rev'], 'receipt.turn_rev'),
            'approved': row['approved']}


def _distinct(entries):
    kept = {}
    for entry in entries:
        key = (entry['session'], entry['asset'], entry['rev'], entry['source'])
        kept.setdefault(key, entry)
    return list(kept.values())


class Splice:
    def __init__(self, agenda, crew, picture, delivery):
        self.agenda = agenda
        self.crew = crew
        self.picture = picture
        self.delivery = delivery

    def claim_faults(self, track, claim):
        asset = self.picture.assets.get(claim['asset'])
        if asset is None:
            return [f'{track}-asset-unknown']
        faults = []
        if asset['rev'] != claim['rev']:
            faults.append(f'{track}-asset-stale')
        if asset['session'] != claim['session']:
            faults.append(f'{track}-asset-session-mismatch')
        return faults

    def receipt_faults(self, ticket):
        faults = []
        for role in TRACKS:
            asset = self.picture.assets.get(ticket[f'{role}_asset'])
            if asset is None:
                faults.append(f'{role}-asset-unknown')
                continue
            if asset['rev'] != ticket[f'{role}_rev']:
                faults.append(f'{role}-asset-stale')
            if asset['session'] != ticket['session']:
                faults.append(f'{role}-asset-session-mismatch')
        turn = self.crew.turns.get(ticket['turn'])
        if turn is None:
            faults.append('turn-unknown')
        elif turn['rev'] != ticket['turn_rev']:
            faults.append('turn-stale')
        return faults

    def source_reasons(self, cache, session_id, asset_id, second):
        key = (session_id, asset_id)
        if key not in cache:
            cache[key] = self.delivery.assess(session_id, asset_id)
        for row in cache[key]['evidence']['timeline']:
            if row['start'] <= second < row['end']:
                return list(row['reasons'])
        return ['source-outside-session']

    def assess(self, plan):
        if not isinstance(plan, dict) or not isinstance(plan.get('fragments'), list) or not plan['fragments']:
            raise ValueError('splice plan requires a nonempty fragments array')
        fragments = [fragment(row) for row in plan['fragments']]
        raw_receipts = plan.get('receipts', [])
        if not isinstance(raw_receipts, list):
            raise ValueError('splice plan receipts must be an array')
        receipts = [receipt(row) for row in raw_receipts]
        if len({r['id'] for r in receipts}) != len(receipts):
            raise ValueError('receipt ids must be distinct')
        lo = min(f['target'][0] for f in fragments)
        hi = max(f['target'][1] for f in fragments)
        claims = {t: {track: [] for track in TRACKS} for t in range(lo, hi)}
        for index, f in enumerate(fragments):
            for at in range(f['target'][0], f['target'][1]):
                claims[at][f['track']].append(
                    {'fragment': index, 'session': f['session'], 'asset': f['asset'],
                     'rev': f['rev'], 'source': f['source'][0] + at - f['target'][0]})
        distinct = {t: {track: _distinct(claims[t][track]) for track in TRACKS} for t in claims}
        reasons, aligned, cache = {}, {}, {}
        for t in range(lo, hi):
            found, picks = [], {}
            for track in TRACKS:
                options = distinct[t][track]
                if not options:
                    found.append(f'{track}-source-missing')
                elif len(options) > 1:
                    found.append(f'{track}-source-ambiguous')
                else:
                    faults = self.claim_faults(track, options[0])
                    found.extend(faults)
                    if not faults:
                        picks[track] = options[0]
            if len(picks) == len(TRACKS):
                program, sign = picks['program'], picks['sign']
                if program['session'] != sign['session']:
                    found.append('session-mismatch')
                elif program['source'] != sign['source']:
                    found.append('source-second-mismatch')
                else:
                    aligned[t] = (sign['session'], sign['source'])
                    found.extend(self.source_reasons(cache, sign['session'], sign['asset'], sign['source']))
            reasons[t] = found
        handoffs, points = {}, {}
        for index, f in enumerate(fragments):
            session_id, at = f['session'], f['source'][0]
            if session_id not in self.agenda.sessions:
                continue
            if session_id not in handoffs:
                handoffs[session_id] = {}
                for report in self.crew.assess(session_id)['handoffs']:
                    handoffs[session_id].setdefault(report['at'], []).append(report)
            if at in handoffs[session_id]:
                points.setdefault((f['target'][0], session_id, at), []).append(index)
        used, seams = set(), []
        for (target, session_id, at), owners in sorted(points.items()):
            seam = {'target': target, 'session': session_id, 'source': at,
                    'handoffs': [{'outgoing': h['outgoing'], 'incoming': h['incoming'], 'status': h['status']}
                                 for h in handoffs[session_id][at]]}
            window = range(target - LEAD_SECONDS, target)
            if all(aligned.get(t) == (session_id, at - target + t) and not reasons[t] for t in window):
                providers = sorted({c['fragment'] for t in window for track in TRACKS
                                    for c in distinct[t][track]})
                seam.update(status='context', reasons=[], context={
                    'kind': 'preroll', 'target': [target - LEAD_SECONDS, target],
                    'source': [at - LEAD_SECONDS, at], 'fragments': providers})
            else:
                program_assets = {c['asset'] for c in distinct[target]['program']}
                sign_assets = {c['asset'] for c in distinct[target]['sign']}
                bound = [r for r in receipts if r['session'] == session_id and r['source'] == at
                         and r['program_asset'] in program_assets and r['sign_asset'] in sign_assets]
                valid = [r for r in bound if r['approved'] == 1 and not self.receipt_faults(r)]
                if valid:
                    used.add(valid[0]['id'])
                    seam.update(status='receipt', reasons=[],
                                context={'kind': 'receipt', 'id': valid[0]['id']})
                else:
                    found = ['missing-relay-context']
                    if any(r['approved'] != 1 for r in bound):
                        found.append('opening-receipt-rejected')
                    if any(r['approved'] == 1 for r in bound):
                        found.append('opening-receipt-expired')
                    end = min(target + LEAD_SECONDS, max(fragments[i]['target'][1] for i in owners))
                    for t in range(target, end):
                        reasons[t].extend(reason for reason in found if reason not in reasons[t])
                    seam.update(status='pending', reasons=found, context=None)
            seams.append(seam)
        receipt_rows = []
        for r in receipts:
            faults = self.receipt_faults(r)
            if r['approved'] != 1:
                status = 'rejected'
            elif faults:
                status = 'expired'
            elif r['id'] in used:
                status = 'accepted'
            else:
                status = 'unused'
            receipt_rows.append({'id': r['id'], 'status': status,
                                 'reasons': ([] if r['approved'] == 1 else ['not-approved']) + faults})

        def interval(claim, start, end):
            f = fragments[claim['fragment']]
            first = f['source'][0] + start - f['target'][0]
            return {'session': claim['session'], 'asset': claim['asset'], 'rev': claim['rev'],
                    'start': first, 'end': first + end - start}

        merged = []
        for t in range(lo, hi):
            key = (tuple(reasons[t]),
                   tuple(c['fragment'] for c in distinct[t]['program']),
                   tuple(c['fragment'] for c in distinct[t]['sign']))
            if merged and merged[-1][0] == key:
                merged[-1][1]['end'] = t + 1
            else:
                merged.append((key, {'start': t, 'end': t + 1}))
        timeline = []
        for (row_reasons, _, _), row in merged:
            start, end = row['start'], row['end']
            program, sign = distinct[start]['program'], distinct[start]['sign']
            entry = {'start': start, 'end': end,
                     'program': interval(program[0], start, end) if len(program) == 1 else None,
                     'sign': interval(sign[0], start, end) if len(sign) == 1 else None,
                     'status': 'pending' if row_reasons else 'ready',
                     'reasons': sorted(set(row_reasons))}
            if len(program) > 1 or len(sign) > 1:
                entry['claims'] = {'program': [interval(c, start, end) for c in program],
                                   'sign': [interval(c, start, end) for c in sign]}
            timeline.append(entry)
        pending = sum(1 for t in range(lo, hi) if reasons[t])
        return {'status': 'pending' if pending else 'ready', 'target': [lo, hi],
                'delivered_seconds': hi - lo - pending, 'pending_seconds': pending,
                'timeline': timeline, 'seams': seams, 'receipts': receipt_rows}
