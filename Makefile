#
# Copyright 1996-2026 Diomidis Spinellis
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
CXXFLAGS=-O3

# Prevent stack overflow under Cygwin
ifeq ($(OS),Windows_NT)
  CXXFLAGS += -Wl,--stack,16777216
endif

all: daglp

daglp: daglp.cpp

test-perl: daglp
	rm -rf code-lifetime-test code-lifetime-test-branch
	git clone ./fixtures/code-lifetime-test.git
	cd code-lifetime-test && ../difflog.sh master | ../lifetime.pl -C ../churn
	diff -r fixtures/churn.ok/ churn/
	git clone ./fixtures/code-lifetime-test-branch.git
	./sync-test-branches.sh
	./lifetime.pl -D u
	TOOL=./lifetime.pl ./runtest.sh
	rm -rf churn/
	rm -rf code-lifetime-test code-lifetime-test-branch diff.diff \
	commit-tree.txt commit-daglp.txt RECONSTRUCTION growth.txt churn

test-python: daglp
	rm -rf code-lifetime-test code-lifetime-test-branch
	(cd fixtures/code-lifetime-test.git/ ; ../../difflog.sh master) | ./lifetime.py -t 2>/dev/null | sort  | diff fixtures/tokens.out  -
	(cd fixtures/code-lifetime-test.git/ ; ../../difflog.sh master) | ./lifetime.py -l 2>/dev/null | sort  | diff fixtures/line-contents.out  -
	git clone ./fixtures/code-lifetime-test.git
	cd code-lifetime-test && ../difflog.sh master | python3 ../lifetime.py --color never -C ../churn
	diff -r fixtures/churn.ok/ churn/
	git clone ./fixtures/code-lifetime-test-branch.git
	./sync-test-branches.sh
	TOOL='./lifetime.py --color never' ./runtest.sh
	GIT_DIR=fixtures/code-lifetime-test.git ./git-hot | diff - fixtures/metrics.out
	rm -rf code-lifetime-test code-lifetime-test-branch diff.diff \
	commit-tree.txt commit-daglp.txt RECONSTRUCTION growth.txt churn

test-python-unit:
	python3 -m unittest discover -s . -p 'test*.py'

lint:
	python3 -m pylint lifetime.py test_lifetime.py

clean:
	rm -f daglp
