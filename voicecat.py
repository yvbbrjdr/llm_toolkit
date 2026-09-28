#!/usr/bin/env python3

import argparse


def main(args: argparse.Namespace):
    pass


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="record voice and transcribe it")
    args = argparser.parse_args()

    main(args)
