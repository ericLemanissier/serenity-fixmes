#!/usr/bin/env python3

# There are about 2000 commits in a month, in the recent time.
# That's about 60 commits per day.
# 1 second per grep invocation would be quite slow, let's assume that.
# The other parts of this script are negligible.
# So this script consumes about 1 minute of CPU time per day.
# That's acceptable. (Less pessimistic numbers predict about 15 seconds per day.)

import datetime
import json
import os
import subprocess
import sys
import time
from typing import Callable, TypeAlias

SERENITY_DIR = "serenity/"
FILENAME_CSV = "tagged_history.csv"
FILENAME_CACHE = "cache_v4.json"
FILENAME_CACHE_COLD = "cache_cold_v4.json"
# Save the cache only every X commits, instead of after every commit.
SAVE_CACHE_INV_FREQ = 200

Cache: TypeAlias = dict[str, tuple[int, int, int]]
OutputNode: TypeAlias = dict[str, str | int | list]

class Node:   # noqa: too-few-public-methods
    name: str
    children: list['Node']
    todos: int = 0
    locs: int = 0

    def __init__(self, name: str, children: list['Node']):
        self.name = name
        self.children = children


def fetch_new() -> None:
    subprocess.run(["git", "-C", SERENITY_DIR, "fetch"], check=True)


def determine_commit_and_date_list() -> list[tuple[str, int]]:
    result = subprocess.run(
        [
            "git",
            "-C",
            SERENITY_DIR,
            "log",
            "origin/master",
            "--reverse",
            "--format=%H %ct",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    lines: list[str] = result.stdout.split("\n")
    assert lines[-1] == "", result.stdout[-10:]
    lines.pop()
    assert lines[-1] != "", result.stdout[-10:]
    print(f"Repo has {len(lines)} commits.")
    entries: list[tuple[str, int]] = []
    for line in lines:
        parts = line.split(" ")
        assert len(parts) == 2, line
        entries.append((parts[0], int(parts[1])))
    return entries


def load_cache() -> Cache:
    if not os.path.exists(FILENAME_CACHE):
        with open(FILENAME_CACHE_COLD, "r", encoding="utf-8") as cache_file:
            cache = json.load(cache_file)
        # Make sure it's writable:
        save_cache(cache)
    else:
        with open(FILENAME_CACHE, "r", encoding="utf-8") as cache_file:
            cache = json.load(cache_file)
    return cache


def save_cache(cache: Cache) -> None:
    with open(FILENAME_CACHE, "w", encoding="utf-8") as cache_file:
        json.dump(cache, cache_file, sort_keys=True, separators=(",", ":"), indent=0)


def count_fixmes_here() -> int:
    # We don't use "-n" here, since we don't use that information, and less output should make it marginally faster.
    # That is also why we use "-h".
    result = subprocess.run(
        ["git", "-C", SERENITY_DIR, "grep", "-IiEh", "FIXME|TODO"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode in [0, 1]
    lines: list[str] = result.stdout.split("\n")
    assert lines[-1] == "", result.stdout[-10:]
    return len(lines)


def count_deprecated_strings_here() -> int:
    # We don't use "-n" here, since we don't use that information, and less output should make it marginally faster.
    # That is also why we use "-h".
    result = subprocess.run(
        ["git", "-C", SERENITY_DIR, "grep", "-IEh", "DeprecatedFlyString"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode in [0, 1]
    lines: list[str] = result.stdout.split("\n")
    assert lines[-1] == "", result.stdout[-10:]
    return len(lines)


def count_deprecated_files_here() -> int:
    # We don't use "-n" here, since we don't use that information, and less output should make it marginally faster.
    # That is also why we use "-h".
    result = subprocess.run(
        ["git", "-C", SERENITY_DIR, "grep", "-IFh", "DeprecatedFile"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode in [0, 1]
    lines: list[str] = result.stdout.split("\n")
    assert lines[-1] == "", result.stdout[-10:]
    return len(lines)


def lookup_commit(commit: str, date: int, cache: Cache) -> dict[str, int | str]:
    if commit in cache:
        fixmes, deprecated_strings, deprecated_files = cache[commit]
    else:
        time_start = time.time()
        subprocess.run(["git", "-C", SERENITY_DIR, "checkout", "-q", commit], check=True)
        fixmes = count_fixmes_here()
        deprecated_strings = count_deprecated_strings_here()
        deprecated_files = count_deprecated_files_here()
        time_done_counting = time.time()
        cache[commit] = fixmes, deprecated_strings, deprecated_files
        if len(cache) % SAVE_CACHE_INV_FREQ == 0:
            print("    (actually saving cache)")
            save_cache(cache)
        time_done_saving = time.time()
        print(
            f"Extended cache by {commit} (now containing {len(cache)} keys) (counting took {time_done_counting - time_start}s, saving took {time_done_saving - time_done_counting}s)"
        )
    return {
        "commit": commit,
        "unix_timestamp": date,
        "human_readable_time": datetime.datetime.fromtimestamp(date).strftime("%Y-%m-%d %H:%M:%S"),
        "fixmes": fixmes,
        "deprecated_strings": deprecated_strings,
        "deprecated_files": deprecated_files,
    }


def write_graphs(most_recent_commit: int) -> None:
    time_now = int(time.time())
    print(f"Plotting with {time_now=}")
    time_last_week = time_now - 3600 * 24 * 7
    time_last_month = time_now - 3600 * 24 * 31  # All months are 31 days. Right.
    time_last_year = time_now - 3600 * 24 * 366  # All years are 366 days. Right.
    timed_plot_commands = ""

    # *Some* versions of gnuplot use year 2000 as epoch, and in those versions *only*
    # the xrange is interpreted relative to this. Aaargh!
    output = subprocess.check_output(['gnuplot', '--version']).split()
    assert output[0] == b"gnuplot"
    if int(output[1].split(b".")[0]) < 5:
        gnuplot_stupidity = 946684800
    else:
        gnuplot_stupidity = 0

    if most_recent_commit > time_last_week:
        timed_plot_commands += f"""
            set output "output_week.png"; plot [{time_last_week - gnuplot_stupidity}:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:2 with lines title "FIXMEs and TODOs";
            set output "output_week_depstr.png"; plot [{time_last_week - gnuplot_stupidity}:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:3 with lines title "DeprecatedFlyStrings";
        """
    else:
        print(f"WARNING: No commits in the last week?! (now={time_now}, a week ago={time_last_week}, latest_commit={most_recent_commit})")
    if most_recent_commit > time_last_month:
        timed_plot_commands += f"""
            set output "output_month.png"; plot [{time_last_month - gnuplot_stupidity}:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:2 with lines title "FIXMEs and TODOs";
            set output "output_month_depstr.png"; plot [{time_last_month - gnuplot_stupidity}:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:3 with lines title "DeprecatedFlyStrings";
        """
    else:
        print(f"ERROR: No commits in the last month?! (now={time_now}, a month ago={time_last_month}, latest_commit={most_recent_commit})")
        raise AssertionError()
    if most_recent_commit > time_last_year:
        timed_plot_commands += f"""
            set output "output_year.png"; plot [{time_last_year - gnuplot_stupidity}:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:2 with lines title "FIXMEs and TODOs";
            set output "output_year_depstr.png"; plot [{time_last_year - gnuplot_stupidity}:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:3 with lines title "DeprecatedFlyStrings";
            set output "output_year_depfil.png"; plot [{time_last_year - gnuplot_stupidity}:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:4 with lines title "DeprecatedFile";
        """
    else:
        print(f"ERROR: No commits in the last YEAR?! (now={time_now}, a year ago={time_last_year}, latest_commit={most_recent_commit})")
        raise AssertionError()
    subprocess.run(
        [
            "gnuplot",
            "-e",
            f"""
                set terminal png size 1700,300 enhanced;
                set xdata time;
                set timefmt "%s";
                set xlabel "Time";
                set format x "%Y-%m-%d %H:%M";
                set ylabel "Count";
                set datafile separator ",";
                set output "output_total.png";
                plot [:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:2 with lines title "FIXMEs and TODOs";
                set output "output_total_depstr.png";
                plot [:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:3 with lines title "DeprecatedFlyStrings";
                set output "output_total_depfil.png";
                plot [:{time_now - gnuplot_stupidity}] "tagged_history.csv" using 1:4 with lines title "DeprecatedFile";
                {timed_plot_commands}
            """,
        ],
        check=True,
    )


def generate_flame_graph() -> None:   # noqa: MC0001
    flamegraph = Node(name=".", children=[])

    def get_node(path: str) -> Node | None:
        node = flamegraph
        for file_name in os.path.normpath(path).split(os.path.sep):
            if file_name in [".git", ".devcontainer"]:
                return None
            for child in node.children:
                if child.name == file_name:
                    node = child
                    break
            else:
                new_node = Node(name=file_name, children=[])
                node.children.append(new_node)
                node = new_node
        return node

    previous_wd = os.getcwd()
    os.chdir(SERENITY_DIR)

    ratios_list = []

    for root, dirs, files in os.walk(".", topdown=False):
        for name in files:
            full_name = os.path.join(root, name)
            if not any(name.endswith(ext) for ext in [".h", ".c", ".cpp", ".html", ".js", ".sh", "*.txt", "*.cmake"]):
                continue
            if full_name in ["./Tests/LibWeb/Layout/input/html-encoding-detection-crash.html",
                             "./Tests/LibWeb/Layout/input/utf-16-be-xhtml-file-should-decode-correctly.html"]:
                continue
            node = get_node(full_name)
            if not node:
                continue
            todos = 0
            locs = 0
            with open(full_name, "rt", encoding="utf-8") as file_p:
                try:
                    for line in file_p:
                        line = line.strip().upper()
                        todos += line.count("FIXME") + line.count("TODO")
                        if line and not line.startswith("//"):
                            locs += 1
                except UnicodeDecodeError as err:
                    print(f"Error decodingfile {full_name}: {err}")
                    continue
            node.todos = todos
            node.locs = locs

            if todos and locs:
                if full_name.startswith("./"):
                    full_name = full_name[2:]
                ratios_list.append([
                    todos,
                    locs,
                    todos / locs,
                    full_name
                ])

        for name in dirs:
            node = get_node(os.path.join(root, name))
            if not node:
                continue
            node.todos = sum(child.todos for child in node.children)
            node.locs = sum(child.locs for child in node.children)
    os.chdir(previous_wd)

    def set_value(calculate: Callable[[Node], int], node: Node) -> OutputNode:
        children = []
        for child in node.children:
            new_child = set_value(calculate, child)
            if new_child["value"] or new_child.get("children", []):
                children.append(new_child)
        new_node: OutputNode = {
            "name": node.name,
            "value": calculate(node)
        }
        if children:
            new_node["children"] = children
        return new_node

    todo_graph = set_value(lambda node: node.todos, flamegraph)
    with open("todo.json", "wt", encoding="utf-8") as file:
        json.dump(todo_graph, file, separators=(",", ":"))

    loc_graph = set_value(lambda node: node.locs, flamegraph)
    with open("loc.json", "wt", encoding="utf-8") as file:
        json.dump(loc_graph, file, separators=(",", ":"))

    with open("ratio.csv", "wt", encoding="utf-8") as file:
        file.write("TODO,LOC,TODO/LOC,FILE\n")
        file.writelines(f"{e[0]},{e[1]},{e[2]:.2%},{e[3]}\n" for e in ratios_list)


def run() -> None:
    if not os.path.exists(SERENITY_DIR + "README.md"):
        print(
            f"Can't find Serenity checkout at {SERENITY_DIR} , please make sure that a reasonably recent git checkout is at that location."
        )
        sys.exit(1)
    fetch_new()
    commits_and_dates = determine_commit_and_date_list()
    print(f"Newest commits are: ...{commits_and_dates[-3 :]}")
    current_time = int(time.time())
    print(
        f"(The time is {current_time}, the last commit is {current_time - commits_and_dates[-1][1]}s ago)"
    )
    cache = load_cache()
    tagged_commits = [
        lookup_commit(commit, date, cache) for commit, date in commits_and_dates
    ]
    save_cache(cache)
    with open(FILENAME_CSV, "w", encoding="utf-8") as csv_file:
        for entry in tagged_commits:
            csv_file.write(f"{entry['unix_timestamp']},{entry['fixmes']},{entry['deprecated_strings']},{entry['deprecated_files']}\n")
    write_graphs(commits_and_dates[-1][1])

    generate_flame_graph()


if __name__ == "__main__":
    run()
