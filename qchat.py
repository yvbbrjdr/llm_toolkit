#!/usr/bin/env python3

import argparse
import atexit
import datetime
import os
import readline
import sys

from openai import OpenAI


def main(args):
    history_file = os.path.expanduser("~/.chat_history")
    if os.path.exists(history_file):
        readline.read_history_file(history_file)
    atexit.register(readline.write_history_file, history_file)

    client = OpenAI(
        base_url=args.api_base,
        api_key=args.api_key,
    )

    print(f"Chatting with {args.model} on {args.api_base}")

    system_message = {
        "role": "system",
        "content": f"You are a helpful assistant. Today's date is {datetime.datetime.now().strftime('%Y-%m-%d')}.",
    }
    messages = [system_message]

    while True:
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
                stream=True,
            )
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            messages.pop()
            continue

        assistant_message = {"role": "assistant", "content": ""}
        messages.append(assistant_message)
        reasoning_mode = False
        try:
            for chunk in response:
                delta = chunk.choices[0].delta

                if args.debug:
                    print(f"\n[DEBUG] Delta: {delta}\n", flush=True)

                reasoning_content = getattr(delta, "reasoning", None) or getattr(
                    delta, "reasoning_content", None
                )
                if reasoning_content:
                    if not reasoning_mode:
                        reasoning_mode = True
                    print(f"\033[90m{reasoning_content}\033[0m", end="", flush=True)

                content = delta.content
                if content:
                    if reasoning_mode:
                        reasoning_mode = False
                        print()
                    print(content, end="", flush=True)
                    assistant_message["content"] += content
        except KeyboardInterrupt:
            messages = messages[:-2]
        except Exception as e:
            print(f"\nError during response: {e}", file=sys.stderr)
            continue
        print()


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
