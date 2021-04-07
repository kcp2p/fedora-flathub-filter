#!/bin/bash

set -e

error() {
    if [ -t 2 ] ; then
        echo $'\e[31m\e[1mERROR\e[0m:'" $*" 1>&2
    else
        echo "ERROR: $*" 1>&2
    fi
    exit 1
}

info() {
    local n
    if [ "$1" = "-n" ] ; then
        n=-n
        shift
    fi

    if [ -t 2 ] ; then
        echo $n $'\e[34m\e[1mINFO\e[0m:'" $*" 1>&2
    else
        echo $n "INFO: $*" 1>&2
    fi
}

toplevel=$(git rev-parse --show-toplevel)
update_py=$toplevel/update.py

[ $# = 1 ] || error "Usage: merge.sh PR_NUMBER"
pr=$1

branch=$(git branch --show-current)
continue=false
if [ "$pr" = "continue" ] ; then
    continue=true
    if [[ $branch =~ merge_pr_[0-9]+ ]] ; then
        pr=${branch#merge_pr_}
    else
        error "Not on an in-progress merge branch"
    fi
else
    info -n "Updating origin ... "
    git fetch origin
    echo "done" 2>&1

    ### Sanity checks

    [ "$branch" == main ] || error "Must be on the main branch"

    if ! git merge-base --is-ancestor origin/main main ; then
        error "origin/main has commits not in local main branch"
    fi

    git diff-index --quiet HEAD -- || error "Uncommitted changes"

    if git rev-parse -q --verify "refs/heads/merge_pr_$pr" ; then
        error "Branch merge_pr_$pr already exists, please delete"
    fi
fi

info -n "Getting pull request title ... "
title=$(curl -s "https://pagure.io/api/0/fedora-flathub-filter/pull-request/$pr" | jq -r .title)
echo "$title"

### Download

if ! $continue ; then
    git fetch origin "pull/$pr/head:merge_pr_$pr"
    git switch "merge_pr_$pr"
fi

delete_branch() {
    git switch -q main
    git branch -q -D "merge_pr_$pr"
}
trap delete_branch EXIT

### Rebase

if ! $continue ; then
    info "Rebasing pull request onto main"
    if "$update_py" --quiet --rebase=main ; then
        :
    else
        if [ $? = 42 ] ; then
            info "After resolving conflicts, run ./update.py --merge-continue"
            trap - EXIT
        fi
        exit $?
    fi
fi

### And merge

info "Merging"

git switch -q main
git merge --no-ff -m "Merge #$pr \`$title\`" "merge_pr_$pr"

info "Successfully merged, please inspect result and run 'git push origin main'"
