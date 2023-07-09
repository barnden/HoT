from os import listdir
from pathlib import Path
from sys import argv
import re
from functools import reduce
from operator import getitem

class GameElement:
    def __init__(self, file=None):
        self.file = str(file)

    def as_str(self, delimiter=","):
        return delimiter.join([str(getattr(self, slot, None)) for slot in self.__slots__])

    def __str__(self):
        return self.as_str()

class Monster(GameElement):
    __slots__ = "file", "damage", "radius", "health", "hitsToKill"

class Item(GameElement):
    __slots__ = "file", "slot", "name", "desc", "grade", "price", "prereqs_any", "prereqs_and", "exclude_any"

class TSCNResource:
    def __init__(self, resource_type, *args, **attr):
        self.resource_type = resource_type
        self.entries = {}

        if attr is not None:
            for k, v in attr.items():
                setattr(self, k, v)

    def query(self, path: str | list, default=None):
        if isinstance(path, str):
            path = path.split("/")

        if not isinstance(path, list) or len(path) == 0:
            return default

        path = list(map(lambda x: x if not x.isnumeric() else int(x), path))

        if hasattr(self, path[0]):
            return reduce(getitem, path, self)
        if path[0] in self.entries:
            return reduce(getitem, path, self.entries)

        return default

    def __str__(self):
        # Get all attrs not "resource_type"
        attrs = set(dir(self)) - set(["resource_type"])

        # Remove all attrs starting with "__" as they are either built-in or intentionally marked to be private
        # Remove all callable attrs
        attrs = [attr for attr in attrs if not attr.startswith("__") and not callable(getattr(self, attr))]

        # Create list of [key: value] strings from set attrs set
        attrs = [f"{attr}: {getattr(self, attr, None)!r}" for attr in attrs]

        # Return human-readable string
        return f"{self.__class__.__name__}(resource_type={self.resource_type!r}{', ' if len(attrs) else ''}{', '.join(attrs)})"

    def __getitem__(self, key):
        return getattr(self, key)

class Selector:
    @staticmethod
    def parse(string):
        try:
            type = re.match("^.*?(?=\[|$)", string)[0]
        except TypeError:
            raise ValueError("[Selector]: invalid selector type")

        try:
            attrs = {}
            queries = re.findall("\[([^!<>=\s]+)\s?([!<>=]+)\s?(.*)\]", string)

            for query in queries:
                attr, *relation = query

                attrs[attr] = relation
        except TypeError:
            attrs = None

        return { type: attrs }

class TSCN:
    """
    Documentation: https://docs.godotengine.org/en/stable/contributing/development/file_formats/tscn.html

    Given a Godot TSCN file, parse its data into a Python object.
    """

    def __init__(self, path):
        self.resources = []

        # https://docs.godotengine.org/en/stable/contributing/development/file_formats/tscn.html#entries-inside-the-file
        # resource_type is one of the following
        types = ["node", "ext_resource", "sub_resource", "connection"]
        for type in types:
            setattr(self, type, [])

        self.parse_file(path)

    def parse_file(self, path: Path):
        with open(path, "r") as file:
            rsc = None

            data = file.read()
            lines = re.findall(r"(?:^\[(\w+)(.*?)\]$|^([\w/]+)\s*=\s*(\w+\(.+?\)|\".+?\"|\[.+?\]|\S+)$)", data, flags=re.DOTALL | re.MULTILINE)

            for line in lines:
                resource_type, rest, key, value = line

                if len(resource_type):
                    # Finds all pairs matching "key=value"
                    pairs = re.findall(r"([\w/]+)\s*=\s*(\w+\(.+?\)|\".+?\"|\[.+?\]|\S+)", rest, flags=re.DOTALL)

                    # https://docs.godotengine.org/en/stable/contributing/development/file_formats/tscn.html#file-structure
                    # Create TSCNResource entry
                    rsc = TSCNResource(resource_type, **{k: v.replace('"', '') for (k, v) in pairs})

                    # File should begin with file descriptor which has heading of resource type "gd_scene"
                    if resource_type == "gd_scene":
                        self.scene = rsc
                    # Otherwise, they must be of a certain type
                    else:
                        setattr(self, resource_type, getattr(self, resource_type) + [rsc])

                    self.resources.append(rsc)
                    continue

                # Otherwise, we are adding key-value pairs as entries of the resource node
                value = value.replace("\n", "\\n")
                value = re.sub(r"^\"(.*)\"$", r"\1", value)

                # Note: Some descriptions begin with a plus symbol to denote positive stats
                #       However, some spreadsheet software interprets this as an equation,
                #       use string equations to get around this.
                if value.startswith("+"):
                    value = f'="{value}"'

                rsc.entries[key] = value

    def select(self, selectors: str | dict):
        if isinstance(selectors, str):
            selectors = Selector.parse(selectors)

        def predicate(obj):
            if obj.resource_type not in selectors:
                return False

            if not (selector := selectors[obj.resource_type]):
                return True

            for path, relation in selector.items():
                if (lhs := obj.query(path)) is None:
                    return False

                op, rhs = relation

                try:
                    lhs = int(lhs)
                    rhs = int(rhs)

                    match op:
                        case "=" | "==":
                            return lhs == rhs
                        case ">=":
                            return lhs >= rhs
                        case "<=":
                            return lhs <= rhs
                        case ">":
                            return lhs > rhs
                        case "<":
                            return lhs < rhs
                        case "!=":
                            return lhs != rhs

                    return False
                except ValueError:
                    match op:
                        case "=" | "==":
                            return lhs == rhs
                        case "!=":
                            return lhs != rhs
                        case _:
                            return False

        resources = [resource for resource in self.resources if predicate(resource)]

        if len(resources):
            return resources

        return None

def parse_monsters(base_path: Path, output_path: Path):
    monster_path = base_path.joinpath("Monsters").absolute()

    monsters = []

    for path in listdir(monster_path):
        if not path.endswith(".tscn"):
            continue

        tscn = TSCN(monster_path.joinpath(path))

        monster = Monster(path.split('.', 1)[0])

        if nodes := tscn.select("node[name=AreaOfEffect]"):
            query = nodes[0].query

            monster.damage = query("ApplyDamage", "0")
            monster.radius = query("Radius", "0")

        if nodes := tscn.select("node[name=Health]"):
            query = nodes[0].query

            monster.health = nodes[0].query("StartHealth", "0")
            monster.hitsToKill = nodes[0].query("KillAfterNumberOfHits", "N/A")

        monsters.append(monster)

    with open(output_path.joinpath("monsters.tsv"), "w") as output:
        output.write("\t".join(Monster.__slots__))
        output.write("\n")
        output.write("\n".join([x.as_str("\t") for x in monsters]))

def parse_items(base_path: Path, output_path: Path):
    item_path = base_path.joinpath("Items").absolute()

    items = []
    slots = ["Head", "Neck", "Ring", "Body", "Feet", "Gloves", "Consumable"]

    for path in listdir(item_path):
        if not path.endswith(".tscn"):
            continue

        tscn = TSCN(item_path.joinpath(path))

        item = Item(path.split('.', 1)[0])

        if nodes := tscn.select("node[script=ExtResource( \"1\" )]"):
            query = nodes[0].query

            item.grade = query("Grade", "1")
            item.name = query("Name", "")
            item.desc = query("Description", "")
            item.price = query("GoldPrice", "")

            item.prereqs_any = query("AnyTagNeeded", "")
            item.prereqs_and = query("AndAnyTagNeeded", "")
            item.exclude_any = query("ExcludeWithAnyTagsActive", "")

            # Note: The devs use naming convention like itm_h to denote an item for the head slot
            #       However, this does not appear to be reliable.
            #       For example, as of 9 July 2023 "SparkingTips" has file name "itm_h_SparkingTips"
            #       but has SlotType=5 (Gloves).
            if (slot := query("SlotType", "0")).isnumeric():
                item.slot = slots[int(slot)]

        items.append(item)

    with open(output_path.joinpath("items.tsv"), "w") as output:
        output.write("\t".join(Item.__slots__))
        output.write("\n")
        output.write("\n".join([x.as_str("\t") for x in items]))

if __name__ == "__main__":
    base_path = Path("../")
    output_path = Path("./output")
    output_path.mkdir(exist_ok=True)

    if len(argv) > 1:
        base_path = Path(argv[1])

    base_path = base_path.joinpath("GameElements")

    parse_monsters(base_path, output_path)
    parse_items(base_path, output_path)