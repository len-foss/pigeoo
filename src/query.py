def get_class_name(c):
    if c.get('_name'):
        return c.get('_name')
    if c.get('_inherit') and isinstance(c.get('_inherit'), list):
        return c.get('_inherit')[0]
    return c.get('_inherit')


def get_class(class_name, class_list):
    return [c for c in class_list if get_class_name(c) == class_name]


def get_depending_modules(mod_name, all_modules) -> [str]:  # -> [module_names]
    return [m for m in all_modules if module_m_depends_on_n(m, mod_name, all_modules)]


def module_m_depends_on_n(m, n, all_modules) -> bool:
    # we only need to look at level k + 1 if module_name has dependency depth k
    if m == n:
        return False
    k = len(all_modules[n])
    result = False
    if len(all_modules[m]) > k:
        result = any(n == md["name"] for md in all_modules[m][k])
    return result

def get_functions(name, function_list):
    functions = {key[1]: function_list[key] for key in function_list if key[0] == name}
    return functions


def get_all_functions(class_list):
    return get_all_entities("functions", class_list)


def get_all_fields(class_list):
    return get_all_entities("fields", class_list)


def get_all_entities(entity, class_list):
    all_entities = {}
    for c in class_list:
        class_name = get_class_name(c)
        if class_name:
            for function in c[entity]:
                key = (function, class_name)
                all_entities.setdefault(key, {})
                all_entities[key][c["module"]] = c[entity][function]
    return all_entities
