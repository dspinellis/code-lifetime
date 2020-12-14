#!/usr/bin/perl
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
# Convert source code of a Git repository into tokens
# See https://github.com/cregit/cregit and
# e.g. https://github.com/dmgerman/linux-token-bfg
#

use strict;
use warnings;

use Date::Parse;
use File::Copy;
use File::Find;
use Getopt::Std;
use Git::FastExport;
use Git::Repository;
use Time::Local;
use IPC::Run qw( run );


sub
main::HELP_MESSAGE
{
	my ($fh) = @_;
	print $fh qq{
Usage: $0 [-d] directory branch_name
-d	Output debug information on standard error
};
}

our($opt_d);

if (!getopts('d')) {
	main::HELP_MESSAGE(*STDERR);
	exit 1;

}

git_import($ARGV[0], $ARGV[1]);

# Filter the passed data through tokenizer
sub
tokenize
{
	my ($data, $path) = @_;

	my $args;

	if (length($data) > 1e6) {
		print STDERR "Long data; skip\n";
		return '';
	}

        # Keep tokenize.pl:tokenize, lifetime.pl:output_source_code, repo-metrics-report.sh, analyze-moves.sh in sync
	if ($path =~ m/\.java$/) {
		$args = '-l Java';
	} elsif ($path =~ m/\.c$/) {
		$args = '-l C';
	} elsif ($path =~ m/\.cs$/i) {
		$args = '-l CSharp';
	} elsif ($path =~ m/\.(C|cc|cpp|cxx|h|H|hh|hpp|hxx|h\+\+|c\+\+)$/) {
		$args = '-l C++';
	} elsif ($path =~ m/\.((php[3457s]?)|pht|php-s)$/i) {
		$args = '-l PHP';
	} elsif ($path =~ m/\.py$/i) {
		$args = '-l Python';
	} else {
		print STDERR "Unkown suffix; skip\n" if ($opt_d);
		return '';
	}

	print STDERR "Run tokenizer -t T $args\n" if ($opt_d);
	my @tokenizer = split(/\s+/, "tokenizer -t T $args");
	my $result;
	run \@tokenizer, \$data, \$result or die "tokenizer $?";
	print STDERR "Tokenizer run finished\n" if ($opt_d);
	return $result;
}

sub
git_import
{

	my ($directory, $branch) = @_;

	# get the object from a Git::Repository
	my $repo = Git::Repository->new(work_tree => $directory) || die;
	my $fh = $repo->command(('fast-export', $branch))->stdout || die;
	# Create parser on the output stream
	my $export = Git::FastExport->new($fh) || die;

	# Record queue; this will be either empty or have a blob at its head
	# (element 0)
	my @rq;

	while (my $block = $export->next_block()) {

		# In an empty queue only queue blobs
		if ($#rq == -1 && $block->{type} ne 'blob') {
			print $block->as_string();
			next;
		}

		# Queue the block
		push(@rq, $block);

		my $files;
		# See if this is a commit whose filemodify command can provide
		# us data regarding the top of queue blob file type
		print "#GFI type: $block->{type}\n";
		if ($block->{type} eq 'commit' && defined($files = $block->{files})) {
			print STDERR "Commit $block->{author}[0]\n" if ($opt_d);
			# Process all the commit's files while a blob is being matched
			my $matched;
			do {
				$matched = 0;
				for my $f (@$files) {
					my ($op, $mode, $dataref, $path) = split(/ /, $f);
					if ($op eq 'M' && $#rq >= 0) {
						print "#GFI check file $dataref against $#rq queue head $rq[0]->{type}: $rq[0]->{mark}->[0]\n";
						if ($rq[0]->{mark}->[0] eq "mark $dataref") {
							$matched = 1;
							print "#GFI $path\n";
							my $blob = shift(@rq);
							print STDERR "Tokenize $path\n" if ($opt_d);
							$blob->{data} = tokenize($blob->{data}, $path);
							print $blob->as_string();
							# Empty queue until next blob
							print "#GFI Empty queue begin\n";
							while ($#rq >= 0 && $rq[0]->{type} ne 'blob') {
								print shift(@rq)->as_string();
							}
							print "#GFI Empty queue end\n";
						}
					}
				}
			} while ($matched && $#rq >= 0);
		}
	}
	print "#GFI Empty queue to end\n";
	while ($#rq >= 0) {
		print shift(@rq)->as_string();
	}
	print "done\n";
}
