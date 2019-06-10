#!/usr/bin/env python
import os
import sys

from collections import namedtuple
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString, DoubleQuotedScalarString

ci_folder = os.path.dirname(os.path.realpath(__file__))
apps_folder = Path(ci_folder) / ".." / "helm-apps"
apps_folder = apps_folder.resolve()

yaml = YAML()
pipeline = {}
repos = set()
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
    if "repo" in app:
        Repo = namedtuple('Repo', ['name', 'url'])
        repos.add(Repo(app['repo']['name'], app['repo']['url']))

    resource = {
        'name': f'kube-iac-{app["name"]}',
        'type': 'git',
        'source': {
            'uri': 'git@github.com:hreeder/kube-iac.git',
            'private_key': LiteralScalarString('((github.deploy_key))'),
            'git_crypt_key': LiteralScalarString('((github.git_crypt_key))'),
            'paths': [f'helm-apps/{app["chartFile"]}']
        }
    }

    if "secrets" in app:
        resource['source']['paths'].extend([f"secrets/{secret}" for secret in app['secrets']])

    if "database" in app:
        resource['source']['paths'].append(f"databases/{app['database']}")

    pipeline['resources'].append(resource)

    if "secrets" in app:
        secrets_job = {
            "name": f"{app['name']}-secrets",
            "plan": [
                {
                    "get": f"kube-iac-{app['name']}",
                    "trigger": True
                }
            ]
        }

        for secret in app['secrets']:
            secret_task = {
                "put": "kube",
                "params": {
                    "kubectl": f"apply -f kube-iac-{app['name']}/secrets/{secret}",
                    "wait_until_ready": 0
                }
            }

            if "namespace" in app:
                secret_task['params']['namespace'] = app['namespace']

            secrets_job['plan'].append(secret_task)        

        pipeline['jobs'].append(secrets_job)

    if "database" in app:
        db_job = {
            "name": f"{app['name']}-database",
            "plan": [
                {
                    "get": f"kube-iac-{app['name']}",
                    "trigger": True
                },
                {
                    "put": "kube",
                    "params": {
                        "kubectl": f"apply -f kube-iac-{app['name']}/databases/{app['database']}",
                        "wait_until_ready": 0
                    }
                }
            ]
        }

        if "namespace" in app:
            db_job['plan'][1]['params']['namespace'] = app['namespace']

        if "secrets" in app:
            db_job['plan'][0]['passed'] = [f"{app['name']}-secrets"]

        pipeline['jobs'].append(db_job)

    job = {
        'name': app['name'],
        'plan': [
            {
                'get': f'kube-iac-{app["name"]}',
                'trigger': True
            },
            {
                'put': 'kube-helm',
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
    }

    if "namespace" in app:
        job['plan'][1]['params']['namespace'] = app['namespace']
    
    if "database" in app:
        job['plan'][0]['passed'] = [f"{app['name']}-database"]

    pipeline['jobs'].append(job)

for resource in pipeline['resources']:
    if resource['type'] == 'helm':
        resource['source']['repos'] = []
        for repo in repos:
            resource['source']['repos'].append({
                "name": repo.name,
                "url": repo.url
            })

yaml.dump(pipeline, sys.stdout)