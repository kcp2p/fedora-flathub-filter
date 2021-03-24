#!/bin/bash

tempdir=$(cd "$1" && pwd)
url=$2
dest=$3

export HOME=$1
export XDG_DATA_HOME=$tempdir/.local/share
export XDG_DATA_DIRS=$XDG_DATA_HOME/flatpak/exports/share:/var/lib/flatpak/exports/share:/usr/local/share:/usr/share

flatpak --user --no-gpg-verify remote-add download "$url"
flatpak remote-ls download --columns="ref,runtime" > "$dest"-remote-ls.txt
flatpak update --appstream download
if [[ "$url" = oci+https:* ]] ; then
    cp "$XDG_DATA_HOME/flatpak/appstream/download/x86_64/appstream.xml.gz" "$dest"-appstream.xml.gz
else
    cp "$XDG_DATA_HOME/flatpak/appstream/download/x86_64/active/appstream.xml.gz" "$dest"-appstream.xml.gz
fi




