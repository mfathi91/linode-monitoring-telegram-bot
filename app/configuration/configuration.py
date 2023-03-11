import json
import os
from collections import namedtuple
from pathlib import Path
from typing import List

from jsonschema import validate

# Data holder classes
Linode = namedtuple('Linode', ['label', 'id', 'max_daily_network_gb'])
User = namedtuple('User', ['name', 'chat_id', 'linodes'])


class Configuration:

    def __init__(self, config_path: str, logger):
        curr_dir = Path(f'{os.path.realpath(__file__)}').parent
        with open(curr_dir.joinpath('configuration_schema.json'), 'r') as f:
            schema = json.load(f)

        with open(config_path) as f:
            data = json.load(f)
            validate(instance=data, schema=schema)
            self.token = data['token']
            self.linode_url = data['linode_url']
            self.linode_pat = data['linode_pat']

            # Initialize linodes
            self.linodes = []
            for linode in data['linodes']:
                self.linodes.append(Linode(linode['label'], linode['id'], linode['max_daily_network_gb']))

            # Initialize users
            self.users = []
            for user in data['users']:
                if 'admin' in user:
                    user_linodes = self.linodes
                else:
                    user_linodes = [li for li in self.linodes if li.id in user['access']]
                self.users.append(User(user['name'], user['telegram_chat_id'], user_linodes))

    def get_token(self) -> str:
        return self.token

    def get_linode_url(self) -> str:
        return self.linode_url

    def get_linode_pat(self) -> str:
        return self.linode_pat

    def get_chat_ids(self) -> List[int]:
        return [u.chat_id for u in self.users]

    def get_linodes(self):
        return self.linodes

    def get_linode_labels(self):
        return [li.label for li in self.linodes]

    def get_linode_by_label(self, linode_label: str) -> Linode:
        for linode in self.linodes:
            if linode.label == linode_label:
                return linode
        raise ValueError(f'Unable to find linode with label "{linode_label}"')

    def get_usernames(self):
        return [u.name for u in self.users]

    def get_user_linodes(self, chat_id):
        for user in self.users:
            if user.chat_id == chat_id:
                return user.linodes
        raise ValueError(f'Unable to find user with chat ID {chat_id}')

    def can_user_access_linode(self, user_chat_id: int, linode_label: str) -> bool:
        for user in self.users:
            if user.chat_id == user_chat_id:
                for user_linode in user.linodes:
                    if user_linode.label == linode_label:
                        return True


class ConfigurationError(ValueError):
    pass
