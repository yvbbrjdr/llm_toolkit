#!/usr/bin/env python3

import argparse
import atexit
import datetime
import json
import os
import readline
import subprocess
import sys

from openai import OpenAI


class Tool:
    def __init__(self, description: str, parameters: dict):
        self.description = description
        self.parameters = parameters

    def execute(self, args: dict) -> dict:
        raise NotImplementedError("Tool execution not implemented")


class ShellTool(Tool):
    def __init__(self):
        super().__init__(
            "Execute a shell command on the host and return its stdout and stderr.",
            {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        )

    def execute(self, args: dict) -> dict:
        command = args["command"]
        user_input = input(
            f"\033[90mAllow execution of command: {command}? [Y/n]\033[0m"
        )
        if user_input.strip().lower() not in ("y", "yes", ""):
            return {"error": "Command execution cancelled by user."}
        result = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        outputs = {
            "returncode": result.returncode,
            "stdout": result.stdout.decode(),
            "stderr": result.stderr.decode(),
        }
        print(f"\033[90m{outputs['stdout']}\033[0m", end="", flush=True)
        print(
            f"\033[90m{outputs['stderr']}\033[0m", end="", flush=True, file=sys.stderr
        )
        return outputs


def main(args: argparse.Namespace):
    history_file = os.path.expanduser("~/.chat_history")
    if os.path.exists(history_file):
        readline.read_history_file(history_file)
    atexit.register(readline.write_history_file, history_file)

    client = OpenAI(
        base_url=args.api_base,
        api_key=args.api_key,
    )

    tools = {
        "shell": ShellTool(),
    }

    print(f"Chatting with {args.model} on {args.api_base}")

    system_message = {
        "role": "system",
        "content": f"You are a helpful assistant. Today's date is {datetime.datetime.now().strftime('%Y-%m-%d')}.",
    }
    messages = [system_message]

    while True:
        if messages[-1]["role"] in ("assistant", "system"):
            try:
                line = input(">>> ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue
            if not line.strip():
                continue

            match line.strip():
                case "/exit" | "/quit":
                    break
                case "/clear" | "/reset":
                    messages = [system_message]
                    print("Chat history cleared.")
                    continue

            messages.append({"role": "user", "content": line})

        try:
            response = client.chat.completions.create(
                model=args.model,
                messages=messages,
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                            "strict": True,
                        },
                    }
                    for name, tool in tools.items()
                ],
                stream=True,
            )
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            messages.pop()
            continue

        assistant_message = {"role": "assistant", "content": ""}
        messages.append(assistant_message)
        reasoning_mode = False
        has_output = False
        try:
            for chunk in response:
                delta = chunk.choices[0].delta

                if args.debug:
                    print(f"\n[DEBUG] Delta: {delta}\n", flush=True)

                tool_calls = delta.tool_calls
                if tool_calls:
                    if assistant_message.get("tool_calls") is None:
                        assistant_message["tool_calls"] = []
                    for tool_call in tool_calls:
                        index = tool_call.index
                        id = tool_call.id
                        function = tool_call.function
                        name = function.name
                        arguments = function.arguments
                        type = tool_call.type
                        while len(assistant_message["tool_calls"]) <= index:
                            assistant_message["tool_calls"].append(
                                {
                                    "type": "",
                                    "id": "",
                                    "function": {
                                        "name": "",
                                        "arguments": "",
                                    },
                                }
                            )
                        if id:
                            assistant_message["tool_calls"][index]["id"] += id
                        if name:
                            assistant_message["tool_calls"][index]["function"][
                                "name"
                            ] += name
                        if arguments:
                            assistant_message["tool_calls"][index]["function"][
                                "arguments"
                            ] += arguments
                        if type:
                            assistant_message["tool_calls"][index]["type"] = type

                reasoning_content = getattr(delta, "reasoning", None) or getattr(
                    delta, "reasoning_content", None
                )
                if reasoning_content:
                    if not reasoning_mode:
                        reasoning_mode = True
                    print(f"\033[90m{reasoning_content}\033[0m", end="", flush=True)
                    has_output = True

                content = delta.content
                if content:
                    if reasoning_mode:
                        reasoning_mode = False
                        print()
                    print(content, end="", flush=True)
                    has_output = True
                    assistant_message["content"] += content
        except KeyboardInterrupt:
            messages = messages[:-2]
        except Exception as e:
            print(f"\nError during response: {e}", file=sys.stderr)
            continue
        if has_output:
            print()

        if assistant_message.get("tool_calls"):
            for tool_call in assistant_message["tool_calls"]:
                name = tool_call["function"]["name"]
                arguments = json.loads(tool_call["function"]["arguments"])
                id = tool_call["id"]
                tool = tools.get(name)
                if not tool:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": id,
                            "content": f"Error: Tool '{name}' not found.",
                        }
                    )
                    continue
                try:
                    result = tool.execute(arguments)
                except Exception as e:
                    result = {"error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": id,
                        "content": json.dumps(result),
                    }
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quick chat")
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.environ.get("OPENAI_API_KEY"),
        help="OpenAI API key",
    )
    parser.add_argument(
        "--api-base",
        type=str,
        default=os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
        help="OpenAI API base URL",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
        help="Model to use",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    if not args.api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        exit(1)

    main(args)
