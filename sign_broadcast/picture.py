from .store import current
from .timeline import clip, covers, span


SAFE_MARGIN = 12
MIN_INSET = (160, 160)
MIN_SIGNER = (100, 120)


def rect(record):
    return record['left'], record['top'], record['right'], record['bottom']


def fits(outer, inner):
    return outer[0] <= inner[0] < inner[2] <= outer[2] and outer[1] <= inner[1] < inner[3] <= outer[3]


def touches(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


class Picture:
    def __init__(self, db, agenda, crew):
        self.agenda = agenda
        self.crew = crew
        self.layouts = current(db, 'layout')
        self.overlays = current(db, 'overlay')
        self.reviews = current(db, 'review')
        self.assets = current(db, 'asset')

    def assess(self, review_id):
        review = self.reviews[review_id]
        turn = self.crew.turns.get(review['turn'])
        asset = self.assets.get(review['asset'])
        layout = self.layouts.get(review['layout'])
        reasons = []
        cue = self.agenda.cues.get(turn['cue']) if turn else None
        session = self.agenda.sessions.get(cue['session']) if cue else None
        if not turn or turn['rev'] != review['turn_rev'] or not cue or turn['cue_rev'] != cue['rev'] or not session:
            reasons.append('stale-turn')
        elif (not covers(span(session), span(cue)) or not covers(span(cue), span(turn))
              or not covers(span(turn), span(review))):
            reasons.append('review-outside-turn')
        if review['asset'] != '-':
            if not asset or asset['rev'] != review['asset_rev'] or not session or asset['session'] != session['id'] or (
                    asset['session_rev'] != session['rev']):
                reasons.append('stale-asset')
            elif not covers(span(asset), span(review)):
                reasons.append('review-outside-asset')
        window = rect(review)
        overlays = []
        if not layout or layout['rev'] != review['layout_rev']:
            reasons.append('stale-layout')
        else:
            inset = rect(layout)
            safe = SAFE_MARGIN, SAFE_MARGIN, layout['width'] - SAFE_MARGIN, layout['height'] - SAFE_MARGIN
            if not fits(safe, inset):
                reasons.append('inset-outside-safe-frame')
            if inset[2] - inset[0] < MIN_INSET[0] or inset[3] - inset[1] < MIN_INSET[1]:
                reasons.append('inset-too-small')
            if not fits(inset, window):
                reasons.append('signer-cropped')
            if window[2] - window[0] < MIN_SIGNER[0] or window[3] - window[1] < MIN_SIGNER[1]:
                reasons.append('signer-too-small')
            for overlay in self.overlays.values():
                if overlay['layout'] == layout['id'] and overlay['layout_rev'] == layout['rev']:
                    overlays.append(overlay)
                    if not fits((0, 0, layout['width'], layout['height']), rect(overlay)):
                        reasons.append('overlay-outside-frame:' + overlay['id'])
                    elif touches(window, rect(overlay)):
                        reasons.append('signer-obscured:' + overlay['id'])
        if not review['approved']:
            reasons.append('operator-rejected')
        return {'review': review, 'status': 'unreadable' if reasons else 'readable', 'reasons': reasons,
                'layout': layout, 'overlays': overlays}

    def for_program(self, turns, asset):
        key, version = (asset['id'], asset['rev']) if asset else ('-', 0)
        current_turns = {turn['id']: turn['rev'] for turn in turns}
        return [self.assess(r['id']) for r in self.reviews.values() if r['asset'] == key
                and r['asset_rev'] == version and current_turns.get(r['turn']) == r['turn_rev']]

    def region(self, reports, turn, window):
        relevant = [r for r in reports if r['review']['turn'] == turn and clip(window, span(r['review']))]
        reasons = sorted({reason for r in relevant for reason in r['reasons']})
        if len({(r['review']['layout'], r['review']['layout_rev']) for r in relevant}) > 1:
            reasons.append('conflicting-layouts')
        if not relevant:
            reasons.append('picture-unreviewed')
        return reasons, [r['review']['id'] for r in relevant]
