#!/usr/bin/env python3

import os
import re
import ast
import time
import click
import shutil
import logging
import argparse
import subprocess
from collections import namedtuple
from lxml import etree  # type: ignore
from lxml.builder import ElementMaker,E  # type: ignore
from lxml.html.builder import CLASS  # type: ignore
from pprint import pformat as pf

from typing import List, Dict

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger("odoodoc")

Path = str
DepTree = List[List[str]]
ModuleInfo = namedtuple('module', ['name', 'path', 'link'])
InfoDepTree = List[List[ModuleInfo]]

PATHS = [
    "~/src/odoo/",
    "~/src/enterprise/",
]
GITHUB_ROOT = "https://github.com/odoo"
WEB_ICON = " 🌐"  # 🔗

STYLE = "style.css"

RE_IGNORE = '((__pycache__)|(test_)|(\.)).*'
PY_RE = '.*\.py$'
NOT_M_RE = '(.*((__manifest__.py)|(__init__.py)))|.*test_.*'

special_attributes_str = (
    '_name',
    '_rec_name',
    '_order',
    '_description',
    '_table',
)
special_attributes_inh = ('_inherit',)
special_attributes_inhs = ('_inherits',)
special_attributes_con = ('_constraints',)
special_attributes_sql = ('_sql_constraints',)
special_attributes_bool = ('_auto', '_parent_store',)

special_attributes = (special_attributes_str +
                      special_attributes_con +
                      special_attributes_sql +
                      special_attributes_inh +
                      special_attributes_inhs +
                      special_attributes_bool)


def memoize_first(f):
    memo = {}
    def helper(x, *args, **kwargs):
        if x not in memo:
            memo[x] = f(x, *args, **kwargs)
        return memo[x]
    return helper


def all_classes(a):
    return [node for node in a.body if isinstance(node, ast.ClassDef)]

    
def all_assigns(a_class):
    return [node for node in a_class.body if isinstance(node, ast.Assign)]


def all_functions(a_class):
    return [node for node in a_class.body if isinstance(node, ast.FunctionDef)]


def parse_value_str(v):
    if 'left' in dir(v):  # google calendar: _name is BinOp
        return v.left.s
    else:
        return v.s


def parse_value_bool(v):
    return v.value


def parse_value_field(v):
    value = {
        'type': v.func.attr,
        'lineno': v.lineno,
    }
    return value


def parse_value_sql(v):
    s = []
    for triplet in v.elts:
        x = tuple([t.s if 'args' not in dir(t) else t.args[0].s
                   for t in triplet.elts])
        s.append(x)
    return s


def parse_value_inh(v):
    if 's' in dir(v):
        return v.s
    elif 'id' in dir(v):
        return v.id
    else:
        return [e.s for e in v.elts]


def parse_value_inhs(v):
    return {k.s: v.s for k, v in zip(v.keys, v.values)}


def parse_value_con(v):
    s = []
    for triplet in v.elts:
        x = (
            (triplet.elts[0].attr if
             'attr' in dir(triplet.elts[0]) else triplet.elts[0].id),
            triplet.elts[1].s,
            [t.s for t in triplet.elts[2].elts]
        )
        s.append(x)
    return s


def is_assign_field(a_a):
    v = a_a.value
    b = (
        isinstance(v, ast.Call) and
        'value' in dir(v.func) and
        'id' in dir(v.func.value) and
        v.func.value.id == 'fields'
    )
    return b


def is_assign_special(a_a):
    name = a_a.targets[0].id if 'id' in dir(a_a.targets[0]) else ''
    return name in special_attributes


def is_assign_X(a_a, type):
    name = a_a.targets[0].id
    return name in type


def is_assign_str(a_a):
    return is_assign_X(a_a, special_attributes_str)


def is_assign_sql(a_a):
    return is_assign_X(a_a, special_attributes_sql)


def is_assign_inh(a_a):
    return is_assign_X(a_a, special_attributes_inh)


def is_assign_inhs(a_a):
    return is_assign_X(a_a, special_attributes_inhs)


def is_assign_constraint(a_a):
    return is_assign_X(a_a, special_attributes_con)


def is_assign_bool(a_a):
    return is_assign_X(a_a, special_attributes_bool)


def parse_class_function(a_a):
    # TODO: kwargs and such
    values = {
        'lineno': a_a.lineno,
        'decorator_list': a_a.decorator_list,
        'args': [v.arg for v in a_a.args.args],
    }
    return a_a.name, values


def parse_class_assign(a_a):
    assert(len(a_a.targets) == 1)
    name = a_a.targets[0].id
    parsers = {
        is_assign_field: parse_value_field,
        is_assign_sql: parse_value_sql,
        is_assign_constraint: parse_value_con,
        is_assign_inh: parse_value_inh,
        is_assign_inhs: parse_value_inhs,
        is_assign_str: parse_value_str,
        is_assign_bool: parse_value_bool,
    }
    dispatch = next(k for k in parsers if k(a_a))

    value = parsers[dispatch](a_a.value)

    return name, value


def parse_odoo_class(a_c, class_dict):
    assigns = all_assigns(a_c)
    functions = all_functions(a_c)
    assign_fields = [assign for assign in assigns if is_assign_field(assign)]
    assign_specials = [assign for assign in assigns if is_assign_special(assign)]
    all_special_pairs = [parse_class_assign(assign)
                         for assign in assign_specials]
    all_fields_pairs = [parse_class_assign(assign)
                        for assign in assign_fields]
    all_function_pairs = [parse_class_function(function)
                          for function in functions]
    class_dict.update({k: v for k, v in all_special_pairs})
    class_dict.update(fields={k: v for k, v in all_fields_pairs})
    class_dict.update(functions={k: v for k, v in all_function_pairs})
    return class_dict


def parse_model_file(module_name, file_name):
    file_content = open(file_name, 'r').read()
    a = ast.parse(file_content)
    classes = all_classes(a)
    result = []
    for odoo_class in classes:
        class_dict = {
            'module': module_name,
            'file': file_name,
            'full path': os.path.realpath(file_name),
            'lineno': odoo_class.lineno,
        }
        parse_odoo_class(odoo_class, class_dict)
        result.append(class_dict)
    return result


def models_files_from_modules(module_list):
    files_list = []
    for module in module_list:
        module_path = (module if re.match('.*base.?$', module)
                       else os.path.join(module, 'models'))
        for (base_path, _, file_names) in os.walk(module_path):
            for file_name in file_names:
                file_path = os.path.join(base_path, file_name)
                if re.match(PY_RE, file_path) and not re.match(NOT_M_RE, file_path):
                    files_list.append(file_path)
                else:
                    pass
    return files_list


def module_name_from_path(path):
    if '/base/' in path:
        return 'base'
    else:
        name_re = re.match('.*\/(.*)/models/(.*)?', path)
        return name_re[1] if name_re else os.path.basename(path)


def module_path_has_manifest(module_path: Path) -> bool:
    manifest_file = os.path.join(module_path, '__manifest__.py')
    return os.path.isdir(module_path) and os.path.exists(manifest_file)


def modules_from_paths(path_list: [Path]) -> [Path]:
    module_list = []
    for path in path_list:
        for module in os.listdir(path):
            module_path = os.path.join(path, module)
            if not re.match(RE_IGNORE, module) and module_path_has_manifest(module_path):
                module_list.append(module_path)
    return module_list


def module_path_from_name(name: str, paths: [Path]) -> Path:
    # check for the manifest as some module move from enterprise to community
    for path in paths:
        module_path = os.path.join(path, name)
        if module_path_has_manifest(module_path):
            return module_path
    raise Exception("Impossible to find module: %s\n"
                    "Wrong name or missing path?" % name)


@memoize_first
def module_dependencies_tree(module_path, paths):
    if module_name_from_path(module_path) == 'base':
        return {}
    if not os.path.exists(module_path):
        module_path = module_path_from_name(module_path, paths)
    manifest_file = os.path.join(module_path, '__manifest__.py')
    if not os.path.exists(manifest_file):
        import pudb; pudb.set_trace()
        _logger.exception("Module without a manifest: " + module_path)
        return {}
    manifest_dict = eval(open(manifest_file, 'r').read())
    dependencies = manifest_dict.get('depends', [])
    modules = [module_path_from_name(dep, paths) for dep in dependencies]
    all_trees = {module_name_from_path(m): module_dependencies_tree(m, paths) for m in modules}
    return all_trees


def dict_depth(d, depth=0):
    if not isinstance(d, dict) or not d:
        return depth
    return max(dict_depth(v, depth+1) for k, v in d.items())


def dict_flatten(d, keys=None):
    if keys is None:
        keys = set()
    if not isinstance(d, dict) or not d:
        return keys
    for key in d.keys():
        keys.add(key)
        dict_flatten(d[key], keys)
    return keys


@memoize_first
def module_dependencies_depth(module_path: Path, paths: [Path]) -> int:
    if module_name_from_path(module_path) == 'base':
        return 0
    dependency_tree = module_dependencies_tree(module_path, paths)
    return dict_depth(dependency_tree)


def invert_dependencies(dependency_tree, paths) -> DepTree:
    if dependency_tree == {}:
        return []
    all_deps = dict_flatten(dependency_tree)
    module_depths = {m: module_dependencies_depth(m, paths) for m in all_deps}
    inverted_tree:DepTree = [[] for i in range(max(module_depths.values()) + 1)]
    for m, d in module_depths.items():
        inverted_tree[d].append(m)
    return inverted_tree


def dep_tree_enrich(dep_tree: DepTree, paths:[Path], github_root) -> InfoDepTree:
    infos = []
    for level in dep_tree:
        info_level = []
        for module in level:
            path = module_path_from_name(module, paths)
            module_info = ModuleInfo(module, path, html_github_link(path, github_root))
            info_level.append(module_info)
        infos.append(info_level)
    return infos


def in_deep(module_name, module_dep_tree):
    sub_trees = module_dep_tree.values()
    if module_name in module_dep_tree:
        return True
    elif sub_trees:
        return any(in_deep(module_name, sub_tree) for sub_tree in sub_trees)
    else:
        return False


def query_class(class_name, class_list):
    is_name = lambda c: (c.get('_name') == class_name or
                         ('_name' not in c and c.get('_inherit') == class_name))
    return [c for c in class_list if is_name(c)]


def query_field(field_name, class_list):
    return [c for c in class_list if field_name in c['functions']]


def class_tree(class_name, class_list, paths, github_root=GITHUB_ROOT):
    classes = query_class(class_name, class_list)
    modules = set(c['module'] for c in classes)
    module_paths = [(m, module_path_from_name(m, paths)) for m in modules]
    module_deps = {m1: module_dependencies_tree(m2, paths)
                   for m1, m2 in module_paths}
    tree = []

    while modules:
        level = {c for c in modules if
                    not any(in_deep(d, module_deps[c]) for d in modules)}
        modules  = modules - level
        tree.append(list(level))

    infos = dep_tree_enrich(tree, paths, github_root)
    class_tree = [[c for c in classes if c['module'] in level] for level in tree]

    return infos, class_tree


def format_class_tree_to_html(index_name, module_tree, class_tree, output_path, github_root=GITHUB_ROOT):
    class_name = ""
    for c in class_tree[0]:
     if c.get('_name'):
         class_name = c['_name']
    title = class_name
    file_name = class_name + '.html'

    body = [
        E.h1(title),
        format_header_to_ethtml(index_name),
        format_inheritance_tree_to_ethtml(module_tree),
        format_class_tree_to_ethtml(class_tree, github_root=github_root),
    ]
    return html_write(title, body, file_name, output_path)


def html_write(title: str, body, file_name: str, output_path: Path):
    body = E.body(*body)
    content = html_generate(title, body)
    file_write(content, os.path.join(output_path, file_name))
    return title, file_name


def format_module_tree_to_html(index_name: str, module: str, module_tree: InfoDepTree, output_path: Path):
    body = [
        E.h1(module),
        format_header_to_ethtml(index_name),
        format_inheritance_tree_to_ethtml(module_tree),
    ]
    return html_write(module, body, module + '.html', output_path)


def html_link(link: str, name: str=""):
    return E.a(name or link, href=link)


def format_header_to_ethtml(name: str):
    e = E.div(CLASS("blocky"))
    e.append(html_link(name, "Return to Index"))
    return e


def format_inheritance_tree_to_ethtml(module_tree):
    e = E.div(CLASS("growy"))
    for level in module_tree:
        l = E.div(CLASS("flowy-row f_c"))
        for module in level:
            l.append(E.div(E.span(
                html_link(module.path, module.name),
                html_link(module.link, ' 🌐')), CLASS("flowy f_c")))
        e.append(l)
    return E.div(CLASS("blocky"), E.h2("Inheritance tree"), e)


def format_class_tree_to_ethtml(class_tree, github_root=GITHUB_ROOT):
    e = E.div(CLASS("blocky"), E.h2("Class tree"))
    for level in class_tree:
        l = E.div(CLASS("flowy-row f_c"))
        for odoo_class in level:
            l.append(format_class_to_ethtml(odoo_class, github_root=github_root))
        e.append(l)
    return e


def filename_to_repository(file_name: Path, memo:[Path]=[]) -> str:
    for repository in memo:
        if repository in file_name:
            return repository

    dir_name = os.path.dirname(file_name)
    while dir_name != '/':
        if os.path.exists(os.path.join(dir_name, '.git')):
            memo.append(dir_name)
            return dir_name
        else:
            dir_name = os.path.abspath(os.path.join(dir_name, os.pardir))
    _logger.exception("Could not find the repository. Online links will be wrong.")
    return "repository"


def html_github_link(file_name:Path, github_root: str=GITHUB_ROOT) -> str:
    repository_path = filename_to_repository(file_name)
    repository = os.path.basename(repository_path)
    hash = git_get_version(os.path.dirname(file_name), hash=True)
    github_base = github_root + '/' + repository + '/blob/' + hash
    end_path = file_name.split(repository, 1)[1]
    return github_base + end_path


def format_class_to_ethtml(odoo_class, github_root: str=GITHUB_ROOT):
    root = E.div(CLASS("flowy maxthird"))

    github_link = html_github_link(odoo_class['file'], github_root=github_root)

    details = E.details()
    summary = E.summary(E.span(html_link(odoo_class['full path'], odoo_class['module']),
                               html_link(github_link, WEB_ICON)))
    e = E.div()
    root.append(details)
    details.append(summary)
    details.append(e)

    for attribute in special_attributes:
        a = odoo_class.get(attribute, False)
        if a:
            e.append(E.div(attribute + ': '+ str(a), CLASS("blocky")))

    fields = odoo_class['fields']
    if len(fields):
        e_d = E.details(E.summary("Fields"))
        e_fields = E.div(CLASS("flowy-row"), e_d)
        for field in fields:
            link = html_link(github_link + "#L" + str(fields[field]['lineno']), WEB_ICON)
            f = E.div(link, field + ": " + fields[field]['type'], CLASS("indnt"))
            e_d.append(f)
        e.append(e_fields)

    functions = odoo_class['functions']
    if len(functions):
        e_d = E.details(E.summary("Functions"))
        e_functions = E.div(CLASS("flowy-row"), e_d)
        for function in functions:
            link = html_link(github_link + "#L" + str(functions[function]['lineno']), WEB_ICON)
            f = E.div(link, function, CLASS("indnt"))
            e_d.append(f)
        e.append(e_functions)

    return root


def html_generate_index(title:str, name: str, file_names, output_path: Path):
    index_file = os.path.join(output_path, name)
    file_names.sort()

    e = E.div(CLASS("blocky indnt"))
    body = E.div(CLASS("blocky"), E.h1(title), e)
    for class_name, file_name in file_names:
        e.append(E.div(CLASS("blocky"), html_link(file_name, class_name)))

    content = html_generate(title, body)

    return file_write(content, index_file)


def html_generate(title, body):
    M = ElementMaker()
    html = M.html(
        E.head(
            E.meta(charset="utf-8"),
            E.link(rel="stylesheet", href=STYLE, type="text/css"),
            E.title(title),
        ),
        body,
        lang="en",
    )
    result = etree.tostring(html,
                            doctype='<!DOCTYPE html>',
                            encoding='unicode',
                            method='xml',
                            pretty_print=True)
    return result


def file_write(content, output_name):
    with open(output_name, 'w') as output:
        output.write(content)
    return output_name


def html_generate_doc(class_list, output_path, github_root=GITHUB_ROOT):
    index_name = "index_class.html"
    title = "Odoo Class Index"
    file_names = [
        format_class_tree_to_html(index_name, module_tree, class_tree, output_path, github_root)
        for module_tree, class_tree in class_list
    ]
    html_generate_index(title, index_name, file_names, output_path)
    return index_name


def html_generate_modules(module_list, output_path):
    index_name = "index_module.html"
    title = "Odoo Module Index"
    file_names = [
        format_module_tree_to_html(index_name, module, dep_tree, output_path)
        for module, dep_tree in module_list.items()
    ]
    html_generate_index(title, index_name, file_names, output_path)
    return index_name


def main_generate_doc(paths: [Path], output_path: Path, github_root: str=GITHUB_ROOT):
    all_modules = modules_from_paths(paths)
    all_models_files = models_files_from_modules(all_modules)
    all_model_dicts = []
    for model_file in all_models_files:
        try:
            all_model_dicts.extend(parse_model_file(
                module_name_from_path(model_file), model_file))
        except Exception as e:
            _logger.exception("Parsing %s:" % model_file)

    file_write(pf(all_model_dicts), os.path.join(output_path, "all_classes.py"))

    all_class_names = {c['_name'] for c in all_model_dicts if '_name' in c}

    all_class_trees = []
    for name in all_class_names:
        try:
            c = class_tree(name, all_model_dicts, paths, github_root)
            all_class_trees.append(c)
        except Exception as e:
            _logger.exception("Processing %s:" % name)

    return html_generate_doc(all_class_trees, output_path, github_root=github_root)


def main_generate_module_deps(paths: [Path], output_path: Path, github_root: str=GITHUB_ROOT):
    all_modules = modules_from_paths(paths)

    all_module_deps = {}
    all_module_infos = {}
    for m in all_modules:
        deps = module_dependencies_tree(m, paths)
        ideps = invert_dependencies(deps, paths)
        n = module_name_from_path(m)
        infos = dep_tree_enrich(ideps, paths, github_root)

        all_module_deps.update({n: infos})
        all_module_infos.update({n: infos})

    file_write(pf(all_module_deps), os.path.join(output_path, "all_modules.py"))
    return html_generate_modules(all_module_infos, output_path)


def git_check_clean_paths(paths: [Path]):
    for path in paths:
        status = subprocess.check_output(['git', 'status'], cwd=path).decode()
        if 'working tree clean' not in status:
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


def normalize_paths(paths: [Path]) -> [Path]:
    normalized_paths = []
    for path in paths:
        if os.path.split(os.path.dirname(path))[-1] == 'odoo':
            normalized_paths.append(os.path.join(path, 'addons/'))
            normalized_paths.append(os.path.join(path, 'odoo/addons/'))
        else:
            normalized_paths.append(path)
    return [os.path.expanduser(path) for path in normalized_paths]


def main_arguments_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='OdooDoc')

    parser.add_argument('--output_path', '-o', type=str, nargs='?',
                        help='Output folder for documentation.')
    parser.add_argument('--web_root', '-w', type=str, nargs='?',
                        default=GITHUB_ROOT, help='Root web path (Github).')
    parser.add_argument('--paths', '-p', type=str, nargs='?',
                        default=PATHS, help='Comma separated list of paths.')
    return parser


if __name__ == "__main__":
    args = main_arguments_parser().parse_args()

    paths = args.paths.split(',') if isinstance(args.paths, str) else args.paths
    paths = normalize_paths(paths)
    git_check_clean_paths(paths)
    versions = [git_get_version(path) for path in paths]
    output_path = args.output_path or "odoo_" + "_".join(set(versions))
    _logger.info("Starting documentation for " + output_path)
    os.makedirs(output_path, mode=0o777, exist_ok=True)

    main_generate_doc(paths, output_path, args.web_root)
    main_generate_module_deps(paths, output_path, args.web_root)

    shutil.copyfile(STYLE, os.path.join(output_path, STYLE))

    _logger.info("Documentation has been generated.")
