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

pipeline['groups'] = []
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

    group = {
        "name": app['name'],
        "jobs": []
    }

    if "secrets" in app:
        resource['source']['paths'].extend([f"secrets/{secret}" for secret in app['secrets']])
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
        group['jobs'].append(secrets_job['name'])

    if "database" in app:
        resource['source']['paths'].append(f"databases/{app['database']}")
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
        group['jobs'].append(db_job['name'])

    if "extra" in app:
        resource['source']['paths'].extend(app['extra'])
        extra_job = {
            "name": f"{app['name']}-extra-resources",
            "plan": [
                {
                    "get": f"kube-iac-{app['name']}",
                    "trigger": True
                }
            ]
        }

        for extra_resource in app['extra']:
            extra_resource_task = {
                "put": "kube",
                "params": {
                    "kubectl": f"apply -f kube-iac-{app['name']}/{extra_resource}",
                    "wait_until_ready": 0
                }
            }

            if "namespace" in app:
                extra_resource_task['params']['namespace'] = app['namespace']

            extra_job['plan'].append(extra_resource_task)

        if "database" in app:
            extra_job['plan'][0]['passed'] = [f"{app['name']}-database"]
        elif "secrets" in app:
            extra_job['plan'][0]['passed'] = [f"{app['name']}-secrets"]

        pipeline['jobs'].append(extra_job)
        group['jobs'].append(extra_job['name'])

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

    group['jobs'].append(job['name'])

    if "namespace" in app:
        job['plan'][1]['params']['namespace'] = app['namespace']

    if "extra" in app:
        job['plan'][0]['passed'] = [f"{app['name']}-extra-resources"]
    elif "database" in app:
        job['plan'][0]['passed'] = [f"{app['name']}-database"]
    elif "secrets" in app:
        job['plan'][0]['passed'] = [f"{app['name']}-secrets"]

    pipeline['resources'].append(resource)
    pipeline['groups'].append(group)
    pipeline['jobs'].append(job)

for resource in pipeline['resources']:
    if resource['type'] == 'helm':
        resource['source']['repos'] = []
        for repo in repos:
            resource['source']['repos'].append({
                "name": repo.name,
                "url": repo.url
            })
del pipeline['groups']
yaml.dump(pipeline, sys.stdout)
