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
CXXFLAGS=-O3

# Prevent stack overflow under Cygwin
ifeq ($(OS),Windows_NT)
  CXXFLAGS += -Wl,--stack,16777216
endif

all: daglp

daglp: daglp.cpp

test:
	rm -rf code-lifetime-test code-lifetime-test-branch
	git clone https://github.com/dspinellis/code-lifetime-test.git
	git clone https://github.com/dspinellis/code-lifetime-test-branch.git
	./sync-test-branches.sh
	perl lifetime.pl -D u
	./runtest.sh
	rm -rf code-lifetime-test code-lifetime-test-branch diff.diff \
	commit-tree.txt commit-daglp.txt RECONSTRUCTION growth.txt

clean:
	rm -f daglp
