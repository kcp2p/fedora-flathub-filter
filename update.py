#!/usr/bin/python
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
import requests
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from textwrap import dedent

import click

import gi
gi.require_version('AppStreamGlib', '1.0')
from gi.repository import AppStreamGlib, GLib  # noqa: E402


source_path = Path(sys.argv[0]).parent
cache_path = source_path / "cache"
tools_path = source_path / "tools"
is_verbose = False
is_quiet = False


def info(*args):
    if not is_quiet:
        print(click.style("INFO", fg="blue", bold=True) + ":",
              *args, file=sys.stderr)


def verbose(*args):
    if is_verbose:
        print(click.style("DEBUG", bold=True) + ":",
                *args, file=sys.stderr)


def warning(*args):
    if not is_quiet:
        print(click.style("WARNING", fg="red", bold=True) + ":",
            *args, file=sys.stderr)


def error(*args):
    print(click.style("ERROR", fg="red", bold=True) + ":",
          *args, file=sys.stderr)
    sys.exit(1)


def id_from_ref(ref):
    ref_split = ref.split("/")
    if ref_split[0] == "app":
        return ref_split[1]
    else:
        assert ref_split[0] == "runtime"
        return ref_split[1] + "/" + ref_split[3]


class Component:
    fields = {
        "name": "Name",
        "homepage": "Homepage",
        "license": "License",
        "runtime": "Runtime",
        "downloads": "Downloads (new last month)",
        "fedora_flatpak": "Fedora Flatpak",
        "comments": "Comments",
        "include": "Include"
    }
    load_fields = ("comments", "include")

    def __init__(self, component_id):
        self.id = component_id
        self.name = None
        self.homepage = None
        self.license = None
        self.runtime = None
        self.download_count = 0
        self.download_rank = 0
        self.fedora_flatpak = False
        self.comments = ""
        self.include = ""

    @property
    def downloads(self):
        return f"{self.download_count} (rank: {self.download_rank})"

    def update_from_as_app(self, app):
        self.name = app.get_name()
        homepage = app.get_url_item(AppStreamGlib.UrlKind.HOMEPAGE)
        if homepage:
            self.homepage = homepage
        self.license = app.get_project_license()

    def _merge_field(self, base, other, field_name):
        new = getattr(other, field_name)
        if not base or new != getattr(base, field_name):
            setattr(self, field_name, new)

    def merge(self, base, other):
        for field_name in self.load_fields:
            self._merge_field(base, other, field_name)

    def dump(self, file):
        print(f"[{self.id}]", file=file)
        for name, pretty in self.fields.items():
            value = getattr(self, name)
            if value is not None:
                if value == "":
                    # Avoid trailing space
                    print(pretty + ":", file=file)
                else:
                    print(pretty + ":", value, file=file)


def download_remote_data(remote_url, short, force_download=False):
    base = cache_path / short
    appstream = cache_path / f'{short}-appstream.xml.gz'
    remote_ls = cache_path / f'{short}-remote-ls.txt'

    if not (appstream.exists() and remote_ls.exists()):
        force_download = True

    if not force_download:
        stat = remote_ls.stat()
        if stat:
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            if datetime.now(timezone.utc) - modified > timedelta(days=1):
                force_download = True

    if force_download:
        info(f"{short}: Downloading data from {remote_url}")
        with tempfile.TemporaryDirectory() as tempdir:
            try:
                subprocess.check_call(
                    [tools_path / "download-remote-data.sh", tempdir, remote_url, base]
                )
            except subprocess.CalledProcessError:
                try:
                    appstream.unlink()
                except FileNotFoundError:
                    pass
                try:
                    remote_ls.unlink()
                except FileNotFoundError:
                    pass

                error("Failed to download data")
    else:
        verbose(f"{short}: using cached remote data")

    return appstream, remote_ls


def load_remote_components(remote_url, short, force_download=False):
    components = {}
    appstream, remote_ls = download_remote_data(remote_url, short,
                                                force_download=force_download)

    with open(remote_ls) as f:
        for line in f:
            fields = line.strip().split()
            component_id = id_from_ref(fields[0])
            component = Component(component_id)
            if len(fields) > 1:
                runtime_parts = fields[1].split("/")
                component.runtime = runtime_parts[0] + "/" + runtime_parts[2]
            components[component.id] = component

    with gzip.open(str(appstream), 'rb') as f:
        store = AppStreamGlib.Store()
        store.from_bytes(GLib.Bytes(f.read()), None)

    for as_app in store.get_apps():
        bundle = as_app.get_bundle_default()
        component_id = id_from_ref(bundle.get_id())
        component = components.get(component_id)
        if component:
            component.update_from_as_app(as_app)
        else:
            warning(f"{short}: {component_id} in appstream not in remote-ls")

    return components


def get_flathub_stats(date):
    cache_file = cache_path / f'flathub-downloads-{date.year}-{date.month:02}-{date.day:02}.json'
    if cache_file.exists():
        with open(cache_file, 'r') as f:
            return json.load(f)

    url = f'https://flathub.org/stats/{date.year}/{date.month:02}/{date.day:02}.json'
    info("Downloading %s", url)
    response = requests.get(url)
    response.raise_for_status()

    with open(cache_file, 'wb') as f:
        f.write(response.content)

    return response.json()


def get_flathub_totals():
    now = datetime.now() - timedelta(days=1)
    date = datetime.now() - timedelta(days=30)

    totals = defaultdict(int)
    while date < now:
        stats = get_flathub_stats(date)
        date += timedelta(days=1)
        for ref, refdata in stats['refs'].items():
            for arch, counts in refdata.items():
                # counts[0]: total downloads
                # counts[1]: delta downloads
                # counts[1] - counts[2]: approximately new downloads
                totals[ref] += counts[0] - counts[1]

    return totals


def add_components_from_path(components, path):
    if not path.exists():
        return

    component = None
    with open(path) as f:
        line_no = 0
        for line in f:
            line_no += 1
            line = line.strip()

            if line == "":
                pass
            elif line.startswith("[") and line.endswith("]"):
                if component:
                    components[component.id] = component
                    component = None

                component = Component(line[1:-1])
            else:
                if not component:
                    error(f"{path}: {line_no}: Text before first component")

                field_name_raw, value = line.split(":", 1)
                field_name = re.sub(r"\s*\([^)]*\)\s*", " ", field_name_raw)
                field_name = field_name.strip().lower().replace(" ", "_")

                if field_name not in Component.fields:
                    error(f"{path}: {line_no}: unknown key '{field_name_raw}'")

                value = value.strip()

                if field_name == "include":
                    value = value.lower()
                    if value not in ("", "yes", "no"):
                        error(f"{path}: {line_no}: include should be 'yes' or 'no', not '{value}'")

                if field_name in Component.load_fields:
                    setattr(component, field_name, value)

    if component:
        components[component.id] = component


def load_components(directory):
    components = {}
    add_components_from_path(components, directory / "apps.txt")
    add_components_from_path(components, directory / "other.txt")

    return components


def load_all_remote_components(force_download=False):
    return (load_remote_components('https://flathub.org/repo', 'flathub',
                                   force_download=force_download),
            load_remote_components('oci+https://registry.fedoraproject.org/', 'fedora',
                                   force_download=force_download))


def update_report(input_dir, delta_from_dir, delta_to_dir, output_dir, force_download=False):
    flathub_components, fedora_components = \
        load_all_remote_components(force_download=force_download)

    for fedora_component in fedora_components.values():
        flathub_component = flathub_components.get(fedora_component.id)
        if flathub_component:
            flathub_component.fedora_flatpak = True

    flathub_totals = get_flathub_totals()

    input_components = load_components(input_dir)
    delta_from_components = delta_from_dir and load_components(delta_from_dir)
    delta_to_components = delta_to_dir and load_components(delta_to_dir)

    filters = []

    app_rank = 1
    other_rank = 1
    with open(output_dir / "apps.txt.new", "w") as apps, \
         open(output_dir / "other.txt.new", "w") as other:
        for component_id in sorted(flathub_components.keys(),
                                   key=lambda short_id: (flathub_totals[short_id], short_id),
                                   reverse=True):
            component = flathub_components.get(component_id)
            component.download_count = flathub_totals[component_id]

            input_component = input_components.get(component_id)
            if input_component:
                component.merge(None, input_component)

            delta_from_component = delta_from_components and delta_from_components.get(component_id)
            delta_to_component = delta_to_components and delta_to_components.get(component_id)
            if delta_from_component and delta_to_component:
                component.merge(delta_from_component, delta_to_component)

            if "/" not in component_id:
                component.download_rank = app_rank

                if app_rank > 1:
                    print(file=apps)
                component.dump(file=apps)

                app_rank += 1
            else:
                component.download_rank = other_rank

                if other_rank > 1:
                    print(file=other)
                component.dump(file=other)

                other_rank += 1

            if component.include == "yes":
                if component.runtime:
                    runtime_component = flathub_components.get(component.runtime)
                    if not runtime_component or runtime_component.include != "yes":
                        warning(f"{component_id}: required runtime '{runtime_id}' not included")

                parts = component_id.split("/")
                if len(parts) == 1:
                    filters.append(parts[0])
                else:
                    filters.append("runtime/" + parts[0] + "/*/" + parts[1])

    with open(output_dir / "filter.txt.new", "w") as f:
        f.write(dedent("""\
            # Autogenerated, do not edit
            # See https://pagure.io/fedora-flathub-filter
            #
            # Deny by default
            deny *
            """))
        for filt in sorted(filters):
            f.write("allow " + filt + "\n")

    os.rename(output_dir / "apps.txt.new", output_dir / "apps.txt")
    os.rename(output_dir / "other.txt.new", output_dir / "other.txt")
    os.rename(output_dir / "filter.txt.new", output_dir / "filter.txt")


@click.command()
@click.option(
    "--input-dir", metavar="DIR", default=str(source_path),
    help="Directory to read app.txt and report.txt from"
)
@click.option(
    "--delta-from-dir", metavar="DIR",
    help="Add a delta from --delta-from-dir to delta-to-dir"
)
@click.option(
    "--delta-to-dir", metavar="DIR",
    help="Add a delta from --delta-from-dir to delta-to-dir"
)
@click.option(
    "--output-dir", metavar="DIR", default=str(source_path),
    help="Directory to write app.txt and report.txt to"
)
@click.option(
    "--cache-dir", metavar="DIR", default=str(cache_path),
    help="Directory to cache downloaded data in"
)
@click.option(
    "--force-download", is_flag=True,
    help="Force downloading of updated remote data"
)
@click.option(
    "--rebase", metavar="TARGET",
    help="Do a git rebase onto TARGET, updating apps.txt and other.txt"
)
@click.option(
    "--verbose", "-v", is_flag=True,
    help="Show debug messages"
)
@click.option(
    "--quiet", "-q", is_flag=True,
    help="Supress non-critical messages"
)
def main(
    input_dir, delta_from_dir, delta_to_dir, output_dir, cache_dir,
    force_download, rebase, quiet, verbose
):
    global cache_path, is_verbose, is_quiet
    cache_path = Path(cache_dir)
    is_verbose = verbose
    is_quiet = quiet

    if not cache_path.exists():
        os.mkdir(cache_path)

    if rebase:
        # We do the downloading upfront to honor --force-download, and show
        # any progress messages
        load_all_remote_components(force_download=force_download)
        get_flathub_totals()
        sys.exit(subprocess.call([tools_path / "rebase.sh", rebase]))

    update_report(
        Path(input_dir),
        delta_from_dir and Path(delta_from_dir),
        delta_to_dir and Path(delta_to_dir),
        Path(output_dir),
        force_download=force_download
    )


if __name__ == "__main__":
    main()
