#!/bin/bash
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
# Incrementally verify all the commits in test
#

# See http://unix.stackexchange.com/questions/48533/exit-shell-script-from-a-subshell
set -E
trap '[ "$?" -ne 77 ] || exit 77' ERR

export TOOLDIR=$(pwd)

compare()
{
  diff --exclude='binary-*' -r RECONSTRUCTION $1 |
  fgrep -v "Only in $1: .git" |
  grep -v 'Binary files .* differ' |
  grep . &&
    echo 'Test failed: directories differ' 1>&2 &&
    exit 77
  reported_loc=$(tail -1 growth.txt | cut -d\  -f 2)
  actual_loc=$(find RECONSTRUCTION/ -type f -print0 | xargs -0 cat | wc -l)
  if [ $reported_loc -ne $actual_loc ] ; then
    echo "Test failed: LOCs differ, reported=$reported_loc actual=$actual_loc" 1>&2
    exit 77
  fi
}

test_one()
{
  (
    cd code-lifetime-test &&
    git log -m -M -C -C --pretty=tformat:'commit %H %ct' --topo-order --reverse -U0  | tee ../diff.diff
  ) | perl lifetime.pl -g growth.txt -D RH || exit 77
  compare code-lifetime-test
}

# Test the final status using difflog and daglp
test_final()
{
  (
    cd $1 &&
      git checkout master &&
    $TOOLDIR/difflog.sh master
  ) | perl lifetime.pl -g growth.txt -D RH || exit 77
  compare $1
}

if [ "x$1" = 'x-1' ] ; then
  test_one
  echo Test succeeded 1>&2
  exit 0
fi

(cd code-lifetime-test && git checkout master >/dev/null && git log --reverse --format=%H master) |
while read sha ; do
  echo Verifying $sha
  ( cd code-lifetime-test &&
    git checkout -q $sha ) &&
  test_one
done

test_final code-lifetime-test
test_final code-lifetime-test-branch

echo All tests succeeded 1>&2
