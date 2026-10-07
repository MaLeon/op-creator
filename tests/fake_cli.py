#!/usr/bin/env python3
"""Isolated CLI contract fixtures. Never used by the installed manager."""
import json
import os
import pathlib
import sys
import time

home = pathlib.Path(os.environ['HOME'])
data = home / '.fake'
data.mkdir(exist_ok=True)
services_file = data / 'services.json'
services = json.loads(services_file.read_text()) if services_file.exists() else {}
args = sys.argv[1:]
tool = pathlib.Path(sys.argv[0]).name
fail = os.environ.get('FAKE_FAIL', '')


def save():
    services_file.write_text(json.dumps(services))


def fail_at(stage):
    if fail == stage:
        print('secret-from-upstream-must-not-leak', file=sys.stderr)
        sys.exit(1)


if tool == 'loginctl':
    print('no' if os.environ.get('FAKE_NO_LINGER') else 'yes')
elif tool == 'ss':
    fail_at('ss')
    ports = [int(p) for p in os.environ.get('FAKE_PORTS', '').split(',') if p]
    ports += [s['port'] for s in services.values() if s['active']]
    for port in ports:
        print(f'tcp LISTEN 0 128 [::]:{port} [::]:*')
elif tool == 'systemctl':
    fail_at('systemctl')
    if 'show-environment' in args:
        sys.exit(0)
    if 'list-unit-files' in args:
        for name in services:
            print(f'openclaw-gateway-{name}.service enabled enabled')
    elif 'show' in args:
        unit = args[args.index('show')+1]
        name = unit.removeprefix('openclaw-gateway-').removesuffix('.service')
        svc = services.get(name)
        fragment = home / '.config/systemd/user' / unit
        if svc:
            print(f'LoadState=loaded\nActiveState={"active" if svc["active"] else "inactive"}\n'
                  f'MainPID={99 if svc["active"] else 0}\nControlPID=0\nFragmentPath={fragment}\nDropInPaths=')
        else:
            print('LoadState=not-found\nActiveState=inactive\nMainPID=0\nControlPID=0\nFragmentPath=\nDropInPaths=')
elif tool == 'openclaw':
    if '--help' in args:
        print('--baseline --workspace --stdin --json --port --no-probe --timeout --force')
        sys.exit(0)
    if '--version' in args:
        print('OpenClaw 2026.9.5 (fixture)')
        sys.exit(0)
    name = 'default'
    if args[:1] == ['--profile']:
        name = args[1]
        args = args[2:]
    root = home / ('.openclaw' if name == 'default' else '.openclaw-' + name)
    config_file = root / 'openclaw.json'
    cfg = json.loads(config_file.read_text()) if config_file.exists() else {}
    unit = home / '.config/systemd/user' / f'openclaw-gateway-{name}.service'
    with (data / 'calls').open('a') as f:
        f.write(json.dumps([name] + args) + '\n')
    if args[0] == 'setup':
        (root / 'workspace').mkdir(parents=True, exist_ok=True)
        cfg = {'agents': {'defaults': {'workspace': str(root / 'workspace')}}}
        config_file.write_text(json.dumps(cfg))
        os.chmod(config_file, 0o600)
        if os.environ.get('FAKE_PAUSE_SETUP'):
            (data / 'setup-entered').touch()
            time.sleep(30)
        fail_at('setup')
    elif args[:2] == ['config', 'get']:
        fail_at('get')
        key = args[2]
        if key not in cfg:
            print(json.dumps({'ok': False, 'error': f'Config path is valid but unset: {key}. The runtime default applies.'}))
            sys.exit(1)
        print(json.dumps(cfg[key]))
    elif args[:2] == ['config', 'patch']:
        fail_at('patch')
        cfg.update(json.load(sys.stdin))
        config_file.write_text(json.dumps(cfg))
    elif args[:2] == ['config', 'validate']:
        fail_at('validate')
        print('{"ok":true}')
    elif args[:2] == ['gateway', 'install']:
        unit.parent.mkdir(parents=True, exist_ok=True)
        port = int(args[args.index('--port')+1])
        services[name] = {'port': port, 'active': True}
        unit.write_text(f'profile={name}\nport={port}\n')
        save()
        (root / 'logs').mkdir(exist_ok=True)
        (root / 'logs/openclaw.log').write_text('gateway started\n')
        fail_at('install')
    elif args[:2] == ['gateway', 'status']:
        fail_at('status')
        print(json.dumps({'config': {'cli': {'path': str(config_file)}, 'daemon': {'path': str(config_file)}},
                          'gateway': {'port': services.get(name, {}).get('port', cfg.get('gateway', {}).get('port', 18789))},
                          'service': {'command': {'programArguments': ['node', 'openclaw', 'gateway']}}}))
    elif args[:2] == ['gateway', 'health']:
        fail_at('health')
        if not services.get(name, {}).get('active'):
            sys.exit(1)
        print('{"ok":true}')
    elif args[:2] == ['gateway', 'stop']:
        if '--force' not in args:
            sys.exit(1)
        fail_at('stop')
        services[name]['active'] = False
        save()
    elif args[:2] == ['gateway', 'start']:
        fail_at('start')
        services[name]['active'] = True
        save()
    elif args[:2] == ['gateway', 'uninstall']:
        fail_at('uninstall')
        services.pop(name, None)
        unit.unlink(missing_ok=True)
        save()
    else:
        sys.exit(2)
else:
    sys.exit(2)
