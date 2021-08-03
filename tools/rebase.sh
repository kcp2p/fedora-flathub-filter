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

original_branch=$(git branch --show-current)

if [ $# == 2 ] ; then
    branch=$1
    shift
else
    branch=$original_branch
fi

[ $# == 1 ] || error "Usage: rebase.sh [BRANCH] UPSTREAM"
upstream=$1

toplevel=$(git rev-parse --show-toplevel)
update_py=$toplevel/update.py

if ! git diff-index --quiet HEAD -- ; then
    error "Uncommitted changes"
fi

SPECIAL_FILES=(apps.txt other.txt wildcard.txt fedora-flathub.filter)

commits=()
parents=()
subjects=()
author_names=()
author_emails=()
author_dates=()
committer_names=()
committer_emails=()
committer_dates=()

### Find the commits we need to rebase

merge_base=$(git merge-base "$branch" "$upstream")

saveIFS=$IFS
IFS=$'\001'
while read -r -d "" \
           commit parent \
           author_name author_email author_date \
           committer_name committer_email committer_date \
           subject ; do
    if [[ $parent = *" "* ]] ; then
        error "Merge commits in history to rebase"
    fi
    commits+=("$commit")
    parents+=("$parent")
    subjects+=("$subject")
    author_names+=("$author_name")
    author_emails+=("$author_email")
    author_dates+=("$author_date")
    committer_names+=("$committer_name")
    committer_emails+=("$committer_email")
    committer_dates+=("$committer_date")
done < <(git log -z --reverse \
         --pretty=tformat:'%H%x01%P%x01%an%x01%ae%x01%ad%x01%cn%x01%ce%x01%cd%x01%s' \
         "$merge_base".."$branch")
IFS=$saveIFS

### Now we rewrites commits with the appropriate other.txt and
### app.txt as if they were rebased, but leaving them them
### attached to the merge base

tmpdir=$(mktemp -d)
success=false

cleanup() {
    unset GIT_WORK_TREE
    rm -rf "$tmpdir"
    $success || git switch --force "$original_branch"
}

trap cleanup EXIT

mkdir "$tmpdir/upstream"
mkdir "$tmpdir/last"
mkdir "$tmpdir/base"
mkdir "$tmpdir/work"

### Add a commit on top of the upstream commit to update apps.txt/etc.

echo -n "Updating ${SPECIAL_FILES[*]} in $upstream ... "

export GIT_WORK_TREE=$tmpdir/upstream
git checkout -q --detach "$upstream"
git checkout -f -- .

"$update_py" -q --input-dir="$tmpdir/upstream" --output-dir="$tmpdir/upstream"
git add "${SPECIAL_FILES[@]}"
if git diff-index --quiet "$upstream" -- ; then
    echo "nothing to do"
else
    git commit -q -m "Update to latest Flathub data"
    echo "done"
fi

onto="$(git rev-parse HEAD)"

### Add a commit on top of the merge base with the updated apps.txt/etc.

export GIT_WORK_TREE=$tmpdir/work
git checkout -q "$merge_base"
git checkout -f -- .

for file in "${SPECIAL_FILES[@]}" ; do
    cp "$tmpdir/upstream/$file" "$tmpdir/work"
done

git add "${SPECIAL_FILES[@]}"
if ! git diff-index --quiet "$merge_base" -- ; then
    git commit -q -m "Update to latest Flathub data"
fi

### Now replay the commits, updating apps.txt/etc.

echo "Rewriting commits with an updated ${SPECIAL_FILES[*]}:"

from=$(git rev-parse HEAD)
last=$from

for ((i = 0; i < ${#commits[@]}; i++)) ; do
    echo -n "  ${subjects[i]} ... "
    GIT_WORK_TREE=$tmpdir/last git checkout -q --force "$last" .
    GIT_WORK_TREE=$tmpdir/base git checkout -q --force "${parents[i]}" .
    git checkout -q --force "${commits[i]}" .
    "$update_py" -q \
        --input-dir="$tmpdir/last" \
        --delta-from-dir="$tmpdir/base" \
        --delta-to-dir="$tmpdir/work" \
        --output-dir="$tmpdir/work"

    git add "${SPECIAL_FILES[@]}"
    if git diff-index --quiet --cached "$last" -- ; then
        echo "skipping (empty)"
        continue
    fi

    tree=$(git write-tree)

    git log --pretty=format:'%B' "${commits[i]}" -1 > "$tmpdir/work/commitmsg"
    last=$(
        GIT_AUTHOR_NAME="${author_names[i]}" \
        GIT_AUTHOR_EMAIL="${author_emails[i]}" \
        GIT_AUTHOR_DATE="${author_dates[i]}" \
        GIT_COMMITTER_NAME="${committer_names[i]}" \
        GIT_COMMITTER_EMAIL="${committer_emails[i]}" \
        GIT_COMMITER_DATE="${committer_dates[i]}" \
            git commit-tree -p "$last" -F "$tmpdir/work/commitmsg" "$tree"
        )
    echo "done"
done

### Update the branch we are rebasing to the last rewritten commit

git branch -f "$branch" "$last"
success=true

unset GIT_WORK_TREE
git reset "$original_branch"
git switch -q -f "$branch"

### Now run the rebase - the user may need to resolve conflicts to
### other files like README.md manually

echo "Rebasing rewritten commits onto $upstream"
if ! git rebase "$from" --onto="$onto" ; then
    echo "update.py: please resolve conflicts manually"
    exit 42
fi

git switch -q -f "$original_branch"
