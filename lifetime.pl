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
# Parse the output of
# git log -M -m --pretty=tformat:'commit %H %ct' --topo-order --reverse -U0
# to track the lifetime of individual lines
#

use strict;
use warnings;
use File::Path qw(make_path remove_tree);
use Getopt::Std;

$main::VERSION = '0.1';

# Exit after command processing error
$Getopt::Std::STANDARD_HELP_VERSION = 1;

sub
main::HELP_MESSAGE
{
	my ($fh) = @_;
	print $fh qq{
Usage: $0 [options ...] [input file ...]
-c	Output in "compressed" format: commit, followed by birthday of deaths
-d 	Report the LoC delta
-D opts	Debug as specified by the letters in opts
	C Show commit set changes
	D Show diff headers
	E Show diff extended headers
	H Show each commit SHA, timestamp header
	L Show LoC change processing
	P Show push to change set operations
	R Reconstruct the repository contents from its log
	@ Show range headers
	S Show results of splicing operations
	u Run unit tests
-e SHA	End processing after the specified (full) SHA commit hash
-E	Redirect (debugging) output to stderr
-g file	Create a growth file with line count of live lines at every commit
-h	Print usage information and exit
-l	Associate with each line details about its composition
-q	Quiet; do not output commit and timestamp on normal processing
-s	Report only changes in source code files (based on their suffix)
-t	Show tokens with lifetime
};
}

our($opt_c, $opt_d, $opt_D, $opt_e, $opt_E, $opt_g, $opt_h, $opt_l, $opt_q, $opt_s, $opt_t);

if (!getopts('cdD:e:Eg:hlqst')) {
	main::HELP_MESSAGE(*STDERR);
	exit 1;
}

if (defined($opt_h)) {
	HELP_MESSAGE(\*STDOUT);
	exit(0);
}

open(STDOUT, ">&STDERR") if (defined($opt_E));

my $growth_file;

my $loc = 0;
my $prev_loc = 0;

open($growth_file, '>', $opt_g) || die "Unable to open $opt_g: $!\n" if ($opt_g);

# Return undef or true depending on whether the specified
# debug option is set
sub
debug_option
{
	my($opt) = @_;

	return undef unless defined($opt_D);
	return ($opt_D =~ m/$opt/);
}

# Reconstruct the repository contents from its log -D R
my $debug_reconstruction = debug_option('R');
# Show results of splicing operations -D S
my $debug_splice = debug_option('S');
# Show each commit SHA, timestamp header -D H
my $debug_commit_header = debug_option('H');
# Show diff headers -D D
my $debug_diff_header = debug_option('D');
# Show diff extended headers -D E
my $debug_diff_extended = debug_option('E');
# Show range headers -D @
my $debug_range_header = debug_option('@');
# Show commit set changes -D C
my $debug_commit_changes = debug_option('C');
# Show push to change set operations -D P
my $debug_push_cc = debug_option('P');
# Show LoC change processing -D L
my $debug_loc = debug_option('L');

if (debug_option('u')) {
	test_line_details();
	exit 0;
}


my $state = 'commit';
$_ = <>;
chop;

# Old and new changed files
my ($old, $new);
# One of inplace, copy, rename, del
my $op;

# Details of current commit
my ($commit, $hash, $timestamp);

# File line timestamps (or contents when debugging through reconstruction)
my %flt;

# Files that are binary; these are not tracked on a line-by-line basis
# (Sometimes line diffs appear for a file that was first committed as
# binary.)
my %binary;

# Commit changes. To preserve the isolation between changes performed
# during a commit, all changes are recorded here and then atomically
# committed at the end.
# Each record has:
#   op {set, del}
#   path
#   lines
my @cc;

# Records of deleted lines
# Output at the end of a commit in order to report
# commit size, if needed
my @delete_records;

# Number of lines added to new file
my $added_lines;
# Number of lines removed from old and new file
my $removed_lines;
# Reference to copy of the old and new file contents
my $oref;
my $nref;

for (;;) {

	if ($state eq 'commit') {
		process_last_commit() if (defined($hash));
		# Timestamp
		($commit, $hash, $timestamp) = split;
		print "commit $hash $timestamp\n" if ($opt_c || $debug_commit_header);
		print STDERR "commit $hash $timestamp\n" if (!$debug_reconstruction && !$opt_q);

		# Separator
		$_ = <>;
		if (!defined($_)) {
			$state = 'EOF';
		} elsif (/^$/) {
			$_ = <>;
			if (!defined($_)) {
				$state = 'EOF';
			} elsif (/^diff /) {
				$state = 'diff';
				chop;
			} elsif (/^commit /) {
				# This happens on an empty commit with git diff
				chop;
			} else {
				bail_out('Expecting diff, commit, or EOF');
			}
		} elsif (/^commit /) {
			# This happens on an empty commit
			chop;
			;
		} else {
			bail_out('Expecting an empty line or commit');
		}
	} elsif ($state eq 'diff') {
		# Diff header
		hide_escaped_quotes();
		bail_out('Expecting a diff command') unless (
			# a b
			m/^diff --git a\/([^ ]*) b\/(.*)/ ||
			# "a" "b"
			# See http://stackoverflow.com/questions/249791/regex-for-quoted-string-with-escaping-quotes
			# for an explanation of the RE that includes escaped
			# quotes
			m/^diff --git "a\/((?:[^"\\]|\\.)*)" "b\/((?:[^"\\]|\\.)*)"/ ||
			# a "b"
			m/^diff --git a\/([^ ]*) "b\/((?:[^"\\]|\\.)*)"/ ||
			# "a" b
			m/^diff --git "a\/((?:[^"\\]|\\.)*)" b\/(.*)/ ||
			# a and b with spaces (and no component " b/")
			# This was found in one of the repos
			m/^diff --git a\/(.*) b\/(.*)/);
		$old = $1;
		$new = $2;
		$old = unescape($old) if (/\"/);
		$new = unescape($new) if (/\"/);

		print "$_\n" if ($debug_diff_header);
		print "old=[$old] new=[$new]\n" if ($debug_diff_header);

		$oref = defined($flt{$old}) ? [@{$flt{$old}}] : [];
		$nref = ($old eq $new) ? $oref : defined($flt{$new}) ? [@{$flt{$new}}] : [];

		$state = 'EOF';
		# Read the "extended header lines" to handle copies and renames
		my $from;
		$op = 'inplace';
		while (<>) {
			print "diff extended header: $_" if ($debug_diff_extended);
			chop;
			if (/^--- /) {
				# Start of a file difference
				# --- a/main.c

				# +++ b/main.c
				$_ = <>;

				# Range
				$_ = <>;
				chop;
				$state = 'range';
				$added_lines = $removed_lines = 0;
				last;
			} elsif (/^(copy|rename) from (.*)/) {
				$from = unquote_unescape($2);
			} elsif (/^rename to (.*)/) {
				my $to = unquote_unescape($1);
				$op = 'rename';
				bail_out('Missing rename from') unless (defined($from));
				push(@cc, { op => 'del', path => $from });
				push(@cc, { op => 'set', path => $to, lines => [@{$flt{$from}}] });
				$oref = $nref = [@{$flt{$old}}];
				$binary{$to} = 1 if ($binary{$from});
			} elsif (/^copy to (.*)/) {
				my $to = unquote_unescape($1);
				$op = 'copy';
				bail_out('Missing copy from') unless (defined($from));
				push(@cc, { op => 'set', path => $to, lines => [@{$flt{$from}}] });
				$loc += $#{$flt{$from}} + 1 if ($opt_g && output_source_code($to));
				$nref = [@{$flt{$old}}];
				$binary{$to} = 1 if ($binary{$from});
			} elsif (/^commit /) {
				$state = 'commit';
				last;
			} elsif (/^diff --git /) {
				$state = 'diff';
				last;
			} elsif (/^new file mode /) {
				push(@cc, { op => 'set', path => $old, lines => [] });
			} elsif (/^deleted file mode /) {
				$op = 'del';
				push(@cc, { op => 'del', path => $old });
				# Print death times of deleted file's lines
				if (!$debug_reconstruction && output_source_code($old)) {
					for my $l (@{$flt{$old}}) {
						if ($opt_c) {
							print "$l\n";
						} else {
							push(@delete_records, "$l $timestamp");
						}
					}
				}
			} elsif (/^Binary files ([^ ]*) and ([^ ]*) differ/) {
				$binary{$old} = 1;
				$_ = <>;
				if (!defined($_)) {
					$state = 'EOF';
					last;
				} elsif (/^commit /) {
					chop;
					$state = 'commit';
					last;
				} elsif (/^diff --git /) {
					chop;
					$state = 'diff';
					last;
				} else {
					bail_out('Expected diff, commit, or EOF');
				}
			}
		}
	} elsif ($state eq 'range') {
		# Ranges within files
		print "$_\n" if ($debug_range_header);
		my ($at1, $old_range, $new_range, $at2) = split;
		bail_out('Expecting a diff range') unless ($at1 eq '@@' && $at2 eq '@@');
		my ($old_start, $old_end) = range_parse($old_range);
		my ($new_start, $new_end) = range_parse($new_range);

		$_ = <>;
		my ($old_offset, $new_offset);
		$new_offset = $added_lines - $removed_lines;
		if ($oref == $nref) {
			$old_offset = $new_offset = $added_lines - $removed_lines;
		} else {
			$old_offset = -$removed_lines;
		}
		my $binary = exists($binary{$old});
		my $output_source_code = output_source_code($old);
		for (my $i = $old_start; $i < $old_end; $i++) {
			if ($binary) {
				$_ = <>;
				next;
			}
			bail_out('Expecting a removed line') unless (m/^-/);
			$loc-- if ($output_source_code);
			if (defined($oref->[$i + $old_offset])) {
				if ($debug_reconstruction) {
					bail_out("Expecting at($i + $old_offset) " . $oref->[$i + $old_offset]) unless (substr($oref->[$i + $old_offset], 1) eq substr($_, 1));
				} elsif ($output_source_code) {
					if ($opt_c) {
						print "$oref->[$i + $old_offset]\n";
					} else {
						push(@delete_records, "$oref->[$i + $old_offset] $timestamp");
					}
				}
			} else {
				print STDERR "Warning: $hash line $. unknown line $old:", $i + 1, "\n";
			}
			$_ = <>;
		}
		my $remove_len = $old_end - $old_start;
		print "before oref=$#$oref ns=$old_start len=$remove_len\n" if ($debug_splice);
		if (!$binary) {
			splice(@$oref, $old_start + $old_offset, $remove_len) unless ($remove_len == 0);
			if ($oref != $nref) {
				splice(@$nref, $old_start + $new_offset, $remove_len) unless ($remove_len == 0);
			}
		}
		print "after oref=$#$oref\n" if ($debug_splice);
		$_ = <> if (defined($_) && $_ =~ m/^\\ No newline at end of file/);
		my @add;
		for (my $i = $new_start; $i < $new_end; $i++) {
			if ($debug_reconstruction) {
				push(@add, $_);
			} elsif ($opt_l) {
				push(@add, "$timestamp L " . line_details(substr($_, 1)));
			} elsif ($opt_t) {
				my $tokinfo = $_;
				$tokinfo =~ s/^.(.*)\n/$1/;
				push(@add, "$timestamp $tokinfo")
			} else {
				push(@add, $timestamp);
			}
			bail_out('Expecting an added line') unless (m/^\+/);
			$loc++ if (!$binary && $output_source_code);
			$_ = <>;
		}
		my $add_len = $new_end - $new_start;
		print "before nref=$#$nref ns=$new_start len=$add_len\n" if ($debug_splice);
		if (!$binary && $add_len > 0) {
			splice(@$nref, $new_start, 0, @add);
		}
		$added_lines += $add_len;
		$removed_lines += $remove_len;
		print "after nref=$#$nref\n" if ($debug_splice);
		$_ = <> if (defined($_) && $_ =~ m/^\\ No newline at end of file/);
		if (!defined($_)) {
			push_to_cc();
			$state = 'EOF';
		} elsif (/^@@ /) {
			chop;
			# implicit $state = 'range';
		} elsif (/^diff --git /) {
			chop;
			push_to_cc();
			$state = 'diff';
		} elsif (/^commit /) {
			chop;
			push_to_cc();
			$state = 'commit';
		} else {
			bail_out('Expected diff, @@, commit, or EOF');
		}
	} elsif ($state eq 'EOF') {
		last;
	} else {
		bail_out("Invalid state $state");
	}
}

process_last_commit();
if ($debug_reconstruction) {
	reconstruct();
} else {
	dump_alive();
}
exit 0;

# Write the commit's effect on the project's LOC value
sub
process_last_commit
{
	my $delta = $loc - $prev_loc;

	print "prev_loc=$prev_loc loc=$loc delta=$delta\n" if ($debug_loc);

	# Print records of deleted lines
	my $eol = ($opt_d ? " $delta\n" : "\n");
	for (@delete_records) {
		print "$_", $eol;
	}
	undef @delete_records;

	commit_changes();
	print $growth_file "$timestamp $loc\n" if ($opt_g);
	$prev_loc = $loc;
}

# Reconstruct the state of the Git tree based on the log
sub
reconstruct
{
	my $base_dir = 'RECONSTRUCTION';
	remove_tree($base_dir);
	for my $f (keys %flt) {
		next if ($f eq '/dev/null');
		next unless defined($flt{$f});
		my $path = "$base_dir/$f";
		my $dir = $path;
		$dir =~ s|[^/]*$||;
		make_path($dir);
		open(my $out, '>', $path) || die "Unable to open $path: $!\n";
		for my $line (@{$flt{$f}}) {
			print $out substr($line, 1);
		}
	}
}

# Print birth timestamps of files that are still alive
sub
dump_alive
{
	my $eol;

	if ($opt_c) {
		print "END\n";
		$eol = "\n";
	} else {
		$eol = " alive NA\n";
	}

	for my $f (keys %flt) {
		next if ($f eq '/dev/null');
		next unless defined($flt{$f});
		next unless (output_source_code($f));
		for my $line (@{$flt{$f}}) {
			print $line, $eol;
		}
	}
}


sub
bail_out
{
	my ($expect) = @_;
	print STDERR "commit $hash $timestamp\n";
	print STDERR "Line $.: Unexpected $_\n";
	print STDERR "($expect)\n";
	reconstruct();
	exit 1;
}

# Return a diff range as a [start, end) interval
sub
range_parse
{
	my ($range) = @_;
	if ($range =~ m/[+-](\d+)\,(\d+)$/) {
		if ($2 == 0) {
			return (0, 0);
		} else {
			return ($1 - 1, $1 + $2 - 1);
		}
	} elsif ($range =~ m/[+-](\d+)$/) {
		return ($1 - 1, $1);
	} else {
		bail_out('Expecting a diff range');
	}
}

# Commit the commit changes recorded in @cc
sub
commit_changes
{
	for my $rec (@cc) {
		print "Change ($rec->{op}) $rec->{path}\n" if ($debug_commit_changes);
		if ($rec->{op} eq 'set') {
			# Mark lines coming from commits with the commit's size
			if (defined($opt_d)) {
				my $delta = $loc - $prev_loc;
				for (@{$rec->{lines}}) {
					if ($opt_t || $opt_l) {
						$_ =~ s/^$timestamp ([A-Z])/$timestamp $delta $1/;
					} else {
						$_ .= " $delta" if ($_ eq $timestamp);
					}
				}
			}
			$flt{$rec->{path}} = $rec->{lines};
		} elsif ($rec->{op} eq 'del') {
			delete $flt{$rec->{path}};
			delete $binary{$rec->{path}};
		} else {
			bail_out("Unknown change record $rec->{op}");
		}
	}
	undef @cc;

	if (defined($opt_e) && $opt_e eq $hash) {
		reconstruct();
		exit 0;
	}
}

# Push the old and new references to the change set
sub
push_to_cc
{
	print "op=$op $old $new\n" if ($debug_push_cc);
	return if ($op eq 'del');
	push(@cc, { op => 'set', path => $old, lines => $oref }) if ($oref != $nref && $op ne 'copy');
	push(@cc, { op => 'set', path => $new, lines => $nref });
}

# Return true if we are supposed to output details regarding the specified file
# (if no -s option was passed or the file contains source code)
sub
output_source_code
{
	return 1 unless ($opt_s);
	my ($name) = @_;
	# Keep tokenize.pl:tokenize, lifetime.pl:output_source_code, repo-metrics-report.sh, analyze-moves.sh in sync
	return ($name =~ m/\.(C|c|cc|cpp|cs|cxx|hh|hpp|h\+\+|c\+\+|h|H|hxx|java|((php[3457s]?)|pht|php-s)|py)$/);


}

# Change escaped quotes into \001 so that the real ones can be used as delimiters
sub
hide_escaped_quotes
{
	s/([^\\])\\\"/$1\001/g;
}


# Fix filename with embedded quotes and escapes
sub
unquote_unescape
{
	my ($n) = @_;
	return $n unless (/\"/);

	$n =~ s/([^\\])\\\"/$1\001/g;
	$n =~ s/\"//g;
	return unescape($n);
}


# Remove escapes and escaped quotes from the passed file name
sub
unescape
{
	my ($n) = @_;

	$n =~ s/\001/"/g;
	$n =~ s/\\t/\t/g;
	$n =~ s/\\n/\n/g;
	$n =~ s/\\"/\"/g;
	$n =~ s/\\(\d{3})/chr(oct($1))/ge;
	$n =~ s/\\\\/\\/g;	# Must be last
	return $n;
}

# Return details about the line's composition
# The values returned appear in the end of this function
sub
line_details
{
	my ($l) = @_;

	my $len = length($l);

	# Count and remove strings
	my $string = 0;
	while ($l =~ s/\"[^"]*\"//) {
		$string++;
	}
	while ($l =~ s/\'[^']*\'//) {
		$string++;
	}

	# Remove comments
	my $comment = (($l =~ s/\/\*.*//) || ($l =~ s/\#.*//) || ($l =~ s/\/\/.*//)) + 0;

	# Spaces (and expanded tabs) at the beginning of the line
	while ($l =~ s/\t+/' ' x (length($&) * 8 - length($`) % 8)/e) {
	    # spin in empty loop until substitution finally fails
	}
	$l =~ /^( *)/g;
	my $startspace = length($1);

	my $comma = () = $l =~ /\,/g;
	my $bracket = () = $l =~ /\(/g;
	my $access = () = $l =~ /\.[^0-9]|\-\>/g;
	my $assignment = () = $l =~ /[^<>!~=]\=[^=]|\<\<\=|\>\>\=/g;
	my $scope = () = $l =~ /\{|(:\s*$)/g;
	# String (done earlier)
	# Structure member access (combined with access)
	# * can be pointer dereference or multiplication; ignore
	# "if" ignore
	my $array = () = $l =~ /\[/g;
	# Comments (done earlier)
	my $logical = () = $l =~ /\=\=|[^>]\>\=|[^<]\<\=|\!\=|[^<]\<[^<]|[^->]\>[^>]|\!|\|\||\&\&|\bor\b|\band\b|\bnot\b|\bis\b/g;
	return "$len $startspace $string $comment $comma $bracket $access $assignment $scope $array $logical";
}

sub
str_equal
{
	my($a, $b) = @_;

	if ($a ne $b) {
		print STDERR "Expected\t[$a]\nObtained\t[$b]\n";
	}
}

sub
test_line_details
{
		 # l s s c c b a a s a l
	str_equal("2 0 0 0 0 0 0 0 0 0 0", line_details("xx"));
	str_equal("3 0 1 0 0 0 0 0 0 0 0", line_details("'x'"));
	str_equal("3 0 0 1 0 0 0 0 0 0 0", line_details('#x('));
	str_equal("3 0 0 1 0 0 0 0 0 0 0", line_details('/*('));
	str_equal("3 0 0 1 0 0 0 0 0 0 0", line_details('//('));
	str_equal("5 0 0 0 2 0 0 0 0 0 0", line_details('a,b,c'));
	str_equal("2 0 0 0 0 2 0 0 0 0 0", line_details('(('));
	str_equal("3 0 0 0 0 0 1 0 0 0 0", line_details('a.b'));
	str_equal("4 0 0 0 0 0 1 0 0 0 0", line_details('a->b'));
	str_equal("3 0 0 0 0 0 0 0 0 0 0", line_details('1.2'));
	str_equal("3 0 0 0 0 0 0 1 0 0 0", line_details('a=b'));
	str_equal("5 0 0 0 0 0 0 1 0 0 0", line_details('a<<=b'));
	str_equal("4 0 0 0 0 0 0 1 0 0 0", line_details('a*=b'));
	str_equal("1 0 0 0 0 0 0 0 1 0 0", line_details('{'));
	str_equal("2 0 0 0 0 0 0 0 1 0 0", line_details(': '));
	str_equal("2 0 0 0 0 0 0 0 1 0 0", line_details('x:'));
	str_equal("1 0 0 0 0 0 0 0 0 1 0", line_details('['));
	str_equal("2 0 0 0 0 0 0 0 0 0 1", line_details('=='));
	str_equal("3 0 0 0 0 0 0 0 0 0 1", line_details('a>='));
	str_equal("3 0 0 0 0 0 0 0 0 0 1", line_details('b<='));
	str_equal("2 0 0 0 0 0 0 0 0 0 1", line_details('!='));
	str_equal("3 0 0 0 0 0 0 0 0 0 1", line_details('a<b'));
	str_equal("4 0 0 0 0 0 0 0 0 0 0", line_details('a<<b'));
	str_equal("3 0 0 0 0 0 0 0 0 0 1", line_details('a>b'));
	str_equal("2 0 0 0 0 0 0 0 0 0 2", line_details('!!'));
	str_equal("2 0 0 0 0 0 0 0 0 0 1", line_details('||'));
	str_equal("2 0 0 0 0 0 0 0 0 0 1", line_details('&&'));
	str_equal("7 0 0 0 0 0 0 0 0 0 1", line_details('a and b'));
	str_equal("6 0 0 0 0 0 0 0 0 0 1", line_details('a or b'));
	str_equal("5 0 0 0 0 0 0 0 0 0 1", line_details('not b'));
	str_equal("4 0 0 0 0 0 0 0 0 0 0", line_details('notb'));
	str_equal("6 0 0 0 0 0 0 0 0 0 2", line_details('is not'));
	str_equal("2 1 0 0 0 0 0 0 0 0 0", line_details(' x'));
	str_equal("4 3 0 0 0 0 0 0 0 0 0", line_details('   x'));
	str_equal("1 8 0 0 0 0 0 0 0 0 0", line_details("\t"));
	str_equal("3 16 0 0 0 0 0 0 0 0 0", line_details("\t\tx"));
}
