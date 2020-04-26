#!/usr/bin/env python3

import os
import click
from configargparse import ArgumentParser
import subprocess

from src import generator

from src.utils import Path, _logger

PATHS = [
    "~/src/odoo/",
    #"~/src/enterprise/",
]


def main_arguments_parser():
    def str2bool(v):
        return str(v).lower() in ('yes', 'true', 't', 'y', '1')

    parser = ArgumentParser(description='OdooDoc', default_config_files=['./odoodoc.rc', '~/.odoodoc.rc'])  # TODO: use standard config file?
    parser.add('-c', '--config', is_config_file=True, help='config file path')

    # parser
    parser.add_argument('--generate', '-g', type=str2bool, nargs='?',
                        default=True, help='Output folder for documentation.')
    parser.add_argument('--output_path', '-o', type=str, nargs='?',
                        help='Output folder for documentation.')
    parser.add_argument('--paths', '-p', type=str, nargs='?',
                        default=PATHS, help='Comma separated list of paths.')
    parser.add_argument('--local', '-l', type=str2bool, nargs='?',
                        default=True, help='If run in local mode, documentation contains links to files.')

    return parser


def deduplicate(seq):
   uniques = []
   [uniques.append(i) for i in seq if not uniques.count(i)]
   return uniques


def normalize_paths(paths: [Path]) -> [Path]:
    normalized_paths = []
    for path in paths:
        if os.path.split(path.rstrip("/"))[-1] == 'odoo':
            normalized_paths.append(os.path.join(path, 'addons/'))
            normalized_paths.append(os.path.join(path, 'odoo/addons/'))
        else:
            normalized_paths.append(path)
    return [os.path.expanduser(path) for path in normalized_paths]


def git_check_clean_paths(paths: [Path]):
    for path in paths:
        status = subprocess.check_output(['git', 'status'], cwd=path).decode()
        branch_name = status.splitlines()[0][len("On branch "):]
        _logger.info(f"Path {path} on branch {branch_name}.")
        if 'changes' in status.lower():
            _logger.exception("You should first clean up path:" + path + "  \n"
                              "Line numbers might be incorrect, etc.")
            if click.confirm("Do you want to clean up with `git clean -fdx`?\n", default=False):
                subprocess.check_output(['git', 'clean', '-fdx'], cwd=path)
            else:
                _logger.info("Continuing with unclean paths.")


def git_get_version(path: Path, hash=False) -> str:
    args = (['git', 'rev-parse', '--abbrev-ref', 'HEAD']
            if not hash else ['git', 'rev-parse', 'HEAD'])
    return subprocess.check_output(args, cwd=path).decode().strip()


def default_output_path(options):
    short_hashes = deduplicate(h[:8] for h in options["hashes"].values())
    return "_".join(["odoo", "_".join(options["versions"]), "_".join(short_hashes)])


def find_latest_version() -> str:
    directories = [d for d in os.listdir(os.getcwd())
                   if os.path.isdir(d) and "odoo_" in d]
    directories.sort(key=lambda x: os.path.getmtime(x))
    if not directories:
        raise Exception("No documentation found, impossible to start the server.")
    return directories[-1]


if __name__ == "__main__":
    args = main_arguments_parser().parse_args()
    if args.generate:
        # TODO: autodetect venv path, etc (project mode)
        paths = args.paths.split(',') if isinstance(args.paths, str) else PATHS
        paths = deduplicate(normalize_paths(paths))
        git_paths = [p for p in paths if "packages" not in p]
        git_check_clean_paths(git_paths)

        versions = deduplicate(git_get_version(path) for path in git_paths)
        hashes = {path: git_get_version(path, hash=True) for path in git_paths}

        options = {'local': args.local, 'hashes': hashes, 'versions': versions}
        options["git_paths"] = git_paths
        output_path = args.output_path or default_output_path(options)

        generator.main(paths, output_path, options)
