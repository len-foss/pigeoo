import os
import re
import ast
from typing import List, Dict, Optional
from subprocess import Popen, PIPE

from . import query
from .utils import _logger, Path

MODEL_FOLDERS = ["models", "components", "wizard", "wizards", "datamodels"]  # TODO: nonstandard

DepTree = List[List[str]]
InfoDepTree = List[List[Dict]]

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
    elif 's' not in dir(v):  # l10n_eu_service: __doc__
        return f"{v.id}"
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
    def _parse_value_inh(va):
        return va.s if 's' in dir(va) else va.id
    if type(v) == ast.List:
        return [_parse_value_inh(e) for e in v.elts]
    return _parse_value_inh(v)


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


def is_assign_x(a_a, type):
    name = a_a.targets[0].id
    return name in type


def is_assign_str(a_a):
    return is_assign_x(a_a, special_attributes_str)


def is_assign_sql(a_a):
    return is_assign_x(a_a, special_attributes_sql)


def is_assign_inh(a_a):
    return is_assign_x(a_a, special_attributes_inh)


def is_assign_inhs(a_a):
    return is_assign_x(a_a, special_attributes_inhs)


def is_assign_constraint(a_a):
    return is_assign_x(a_a, special_attributes_con)


def is_assign_bool(a_a):
    return is_assign_x(a_a, special_attributes_bool)


def parse_class_function(a_a):
    # TODO: kwargs and such
    values = {
        'lineno': a_a.lineno,
        # 'decorator_list': a_a.decorator_list,
        'args': [v.arg for v in a_a.args.args],
    }
    return a_a.name, values


def parse_class_assign(a_a):
    # assert(len(a_a.targets) == 1)  # api.key in v14 assigns _name and_description
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
    def is_base_module(module):
        return re.match('.*base.?$', module)

    def get_module_paths(module):
        if is_base_module(module):
            return [module]
        else:
            module_folders = [os.path.join(module, subfolder) for subfolder in MODEL_FOLDERS]
            return [folder for folder in module_folders if os.path.exists(folder)]

    files_list = []
    for module in module_list:
        for module_path in get_module_paths(module):
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
        folders_re = "|".join(MODEL_FOLDERS)
        name_re = re.match(f'.*\/(.*)/({folders_re})/(.*)?', path)
        return name_re[1] if name_re else os.path.basename(path)


def module_path_has_manifest(module_path: Path) -> bool:
    manifest_file = os.path.join(module_path, '__manifest__.py')
    return os.path.isdir(module_path) and os.path.exists(manifest_file)


def modules_from_paths(path_list: [Path], all_module_depths=None) -> [Path]:
    module_list = []
    for path in path_list:
        for module in os.listdir(path):
            if all_module_depths:
                if module in all_module_depths:
                    module_list.append(os.path.join(path, module))
            else:
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
    manifest_file = os.path.join(module_path, '__manifest__.py')
    if not os.path.exists(manifest_file):
        module_path = module_path_from_name(module_path, paths)
        manifest_file = os.path.join(module_path, '__manifest__.py')
    if not os.path.exists(manifest_file):
        _logger.exception("Module without a manifest: " + module_path)
        return {}
    manifest_dict = eval(open(manifest_file, 'r').read())
    dependencies = manifest_dict.get('depends', ['base'])
    modules = [module_path_from_name(dep, paths) for dep in dependencies]
    all_trees = {module_name_from_path(m): module_dependencies_tree(m, paths) for m in modules}
    return all_trees


def dict_depth(d):
    # awful algorithm, but the recursive dict_depth is way too inefficient
    depth = 0
    if d:
        level = [i for i in d.values()]
        while level:
            depth += 1
            next_level = []
            for ld in level:
                if ld:
                    ld_values = [i for i in ld.values()]
                    for v in ld_values:
                        if v not in next_level:
                            next_level.append(v)
            level = next_level
    return depth


def dict_flatten(d, keys=None):
    if keys is None:
        keys = set()
    if not isinstance(d, dict) or not d:
        return keys
    for key in d.keys():
        if key not in keys:  # only process each branch once
            keys.add(key)
            dict_flatten(d[key], keys)
    return keys


@memoize_first
def module_dependencies_depth(module_path: Path, paths: [Path]) -> int:
    if module_name_from_path(module_path) == 'base':
        return 0
    dependency_tree = module_dependencies_tree(module_path, paths)
    return dict_depth(dependency_tree)


@memoize_first
def module_flat_dependencies(module_name, dependency_tree) -> List[str]:
    return dict_flatten(dependency_tree)


def invert_dependencies(name, dependency_tree, paths) -> DepTree:
    if dependency_tree == {}:
        return []
    all_deps = module_flat_dependencies(name, dependency_tree)
    module_depths = {m: module_dependencies_depth(m, paths) for m in all_deps}
    inverted_tree:DepTree = [[] for i in range(max(module_depths.values()) + 1)]
    for m, d in module_depths.items():
        inverted_tree[d].append(m)
    return inverted_tree


def dep_tree_enrich(dep_tree: DepTree, paths:[Path], options: Dict) -> InfoDepTree:
    infos = []
    for level in dep_tree:
        info_level = []
        for module in level:
            path = module_path_from_name(module, paths)
            module_info = {'name': module,'path': path, 'link': web_link(path, options)}
            info_level.append(module_info)
        infos.append(info_level)
    return infos


def class_tree(class_name, class_list, paths, github_root, all_module_deps):
    classes = query.get_class(class_name, class_list)
    modules = set(c['module'] for c in classes)
    tree = []
    while modules:
        depends = query.module_m_depends_on_n
        level = {c for c in modules if
                 not any(depends(c, d, all_module_deps) for d in modules)}
        modules  = modules - level
        tree.append(list(level))

    infos = dep_tree_enrich(tree, paths, github_root)
    class_tree = [[c for c in classes if c['module'] in level] for level in tree]

    return infos, class_tree


def git_repository_folder_from_filename(file_name: Path, memo:[Path]=[]) -> str:
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


def git_repository_folder_to_remote(repository_folder: Path, memo:Dict[Path, str]={}) -> str:
    # toclean
    if repository_folder in memo:
        return memo[repository_folder]
    try:
        output, err = Popen(['git', 'remote', '-v'], cwd=repository_folder, stdout=PIPE, stderr=PIPE).communicate()
        lines = output.decode().split("\n")
        for line in lines:
            origin_tag = "origin\t"
            fetch_tag = " (fetch)"
            if line.startswith(origin_tag) and line.endswith(fetch_tag):
                remote = line[len(origin_tag):-len(fetch_tag)]
                memo[repository_folder] = remote
                return remote
    except KeyboardInterrupt:
        exit()
    except Exception as e:
        _logger.exception(f"Error finding git remote: {e}")
    _logger.exception(f"No origin found for {repository_folder}")
    remote = "unknown"
    memo[repository_folder] = remote
    return remote


def git_to_https(repository: str) -> str:
    if repository.startswith("git@"):  # replace prefix, remove .git suffix
        return repository.replace(":", "/").replace("git@", "https://")[:-4]
    else:
        return repository


def web_link(file_name:Path, options: Dict) -> Optional[str]:
    if "packages" in file_name:  # "git_paths" in options
        return None
    repository_path = git_repository_folder_from_filename(file_name)
    repository = git_to_https(git_repository_folder_to_remote(repository_path))
    hash = ""
    for key in options['hashes']:
        if repository_path in key:
            hash = options['hashes'][key]
    link_base = repository + '/blob/' + hash
    link_end = file_name.split(repository_path, 1)[1]
    return link_base + link_end
