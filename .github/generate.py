import json
import os
import re
import subprocess
from typing import Any, Dict, Iterable, List, Tuple

from nvim_doc_tools.apidoc import (
    LuaParam,
    format_params,
    parse_functions,
    render_api_md,
    render_api_vimdoc,
)
from nvim_doc_tools.util import (
    MD_LINK_PAT,
    Vimdoc,
    VimdocSection,
    dedent,
    format_md_table,
    generate_md_toc,
    indent,
    leftright,
    read_section,
    replace_section,
    wrap,
)

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, os.path.pardir))
README = os.path.join(ROOT, "README.md")
DOC = os.path.join(ROOT, "doc")
VIMDOC = os.path.join(DOC, "overseer.txt")

MD_BOLD_PAT = re.compile(r"\*\*([^\*]+)\*\*")
MD_LINE_BREAK_PAT = re.compile(r"\s*\\$")


def read_nvim_json(lua: str) -> Any:
    cmd = f"nvim --headless --noplugin -u /dev/null -c 'set runtimepath+=.' -c 'lua print(vim.json.encode({lua}))' +qall"
    print(cmd)
    code, txt = subprocess.getstatusoutput(cmd)
    if code != 0:
        raise Exception(f"Error exporting data from overseer: {txt}")
    try:
        return json.loads(txt)
    except json.JSONDecodeError as e:
        raise Exception(f"Json decode error: {txt}") from e


def update_config_options():
    config_file = os.path.join(ROOT, "lua", "overseer", "config.lua")
    opt_lines = read_section(config_file, r"^local default_config =", r"^}$")
    replace_section(
        os.path.join(DOC, "reference.md"),
        r"^require\(\"overseer\"\).setup\({$",
        r"^}\)$",
        opt_lines,
    )


def params_sort_key(item):
    name, param = item
    is_optional = param.get("optional", "default" in param)
    return (is_optional, name)


def update_components_md():
    components = read_nvim_json('require("overseer.component").get_all_descriptions()')
    doc = os.path.join(ROOT, "doc", "components.md")
    lines = ["# Built-in components\n", "\n", "<!-- TOC -->\n", "<!-- /TOC -->\n", "\n"]
    for comp in components:
        lines.append(f"## {comp['name']}\n\n")
        lines.append(
            f"[{comp['name']}.lua](../lua/overseer/component/{comp['name']}.lua)\n"
        )
        lines.append("\n")
        if comp.get("desc"):
            lines.append(comp["desc"] + "\n")
        if comp.get("long_desc"):
            lines.append("\n")
            lines.extend(wrap(comp["long_desc"], width=100))
        long_desc_params = []
        if comp.get("params"):
            lines.append("\n")
            rows = []
            has_default = False
            for k, param in sorted(comp["params"].items(), key=params_sort_key):
                typestr = param["type"]
                if "subtype" in param:
                    typestr += "[" + str(param["subtype"]["type"]) + "]"
                required = not param.get("optional")
                name = k
                row = {
                    "Type": f"`{typestr}`",
                    "Desc": param.get("desc", ""),
                }
                if param.get("default") is not None:
                    row["Default"] = "`" + json.dumps(param["default"]) + "`"
                    required = False
                    has_default = True
                if required:
                    name = "*" + name
                row["Param"] = name
                rows.append(row)
                if "long_desc" in param:
                    long_desc_params.append(
                        {"name": k, "long_desc": param["long_desc"]}
                    )
            cols = ["Param", "Type", "Desc"]
            if has_default:
                cols.insert(2, "Default")
            lines.extend(format_md_table(rows, cols))
        if long_desc_params:
            lines.append("\n")
            for param in long_desc_params:
                lines.extend(
                    "- **" + param["name"] + ":** " + param["long_desc"] + "\n"
                )
        lines.append("\n")
    with open(doc, "w", encoding="utf-8") as ofile:
        ofile.writelines(lines)


def iter_parser_nodes() -> Iterable[Dict]:
    for filename in sorted(os.listdir(os.path.join(ROOT, "lua", "overseer", "parser"))):
        basename = os.path.splitext(filename)[0]
        if basename == "init":
            continue
        parser = read_nvim_json(
            f'require("overseer.parser").get_parser_docs("{basename}")'
        )
        if parser:
            yield parser


def format_parser_arg(arg: Dict) -> Iterable[str]:
    pieces = [f"**{arg['name']}**[`{arg['type']}`]:", arg["desc"]]
    if arg.get("default") is not None:
        pieces.append("(default `%s`)" % json.dumps(arg["default"]))
    yield " ".join(pieces) + " \\\n"
    if arg.get("long_desc"):
        yield from wrap(arg["long_desc"], 4, 100, " \\\n")
    for subarg in arg.get("fields", []):
        for line in format_parser_arg(subarg):
            yield 4 * "&nbsp;" + line


def format_parser_args(name: str, args: List[Dict]) -> Iterable[str]:
    yield "```lua\n"

    def arg_name(arg: Dict) -> str:
        if arg.get("vararg"):
            return arg["name"] + "..."
        else:
            return arg["name"]

    required_args = ['"%s"' % name] + [
        arg_name(arg) for arg in args if not arg.get("position_optional")
    ]
    yield "{" + ", ".join(required_args) + "}\n"
    all_args = ['"%s"' % name] + [arg_name(arg) for arg in args]
    if len(all_args) != len(required_args):
        yield "{" + ", ".join(all_args) + "}\n"
    yield "```\n"
    yield "\n"
    for arg in args:
        yield from format_parser_arg(arg)


def format_example_code(code: str) -> Iterable[str]:
    lines = code.split("\n")
    while re.match(r"^\s*$", lines[0]):
        lines.pop(0)
    while re.match(r"^\s*$", lines[-1]):
        lines.pop()
    for line in dedent(lines):
        yield line + "\n"


def update_parsers_md():
    doc = os.path.join(ROOT, "doc", "parsers.md")
    prefix = [
        "\n",
        "This is a list of the parser nodes that are built-in to overseer. They can be found in [lua/overseer/parser](../lua/overseer/parser)\n",
        "\n",
    ]
    toc = []
    lines = []
    for parser in iter_parser_nodes():
        toc.append(f"- [{parser['name']}](#{parser['name']})\n")
        lines.append(
            f"## [{parser['name']}](../lua/overseer/parser/{parser['name']}.lua)\n\n"
        )
        lines.append(parser["desc"] + " \\\n")
        if parser.get("long_desc"):
            lines.extend(wrap(parser["long_desc"], width=100))
        lines.append("\n")
        lines.extend(format_parser_args(parser["name"], parser["doc_args"]))
        if parser.get("examples"):
            lines.extend(["\n", "### Examples\n", "\n"])
            for example in parser["examples"]:
                lines.extend(
                    [
                        example["desc"] + "\n",
                        "\n",
                        "```lua\n",
                    ]
                )
                lines.extend(format_example_code(example["code"]))
                lines.extend(["```\n", "\n"])
        lines.append("\n")
    toc.append("\n")
    while lines[-1] == "\n":
        lines.pop()
    replace_section(
        doc,
        r"^# Parser nodes",
        None,
        prefix + toc + lines,
    )


def update_commands_md():
    commands = read_nvim_json('require("overseer").get_all_commands()')
    lines = ["\n"]
    rows = []
    for command in commands:
        cmd = command["cmd"]
        if command["def"].get("bang"):
            cmd += "[!]"
        rows.append(
            {
                "Command": "`" + cmd + "`",
                "Args": command.get("args", ""),
                "Description": command["def"]["desc"],
            }
        )
    lines.extend(format_md_table(rows, ["Command", "Args", "Description"]))
    lines.append("\n")
    replace_section(
        os.path.join(DOC, "reference.md"),
        r"^## Commands",
        r"^#",
        lines,
    )


def update_highlights_md():
    highlights = read_nvim_json('require("overseer").get_all_highlights()')
    lines = [
        "\n",
        "Overseer defines the following highlights. Override them to customize the colors.\n",
        "\n",
    ]
    rows = []
    for hl in highlights:
        name = hl["name"]
        desc = hl.get("desc")
        if desc is None:
            continue
        rows.append(
            {
                "Group": "`" + name + "`",
                "Description": desc,
            }
        )
    lines.extend(format_md_table(rows, ["Group", "Description"]))
    lines.append("\n")
    replace_section(
        os.path.join(DOC, "reference.md"),
        r"^## Highlight groups",
        r"^#",
        lines,
    )


def get_commands_vimdoc() -> "VimdocSection":
    section = VimdocSection("Commands", "overseer-commands", ["\n"])
    commands = read_nvim_json('require("overseer").get_all_commands()')
    for command in commands:
        cmd = command["cmd"]
        if command["def"].get("bang"):
            cmd += "[!]"
        if "args" in command:
            cmd += " " + command["args"]
        section.body.append(leftright(cmd, f"*:{command['cmd']}*"))
        section.body.extend(wrap(command["def"]["desc"], 4))
        section.body.append("\n")
    return section


def get_options_vimdoc() -> "VimdocSection":
    section = VimdocSection("options", "overseer-options")
    config_file = os.path.join(ROOT, "lua", "overseer", "config.lua")
    opt_lines = read_section(config_file, r"^local default_config =", r"^}$")
    lines = ["\n", ">\n", '    require("overseer").setup({\n']
    lines.extend(indent(opt_lines, 4))
    lines.extend(["    })\n", "<\n"])
    section.body = lines
    return section


def get_highlights_vimdoc() -> "VimdocSection":
    section = VimdocSection("Highlights", "overseer-highlights", ["\n"])
    highlights = read_nvim_json('require("overseer").get_all_highlights()')
    for hl in highlights:
        name = hl["name"]
        desc = hl.get("desc")
        if desc is None:
            continue
        section.body.append(leftright(name, f"*hl-{name}*"))
        section.body.extend(wrap(desc, 4))
        section.body.append("\n")
    return section


def get_components_vimdoc() -> "VimdocSection":
    section = VimdocSection("Components", "overseer-components", ["\n"])
    components = read_nvim_json('require("overseer.component").get_all_descriptions()')
    for comp in components:
        section.body.append(leftright(comp["name"], f"*{comp['name']}*"))
        if "desc" in comp:
            section.body.append(4 * " " + comp["desc"] + "\n")
        if "long_desc" in comp:
            section.body.extend(wrap(comp["long_desc"], 4))
        if comp.get("params"):
            section.body.append("\n")
            section.body.append(4 * " " + "Parameters:\n")
            lua_params = []
            for k, param in sorted(comp["params"].items(), key=params_sort_key):
                typestr = param["type"]
                if "subtype" in param:
                    typestr += "[" + str(param["subtype"]["type"]) + "]"
                required = not param.get("optional")
                name = k
                desc = param.get("desc", "")
                if param.get("default") is not None:
                    desc = desc + " (default `" + json.dumps(param["default"]) + "`)"
                    required = False
                if "long_desc" in param:
                    desc = desc + " " + param["long_desc"]
                if required:
                    name = "*" + name
                lua_params.append(LuaParam(name, typestr, desc))
            section.body.extend(format_params(lua_params, 6))
        section.body.append("\n")
    return section


def convert_md_link(match):
    text = match[1]
    dest = match[2]
    if dest.startswith("#"):
        return f"|{dest[1:]}|"
    else:
        return text


def convert_markdown_to_vimdoc(lines: List[str]) -> List[str]:
    while lines[0] == "\n":
        lines.pop(0)
    while lines[-1] == "\n":
        lines.pop()
    i = 0
    code_block = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            code_block = not code_block
            if code_block:
                lines[i] = ">\n"
            else:
                lines[i] = "<\n"
        else:
            if code_block:
                lines[i] = 4 * " " + line
            else:
                line = MD_LINK_PAT.sub(convert_md_link, line)
                line = MD_BOLD_PAT.sub(lambda x: x[1], line)
                line = MD_LINE_BREAK_PAT.sub("", line)

                if len(line) > 80:
                    new_lines = wrap(line)
                    lines[i : i + 1] = new_lines
                    i += len(new_lines)
                    continue
                else:
                    lines[i] = line
        i += 1
    return lines


def convert_md_section(
    filename: str,
    start_pat: str,
    end_pat: str,
    section_name: str,
    section_tag: str,
    inclusive: Tuple[bool, bool] = (False, False),
) -> VimdocSection:
    lines = read_section(filename, start_pat, end_pat, inclusive)
    lines = convert_markdown_to_vimdoc(lines)
    return VimdocSection(section_name, section_tag, lines)


def generate_vimdoc():
    doc = Vimdoc("overseer.txt", "overseer")
    funcs = parse_functions(os.path.join(ROOT, "lua", "overseer", "init.lua"))
    doc.sections.extend(
        [
            get_commands_vimdoc(),
            get_options_vimdoc(),
            get_highlights_vimdoc(),
            VimdocSection("API", "overseer-api", render_api_vimdoc("overseer", funcs)),
            get_components_vimdoc(),
            convert_md_section(
                os.path.join(DOC, "reference.md"),
                "^## Parameters",
                "^#",
                "Parameters",
                "overseer-params",
            ),
            convert_md_section(
                os.path.join(DOC, "guides.md"),
                "^## Actions",
                "^#",
                "Actions",
                "overseer-actions",
            ),
        ]
    )

    # TODO check for missing tags
    with open(VIMDOC, "w", encoding="utf-8") as ofile:
        ofile.writelines(doc.render())


def update_md_api():
    funcs = parse_functions(os.path.join(ROOT, "lua", "overseer", "init.lua"))
    lines = ["\n"] + render_api_md(funcs) + ["\n"]
    replace_section(
        os.path.join(DOC, "reference.md"),
        r"^<!-- API -->$",
        r"^<!-- /API -->$",
        lines,
    )


def update_md_toc(filename: str):
    toc = ["\n"] + generate_md_toc(filename) + ["\n"]
    replace_section(
        filename,
        r"^<!-- TOC -->$",
        r"^<!-- /TOC -->$",
        toc,
    )


def add_md_link_path(path: str, lines: List[str]) -> List[str]:
    ret = []
    for line in lines:
        ret.append(re.sub(r"(\(#)", "(" + path + "#", line))
    return ret


def update_readme_toc():
    toc = generate_md_toc(README)

    def get_toc(filename: str) -> List[str]:
        subtoc = generate_md_toc(os.path.join(DOC, filename))
        return add_md_link_path("doc/" + filename, subtoc)

    tutorials_toc = get_toc("tutorials.md")
    guides_toc = get_toc("guides.md")
    reference_toc = get_toc("reference.md")
    explanation_toc = get_toc("explanation.md")
    third_party_toc = get_toc("third_party.md")
    recipes_toc = get_toc("recipes.md")

    def add_subtoc(title: str, lines: List[str]):
        for i, line in enumerate(toc):
            if line.strip().startswith(f"- [{title}]"):
                toc[i + 1 : i + 1] = indent(
                    # Only add subtoc one level deep
                    [line for line in lines if not line.startswith(" ")],
                    2,
                )
                return
        raise Exception(f"could not find README section {title} in TOC")

    add_subtoc("Tutorials", tutorials_toc)
    add_subtoc("Guides", guides_toc)
    add_subtoc("Explanation", explanation_toc)
    add_subtoc("Third-party integrations", third_party_toc)
    add_subtoc("Recipes", recipes_toc)
    add_subtoc("Reference", reference_toc)

    replace_section(
        README,
        r"^## Tutorials$",
        r"^#",
        ["\n"] + tutorials_toc + ["\n"],
    )
    replace_section(
        README,
        r"^## Guides$",
        r"^#",
        ["\n"] + guides_toc + ["\n"],
    )
    replace_section(
        README,
        r"^## Reference$",
        r"^#",
        ["\n"] + reference_toc + ["\n"],
    )
    replace_section(
        README,
        r"^## Explanation$",
        r"^#",
        ["\n"] + explanation_toc + ["\n"],
    )
    replace_section(
        README,
        r"^## Third-party integrations$",
        r"^#",
        ["\n"] + third_party_toc + ["\n"],
    )
    replace_section(
        README,
        r"^## Recipes$",
        r"^#",
        ["\n"] + recipes_toc + ["\n"],
    )
    replace_section(
        README,
        r"^<!-- TOC -->$",
        r"^<!-- /TOC -->$",
        ["\n"] + toc + ["\n"],
    )


def update_reference_md():
    update_commands_md()
    update_md_api()
    update_highlights_md()
    components_toc = add_md_link_path(
        "components.md", generate_md_toc(os.path.join(DOC, "components.md"))
    )
    reference_doc = os.path.join(DOC, "reference.md")
    toc = ["\n"] + generate_md_toc(reference_doc) + ["\n"]
    idx = toc.index("- [Components](#components)\n")
    toc[idx+1:idx+1] = ["  " + line for line in components_toc]
    replace_section(
        reference_doc,
        r"^<!-- TOC -->$",
        r"^<!-- /TOC -->$",
        toc,
    )
    replace_section(
        reference_doc,
        r"^<!-- TOC.components -->$",
        r"^<!-- /TOC.components -->$",
        ["\n"] + components_toc + ["\n"],
    )


def main() -> None:
    """Update the README"""
    update_config_options()
    update_components_md()
    update_parsers_md()
    update_md_toc(os.path.join(DOC, "components.md"))
    update_reference_md()
    update_md_toc(os.path.join(DOC, "tutorials.md"))
    update_md_toc(os.path.join(DOC, "guides.md"))
    update_md_toc(os.path.join(DOC, "explanation.md"))
    update_md_toc(os.path.join(DOC, "third_party.md"))
    update_md_toc(os.path.join(DOC, "recipes.md"))
    update_readme_toc()
    generate_vimdoc()
