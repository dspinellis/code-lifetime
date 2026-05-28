/*
 * Copyright 1996-2026 Diomidis Spinellis
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
 * The output is "SHA identifier" lines.
 *
 */

use std::collections::HashMap;
use std::env;
use std::fs::File;
use std::io::{self, BufRead, BufReader};
use std::process;

const DEBUG: bool = false;

#[derive(Default)]
struct Vertex {
    name: String,
    // Author/commit time, SHA, bug ids, or any other tracked commit element.
    identifier: String,
    // Longest path ending here; None means it has not yet been calculated.
    max_length: Option<i32>,
    // Parent commits of this commit.
    edges: Vec<String>,
    // The next vertex in the recorded longest path.
    lp_from: Option<String>,
}

impl Vertex {
    fn new(name: &str, identifier: &str) -> Self {
        Self {
            name: name.to_string(),
            identifier: identifier.to_string(),
            max_length: None,
            edges: Vec::new(),
            lp_from: None,
        }
    }
}

fn get_vertex<'a>(
    vertices: &'a mut HashMap<String, Vertex>,
    name: &str,
    identifier: &str,
) -> &'a mut Vertex {
    // Return a node by name, adding it to the map if needed.
    let vertex = vertices
        .entry(name.to_string())
        .or_insert_with(|| Vertex::new(name, identifier));
    if !identifier.is_empty() {
        vertex.identifier = identifier.to_string();
    }
    vertex
}

fn reader_from_args() -> Box<dyn BufRead> {
    let args: Vec<String> = env::args().collect();
    if args.len() == 2 {
        match File::open(&args[1]) {
            Ok(file) => Box::new(BufReader::new(file)),
            Err(error) => {
                eprintln!("{}: {error}", args[1]);
                process::exit(1);
            }
        }
    } else {
        Box::new(BufReader::new(io::stdin()))
    }
}

fn read_graph(
    reader: Box<dyn BufRead>,
) -> io::Result<(HashMap<String, Vertex>, Vec<String>, Option<String>)> {
    let mut vertices = HashMap::new();
    let mut order = Vec::new();
    let mut end = None;

    for line in reader.lines() {
        let line = line?;
        let mut parts = line.split_whitespace();
        let Some(node_name) = parts.next() else {
            continue;
        };
        let identifier = parts.next().unwrap_or("");

        // Read node, adding it to the map if needed.
        get_vertex(&mut vertices, node_name, identifier);
        order.push(node_name.to_string());
        if end.is_none() {
            end = Some(node_name.to_string());
        }

        // Create edges from this commit to its parents.
        for parent_name in parts {
            if DEBUG {
                eprintln!("{parent_name} parent of {node_name}");
            }
            get_vertex(&mut vertices, parent_name, "");
            vertices
                .get_mut(node_name)
                .expect("current vertex exists")
                .edges
                .push(parent_name.to_string());
        }
    }

    Ok((vertices, order, end))
}

fn calculate_max_lengths(vertices: &mut HashMap<String, Vertex>, order: &[String]) {
    // Parent vertices that do not appear as full input lines are roots.
    for vertex in vertices.values_mut() {
        vertex.max_length = Some(0);
    }

    // Record the maximum path associated with each vertex.  The input is
    // topologically sorted newest to oldest, so reverse order gives parents
    // before children and avoids recursion over long commit histories.
    for name in order.iter().rev() {
        let edges = vertices
            .get(name)
            .map(|vertex| vertex.edges.clone())
            .unwrap_or_default();
        let max_path = edges
            .iter()
            .filter_map(|edge| vertices.get(edge).and_then(|vertex| vertex.max_length))
            .max()
            .unwrap_or(-1);
        let length = max_path + 1;
        if DEBUG {
            eprintln!("max_length({name}) = {length}");
        }
        if let Some(vertex) = vertices.get_mut(name) {
            vertex.max_length = Some(length);
        }
    }
}

fn mark_longest_path(
    vertices: &mut HashMap<String, Vertex>,
    order: &[String],
    end: &str,
) -> Option<String> {
    // Calculate the maximum paths of all vertices.
    calculate_max_lengths(vertices, order);

    // Obtain and record the longest path.  The strict comparison preserves
    // the original first-parent tie behavior.
    let mut current = Some(end.to_string());
    let mut start = Some(end.to_string());
    while let Some(name) = current {
        let edges = vertices
            .get(&name)
            .map(|vertex| vertex.edges.clone())
            .unwrap_or_default();
        let mut longest = None;
        let mut longest_length = None;
        for edge in edges {
            let length = vertices.get(&edge).and_then(|vertex| vertex.max_length);
            if longest.is_none() || length > longest_length {
                longest = Some(edge);
                longest_length = length;
            }
        }

        if let Some(parent) = longest {
            if let Some(vertex) = vertices.get_mut(&parent) {
                vertex.lp_from = Some(name);
            }
            start = Some(parent.clone());
            current = Some(parent);
        } else {
            current = None;
        }
    }

    start
}

fn print_longest_path(vertices: &HashMap<String, Vertex>, start: Option<String>) {
    // Display the longest path.
    let mut current = start;
    while let Some(name) = current {
        let vertex = vertices.get(&name).expect("path vertex exists");
        println!("{} {}", vertex.name, vertex.identifier);
        current = vertex.lp_from.clone();
    }
}

fn run() -> io::Result<()> {
    let reader = reader_from_args();
    let (mut vertices, order, end) = read_graph(reader)?;
    let Some(end) = end else {
        return Ok(());
    };

    let start = mark_longest_path(&mut vertices, &order, &end);
    print_longest_path(&vertices, start);
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        process::exit(1);
    }
}
