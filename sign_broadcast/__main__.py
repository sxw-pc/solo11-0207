import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .agenda import Agenda
from .recorder_uptime import assess as recorder_uptime
from .crew import Crew
from .delivery import Delivery, resign
from .picture import Picture
from .store import connect, ingest, transaction


def build(db):
    agenda = Agenda(db)
    crew = Crew(db, agenda)
    picture = Picture(db, agenda, crew)
    return agenda, crew, picture, Delivery(db, agenda, crew, picture)


def recompute(db):
    agenda, crew, picture, delivery = build(db)
    return {'agendas': [agenda.assess(key) for key in agenda.sessions],
            'crew': [crew.assess(key) for key in agenda.sessions],
            'pictures': [picture.assess(key) for key in picture.reviews],
            'live': [delivery.assess(key) for key in agenda.sessions],
            'replay': [delivery.assess(asset['session'], key) for key, asset in picture.assets.items()
                       if asset['session'] in agenda.sessions],
            'unlocated_assets': [key for key, asset in picture.assets.items() if asset['session'] not in agenda.sessions]}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def demo(db, fixture):
    data = read(fixture)
    ingest(db, data['capture'])
    for key in data['sign']:
        with transaction(db, write=False):
            _, _, picture, delivery = build(db)
            basis = delivery.assess(picture.assets[key]['session'], key)['basis']
        resign(db, build, key, basis, 'demo-director')
    with transaction(db, write=False):
        return recompute(db)


def parser():
    cli = argparse.ArgumentParser(description='Offline sign-language broadcast evidence')
    cli.add_argument('--db', required=True)
    sub = cli.add_subparsers(dest='command', required=True)
    sub.add_parser('demo').add_argument('fixture')
    sub.add_parser('ingest').add_argument('file')
    for name in ('agenda', 'crew', 'picture'):
        sub.add_parser(name).add_argument('id')
    report = sub.add_parser('delivery')
    report.add_argument('session')
    report.add_argument('--asset')
    sub.add_parser('recompute')
    monitor = sub.add_parser('recorder-health')
    monitor.add_argument('session')
    monitor.add_argument('file')
    sign = sub.add_parser('resign')
    for key in ('asset', 'basis', 'operator'):
        sign.add_argument(key)
    return cli


def run(db, args):
    if args.command == 'demo':
        return demo(db, args.fixture)
    if args.command == 'ingest':
        return ingest(db, read(args.file))
    if args.command == 'resign':
        return {'signature': resign(db, build, args.asset, args.basis, args.operator)}
    with transaction(db, write=False):
        if args.command == 'recompute':
            return recompute(db)
        agenda, crew, picture, delivery = build(db)
        if args.command == 'recorder-health':
            return recorder_uptime(read(args.file), agenda.sessions[args.session])
        if args.command == 'delivery':
            return delivery.assess(args.session, args.asset)
        return {'agenda': agenda, 'crew': crew, 'picture': picture}[args.command].assess(args.id)


def main():
    cli = parser()
    args = cli.parse_args()
    try:
        with closing(connect(args.db, create=args.command in ('demo', 'ingest'))) as db:
            output = run(db, args)
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        cli.exit(2, f'error: {exc}\n')
    print(json.dumps(output, sort_keys=True, ensure_ascii=True))


if __name__ == '__main__':
    main()
