import os
import sys

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString, DoubleQuotedScalarString

ci_folder = os.path.dirname(os.path.realpath(__file__))
apps_folder = Path(ci_folder) / ".." / "helm-apps"
apps_folder = apps_folder.resolve()

yaml = YAML()
pipeline = {}
apps = []

with open((Path(ci_folder) / 'helm-apps.base.yml').resolve()) as fp:
    pipeline = yaml.load(fp)

pipeline['jobs'] = []

for base, _, files in os.walk(apps_folder):
    for file in files:
        with open(f"{base}/{file}") as fp:
            app = yaml.load(fp)
            if app and "meta" in app:
                meta = app['meta']
                meta['chartFile'] = file
                apps.append(meta)

for app in apps:
    pipeline['resources'].append({
        'name': f'kube-iac-{app["name"]}',
        'type': 'git',
        'source': {
            'uri': 'git@github.com:hreeder/kube-iac.git',
            'private_key': LiteralScalarString('((github.deploy_key))'),
            'paths': [f'helm-apps/{app["chartFile"]}']
        }
    })
    pipeline['jobs'].append({
        'name': app['name'],
        'plan': [
            {
                'get': f'kube-iac-{app["name"]}',
                'trigger': True
            },
            {
                'put': 'kube-cluster',
                'params': {
                    'chart': app['chart'],
                    'release': app['name'],
                    'values': f'kube-iac-{app["name"]}/helm-apps/{app["chartFile"]}'
                },
                'on_success': {
                    'put': 'discord',
                    'params': {
                        'channel': DoubleQuotedScalarString("((discord.channel_id))"),
                        'color': 0x5CB85C,
                        'title': '[Concourse] Helm App Deployed',
                        'message': LiteralScalarString(f'**Pipeline**: helm-apps\n**Job**: {app["name"]}\n:airplane_departure: {app["name"]} has now been deployed/updated')
                    }
                },
                'on_failure': {
                    'put': 'discord',
                    'params': {
                        'channel': DoubleQuotedScalarString("((discord.channel_id))"),
                        'color': 0xFF0000,
                        'title': '[Concourse] Helm App FAILURE',
                        'message': LiteralScalarString(f'**Pipeline**: helm-apps\n**Job**: {app["name"]}\n:warning: {app["name"]} has FAILED to deploy/update. ROLLING BACK')
                    }
                }
            }
        ]
    })

yaml.dump(pipeline, sys.stdout)