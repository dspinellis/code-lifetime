#!/bin/bash
#
# Use locally the remote's branches required for testing
#

cd code-lifetime-test-branch

git branch --all |
grep '^\s*remotes' |
egrep --invert-match '(:?HEAD|master)$' |
while read branch ; do
  git branch --track "${branch##*/}" "$branch"
done
