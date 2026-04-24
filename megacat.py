#!/usr/bin/env python3

import argparse
import fnmatch
import os


def is_ignored(name: str, ignores: list[str]) -> bool:
    for raw_pattern in reversed(ignores):
        pattern = raw_pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue

        is_negation = False
        if pattern.startswith("!"):
            is_negation = True
            pattern = pattern[1:].strip()
            if not pattern:
                continue

        while pattern[-1] == "/":
            pattern = pattern[:-1]
        while pattern.endswith("/*"):
            pattern = pattern[:-2]
        if "/" in pattern:
            pattern = pattern.split("/")[-1]

        if not pattern:
            continue

        if fnmatch.fnmatch(name, pattern):
            return not is_negation

    return False


class MegacatNode:
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        self.children = []
        self.content = None

    def populate(self, ignores: list[str] = [".git", "*lock.json", "*lock.yaml"]):
        if not os.path.isdir(self.path):
            with open(self.path) as fp:
                self.content = fp.read()
            return

        entries = os.listdir(self.path)

        ignore_files = [
            os.path.join(self.path, f) for f in entries if f == ".gitignore"
        ]
        ignores = ignores.copy()
        for f in ignore_files:
            with open(f) as fp:
                ignores.extend(fp.read().splitlines())

        for entry in entries:
            if is_ignored(entry, ignores):
                continue
            child = MegacatNode(entry, os.path.join(self.path, entry))
            try:
                child.populate(ignores)
            except UnicodeDecodeError:
                continue
            self.children.append(child)

    def tree(self, lasts: list[bool] = []) -> str:
        result = ""

        for i, last in enumerate(lasts):
            if i == len(lasts) - 1:
                if last:
                    result += "└─"
                else:
                    result += "├─"
            else:
                if last:
                    result += "  "
                else:
                    result += "│ "

        result += self.name + "\n"

        for i, child in enumerate(self.children):
            result += child.tree(lasts + [i == len(self.children) - 1])

        return result

    def concat(self, path: str = "") -> str:
        if self.content is not None:
            return (
                "======== "
                + os.path.join(path, self.name)
                + " ========\n"
                + self.content
            )
        return "\n".join(
            [child.concat(os.path.join(path, self.name)) for child in self.children]
        )

    def __str__(self) -> str:
        return self.tree() + "\n" + self.concat()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path", nargs="?", default=os.getcwd(), help="The path to megacat"
    )
    args = parser.parse_args()

    root = MegacatNode(os.path.basename(args.path), args.path)
    root.populate()

    print(root)


if __name__ == "__main__":
    main()
