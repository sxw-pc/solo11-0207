from .store import current
from .timeline import append_slice, clip, covers, slices, span


LEAD_SECONDS = 3


class Crew:
    def __init__(self, db, agenda):
        self.agenda = agenda
        self.credentials = current(db, 'credential')
        self.shifts = current(db, 'shift')
        self.turns = current(db, 'turn')
        self.relays = current(db, 'relay')

    def for_cue(self, cue):
        return [t for t in self.turns.values() if t['cue'] == cue['id'] and t['cue_rev'] == cue['rev']]

    def qualifications(self, session, turn):
        return [c for c in self.credentials.values() if c['person'] == turn['person']
                and c['language'] == session['language']]

    def availability(self, session, turn, region, competing):
        shift = self.shifts.get(turn['shift'])
        credentials = [c for c in self.qualifications(session, turn) if clip(span(c), region)]
        conflicts = [t for t in competing if clip(span(t), region)]
        evidence = {'shift': shift, 'credentials': credentials, 'competing_turns': conflicts}
        if not shift or shift['person'] != turn['person'] or shift['session'] != session['id']:
            return {**evidence, 'reason': 'shift-identity'}
        if not covers(span(shift), region):
            return {**evidence, 'reason': 'outside-shift'}
        if any(not c['approved'] for c in credentials):
            return {**evidence, 'reason': 'credential-denied'}
        if not all(active for _, active in slices(region, [(span(c), c['id']) for c in credentials])):
            return {**evidence, 'reason': 'credential-missing'}
        return {**evidence, 'reason': 'double-booked' if conflicts else None}

    def check_relay(self, session, outgoing, incoming, competing):
        at = incoming['start']
        evidence = [r for r in self.relays.values() if r['outgoing'] == outgoing['id']
                    and r['out_rev'] == outgoing['rev'] and r['incoming'] == incoming['id']
                    and r['in_rev'] == incoming['rev'] and r['at'] == at]
        ready = (at - LEAD_SECONDS, at)
        participants = [self.availability(session, turn, ready, competing[turn['id']])
                        for turn in (outgoing, incoming)]
        status = 'ready'
        if at - outgoing['start'] < LEAD_SECONDS or any(p['reason'] for p in participants):
            status = 'no-qualified-overlap'
        elif len(evidence) != 1 or not evidence[0]['witnessed']:
            status = 'relay-unwitnessed'
        return {'at': at, 'outgoing': outgoing['id'], 'incoming': incoming['id'], 'status': status,
                'participants': participants, 'evidence': evidence}

    def session_turns(self, schedule):
        return [t for cue in schedule['cues'] for t in self.for_cue(cue) if covers(span(cue), span(t))]

    def competing_turns(self, session, turns):
        elsewhere = [t for session_id in self.agenda.sessions if session_id != session['id']
                     for t in self.session_turns(self.agenda.assess(session_id))]
        return {t['id']: [other for other in elsewhere if other['person'] == t['person']] for t in turns}

    def handoffs(self, session, turns, competing):
        reports = []
        for incoming in turns:
            at = incoming['start']
            outgoing = [t for t in turns if t['start'] < at <= t['end']]
            if len(outgoing) > 1 and any(t['end'] == at for t in outgoing):
                reports.append({'at': at, 'outgoing': [t['id'] for t in outgoing], 'incoming': incoming['id'],
                                'status': 'ambiguous-outgoing', 'participants': [], 'evidence': []})
            elif len(outgoing) == 1 and outgoing[0]['end'] == at and outgoing[0]['person'] != incoming['person']:
                reports.append(self.check_relay(session, outgoing[0], incoming, competing))
        return sorted(reports, key=lambda r: (r['at'], r['incoming']))

    def assess(self, session_id):
        schedule = self.agenda.assess(session_id)
        session = schedule['session']
        turns = self.session_turns(schedule)
        competing = self.competing_turns(session, turns)
        handoffs = self.handoffs(session, turns, competing)
        invalid = [t for cue in schedule['cues'] for t in self.for_cue(cue) if not covers(span(cue), span(t))]
        marks = [(span(t), ('turn', t['id'])) for t in turns]
        for turn in turns:
            shift = self.shifts.get(turn['shift'])
            sources = ([shift] if shift else []) + self.qualifications(session, turn) + competing[turn['id']]
            marks.extend((span(row), ('boundary', row['id'])) for row in sources)
        for relay in handoffs:
            if relay['status'] != 'ready':
                incoming = self.turns[relay['incoming']]
                marks.append(((relay['at'], min(relay['at'] + LEAD_SECONDS, incoming['end'])),
                              ('relay', incoming['id'])))
        partitions = []
        for region, labels in slices(span(session), marks):
            active = [value for kind, value in labels if kind == 'turn']
            evidence = None
            if len(active) != 1:
                status = 'turn-overlap' if active else 'no-turn'
            else:
                selected = active[0]
                evidence = self.availability(session, self.turns[selected], region, competing[selected])
                status = evidence['reason'] or ('relay-gap' if ('relay', selected) in labels else 'covered')
            append_slice(partitions, region, turns=active, status=status, evidence=evidence)
        return {'session': session_id, 'turns': turns, 'invalid_turns': invalid, 'partitions': partitions,
                'handoffs': handoffs}
