#!/bin/sh
#
# Copyright 1996-2000 Diomidis Spinellis
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
# Produce a log of changes in unified diff format
# This is the equivalent of running
# git -c diff.renameLimit=30000 log -m -M -C --pretty=tformat:'commit %H %at' --topo-order --reverse -U0
# However, the former command has been known to produce incorrect results;
# see http://stackoverflow.com/questions/38839595/how-can-i-obtain-with-git-log-a-series-of-patches-that-can-be-auto-applied
# Any command line options are passed as arguments to git diff


BRANCH="$1"
shift

# Default 8k ulimit core dumps
ulimit -s 65536

# Obtain a list of commit timestamp parents in topological order
git log --pretty=tformat:'%H %at %P' --topo-order $BRANCH -- |
tee $TOOLDIR/$outdir/commit-tree.txt |
# Provide the graph's longest path
$TOOLDIR/daglp |
tee $TOOLDIR/$outdir/commit-daglp.txt |
while read sha ts ; do
  if [ "$prev" ] ; then
    echo "commit $sha $ts"
    echo
    # Output difference between successive commits
    git -c diff.renameLimit=30000 diff -m -M -C -U0 $@ $prev..$sha
  else
    # Show first commit
    git show --pretty=tformat:'commit %H %at' --topo-order --reverse -U0 $sha
  fi
  prev=$sha
done
