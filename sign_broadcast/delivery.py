from .store import encode, fingerprint, transaction
from .timeline import append_slice, covers, slices, span


class Delivery:
    def __init__(self, db, agenda, crew, picture):
        self.db = db
        self.agenda = agenda
        self.crew = crew
        self.picture = picture

    def assess(self, session_id, asset_id=None):
        schedule = self.agenda.assess(session_id)
        crew = self.crew.assess(session_id)
        session = schedule['session']
        asset = self.picture.assets[asset_id] if asset_id is not None else None
        if asset is not None and asset['session'] != session_id:
            raise ValueError('asset belongs to another session')
        current_asset = asset is None or asset['session_rev'] == session['rev']
        reviews = self.picture.for_program(crew['turns'], asset)
        regions = [(span(item), ('agenda', item)) for item in schedule['partitions']]
        regions.extend((span(item), ('crew', item)) for item in crew['partitions'])
        regions.extend((span(item['review']), ('picture', item['review']['id'])) for item in reviews)
        if asset:
            regions.append((span(asset), ('asset', asset['id'])))
        timeline = []
        for window, active in slices(span(session), regions):
            agenda = next(item for key, item in active if key == 'agenda')
            staffing = next(item for key, item in active if key == 'crew')
            reasons = []
            if agenda['status'] != 'scheduled':
                reasons.append('agenda-' + agenda['status'])
            for cue in agenda['cues']:
                reasons.extend('term-unready:' + term for term, status in schedule['terms'][cue].items()
                               if status['status'] != 'ready')
            if staffing['status'] != 'covered':
                reasons.append(staffing['status'])
            proofs = []
            if len(staffing['turns']) == 1:
                picture_reasons, proofs = self.picture.region(reviews, staffing['turns'][0], window)
                reasons.extend(picture_reasons)
            if not current_asset:
                reasons.append('stale-session-asset')
            if asset and not covers(span(asset), window):
                reasons.append('asset-gap')
            append_slice(timeline, window, cues=agenda['cues'], turns=staffing['turns'],
                         reviews=proofs, reasons=sorted(set(reasons)))
        holds = []
        if schedule['outside']:
            holds.append('cue-outside-session')
        if crew['invalid_turns']:
            holds.append('turn-outside-cue')
        evidence = {'agenda': schedule, 'crew': crew, 'asset': asset, 'pictures': reviews,
                    'timeline': timeline, 'holds': holds}
        gap_seconds = sum(row['end'] - row['start'] for row in timeline if row['reasons'])
        state = 'incomplete' if gap_seconds or holds else 'ready'
        basis = fingerprint(evidence)
        signature = None
        if asset:
            signed = self.db.execute('SELECT seq,basis FROM replay_sign WHERE asset=? ORDER BY seq DESC LIMIT 1',
                                     (asset['id'],)).fetchone()
            status = 'unsigned' if signed is None else 'stale'
            if signed and signed['basis'] == basis and state == 'ready':
                status = 'current'
            signature = {'status': status, 'seq': signed['seq'] if signed else None}
        return {'session': session_id, 'mode': 'replay' if asset else 'live', 'asset': asset_id,
                'status': state, 'gap_seconds': gap_seconds,
                'gaps': [row for row in timeline if row['reasons']], 'holds': holds,
                'basis': basis, 'signature': signature, 'evidence': evidence}


def resign(db, build, asset_id, basis, operator):
    if not operator.strip():
        raise ValueError('operator required')
    with transaction(db):
        _, _, picture, delivery = build(db)
        asset = picture.assets[asset_id]
        result = delivery.assess(asset['session'], asset_id)
        if result['basis'] != basis:
            raise ValueError('replay basis changed; assess again')
        if result['status'] != 'ready':
            raise ValueError('cannot sign incomplete replay')
        if result['signature']['status'] == 'current':
            return result['signature']['seq']
        return db.execute('INSERT INTO replay_sign(asset,basis,operator,evidence) VALUES (?,?,?,?)',
                          (asset_id, basis, operator, encode(result['evidence']))).lastrowid
