import re
import logging
import time
import os
from dataclasses import dataclass
from typing import Optional, Dict, Iterable
from dotenv import load_dotenv

from slackclient import SlackClient

EventMapping = Dict[str, str]

logger = logging.getLogger(__name__)
load_dotenv()

SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN')
SLACK_BOT_OAUTH = os.environ.get('SLACK_BOT_OAUTH')
slack_client = SlackClient(SLACK_BOT_OAUTH)
bot_id = None
STANDUP_CHANNELS = {}


@dataclass
class Command:
    validator = None

    input: str
    channel: str

    @classmethod
    def recognize(cls, event: EventMapping) -> bool:
        return len(re.findall(re.compile(cls.validator), event['text'])) > 0

    def do(self) -> None:
        raise NotImplementedError()


class HelpCommand(Command):
    validator = 'help'

    def do(self) -> None:
        slack_client.api_call(
            "chat.postMessage",
            channel=self.channel,
            text="""
                Here are some things I can do:
                    - type help to see this message
                    - type "Standup for: <comma separated members list>" to start recording the standup
                """
        )


class StartStandupCommand(Command):
    validator = '^Standup for:'

    def do(self) -> None:
        groups = re.findall(re.compile('(?P<names>[a-z0-9\.]*@[a-z\.]*)'), self.input)
        members = slack_client.api_call("users.list")['members']
        members = [(m['id'], m['profile'].get('email')) for m in members if m['profile'].get('email') in groups]

        for id_, email in members:
            channel_id = slack_client.api_call(
                "conversations.open",
                users=[id_]
            )['channel']['id']

            slack_client.api_call(
                "chat.postMessage",
                channel=channel_id,
                text="""
                Hey! It's standup time! Please answer:
                1. What are you working on?
                2. Do you encounter any problems?
                3. What are your plans for later?
                """
            )
            STANDUP_CHANNELS[channel_id] = {'origin': self.channel, 'author': email, 'response': []}

        slack_client.api_call(
            "chat.postMessage",
            channel=self.channel,
            text=f"Be right back! Gathering feedback from {', '.join([m[1] for m in members])}"
        )


class RespondStandupCommand(Command):

    @classmethod
    def recognize(cls, event: EventMapping) -> bool:
        return event['channel'] in STANDUP_CHANNELS

    def do(self) -> None:
        data = STANDUP_CHANNELS.pop(self.channel)
        slack_client.api_call(
            "chat.postMessage",
            channel=data['origin'],
            text=f"""
            Here is the standup from {data['author']}
            {self.input}
            """
        )


ALLOWED_COMMANDS = [
    HelpCommand,
    StartStandupCommand,
    RespondStandupCommand
]


def parse_slack_incoming(incoming: Iterable[EventMapping]) -> Optional[Command]:
    for event in incoming:
        if event['type'] == 'message' and not 'subtype' in event:
            for command in ALLOWED_COMMANDS:
                if command.recognize(event):
                    return command(input=event['text'], channel=event['channel'])


if __name__ == '__main__':
    if slack_client.rtm_connect(with_team_state=False):
        logger.info("StandupBot connected and ready to work!")
        bot_id = slack_client.api_call("auth.test")["user_id"]
        while True:
            command = parse_slack_incoming(slack_client.rtm_read())
            if command:
                command.do()
            time.sleep(1)
    else:
        logger.error("Something went wrong. Exception traceback printed aboce.")
