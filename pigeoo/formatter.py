from typing import Dict

from lxml.builder import E
from lxml.html.builder import CLASS  # type: ignore

from . import parser


WEB_ICON = "🌐"


def html_link(link: str, name: str=""):
    return E.a(name or link, href=link)


def header_to_ethtml(name: str):
    e = E.div(CLASS("blocky"))
    e.append(html_link(name, "Return to Index"))
    return e


def class_to_ethtml(odoo_class, options: Dict):
    root = E.div(CLASS("flowy maxthird"))

    github_link = parser.web_link(odoo_class['file'], options)

    details = E.details()
    if options['local']:
        span = [html_link(odoo_class['full path'], odoo_class['module'])]
    else:
        span = [odoo_class['module']]
    if github_link:
        span.append(html_link(github_link, WEB_ICON))
    summary = E.summary(E.span(*span))
    e = E.div()
    root.append(details)
    details.append(summary)
    details.append(e)

    for attribute in parser.special_attributes:
        a = odoo_class.get(attribute, False)
        if a:
            e.append(E.div(attribute + ': '+ str(a), CLASS("blocky")))

    fields = odoo_class['fields']
    if len(fields):
        e_d = E.details(E.summary("Fields"))
        e_fields = E.div(CLASS("flowy-row"), e_d)
        for field in fields:
            div = []
            if github_link:
                line_no = str(fields[field]['lineno'])
                div.append(html_link(github_link + "#L" + line_no, WEB_ICON))
            div += [field + ": " + fields[field]['type'], CLASS("indnt")]
            f = E.div(*div)
            e_d.append(f)
        e.append(e_fields)

    functions = odoo_class['functions']
    if len(functions):
        e_d = E.details(E.summary("Functions"))
        e_functions = E.div(CLASS("flowy-row"), e_d)
        for function in functions:
            div = []
            if github_link:
                line_no = str(functions[function]['lineno'])
                div.append(html_link(github_link + "#L" + line_no, WEB_ICON))
            div += [function, CLASS("indnt")]
            f = E.div(*div)
            e_d.append(f)
        e.append(e_functions)

    return root


def class_tree_to_ethtml(class_tree, options):
    e = E.div(CLASS("blocky"), E.h2("Class tree"))
    for level in class_tree:
        l = E.div(CLASS("flowy-row f_c"))
        for odoo_class in level:
            l.append(class_to_ethtml(odoo_class, options))
        e.append(l)
    return e


def inheritance_tree_to_ethtml(module_tree, options: Dict):
    e = E.div(CLASS("growy"))
    for level in module_tree:
        l = E.div(CLASS("flowy-row f_c"))
        for module in level:
            if options["local"]:
                span = [html_link(module["path"], module["name"])]
            else:
                span = [module["name"]]
            if module["link"]:
                span.append(html_link(module["link"], ' 🌐'))
            l.append(E.div(E.span(*span), CLASS("flowy f_c")))
        e.append(l)
    return E.div(CLASS("blocky"), E.h2("Inheritance tree"), e)


def functions_to_ethtml(name, fdict, options: Dict):
    e = E.div(CLASS("growy"))
    for model in fdict:
        ul = E.ul(*[E.li(m) for m in list(fdict[model].keys())])
        l = E.div(CLASS("flowy-row f_c"), E.h4(model), ul)
        e.append(l)
    return E.div(CLASS("blocky"), E.h2(name), e)
