import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from sign_broadcast.__main__ import build, demo, read, recompute, run
from sign_broadcast.delivery import resign
from sign_broadcast.splice import Splice
from sign_broadcast.store import connect, ingest, transaction


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'fixtures'


class BroadcastTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(dir=ROOT))
        self.path = Path(directory) / 'test.sqlite'
        self.db = self.enterContext(closing(connect(self.path, create=True)))
        self.capture = read(FIXTURES / 'demo.json')['capture']
        self.baseline = demo(self.db, FIXTURES / 'demo.json')

    def edit(self, table, key, **updates):
        row = next(row for row in self.capture if row['type'] == table and row['id'] == key)
        return {**row, 'rev': 2, **updates}

    def crew(self, session='main'):
        return build(self.db)[1].assess(session)

    def replay(self):
        return build(self.db)[3].assess('main', 'replay-main')

    def splice(self, plan):
        agenda, crew, picture, delivery = build(self.db)
        return Splice(agenda, crew, picture, delivery).assess(plan)

    def plan(self):
        return read(FIXTURES / 'splice-main.json')

    def preroll(self, target):
        return [{'track': track, 'target': list(target), 'session': 'main',
                 'asset': 'replay-main', 'rev': 1, 'source': [117, 120]} for track in ('program', 'sign')]

    def test_agenda_reports_gaps_conflicts_and_outside_cues(self):
        agenda = build(self.db)[0]
        self.assertEqual(agenda.assess('side')['partitions'][-1],
                         {'start': 156, 'end': 160, 'cues': [], 'status': 'unscheduled'})
        ingest(self.db, [self.edit('cue', 'welcome', end=123)])
        self.assertIn('overlap', [s['status'] for s in build(self.db)[0].assess('main')['partitions']])
        ingest(self.db, [self.edit('cue', 'welcome', rev=3, start=99)])
        self.assertEqual(build(self.db)[3].assess('main')['holds'], ['cue-outside-session'])

    def test_late_agenda_invalidates_terms_turns_picture_and_replay(self):
        self.assertEqual(self.replay()['signature']['status'], 'current')
        ingest(self.db, read(FIXTURES / 'late-agenda.json'))
        agenda, crew, picture, delivery = build(self.db)
        self.assertEqual(agenda.assess('main')['terms']['questions']['estuary']['status'], 'unready')
        self.assertNotIn('turn-b', [turn['id'] for turn in crew.assess('main')['turns']])
        self.assertIn('stale-turn', picture.assess('replay-b')['reasons'])
        new = delivery.assess('main', 'replay-main')
        self.assertEqual(new['signature']['status'], 'stale')
        self.assertEqual(new['gap_seconds'], 20)
        self.assertIn('term-unready:salinity', new['gaps'][0]['reasons'])

    def test_agenda_recovery_rebinds_each_proof_before_new_signature(self):
        sequence = self.replay()['signature']['seq']
        ingest(self.db, read(FIXTURES / 'late-agenda.json'))
        ingest(self.db, read(FIXTURES / 'repair-agenda.json')[:-1])
        self.assertEqual(self.replay()['gaps'][0]['reasons'], ['picture-unreviewed'])
        ingest(self.db, read(FIXTURES / 'repair-agenda.json')[-1:])
        repaired = self.replay()
        self.assertEqual(repaired['status'], 'ready')
        self.assertEqual(repaired['signature']['status'], 'stale')
        self.assertGreater(resign(self.db, build, 'replay-main', repaired['basis'], 'director'), sequence)
        self.assertEqual(build(self.db)[3].assess('main')['gap_seconds'], 6)

    def test_live_and_replay_repairs_change_distinct_delivery_commitments(self):
        late = read(FIXTURES / 'late-overlay.json')
        ingest(self.db, late + read(FIXTURES / 'repair-live.json'))
        self.assertEqual(build(self.db)[3].assess('main')['gap_seconds'], 0)
        self.assertEqual(self.replay()['gap_seconds'], 40)
        other_path = self.path.with_name('alternate.sqlite')
        with closing(connect(other_path, create=True)) as other:
            demo(other, FIXTURES / 'demo.json')
            ingest(other, late + read(FIXTURES / 'repair-overlay.json'))
            delivery = build(other)[3]
            self.assertEqual(delivery.assess('main')['gap_seconds'], 6)
            replay = delivery.assess('main', 'replay-main')
            self.assertEqual(replay['gap_seconds'], 0)
            resign(other, build, 'replay-main', replay['basis'], 'director')
            self.assertEqual(delivery.assess('main', 'replay-main')['signature']['status'], 'current')

    def test_terms_require_matching_language_and_no_rejection(self):
        agenda = build(self.db)[0]
        self.assertEqual(agenda.assess('main')['terms']['welcome']['silt']['status'], 'ready')
        alternate = self.edit('rehearsal', 'r-silt', id='other-director', rev=1, accepted=0)
        ingest(self.db, [alternate])
        self.assertEqual(build(self.db)[0].assess('main')['terms']['welcome']['silt']['status'], 'unready')
        ingest(self.db, [{**alternate, 'rev': 2, 'language': 'ASL'}])
        self.assertEqual(build(self.db)[0].assess('main')['terms']['welcome']['silt']['status'], 'ready')

    def test_credential_denial_in_preroll_invalidates_witnessed_relay(self):
        self.assertEqual(self.crew()['handoffs'][0]['status'], 'ready')
        deny = self.edit('credential', 'c-lin-early', id='denial', rev=1, start=118, approved=0)
        ingest(self.db, [deny])
        crew = self.crew()
        self.assertEqual(crew['handoffs'][0]['status'], 'no-qualified-overlap')
        self.assertEqual(crew['handoffs'][0]['participants'][1]['reason'], 'credential-denied')
        self.assertEqual(self.replay()['gap_seconds'], 3)
        self.assertEqual(self.replay()['gaps'][0]['reasons'], ['relay-gap'])
        live = build(self.db)[3].assess('main')
        self.assertEqual(live['gap_seconds'], 6)
        self.assertEqual(live['gaps'][0]['reasons'], ['relay-gap', 'signer-obscured:live-bug'])

    def test_shift_and_credential_boundaries_are_independent(self):
        ingest(self.db, [self.edit('shift', 'shift-b', end=138), self.edit('credential', 'c-lin', end=135)])
        partitions = self.crew()['partitions']
        self.assertEqual([(p['start'], p['end'], p['status']) for p in partitions[-2:]],
                         [(135, 138, 'credential-missing'), (138, 140, 'outside-shift')])
        ingest(self.db, [self.edit('shift', 'shift-b', rev=3, person='Qiao')])
        self.assertIn('shift-identity', [p['status'] for p in self.crew()['partitions']])

    def test_witness_must_match_turn_versions_and_ambiguity_is_reported(self):
        ingest(self.db, [self.edit('turn', 'turn-b')])
        self.assertEqual(self.crew()['handoffs'][0]['status'], 'relay-unwitnessed')
        ingest(self.db, [self.edit('relay', 'relay-120', in_rev=2)])
        self.assertEqual(self.crew()['handoffs'][0]['status'], 'ready')
        ingest(self.db, [self.edit('turn', 'turn-a', id='duplicate-a', rev=1, start=119)])
        self.assertEqual(self.crew()['handoffs'][0]['status'], 'ambiguous-outgoing')
        self.assertIn('turn-overlap', [p['status'] for p in self.crew()['partitions']])

    def test_double_booking_in_other_session_breaks_preroll_and_on_air(self):
        data = [self.edit('session', 'side', start=117, end=130),
                self.edit('cue', 'workshop', start=117, end=124),
                self.edit('shift', 'shift-b', id='side-shift', rev=1, session='side'),
                self.edit('turn', 'turn-b', id='side-turn', rev=1, cue='workshop', cue_rev=2,
                          shift='side-shift', start=118, end=124)]
        ingest(self.db, data)
        crew = self.crew()
        relay = crew['handoffs'][0]
        self.assertEqual(relay['participants'][1]['competing_turns'][0]['id'], 'side-turn')
        self.assertEqual(relay['status'], 'no-qualified-overlap')
        self.assertEqual(self.replay()['gap_seconds'], 4)
        self.assertIn('double-booked', self.replay()['gaps'][0]['reasons'])

    def test_picture_safe_frame_size_crop_and_overlay_contact(self):
        picture = build(self.db)[2]
        self.assertEqual(picture.assess('live-b0')['reasons'], ['signer-obscured:live-bug'])
        self.assertEqual(picture.assess('replay-b')['status'], 'readable')
        ingest(self.db, [self.edit('layout', 'replay-right', left=5, right=140),
                         self.edit('review', 'replay-b', layout_rev=2, left=90, right=180, top=180, bottom=290)])
        self.assertEqual(set(build(self.db)[2].assess('replay-b')['reasons']),
                         {'inset-outside-safe-frame', 'inset-too-small', 'signer-cropped', 'signer-too-small'})

    def test_picture_review_conflict_and_uncovered_live_slice(self):
        data = [self.edit('review', 'live-b1', start=128),
                self.edit('review', 'live-b0', id='conflicting-review', rev=1, start=123, end=126,
                          layout='live-left', left=40, right=180)]
        ingest(self.db, data)
        result = build(self.db)[3].assess('main')
        self.assertEqual(result['gap_seconds'], 8)
        self.assertIn('conflicting-layouts', result['gaps'][1]['reasons'])
        self.assertEqual(result['gaps'][-1]['reasons'], ['picture-unreviewed'])
        self.assertEqual(self.replay()['status'], 'ready')

    def test_delivery_keeps_asset_boundaries_and_live_separate(self):
        delivery = build(self.db)[3]
        self.assertEqual(delivery.assess('main')['gap_seconds'], 6)
        self.assertEqual(delivery.assess('main', 'replay-main')['gap_seconds'], 0)
        self.assertEqual(delivery.assess('side', 'replay-side')['gap_seconds'], 10)
        with self.assertRaisesRegex(ValueError, 'another session'):
            delivery.assess('side', 'replay-main')
        ingest(self.db, [self.edit('asset', 'replay-main', end=139)])
        after = self.replay()
        self.assertIn('stale-asset', build(self.db)[2].assess('replay-b')['reasons'])
        self.assertIn('asset-gap', after['gaps'][-1]['reasons'])
        self.assertEqual(after['signature']['status'], 'stale')

    def test_overlay_evidence_reopens_replay_then_resigns(self):
        initial = self.replay()
        basis = initial['basis']
        sequence = initial['signature']['seq']
        self.assertEqual(resign(self.db, build, 'replay-main', basis, 'director'), sequence)
        ingest(self.db, read(FIXTURES / 'late-overlay.json'))
        stale = self.replay()
        self.assertEqual(stale['gap_seconds'], 40)
        self.assertEqual(stale['signature']['status'], 'stale')
        with self.assertRaisesRegex(ValueError, 'basis changed'):
            resign(self.db, build, 'replay-main', basis, 'director')
        with self.assertRaisesRegex(ValueError, 'incomplete replay'):
            resign(self.db, build, 'replay-main', stale['basis'], 'director')
        ingest(self.db, read(FIXTURES / 'repair-overlay.json'))
        repaired = self.replay()
        self.assertEqual(repaired['gap_seconds'], 0)
        self.assertEqual(repaired['signature']['status'], 'stale')
        next_seq = resign(self.db, build, 'replay-main', repaired['basis'], 'director')
        self.assertGreater(next_seq, sequence)
        self.assertEqual(self.replay()['signature'], {'status': 'current', 'seq': next_seq})
        old = self.db.execute('SELECT evidence FROM replay_sign WHERE seq=?', (sequence,)).fetchone()
        self.assertEqual(json.loads(old['evidence'])['pictures'][0]['overlays'][0]['rev'], 1)

    def test_atomic_ingest_idempotency_and_arrival_order(self):
        with self.assertRaisesRegex(ValueError, 'conflicting cue'):
            ingest(self.db, [self.edit('cue', 'questions', rev=3), self.edit('cue', 'questions', rev=1, end=138)])
        self.assertEqual(recompute(self.db), self.baseline)
        latest = self.edit('cue', 'questions', rev=3)
        self.assertEqual(ingest(self.db, [latest, self.edit('cue', 'questions'), latest]),
                         {'inserted': 2, 'replayed': 1})
        self.assertEqual(build(self.db)[0].cues['questions']['rev'], 3)

    def test_ingest_recompute_and_replay_from_new_connection(self):
        with closing(connect(self.path)) as other, transaction(other, write=False):
            self.assertEqual(recompute(other), self.baseline)
        self.assertEqual(demo(self.db, FIXTURES / 'demo.json'), self.baseline)

    def test_splice_inherited_preroll_delivers_full_master(self):
        plan = self.plan()
        plan['fragments'] += self.preroll((117, 120))
        result = self.splice(plan)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['target'], [100, 140])
        self.assertEqual(result['delivered_seconds'], 40)
        self.assertEqual(result['pending_seconds'], 0)
        seam = result['seams'][0]
        self.assertEqual((seam['target'], seam['session'], seam['source']), (120, 'main', 120))
        self.assertEqual(seam['handoffs'], [{'outgoing': 'turn-a', 'incoming': 'turn-b', 'status': 'ready'}])
        self.assertEqual(seam['status'], 'context')
        self.assertEqual(seam['context']['kind'], 'preroll')
        self.assertEqual(seam['context']['target'], [117, 120])
        self.assertEqual(seam['context']['source'], [117, 120])
        self.assertEqual(result['receipts'][0]['status'], 'unused')

    def test_splice_opening_receipt_covers_seam_for_short_master(self):
        result = self.splice(self.plan())
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['delivered_seconds'], 37)
        self.assertEqual(result['pending_seconds'], 3)
        gap = result['timeline'][1]
        self.assertEqual((gap['start'], gap['end']), (117, 120))
        self.assertEqual(gap['reasons'], ['program-source-missing', 'sign-source-missing'])
        seam = result['seams'][0]
        self.assertEqual(seam['status'], 'receipt')
        self.assertEqual(seam['context'], {'kind': 'receipt', 'id': 'opening-120'})
        self.assertEqual(result['receipts'], [{'id': 'opening-120', 'status': 'accepted', 'reasons': []}])

    def test_splice_short_master_without_receipt_pends_seam(self):
        plan = self.plan()
        del plan['receipts']
        result = self.splice(plan)
        self.assertEqual(result['delivered_seconds'], 34)
        self.assertEqual(result['pending_seconds'], 6)
        seam = result['seams'][0]
        self.assertEqual(seam['status'], 'pending')
        self.assertEqual(seam['context'], None)
        self.assertEqual(seam['reasons'], ['missing-relay-context'])
        row = next(row for row in result['timeline'] if row['start'] == 120)
        self.assertEqual((row['end'], row['reasons']), (123, ['missing-relay-context']))

    def test_splice_preroll_elsewhere_leaves_seam_pending(self):
        plan = self.plan()
        del plan['receipts']
        plan['fragments'] += self.preroll((140, 143))
        result = self.splice(plan)
        self.assertEqual(result['seams'][0]['status'], 'pending')
        self.assertEqual(result['seams'][0]['reasons'], ['missing-relay-context'])
        self.assertEqual(result['pending_seconds'], 6)
        moved = next(row for row in result['timeline'] if row['start'] == 140)
        self.assertEqual(moved['status'], 'ready')
        self.assertEqual((moved['program']['start'], moved['program']['end']), (117, 120))
        self.assertEqual((moved['sign']['start'], moved['sign']['end']), (117, 120))

    def test_splice_sign_offset_breaks_source_alignment(self):
        plan = self.plan()
        del plan['receipts']
        for row in plan['fragments']:
            if row['track'] == 'sign':
                row['source'] = [row['source'][0] + 1, row['source'][1] + 1]
        result = self.splice(plan)
        self.assertEqual(result['timeline'][0]['reasons'], ['source-second-mismatch'])
        self.assertEqual(result['timeline'][-1]['reasons'], ['source-second-mismatch'])
        shifted = next(row for row in result['timeline'] if row['start'] == 120)
        self.assertEqual(shifted['reasons'], ['missing-relay-context', 'source-second-mismatch'])
        self.assertEqual(result['pending_seconds'], 40)
        self.assertEqual(result['delivered_seconds'], 0)

    def test_splice_keeps_ambiguous_sources_for_a_target_second(self):
        plan = self.plan()
        del plan['receipts']
        plan['fragments'].append({'track': 'program', 'target': [110, 120], 'session': 'side',
                                  'asset': 'replay-side', 'rev': 1, 'source': [150, 160]})
        result = self.splice(plan)
        row = next(row for row in result['timeline'] if row['start'] == 110)
        self.assertEqual((row['end'], row['reasons']), (117, ['program-source-ambiguous']))
        self.assertIsNone(row['program'])
        self.assertEqual(row['claims']['program'], [
            {'session': 'main', 'asset': 'replay-main', 'rev': 1, 'start': 110, 'end': 117},
            {'session': 'side', 'asset': 'replay-side', 'rev': 1, 'start': 150, 'end': 157}])
        self.assertEqual(row['claims']['sign'], [
            {'session': 'main', 'asset': 'replay-main', 'rev': 1, 'start': 110, 'end': 117}])

    def test_splice_relay_witness_loss_propagates_to_source_seconds(self):
        plan = self.plan()
        plan['fragments'] += self.preroll((117, 120))
        ingest(self.db, [self.edit('credential', 'c-lin-early', id='denial', rev=1, start=118, approved=0)])
        agenda, crew, picture, delivery = build(self.db)
        self.assertEqual(crew.assess('main')['handoffs'][0]['status'], 'no-qualified-overlap')
        self.assertEqual(delivery.assess('main', 'replay-main')['gaps'][0]['reasons'], ['relay-gap'])
        result = Splice(agenda, crew, picture, delivery).assess(plan)
        row = next(row for row in result['timeline'] if row['start'] == 120)
        self.assertEqual((row['end'], row['reasons']), (123, ['relay-gap']))
        self.assertEqual(result['seams'][0]['status'], 'context')
        self.assertEqual(result['delivered_seconds'], 37)

    def test_splice_receipt_expiry_and_rejection_return_seam_reasons(self):
        plan = self.plan()
        plan['receipts'][0]['turn_rev'] = 2
        result = self.splice(plan)
        self.assertEqual(result['seams'][0]['reasons'], ['missing-relay-context', 'opening-receipt-expired'])
        self.assertEqual(result['receipts'][0]['status'], 'expired')
        self.assertEqual(result['receipts'][0]['reasons'], ['turn-stale'])
        self.assertEqual(result['pending_seconds'], 6)
        plan = self.plan()
        plan['receipts'][0]['approved'] = 0
        result = self.splice(plan)
        self.assertEqual(result['seams'][0]['reasons'], ['missing-relay-context', 'opening-receipt-rejected'])
        self.assertEqual(result['receipts'][0]['status'], 'rejected')
        self.assertEqual(result['receipts'][0]['reasons'], ['not-approved'])

    def test_splice_layout_revocation_reopens_inherited_intervals(self):
        ingest(self.db, [self.edit('layout', 'replay-right')])
        agenda, crew, picture, delivery = build(self.db)
        self.assertEqual(delivery.assess('main', 'replay-main')['gap_seconds'], 40)
        result = Splice(agenda, crew, picture, delivery).assess(self.plan())
        self.assertEqual(result['pending_seconds'], 40)
        self.assertEqual(result['delivered_seconds'], 0)
        first, last = result['timeline'][0], result['timeline'][-1]
        self.assertEqual((first['start'], first['end'], first['reasons']), (100, 117, ['stale-layout']))
        self.assertEqual((last['start'], last['end'], last['reasons']), (120, 140, ['stale-layout']))
        self.assertEqual(result['seams'][0]['status'], 'receipt')

    def test_splice_plan_validation(self):
        with self.assertRaisesRegex(ValueError, 'fragments array'):
            self.splice({'fragments': []})
        with self.assertRaisesRegex(ValueError, 'fragment requires'):
            self.splice({'fragments': [{'track': 'program', 'target': [100, 117]}]})
        with self.assertRaisesRegex(ValueError, 'equal length'):
            self.splice({'fragments': [{'track': 'program', 'target': [100, 117], 'session': 'main',
                                        'asset': 'replay-main', 'rev': 1, 'source': [100, 118]}]})
        with self.assertRaisesRegex(ValueError, 'fragment.track'):
            self.splice({'fragments': [{'track': 'dubbed', 'target': [100, 117], 'session': 'main',
                                        'asset': 'replay-main', 'rev': 1, 'source': [100, 117]}]})
        plan = self.plan()
        plan['receipts'].append(plan['receipts'][0])
        with self.assertRaisesRegex(ValueError, 'distinct'):
            self.splice(plan)

    def test_splice_cli_stays_read_only(self):
        args = SimpleNamespace(command='splice', file=str(FIXTURES / 'splice-main.json'))
        before = recompute(self.db)
        output = run(self.db, args)
        self.assertEqual(output['delivered_seconds'], 37)
        self.assertEqual(output['seams'][0]['status'], 'receipt')
        self.assertEqual(recompute(self.db), before)

