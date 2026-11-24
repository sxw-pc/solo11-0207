from .store import current
from .timeline import append_slice, covers, slices, span


class Agenda:
    def __init__(self, db):
        self.sessions = current(db, 'session')
        self.cues = current(db, 'cue')
        self.rehearsals = current(db, 'rehearsal')

    def terms(self, cue):
        session = self.sessions[cue['session']]
        relevant = [r for r in self.rehearsals.values() if r['cue'] == cue['id']
                    and r['cue_rev'] == cue['rev'] and r['language'] == session['language']]
        result = {}
        for term in cue['terms'].split(',') if cue['terms'] else ():
            tickets = [r for r in relevant if r['term'] == term]
            status = 'ready' if tickets and all(r['accepted'] for r in tickets) else 'unready'
            result[term] = {'status': status, 'evidence': tickets}
        return result

    def assess(self, session_id):
        session = self.sessions[session_id]
        requested = [cue for cue in self.cues.values() if cue['session'] == session_id]
        cues = [cue for cue in requested if covers(span(session), span(cue))]
        partitions = []
        for region, active in slices(span(session), [(span(cue), cue['id']) for cue in cues]):
            status = 'scheduled' if len(active) == 1 else ('overlap' if active else 'unscheduled')
            append_slice(partitions, region, cues=active, status=status)
        terms = {cue['id']: self.terms(cue) for cue in cues}
        return {'session': session, 'cues': cues, 'outside': [c for c in requested if c not in cues],
                'partitions': partitions, 'terms': terms}
