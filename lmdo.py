#!/usr/bin/env python3

import json
import os
import gnureadline as readline
import subprocess
import sys

from openai import OpenAI


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        exit(1)

    api_base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
    model = os.environ.get("OPENAI_MODEL", "gpt-5.4-nano")

    user_input = " ".join(sys.argv[1:])
    uname = str(os.uname())
    current_dir = os.getcwd()
    files = subprocess.check_output("ls -al", shell=True, text=True)

    client = OpenAI(
        base_url=api_base,
        api_key=api_key,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"You are lmdo, a command line tool that can be used to generate commands for the user based on the user's request. The user is running {uname}. The current directory is {current_dir} and the files in the current directory are\n{files}",
            },
            {"role": "user", "content": user_input},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "command",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The command to execute",
                        }
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        },
    )

    command = json.loads(response.choices[0].message.content)["command"]

    def prefill():
        readline.insert_text(command)
        readline.redisplay()

    readline.set_pre_input_hook(prefill)
    try:
        line = input("$ ")
    except KeyboardInterrupt:
        print()
        return
    readline.set_pre_input_hook()
    if line:
        subprocess.run(line, shell=True)


if __name__ == "__main__":
    main()
