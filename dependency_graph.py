import os
import xml.etree.ElementTree as ET
import logging
import re
import json
import sys
import urllib.parse


class Module(object):
    def __init__(self, path, name):
        self.path = path
        self.name = name
        self.references = set()
        self.usages = set()
        self.output_type = 'Unknown'
        self.team = ''

    def __eq__(self, other):
        return self.path == other.path

    def __hash__(self):
        return hash(self.path)

    def add_reference(self, module):
        self.references.add(module)
        module.usages.add(self)

    def remove_references_to_module(self, module):
        self.references.discard(module)
        self.usages.discard(module)

    def get_recursive_usages(self, modules=None):
        modules = modules or set()
        if self not in modules:
            modules.add(self)
            for module in self.usages:
                module.get_recursive_usages(modules)
        return modules

    def get_recursive_references(self, modules=None):
        modules = modules or set()
        if self not in modules:
            modules.add(self)
            for module in self.references:
                module.get_recursive_references(modules)
        return modules


class Modules(object):
    def __init__(self):
        self.dict = {}

    def create(self, path, name):
        if path in self.dict:
            raise Exception("Module %s already defined" % path)
        self.dict[path] = Module(path, name)
        return self.dict[path]

    def find_by_path(self, path):
        return self.dict.get(path)

    def remove_by_pattern(self, pattern):
        removed_modules = []
        for path in self.dict:
            if re.search(pattern, path, re.IGNORECASE):
                removed_modules.append(self.dict[path])

        for removed_module in removed_modules:
            self.remove_module(removed_module)

    def remove_module(self, module_to_remove):
        logging.debug('Discarding %s', module_to_remove.path)
        for module in self.dict.values():
            module.remove_references_to_module(module_to_remove)
        del self.dict[module_to_remove.path]

    def __iter__(self):
        return iter(self.dict.values())


class MSBuildParser(object):
    def parse_assembly_definition(self, assembly_definition):
        assembly_props = re.split('\s*,\s*', assembly_definition)
        assembly_name = assembly_props.pop(0)
        assembly_props = filter(len, assembly_props)
        assembly_props = {k: v for k, v in [re.split('\s*=\s*', x) for x in assembly_props]}
        return assembly_name.lower(), assembly_props

    def find_output_type_by_project_guid(self, project_guids):
        project_guids = set((project_guids or '').upper().split(';'))
        web_app_guids = {
            '{349C5851-65DF-11DA-9384-00065B846F21}',
            '{603C0E0B-DB56-11DC-BE95-000D561079B0}',
            '{F85E285D-A4E0-4152-9332-AB1D724D3325}',
            '{E53F8FEA-EAE0-44A6-8774-FFD645390401}',
            '{E3E379DF-F4C6-4180-9B81-6769533ABE47}'
        }

        if web_app_guids & project_guids:
            return 'Web Application'
        return None

    def build_module_path(self, base_dir, proj_path):
        return os.path.relpath(proj_path, base_dir).lower()

    def create_module_from_msbuild_proj(self, modules, base_dir, proj_path):
        logging.debug('Parsing %s ', proj_path)
        tree = ET.parse(proj_path)

        module_path = self.build_module_path(base_dir, proj_path)
        module = modules.find_by_path(module_path)
        if not module:
            logging.debug('Processing %s', module_path)
            module = modules.create(module_path, (
                tree.findtext('.//{http://schemas.microsoft.com/developer/msbuild/2003}AssemblyName') or
                tree.findtext('.//{http://schemas.microsoft.com/developer/msbuild/2003}RootNamespace') or
                os.path.basename(proj_path)
            ))

            module.output_type = (
                self.find_output_type_by_project_guid(tree.findtext('.//{http://schemas.microsoft.com/developer/msbuild/2003}ProjectTypeGuids')) or
                tree.findtext('.//{http://schemas.microsoft.com/developer/msbuild/2003}OutputType') or
                tree.findtext('.//{http://schemas.microsoft.com/developer/msbuild/2003}ConfigurationType') or
                module.output_type
            )

            for project_reference_el in tree.findall('.//{http://schemas.microsoft.com/developer/msbuild/2003}ProjectReference[@Include]'):
                include_attr = urllib.parse.unquote(project_reference_el.attrib['Include'])
                ref_prj_path = os.path.abspath(os.path.join(os.path.dirname(proj_path), include_attr))
                if not os.path.exists(ref_prj_path):
                    logging.warn('Broken reference "%s" => "%s"', proj_path, ref_prj_path)
                    continue
                ref_module = self.create_module_from_msbuild_proj(modules, base_dir, ref_prj_path)
                module.add_reference(ref_module)

            for reference_el in tree.findall('.//{http://schemas.microsoft.com/developer/msbuild/2003}Reference'):
                ref_assembly_name = self.parse_assembly_definition(reference_el.attrib['Include'])[0]
                ref_module_path = reference_el.findtext('{http://schemas.microsoft.com/developer/msbuild/2003}HintPath')
                if ref_module_path:
                    ref_module_path = os.path.join(os.path.dirname(proj_path), ref_module_path)
                    ref_module_path = self.build_module_path(base_dir, ref_module_path)
                else:
                    ref_module_path = ref_assembly_name
                ref_module = modules.find_by_path(ref_module_path)
                if not ref_module:
                    ref_module = modules.create(ref_module_path, ref_assembly_name)
                    ref_module.output_type = 'DynamicLibrary'
                module.add_reference(ref_module)

        return module


PROJECT_FILE_EXTENSIONS = ['.vcproj', '.csproj', '.vcxproj', '.vbproj']


def pasre_dir(base_dir):
    logging.debug('Parsing dir %s', base_dir)

    parser = MSBuildParser()
    modules = Modules()

    for directory, directories, files in os.walk(base_dir):
        if '.git' in directories:
            directories.remove('.git')
        if '$tf' in directories:
            directories.remove('$tf')
        for proj_file in [x for x in files if os.path.splitext(x)[1].lower() in PROJECT_FILE_EXTENSIONS]:
            proj_path = os.path.join(directory, proj_file)
            parser.create_module_from_msbuild_proj(modules, base_dir, proj_path)

    return modules


def write_graphml(modules, filename):
    logging.info('Writing %s', filename)

    graphml_el = ET.Element('graphml')
    ET.SubElement(graphml_el, 'key', {'id': 'module_path', 'for': 'node', 'attr.name': 'Module Path', 'attr.type': 'string'})
    ET.SubElement(graphml_el, 'key', {'id': 'module_name', 'for': 'node', 'attr.name': 'Module Name', 'attr.type': 'string'})
    ET.SubElement(graphml_el, 'key', {'id': 'module_type', 'for': 'node', 'attr.name': 'Module Type', 'attr.type': 'string'})
    ET.SubElement(graphml_el, 'key', {'id': 'module_team', 'for': 'node', 'attr.name': 'Module Team', 'attr.type': 'string'})
    ET.SubElement(graphml_el, 'key', {'id': 'reference_crossteam', 'for': 'edge', 'attr.name': 'Cross Team', 'attr.type': 'boolean'})
    graph_el = ET.SubElement(graphml_el, 'graph', {'id': 'G', 'edgedefault': 'directed'})
    for module in modules.dict.values():
        node_el = ET.SubElement(graph_el, 'node', {'id': module.path})
        ET.SubElement(node_el, 'data', {'key': 'module_path'}).text = module.path
        ET.SubElement(node_el, 'data', {'key': 'module_name'}).text = module.name
        ET.SubElement(node_el, 'data', {'key': 'module_type'}).text = module.output_type
        ET.SubElement(node_el, 'data', {'key': 'module_team'}).text = module.team

        reference_teams = module.get_recursive_references()
        reference_teams = set([x.team for x in reference_teams])
        reference_teams.discard(module.team)
        usage_teams = set([x.team for x in module.usages])
        usage_teams.discard(module.team)

        for ref_module in module.references:
            edge_el = ET.SubElement(graph_el, 'edge', {'id': module.path + ':' + ref_module.path, 'source': module.path, 'target': ref_module.path})
            ET.SubElement(edge_el, 'data', {'key': 'reference_crossteam'}).text = 'false' if module.team == ref_module.team else 'true'
    ET.ElementTree(graphml_el).write(filename, encoding='utf-8', xml_declaration=True)


def set_external_attr(modules, filename, new_attr_filename=None):
    new_modules_attrs = dict()

    with open(filename) as f:
        modules_attrs = json.load(f)

    for module in modules.dict.values():
        module_attrs = modules_attrs.get(module.path)
        if module_attrs:
            for attr_name, attr_value in module_attrs.items():
                attr_type = type(getattr(module, attr_name))
                setattr(module, attr_name, attr_type(attr_value))
        else:
            logging.debug('New module %s', module.path)
            new_modules_attrs[module.path] = dict(team='?')

    if new_modules_attrs and new_attr_filename:
        logging.info('Updating file %s', new_attr_filename)
        with open(new_attr_filename, 'w') as f:
            json.dump(new_modules_attrs, f, indent='\t')


def init_logging():
    fmt = logging.Formatter(logging.BASIC_FORMAT, None)

    shdlr = logging.StreamHandler()
    shdlr.setFormatter(fmt)
    shdlr.setLevel(logging.INFO)
    logging.root.addHandler(shdlr)

    fhdlr = logging.FileHandler('log.txt', 'w')
    fhdlr.setFormatter(fmt)
    fhdlr.setLevel(logging.DEBUG)
    logging.root.addHandler(fhdlr)

    logging.root.setLevel(logging.DEBUG)


def main():
    init_logging()

    base_dir = sys.argv[1]
    logging.info('Starting from %s', base_dir)

    modules = pasre_dir(base_dir)

    modules.remove_by_pattern('tests?\.csproj$')
    modules.remove_by_pattern('\.tests?\.')
    modules.remove_by_pattern('\.testsupport\.')
    modules.remove_by_pattern('\.testsuite\.csproj$')
    modules.remove_by_pattern(r'\\gmock-\d.\d.\d\\')

    for module in list(modules):
        if not os.path.splitext(module.path)[1] in PROJECT_FILE_EXTENSIONS:
            logging.debug("Discarding binary module '%s'", module.path)
            modules.remove_module(module)

    set_external_attr(modules, 'extra_attrs.json', 'extra_attrs_new.json')

    write_graphml(modules, 'out.graphml')


if __name__ == '__main__':
    main()
