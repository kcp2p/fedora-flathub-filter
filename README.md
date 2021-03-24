Fedora Workstation ships with a flathub remote which is filtered.
Only explicitly allowed applications and runtimes are available,
unless the user has explicitly installed the full Flatpak remote.

This repository holds data files with the status of available
downloads from Flathub,
and scripts for updating those files.

The data files are [apps.txt](apps.txt) with applications and
[other.txt](other.txt) with other downloads:
runtime, runtime extensions, and app extensions. An entry in
one of these files looks like:

```
[com.spotify.Client]
Name: Spotify
Homepage: https://www.spotify.com
License: LicenseRef-proprietary=https://www.spotify.com/us/legal/end-user-agreement/
Runtime: org.freedesktop.Platform/x86_64/20.08
Downloads (new last month): 29074 (rank: 1)
Fedora Flatpak: False
Comments: very popular. Downloads via extra-data
Include: yes
```

[filter.txt](filter.txt) is the final filter file. It shouldn't
be edited manually.

Notes:

* `Downloads (new last month)` is non-incremental downloads in the last month.
   We ignore incremental updates,
   because we don't want to count apps that are frequently updated as more popular.
   Rank is separate for applications and other downloads.
* `Comments` is free-form text explaining a value of `yes` or `no` in `Include`
* `Include` indicates a decision to include or exclude the Flatpak from Fedora.
   For now, most components will have blank values for `Include`, which means
   they will be excluded, but no decision has been made.

Updating
--------
The `update.py` script is used to update `apps.txt`, `other.txt`, and `filter.txt`.
Usage is simple. To download the latest data from Flathub and Fedora,
and update the data files, run:

```
./update.py
```

Interesting options are:
* `--verbose` show slightly more output
* `--quiet` show less output
* `--force-download` force downloading current application data,
     even if the cached data is recent.
* `--rebase=TARGET` like `git rebase TARGET`,
  but with special handling of `apps.txt` and `other.text`

The last deserves more explanation.
The big problem with the strategy of checking `apps.txt` and `other.txt` into git
is that as download statistics change, they change a *lot*.
Commits to this repository that mixed updates and substantive changes would be unreadable.

What `--rebase=TARGET` does is create a single commit on top of `TARGET`
with only changes from running `update.py`, and then replays commits not in `TARGET`,
merging changes to `apps.txt` and `other.txt` in a smart fashion.

Workflow
--------
``` sh
git clone https://pagure.io/fedora-flathub-filter
cd fedora-flathub-filter
# make a branch to work on
git checkout -b updates-2021-03-24
# add an initial commit with just update.py changes
./update.py --rebase main

# Edit, edit, edit, commit, edit, ..., commit

# update your branch with any upstream and Flathub changes
git fetch origin
git --rebase origin/main

# File your branch as a pull request
```

Guidelines
----------
* We initially want to keep the set of included applications small. We will concentrate on including:
  * The most popular applications on Flathub
  * Applications of interest to Fedora's developer target audience
  * Applications that fill a role not satisfied by any available application for Fedora.
* Once a Flathub Flatpak is included,
  it should only be excluded if there are urgent reasons to do so.
  The reason for this,
  is that users that have installed that Flatpak will have a leftover Flatpak with no update stream.
* Applications that have equivalent Fedora Flatpaks should, generally speaking,
  not be included.
  But an application shouldn't be removed if a Fedora Flatpak is subsequently created (see above.)
* Some Flatpaks on Flatpaks are wrappers
  that download the actual program via the Flatpak `extra-data` mechanism.
  If the program is coming from an established, well-known commercial entity,
  you can assume they have obtained all necessary patent and other licenses.
* Open source code hosted on Flathub needs to be checked that it doesn't contain:
  * Codecs and other potentially patent-encumbered technology that aren't shipped in Fedora.
  * Other [Forbidden Items](https://fedoraproject.org/wiki/Forbidden_items?rd=ForbiddenItems)
* As a non-lawyer,
  you should not be doing extra new research to check for patent problems.
  Some appropriate checks:
  * If the application is shipped in RPM form in Fedora,
    does Fedora do anything special to strip it down?
  * If the application is not shipped in Fedora,
    does it contain multimedia codecs? Are there any that are not shipped in Fedora?
* Keep notes in `Comments` non-speculative. Something like:
  "Contains h264, not currently shipped with Fedora" is appropriate.