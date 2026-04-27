#!/usr/bin/env python3

import argparse
import atexit
import datetime
import json
import os
import readline
import subprocess
import sys
import threading
from typing import IO
import urllib.parse

import json_repair
from openai import OpenAI
import requests


class Tool:
    def __init__(self, description: str, parameters: dict):
        self.description = description
        self.parameters = parameters

    def execute(self, args: dict) -> dict:
        raise NotImplementedError("Tool execution not implemented")


class ChdirTool(Tool):
    def __init__(self):
        super().__init__(
            "Change the current working directory. Use this tool to navigate the file system when needed.",
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to change to. Can be absolute or relative.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )

    def execute(self, args: dict) -> dict:
        path = args["path"]

        print(f"\033[90mChanging directory to: {path}\033[0m")

        try:
            os.chdir(os.path.expanduser(path))
            return {"success": True, "cwd": getcwd()}
        except Exception as e:
            return {"success": False, "error": str(e), "cwd": getcwd()}


class ShellTool(Tool):
    def __init__(self, client: OpenAI, model: str):
        super().__init__(
            "Execute a shell command on the host and return its stdout and stderr. If you need to execute Python code for some task, use this tool.",
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
        self._client = client
        self._model = model

    def execute(self, args: dict) -> dict:
        command = args["command"]
        if not is_shell_command_readonly(command, self._client, self._model):
            try:
                user_input = input(f"Allow execution of command: {command}? [Y/n] ")
            except EOFError, KeyboardInterrupt:
                print()
                user_input = "n"
            if user_input.strip().lower() not in ("y", "yes", ""):
                return {"error": "Command execution cancelled by user."}
        else:
            print(f"\033[90mExecuting command: {command}\033[0m")

        p = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def forward_output(pipe: IO[bytes], log: list[str], is_stderr=False):
            for line in iter(pipe.readline, b""):
                decoded = line.decode()
                print(
                    f"\033[90m{decoded}\033[0m",
                    end="",
                    flush=True,
                    file=sys.stderr if is_stderr else sys.stdout,
                )
                log.append(decoded)
            pipe.close()

        stdout, stderr = [], []
        stdout_thread = threading.Thread(target=forward_output, args=(p.stdout, stdout))
        stderr_thread = threading.Thread(
            target=forward_output, args=(p.stderr, stderr, True)
        )
        stdout_thread.start()
        stderr_thread.start()

        while True:
            try:
                p.wait()
                break
            except KeyboardInterrupt:
                p.send_signal(subprocess.signal.SIGINT)
                print()
        stdout_thread.join()
        stderr_thread.join()
        outputs = {
            "returncode": p.returncode,
            "stdout": "".join(stdout),
            "stderr": "".join(stderr),
        }
        return outputs


class SearchTool(Tool):
    def __init__(self, api_key: str):
        super().__init__(
            "Search the web and return relevant results with titles, URLs, and content snippets.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "page": {
                        "type": "integer",
                        "description": "The page of results to return (default 1).",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )
        self._api_key = api_key

    def execute(self, args: dict) -> dict:
        query = args["query"]
        page = args.get("page", 1)

        print(f"\033[90mSearching for: {query} (page {page})\033[0m")

        encoded = urllib.parse.quote_plus(query)
        url = f"https://s.jina.ai/{encoded}?page={page}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-Respond-With": "no-content",
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except Exception as e:
            return {"error": str(e)}

        return response.json()


class FetchTool(Tool):
    def __init__(self, api_key: str):
        super().__init__(
            "Fetch the content of a web page given its URL. Use this tool when you need to access information from a specific web page.",
            {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL of the web page to fetch.",
                    }
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        )
        self._api_key = api_key

    def execute(self, args: dict) -> dict:
        url = args["url"]

        print(f"\033[90mFetching URL: {url}\033[0m")

        encoded = urllib.parse.quote_plus(url)
        url = f"https://r.jina.ai/{encoded}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except Exception as e:
            return {"error": str(e)}

        return response.json()


def getcwd():
    while True:
        try:
            return os.getcwd().replace(os.path.expanduser("~"), "~")
        except FileNotFoundError:
            os.chdir("..")


def system_message():
    return {
        "role": "system",
        "content": f"You are QChat, an AI-assisted shell environment. Today's date is {datetime.datetime.now().strftime('%Y-%m-%d')}. Current working directory is {getcwd()}. The operating system is {str(os.uname())}.",
    }


def is_shell_command(message: str, client: OpenAI, model: str) -> bool:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that determines whether a string is a shell command or not, like a request or a sentence.",
                },
                {
                    "role": "user",
                    "content": message,
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "is_command_response",
                    "description": "Determines whether the input is a shell command. Return true if it is a command, false otherwise.",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "is_command": {
                                "type": "boolean",
                                "description": "Whether the input is a shell command. Return true if it is a command, false otherwise.",
                            }
                        },
                        "required": ["is_command"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )
        result = json_repair.loads(response.choices[0].message.content)
        return result.get("is_command", False)
    except Exception as e:
        print(f"Error determining if message is shell command: {e}", file=sys.stderr)
        return False


def is_shell_command_readonly(message: str, client: OpenAI, model: str) -> bool:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that determines whether a shell command is readonly or it modifies the system or has side effects.",
                },
                {
                    "role": "user",
                    "content": message,
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "is_command_readonly_response",
                    "description": "Determines whether the input is a readonly shell command. Return true if it is a readonly command, false otherwise.",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "is_command_readonly": {
                                "type": "boolean",
                                "description": "Whether the input is a readonly shell command. Return true if it is a readonly command, false otherwise.",
                            }
                        },
                        "required": ["is_command_readonly"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )
        result = json_repair.loads(response.choices[0].message.content)
        return result.get("is_command_readonly", False)
    except Exception as e:
        print(
            f"Error determining if message is readonly shell command: {e}",
            file=sys.stderr,
        )
        return False


def main(args: argparse.Namespace):
    history_file = os.path.expanduser("~/.qchat_history")
    if os.path.exists(history_file):
        readline.read_history_file(history_file)
    atexit.register(readline.write_history_file, history_file)

    client = OpenAI(
        base_url=args.api_base,
        api_key=args.api_key,
    )

    tools = {
        "chdir": ChdirTool(),
        "shell": ShellTool(client, args.small_model),
        **(
            {
                "search": SearchTool(api_key=args.jina_api_key),
                "fetch": FetchTool(api_key=args.jina_api_key),
            }
            if args.jina_api_key
            else {}
        ),
    }

    messages = []
    while True:
        if not messages or messages[-1]["role"] == "assistant":
            try:
                line = input(f"{args.model}:{getcwd()}$ ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue

            stripped = line.strip()
            if not stripped:
                continue

            match stripped:
                case "/exit" | "/quit":
                    break
                case "/clear" | "/reset":
                    messages = []
                    print("Chat history cleared.")
                    continue
                case "/shell":
                    shell = os.environ.get("SHELL", "/bin/sh")
                    try:
                        subprocess.run(shell)
                    except Exception as e:
                        print(f"Error launching shell: {e}", file=sys.stderr)

            if stripped[0] == "!" or is_shell_command(
                stripped, client, args.small_model
            ):
                cmd = stripped[1:] if stripped[0] == "!" else stripped
                if not cmd:
                    continue

                if cmd == "cd" or cmd.startswith("cd "):
                    parts = cmd.split(maxsplit=1)
                    target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
                    try:
                        os.chdir(os.path.expanduser(target))
                    except Exception as e:
                        print(f"cd: {e}", file=sys.stderr)
                    continue

                p = subprocess.Popen(cmd, shell=True)
                while True:
                    try:
                        p.wait()
                        break
                    except KeyboardInterrupt:
                        p.send_signal(subprocess.signal.SIGINT)
                        print()
                continue

            messages.append({"role": "user", "content": line})

        try:
            response = client.chat.completions.create(
                model=args.model,
                messages=[system_message(), *messages],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": tool.description,
                            "parameters": tool.parameters,
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
                    print(f"\n[DEBUG] Delta: {delta}\n")

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
                    if hasattr(delta, "reasoning_content"):
                        if assistant_message.get("reasoning_content") is None:
                            assistant_message["reasoning_content"] = ""
                        assistant_message["reasoning_content"] += (
                            delta.reasoning_content
                        )

                content = delta.content
                if content:
                    if reasoning_mode:
                        reasoning_mode = False
                        print()
                    print(content, end="", flush=True)
                    has_output = True
                    assistant_message["content"] += content
        except KeyboardInterrupt:
            print()
            continue
        except Exception as e:
            print(f"\nError during response: {e}", file=sys.stderr)
            continue
        if has_output:
            print()

        if assistant_message.get("tool_calls"):
            for tool_call in assistant_message["tool_calls"]:
                name = tool_call["function"]["name"]
                arguments = json_repair.loads(tool_call["function"]["arguments"])
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
    parser.add_argument(
        "--small-model",
        type=str,
        default=os.environ.get("OPENAI_SMALL_MODEL", "gpt-5.4-mini"),
        help="Smaller model to use for easy decisions",
    )
    parser.add_argument(
        "--jina-api-key",
        type=str,
        default=os.environ.get("JINA_API_KEY"),
        help="Jina API key for search tool",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    if not args.api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        exit(1)

    main(args)
