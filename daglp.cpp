/*
 *
 * Copyright 1996-2000 Diomidis Spinellis
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 *
 * Given as input a topologically sorted list of each commit's parents,
 * output the longest path of the DAG from the beginning (the oldest commit)
 * to the end (the newest one).
 * See https://en.wikipedia.org/wiki/Longest_path_problem#Acyclic_graphs_and_critical_paths
 * The input should come from
 * git log --topo-order --pretty=format:'%H %at %P'
 * The output is "SHA timestamp" lines.
 *
 */

#include <cstdlib>

#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <map>

using namespace std;

static bool debug = false;

typedef unsigned long Timestamp;

class Vertex {
public:
	string name;
	int maxLength;			// Longest path ending here
	Timestamp timestamp;		// Author or commit time
	vector <Vertex *> edges;
	Vertex *lpFrom;			// The from vertex of the longest path
	Vertex(const string &n, Timestamp ts) : name(n), timestamp(ts),
		maxLength(-1) {}
	void add_edge(Vertex *to) {
		edges.push_back(to);
	}
};

typedef map <string, Vertex *> VertexMap;
VertexMap vertices;

/*
 * Return a pointer to a node given its name.
 * The node is added to the map if it is not there.
 */
static Vertex *
get_vertex(const string &name, Timestamp ts)
{
	VertexMap::const_iterator ni = vertices.find(name);
	if (ni == vertices.end()) {
		Vertex *v = new Vertex(name, ts);
		vertices.insert(VertexMap::value_type(name, v));
		return v;
	} else {
		if (ts != -1)
			ni->second->timestamp = ts;
		return ni->second;
	}
}

/*
 * Return a pointer to a node given its name.
 */
static Vertex *
get_vertex(const string &name)
{
	return vertices.find(name)->second;
}

// Return and record the maximum path associated with a given vertex
static int
maxLength(Vertex *v)
{
	if (v->maxLength != -1)
		return v->maxLength;
	// One more than the maximum path of its neighbours
	int mp = -1;
	for (vector <Vertex *>::iterator i = v->edges.begin(); i != v->edges.end(); i++) {
		int p = maxLength(*i);
		if (p > mp)
			mp = p;
	}
	if (debug)
		cerr << "maxLength(" << v->name << ") = " << mp + 1 << endl;
	return v->maxLength = mp + 1;
}

int
main(int argc, char *argv[])
{
	string line;
	Vertex *start, *end = NULL;
	istream *in = &cin;
	ifstream input;

	if (argc == 2) {
		input.open(argv[1]);
		if (!input) {
			perror(argv[1]);
			exit(1);
		}
		in = &input;
	}


	/*
	 * Read the graph, which should come out of
	 * git log --topo-order --pretty=format:'%H %at %P'
	 */
	while (getline(*in, line)) {
		istringstream iss(line);

		// Read node v adding it to the map if needed
		string nodeName;
		iss >> nodeName;
		long ts;
		iss >> ts;
		Vertex *v = get_vertex(nodeName, ts);

		if (end == NULL)
			end = v;

		// Create edges
		string parentName;
		while (iss >> parentName) {
			if (debug)
				cerr << parentName << " parent of " << nodeName << endl;
			v->add_edge(get_vertex(parentName, -1));
		}
	}

	// Calculate the maximum paths of all vertices
	(void)maxLength(end);

	// Obtain and record the longest path
	end->lpFrom = NULL;
	for (Vertex *v = end; v; ) {
		Vertex *lv = NULL;	// Vertex with longest path
		int lp = -1;		// Longest path length
		for (vector <Vertex *>::iterator i = v->edges.begin(); i != v->edges.end(); i++)
			if (lv == NULL || (*i)->maxLength > lp) {
				lv = *i;
				lp = lv->maxLength;
			}
		if (lv) {
			lv->lpFrom = v;
			start = lv;
		}
		v = lv;
	}

	// Display the longest path
	for (Vertex *v = start; v; v = v->lpFrom)
		cout << v->name << ' ' << v->timestamp << endl;
	return 0;
}
