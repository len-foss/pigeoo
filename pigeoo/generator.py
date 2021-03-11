import os
import shutil
from lxml import etree  # type: ignore
from lxml.builder import ElementMaker,E  # type: ignore
from lxml.html.builder import CLASS  # type: ignore
from pprint import pformat as pf

from typing import Dict

from . import formatter
from . import parser
from . import query
from .parser import InfoDepTree
from .utils import _logger, Path, file_write


STYLE = "style.css"


def index_class_name():
    return "index_class.html"


def index_module_name():
    return "index_module.html"


def format_class_tree_to_html(index_name, module_tree, class_tree, output_path: Path, options: Dict):
    class_name = ""
    for c in class_tree[0]:
     if c.get('_name'):
         class_name = c['_name']
    title = class_name
    file_name = class_name + '.html'

    body = [
        E.h1(title),
        formatter.header_to_ethtml(index_name),
        formatter.inheritance_tree_to_ethtml(module_tree, options),
        formatter.class_tree_to_ethtml(class_tree, options),
    ]
    return html_write(title, body, file_name, output_path)


def html_write(title: str, body, file_name: str, output_path: Path):
    body = E.body(*body)
    content = html_generate(title, body)
    file_write(content, os.path.join(output_path, file_name))
    return title, file_name


def format_module_tree_to_html(index_name: str, module: str, module_tree: InfoDepTree, output_path: Path, options):
    body = [
        E.h1(module),
        formatter.header_to_ethtml(index_name),
        formatter.inheritance_tree_to_ethtml(module_tree, options),
    ]
    return html_write(module, body, module + '.html', output_path)


def html_generate_index(title:str, name: str, file_names, output_path: Path):
    index_file = os.path.join(output_path, name)
    file_names.sort()

    e = E.div(CLASS("blocky indnt"))
    body = E.div(CLASS("blocky"), E.h1(title), e)
    for class_name, file_name in file_names:
        e.append(E.div(CLASS("blocky"), formatter.html_link(file_name, class_name)))

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


def html_generate_doc(class_list, output_path, options:Dict):
    index_name = index_class_name()
    title = "Odoo Class Index"
    file_names = [
        format_class_tree_to_html(index_name, module_tree, class_tree, output_path, options)
        for module_tree, class_tree in class_list
    ]
    html_generate_index(title, index_name, file_names, output_path)
    return index_name


def html_generate_modules(module_list, output_path, options:Dict):
    index_name = index_module_name()
    title = "Odoo Module Index"
    file_names = [
        format_module_tree_to_html(index_name, module, dep_tree, output_path, options)
        for module, dep_tree in module_list.items()
    ]
    html_generate_index(title, index_name, file_names, output_path)
    return index_name


def main_generate_doc(paths: [Path], all_module_deps, output_path: Path, options:Dict):
    all_modules = parser.modules_from_paths(paths, all_module_deps)
    all_models_files = parser.models_files_from_modules(all_modules)
    all_model_dicts = []
    for model_file in all_models_files:
        try:
            all_model_dicts.extend(parser.parse_model_file(
                parser.module_name_from_path(model_file), model_file))
        except KeyboardInterrupt:
            exit()
        except Exception as e:
            _logger.exception("Parsing %s:" % model_file)

    file_write(pf(all_model_dicts), os.path.join(output_path, "all_classes.py"))

    all_class_names = {c['_name'] for c in all_model_dicts if '_name' in c}

    all_class_trees = []
    for name in all_class_names:
        try:
            c = parser.class_tree(name, all_model_dicts, paths, options, all_module_deps)
            all_class_trees.append(c)
        except KeyboardInterrupt:
            exit()
        except Exception as e:
            _logger.exception("Processing %s:" % name)

    return html_generate_doc(all_class_trees, output_path, options)


def generate_module_deps(paths: [Path], options:Dict):
    all_modules = parser.modules_from_paths(paths)

    all_module_deps = {}
    for m in all_modules:
        deps = parser.module_dependencies_tree(m, paths)
        ideps = parser.invert_dependencies(m, deps, paths)
        n = parser.module_name_from_path(m)
        infos = parser.dep_tree_enrich(ideps, paths, options)

        all_module_deps.update({n: infos})
    return all_module_deps

def main_generate_module_deps(all_module_deps, output_path: Path, options: Dict) -> str:
    file_write(pf(all_module_deps), os.path.join(output_path, "all_modules.py"))
    return html_generate_modules(all_module_deps, output_path, options)


def filter_modules(all_module_deps, options: Dict):
    result = all_module_deps
    if options["modules"]:
        filter = options["modules"]
        depends = query.module_m_depends_on_n
        result = {
            m: all_module_deps[m] for m in all_module_deps if
            m in filter or any(depends(f, m, all_module_deps) for f in filter)
        }
    return result


def copy_stylesheet(output_path):
    source = os.path.dirname(os.path.realpath(__file__))
    stylesheet = os.path.join(source, "static/", STYLE)
    shutil.copyfile(stylesheet, os.path.join(output_path, STYLE))


def main(paths, output_path, options):
    _logger.info("Starting documentation for " + output_path)
    os.makedirs(output_path, mode=0o777, exist_ok=True)

    all_module_deps = generate_module_deps(paths, options)
    all_module_deps = filter_modules(all_module_deps, options)
    main_generate_module_deps(all_module_deps, output_path, options)
    main_generate_doc(paths, all_module_deps, output_path, options)

    copy_stylesheet(output_path)
    file_write(pf(options), os.path.join(output_path, "options.py"))

    _logger.info("Documentation has been generated.")
